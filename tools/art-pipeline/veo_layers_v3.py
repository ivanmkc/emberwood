#!/usr/bin/env python3
"""4-layer estimator v3: MAGENTA-KEYED walkers (GEPA-locked camera, scene-
absent key color) on stabilized videos. Walker = pixels within 90 of #FF00FF
(smoke/steam/flicker cannot fake this). Occluder holes additionally require
hole pixels to MATCH the static background (Ivan: transient effects like
smoke in front of the walker must not count as occluders)."""
import glob
import json
import os

import cv2
import numpy as np
from PIL import Image

import occprobe2_run as o2
import veo_z as vz

ROOT = o2.ROOT
ROOM = 'night-bazaar'
MAG = np.array([255, 0, 255], np.int16)
KEY_R = 90
MIN_VOTE_PX = 60
CONFLICT_RATIO = 0.35
STATIC_T = 40


def main():
    parts = np.load(os.path.join(ROOT, f'tools/art-pipeline/_srcmasks_{ROOM}-parts.npz'))['inst']
    ground = np.asarray(Image.open(os.path.join(
        ROOT, f'docs/art-options/magenta-ground-{ROOM}-nowires.png')).convert('L')) > 127
    coll = np.asarray(Image.open(os.path.join(
        ROOT, f'assets/rooms/{ROOM}.collision.png')).convert('L').resize(
        (parts.shape[1], parts.shape[0]), Image.NEAREST)) > 127
    plate = cv2.imread(os.path.join(ROOT, f'docs/art-options/rooms/{ROOM}/plate.png'))
    plate_small = cv2.resize(plate, (1200, 900))
    sx, sy = plate.shape[1] / 1200, plate.shape[0] / 900
    pids = [int(p) for p in np.unique(parts) if p > 0]
    blocks = {}
    for pid in pids:
        m = parts == pid
        nong = m & ~ground
        blocks[pid] = bool(nong.sum() and (~coll[nong]).mean() > 0.5)
    votes_occ = {p: 0 for p in pids}
    votes_under = {p: 0 for p in pids}
    feet_hits = {p: 0 for p in pids}
    records = []
    for it, mp4 in enumerate(sorted(glob.glob('/home/ivanmkc/.claude/jobs/92f6b395/tmp/veostab/mwalk*_stab.mp4')), 1):
        cap = cv2.VideoCapture(mp4)
        frames = []
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            frames.append(cv2.resize(fr, (1200, 675)))
        cap.release()
        bg = np.median(np.stack(frames[::6]), axis=0).astype(np.uint8)
        H, inl = vz.homography(bg, plate_small)
        print(f'iter {it}: inliers {inl}')
        if H is None or inl < 60:
            records.append({'iteration': it, 'video': os.path.basename(mp4), 'skipped': f'registration ({inl})'})
            continue
        for fi in range(0, len(frames), 4):
            rgb = frames[fi][:, :, ::-1].astype(np.int16)
            keyed = (np.linalg.norm(rgb - MAG, axis=2) < KEY_R).astype(np.uint8)
            keyed = cv2.morphologyEx(keyed, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            n, lab = cv2.connectedComponents(keyed)
            static = np.abs(frames[fi].astype(np.int16) - bg).max(axis=2) < STATIC_T
            for c in range(1, n):
                comp = lab == c
                a = int(comp.sum())
                if not (400 <= a <= 30000):
                    continue
                ys, xs = np.nonzero(comp)
                x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
                occ = o2.column_fill_holes(comp.astype(bool), x0, y0, x1 + 1, y1 + 1)
                occ &= static  # smoke-in-front cannot fake an occluder
                fx, fy = (x0 + x1) / 2, y1
                fp2 = cv2.perspectiveTransform(np.float32([[[fx, fy]]]), H).reshape(2)
                fpx = int(np.clip(fp2[0] * sx, 0, parts.shape[1] - 1))
                fpy = int(np.clip(fp2[1] * sy, 0, parts.shape[0] - 1))
                pid_at_feet = int(parts[fpy, fpx])
                if pid_at_feet > 0 and not ground[fpy, fpx]:
                    feet_hits[pid_at_feet] += 1
                for kind, m in (('under', comp.astype(bool)), ('occ', occ)):
                    yy, xx = np.nonzero(m)
                    if not len(yy):
                        continue
                    pts = cv2.perspectiveTransform(
                        np.float32(np.stack([xx, yy], 1)).reshape(-1, 1, 2), H).reshape(-1, 2)
                    px = np.clip((pts[:, 0] * sx).astype(int), 0, parts.shape[1] - 1)
                    py = np.clip((pts[:, 1] * sy).astype(int), 0, parts.shape[0] - 1)
                    ids, cts = np.unique(parts[py, px], return_counts=True)
                    for pid, ct in zip(ids, cts):
                        if pid > 0 and ct >= MIN_VOTE_PX:
                            (votes_under if kind == 'under' else votes_occ)[int(pid)] += int(ct)
        layers = {}
        for pid in pids:
            o_, u_ = votes_occ[pid], votes_under[pid]
            pt = feet_hits[pid] >= 3
            if o_ + u_ == 0:
                lay = 'collision' if (blocks[pid] and not pt) else 'collision-prior'
            elif min(o_, u_) / (o_ + u_) >= CONFLICT_RATIO and o_ + u_ >= 4 * MIN_VOTE_PX:
                lay = 'conflict'
            elif o_ > u_:
                lay = 'overhead'
            else:
                lay = 'ground'
            layers[pid] = lay
        prev = records[-1].get('layers', {}) if records else {}
        changes = [f'part{p}: {prev[str(p)]} -> {l}' for p, l in layers.items()
                   if prev.get(str(p)) not in (None, l)]
        counts = {}
        for l in layers.values():
            counts[l] = counts.get(l, 0) + 1
        col_map = {'ground': (255, 80, 255), 'collision': (255, 150, 40),
                   'collision-prior': (150, 150, 150), 'overhead': (80, 160, 255),
                   'conflict': (255, 60, 60)}
        b = plate[:, :, ::-1].astype(np.float32) * 0.30
        b[ground] = b[ground] * 0.55 + np.array((255, 80, 255), np.float32) * 0.225
        for pid in pids:
            m = (parts == pid) & ~ground
            b[m] = b[m] * 0.35 + np.array(col_map[layers[pid]], np.float32) * 0.65
        img = Image.fromarray(b.clip(0, 255).astype(np.uint8))
        img.thumbnail((1400, 1400))
        img.save(os.path.join(ROOT, f'docs/art-options/layersv3-iter{it}-{ROOM}.jpg'), quality=86)
        records.append({'iteration': it, 'video': os.path.basename(mp4), 'counts': counts,
                        'changes': changes[:12], 'layers': {str(k): v for k, v in layers.items()}})
        print(f'iter {it}: {counts}, {len(changes)} changes')
    json.dump({'room': ROOM, 'iterations': [{k: v for k, v in r.items() if k != 'layers'} for r in records]},
              open(os.path.join(ROOT, f'docs/art-options/veo-layersv3-{ROOM}.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
