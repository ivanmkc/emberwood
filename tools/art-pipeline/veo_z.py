#!/usr/bin/env python3
"""Derive per-part z evidence from the Veo walk videos (Ivan). Deterministic:
median-over-time removes the walkers (static camera) -> background; per-frame
background subtraction extracts characters; ONE homography (ORB+RANSAC)
registers video space to the plate; silhouette holes/visible pixels attribute
behind/front constraints to the parts map via the probe aggregation rules.
"""
import glob
import json
import os

import cv2
import numpy as np
from PIL import Image

import occprobe2_run as o2

ROOT = o2.ROOT
ROOM = 'night-bazaar'
FG_T = 34
MIN_CHAR, MAX_CHAR = 1000, 20000


def homography(bg, plate):
    orb = cv2.ORB_create(4000)
    k1, d1 = orb.detectAndCompute(bg, None)
    k2, d2 = orb.detectAndCompute(plate, None)
    m = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d1, d2)
    m = sorted(m, key=lambda x: x.distance)[:800]
    src = np.float32([k1[x.queryIdx].pt for x in m]).reshape(-1, 1, 2)
    dst = np.float32([k2[x.trainIdx].pt for x in m]).reshape(-1, 1, 2)
    H, inl = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    return H, int(inl.sum())


def main():
    parts = np.load(os.path.join(ROOT, f'tools/art-pipeline/_srcmasks_{ROOM}-parts.npz'))['inst']
    pmeta = json.load(open(os.path.join(ROOT, f'docs/art-options/parts-{ROOM}-metrics.json')))
    imeta = json.load(open(os.path.join(ROOT, f'docs/art-options/occprobe2-instances-{ROOM}-aligned.json')))
    iblock = {o['id'] for o in imeta['instances'] if o.get('blocking')}
    parent = {int(k): v for k, v in pmeta['parent'].items()}
    blocking = {pid: f'part{pid}<{parent[pid]}>' for pid in parent if parent[pid] in iblock}
    plate = cv2.imread(os.path.join(ROOT, f'docs/art-options/rooms/{ROOM}/plate.png'))
    plate_small = cv2.resize(plate, (1200, 900))  # true 4:3: anisotropic stretch degrades ORB matching
    sx, sy = plate.shape[1] / 1200, plate.shape[0] / 900
    interior = o2.interior_mask(parts)

    evidence = []
    dbg = []
    iter_records = []
    prev_verdicts = {}
    for mp4 in sorted(glob.glob(os.path.join(ROOT, 'docs/art-options/veo/walk*.mp4'))):
        cap = cv2.VideoCapture(mp4)
        frames = []
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            frames.append(cv2.resize(fr, (1200, 675)))
        cap.release()
        stack = np.stack(frames[::6])
        bg = np.median(stack, axis=0).astype(np.uint8)
        # animated decor (swaying awnings, flicker) differs from bg in MOST
        # frames; a walker passes any pixel briefly. Exclude persistent movers.
        occup = np.mean([(np.abs(f.astype(np.int16) - bg).max(axis=2) > FG_T)
                         for f in frames[::6]], axis=0)
        decor = (occup > 0.35).astype(np.uint8)
        decor = cv2.dilate(decor, np.ones((5, 5), np.uint8))
        H, inliers = homography(bg, plate_small)
        print(f'{os.path.basename(mp4)}: {len(frames)} frames, homography inliers {inliers}')
        if H is None or inliers < 60:
            print('  SKIP: registration failed')
            continue
        for fi in range(0, len(frames), 4):
            fg = (np.abs(frames[fi].astype(np.int16) - bg).max(axis=2) > FG_T).astype(np.uint8)
            fg &= 1 - decor
            fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            n, lab = cv2.connectedComponents(fg)
            for c in range(1, n):
                comp = lab == c
                a = int(comp.sum())
                if not (MIN_CHAR <= a <= MAX_CHAR):
                    continue
                ys, xs = np.nonzero(comp)
                x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
                h, w = y1 - y0, x1 - x0
                if h < w * 1.15 or h > w * 5:        # walkers are tall
                    continue
                if a / max(1, h * w) < 0.35:          # swaying cloth is sparse
                    continue
                vis = comp
                occ = o2.column_fill_holes(vis, x0, y0, x1 + 1, y1 + 1)
                # warp evidence px + feet into plate space
                def warp(mask):
                    yy, xx = np.nonzero(mask)
                    if not len(yy):
                        return np.zeros_like(parts, dtype=bool)
                    pts = cv2.perspectiveTransform(
                        np.float32(np.stack([xx, yy], 1)).reshape(-1, 1, 2), H).reshape(-1, 2)
                    px = np.clip((pts[:, 0] * sx).astype(int), 0, parts.shape[1] - 1)
                    py = np.clip((pts[:, 1] * sy).astype(int), 0, parts.shape[0] - 1)
                    m = np.zeros_like(parts, dtype=bool)
                    m[py, px] = True
                    return m
                feet = cv2.perspectiveTransform(
                    np.float32([[[(x0 + x1) / 2, y1]]]), H).reshape(2)
                gy = int(np.clip(feet[1] * sy, 0, parts.shape[0] - 1))
                evidence.append(o2.MarkerEvidence(
                    (int(feet[0] * sx), gy), warp(vis), warp(occ), (0, 0)))
        dbg.append((os.path.basename(mp4), inliers))
        # ---- posterior update after THIS video ----
        it = len(dbg)
        base_row_l = {}
        for pid in blocking:
            m = parts == pid
            if m.any():
                base_row_l[pid] = int(np.where(m.any(axis=1))[0][-1])
        fp_l = frozenset(pid for pid in blocking)
        interior_l = o2.interior_mask(parts)
        post = o2.aggregate(evidence, parts, interior_l, blocking, 40, o2.CONCORDANCE, fp_l)
        counts = {v: sum(1 for r in post.values() if r['verdict'] == v)
                  for v in (o2.YSORT, o2.OVERHEAD, o2.CONTRA, o2.NOEV)}
        changes = []
        for pid, r in post.items():
            if prev_verdicts.get(pid) != r['verdict']:
                changes.append(f"{blocking.get(pid,'?')}: {prev_verdicts.get(pid,'new')} -> {r['verdict']}")
        prev_verdicts = {pid: r['verdict'] for pid, r in post.items()}
        tint = {o2.YSORT: (80, 230, 120), o2.OVERHEAD: (80, 170, 255),
                o2.CONTRA: (255, 90, 90), o2.NOEV: (150, 150, 150)}
        pb = plate[:, :, ::-1].astype(np.float32) * 0.32
        for pid, r in post.items():
            m = parts == pid
            pb[m] = pb[m] * 0.40 + np.array(tint[r['verdict']], np.float32) * 0.60
        oimg = Image.fromarray(pb.clip(0, 255).astype(np.uint8))
        oimg.thumbnail((1400, 1400))
        oimg.save(os.path.join(ROOT, f'docs/art-options/veo-iter{it}-zmap-{ROOM}.jpg'), quality=86)
        iter_records.append({'iteration': it, 'video': os.path.basename(mp4),
                             'cum_samples': len(evidence), 'verdicts': counts,
                             'changes': changes[:12]})
        print(f'iter {it} ({os.path.basename(mp4)}): cum {len(evidence)} samples, {counts}, {len(changes)} changes')

    print(f'total evidence samples: {len(evidence)}')
    base_row = {}
    for pid in blocking:
        m = parts == pid
        if m.any():
            base_row[pid] = int(np.where(m.any(axis=1))[0][-1])
    fp = frozenset(pid for pid in blocking)  # video chars roam everywhere; front coverage broad
    _bound = o2.bound
    def bound_hard(vals, conc, upper):
        # walkers must attest a bound from >=3 samples spanning >=24px of
        # ground-y, else the bound is a single-pass fluke
        if len(vals) < 3 or (max(vals) - min(vals)) < 24:
            return None
        if len(vals) >= 8:
            return float(np.percentile(vals, 20 if upper else 80))
        return _bound(vals, conc, upper)
    o2.bound = bound_hard
    base = o2.aggregate(evidence, parts, interior, blocking, 40, o2.CONCORDANCE, fp)
    counts = {v: sum(1 for r in base.values() if r['verdict'] == v)
              for v in (o2.YSORT, o2.OVERHEAD, o2.CONTRA, o2.NOEV)}
    print('veo-z verdicts:', counts)
    for pid, r in base.items():
        r['label'] = blocking.get(pid, '?')
    json.dump({'room': ROOM, 'videos': dbg, 'evidence_samples': len(evidence),
               'iterations': iter_records,
               'verdict_counts': counts,
               'objects': {str(k): v for k, v in sorted(base.items())}},
              open(os.path.join(ROOT, f'docs/art-options/veo-z-{ROOM}.json'), 'w'), indent=1)

    tint = {o2.YSORT: (80, 230, 120), o2.OVERHEAD: (80, 170, 255),
            o2.CONTRA: (255, 90, 90), o2.NOEV: (150, 150, 150)}
    b = plate[:, :, ::-1].astype(np.float32) * 0.32
    for pid, r in base.items():
        m = parts == pid
        b[m] = b[m] * 0.40 + np.array(tint[r['verdict']], np.float32) * 0.60
    o = Image.fromarray(b.clip(0, 255).astype(np.uint8))
    o.thumbnail((1400, 1400))
    o.save(os.path.join(ROOT, f'docs/art-options/veo-z-zmap-{ROOM}.jpg'), quality=86)


if __name__ == '__main__':
    main()
