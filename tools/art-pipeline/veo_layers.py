#!/usr/bin/env python3
"""4-LAYER model per Ivan (replaces z-indexes): render order is
GROUND (magenta 5-pass consensus) -> CHARACTER -> COLLISION (occludes+blocks)
-> OVERHEAD (occludes, no collision).

PRIOR: ground = magenta consensus; every segmented object starts in COLLISION
(blocking known deterministically from the shipped collision mask).
UPDATE: every walk-video frame votes per object — character drawn OVER the
object => object does not occlude (drop toward GROUND); object drawn over the
character => occludes (stay COLLISION if it blocks, promote to OVERHEAD if
its pixels don't block). Objects with strong votes BOTH ways are flagged
CONFLICT (the y-sort exceptions Ivan's model deliberately squeezes out).
Emits a per-iteration 4-layer estimate image after each video.
"""
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
MIN_VOTE_PX = 60
CONFLICT_RATIO = 0.35   # minority side >= this fraction => conflict


def main():
    parts = np.load(os.path.join(ROOT, f'tools/art-pipeline/_srcmasks_{ROOM}-parts.npz'))['inst']
    ground = np.asarray(Image.open(os.path.join(
        ROOT, f'docs/art-options/magenta-ground-{ROOM}-nowires.png')).convert('L')) > 127
    coll = np.asarray(Image.open(os.path.join(
        ROOT, f'assets/rooms/{ROOM}.collision.png')).convert('L').resize(
        (parts.shape[1], parts.shape[0]), Image.NEAREST)) > 127  # walkable=True
    plate = cv2.imread(os.path.join(ROOT, f'docs/art-options/rooms/{ROOM}/plate.png'))
    plate_small = cv2.resize(plate, (1200, 900))
    sx, sy = plate.shape[1] / 1200, plate.shape[0] / 900

    pids = [int(p) for p in np.unique(parts) if p > 0]
    blocks = {}   # does the part block? (deterministic prior from collision)
    for pid in pids:
        m = parts == pid
        nong = m & ~ground
        blocks[pid] = bool(nong.sum() and (~coll[nong]).mean() > 0.5)
    votes_occ = {p: 0 for p in pids}     # object drew over character
    votes_under = {p: 0 for p in pids}   # character drew over object
    feet_hits = {p: 0 for p in pids}     # walker feet INSIDE part footprint = passes through = non-collider
    records = []

    STAB = '/home/ivanmkc/.claude/jobs/92f6b395/tmp/veostab'
    for it, mp4 in enumerate(sorted(glob.glob(os.path.join(STAB, 'walk*_stab.mp4'))), 1):
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
        H, inl = vz.homography(bg, plate_small)
        if H is None or inl < 60:
            records.append({'iteration': it, 'video': os.path.basename(mp4),
                            'skipped': f'registration failed ({inl} inliers)'})
            print(f'iter {it}: SKIP registration ({inl})')
            continue
        occup = np.mean([(np.abs(f.astype(np.int16) - bg).max(axis=2) > vz.FG_T)
                         for f in frames[::6]], axis=0)
        decor = cv2.dilate((occup > 0.35).astype(np.uint8), np.ones((5, 5), np.uint8))
        for fi in range(0, len(frames), 4):
            fg = (np.abs(frames[fi].astype(np.int16) - bg).max(axis=2) > vz.FG_T).astype(np.uint8)
            fg &= 1 - decor
            fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            n, lab = cv2.connectedComponents(fg)
            for c in range(1, n):
                comp = lab == c
                a = int(comp.sum())
                if not (vz.MIN_CHAR <= a <= vz.MAX_CHAR):
                    continue
                ys, xs = np.nonzero(comp)
                x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
                h, w = y1 - y0, x1 - x0
                if h < w * 1.15 or h > w * 5 or a / max(1, h * w) < 0.35:
                    continue
                occ = o2.column_fill_holes(comp, x0, y0, x1 + 1, y1 + 1)
                fx, fy = (x0 + x1) / 2, y1  # feet point in video space
                fp2 = cv2.perspectiveTransform(np.float32([[[fx, fy]]]), H).reshape(2)
                fpx = int(np.clip(fp2[0] * sx, 0, parts.shape[1] - 1))
                fpy = int(np.clip(fp2[1] * sy, 0, parts.shape[0] - 1))
                pid_at_feet = int(parts[fpy, fpx])
                if pid_at_feet > 0 and not ground[fpy, fpx]:
                    feet_hits[pid_at_feet] += 1
                for kind, m in (('under', comp), ('occ', occ)):
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
        # ---- layer estimate after this video ----
        layers = {}
        changes = []
        for pid in pids:
            o_, u_ = votes_occ[pid], votes_under[pid]
            passes_through = feet_hits[pid] >= 3
            # Ivan's simplification: a collider can never be overlapped, so
            # OBSERVED occlusion implies the character got under/behind it =>
            # OVERHEAD; observed char-over => GROUND; untouched => COLLISION.
            if o_ + u_ == 0:
                lay = 'collision' if (blocks[pid] and not passes_through) else 'collision-prior'
            elif min(o_, u_) / (o_ + u_) >= CONFLICT_RATIO and o_ + u_ >= 4 * MIN_VOTE_PX:
                lay = 'conflict'
            elif o_ > u_:
                lay = 'overhead'
            else:
                lay = 'ground'
            layers[pid] = lay
        prev = records[-1]['layers'] if records and 'layers' in records[-1] else {}
        for pid, lay in layers.items():
            if prev.get(str(pid), prev.get(pid)) not in (None, lay):
                changes.append(f'part{pid}: {prev.get(str(pid), prev.get(pid))} -> {lay}')
        counts = {}
        for lay in layers.values():
            counts[lay] = counts.get(lay, 0) + 1
        # render: ground magenta, collision orange, overhead blue, conflict red,
        # collision-prior (no evidence, doesn't block) light gray
        col_map = {'ground': (255, 80, 255), 'collision': (255, 150, 40),
                   'collision-prior': (150, 150, 150), 'overhead': (80, 160, 255),
                   'conflict': (255, 60, 60)}
        b = plate[:, :, ::-1].astype(np.float32) * 0.30
        gm = ground
        b[gm] = b[gm] * 0.55 + np.array((255, 80, 255), np.float32) * 0.45 * 0.5
        for pid in pids:
            m = (parts == pid) & ~gm
            b[m] = b[m] * 0.35 + np.array(col_map[layers[pid]], np.float32) * 0.65
        img = Image.fromarray(b.clip(0, 255).astype(np.uint8))
        img.thumbnail((1400, 1400))
        img.save(os.path.join(ROOT, f'docs/art-options/layers-iter{it}-{ROOM}.jpg'), quality=86)
        records.append({'iteration': it, 'video': os.path.basename(mp4),
                        'counts': counts, 'changes': changes[:12],
                        'layers': {str(k): v for k, v in layers.items()}})
        print(f'iter {it} ({os.path.basename(mp4)}): {counts}, {len(changes)} changes')

    json.dump({'room': ROOM, 'model': 'ground->character->collision->overhead',
               'iterations': [{k: v for k, v in r.items() if k != 'layers'} for r in records],
               'final_layers': records[-1].get('layers', {}) if records else {}},
              open(os.path.join(ROOT, f'docs/art-options/veo-layers-{ROOM}.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
