#!/usr/bin/env python3
"""Per-object instance-mask realignment (Ivan: "your masks are misaligned").

The instance masks come from single judge-gated NBP repaint rolls, which carry
the model's spatial jitter (~15-30px, varying by region) — unlike the walk
mask, whose 5-roll pixel consensus averages drift out. Fix: for each instance,
search the +-R translation that best aligns its boundary with the plate's
Canny edges, then rebuild the instance array from the snapped masks.

Outputs: _srcmasks_<room>-aligned.npz, realign-<room>-metrics.json,
docs/art-options/inst-edges-<room>-aligned.jpg (before/after visual).
"""
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCENES = {
 'anchorroom': 'docs/art-options/nbp-scifi-anchor-clean.png',
 'night-bazaar': 'docs/art-options/rooms/night-bazaar/plate.png',
 'plaza-market-inside': 'docs/art-options/rooms/plaza-market-inside/plate.png',
}
R = 32          # search radius (px)
STEP = 2        # coarse step; refined +-2 at step 1
EDGE_DILATE = 2  # tolerance band on plate edges


def boundary(mask):
    k = np.ones((3, 3), np.uint8)
    m = mask.astype(np.uint8)
    return (cv2.dilate(m, k) > 0) & (cv2.erode(m, k) == 0)


def score_at(bnd_pts, edge, dy, dx, H, W):
    yy = bnd_pts[0] + dy
    xx = bnd_pts[1] + dx
    ok = (yy >= 0) & (yy < H) & (xx >= 0) & (xx < W)
    if not ok.any():
        return 0.0
    return float(edge[yy[ok], xx[ok]].mean())


def best_offset(bnd_pts, edge, H, W):
    best = (0.0, 0, 0)
    for dy in range(-R, R + 1, STEP):
        for dx in range(-R, R + 1, STEP):
            s = score_at(bnd_pts, edge, dy, dx, H, W)
            if s > best[0]:
                best = (s, dy, dx)
    _, cy, cx = best
    for dy in range(cy - 2, cy + 3):
        for dx in range(cx - 2, cx + 3):
            s = score_at(bnd_pts, edge, dy, dx, H, W)
            if s > best[0]:
                best = (s, dy, dx)
    return best


def run(room):
    plate = np.asarray(Image.open(os.path.join(ROOT, SCENES[room])).convert('L'))
    H, W = plate.shape
    edge = cv2.Canny(plate, 60, 120)
    edge = cv2.dilate(edge, np.ones((EDGE_DILATE * 2 + 1,) * 2, np.uint8)) > 0

    inst = np.load(os.path.join(ROOT, 'tools/art-pipeline', f'_srcmasks_{room}.npz'))['inst']
    meta = json.load(open(os.path.join(ROOT, 'assets/rooms', f'{room}.instances.json')))
    ids = [o['id'] for o in meta['instances']]

    aligned = np.zeros_like(inst)
    report = {}
    # paint largest first so smaller objects win overlap conflicts
    order = sorted(ids, key=lambda i: int((inst == i).sum()), reverse=True)
    for oid in order:
        m = inst == oid
        n = int(m.sum())
        if n < 400:
            continue
        bnd = np.nonzero(boundary(m))
        s0 = score_at(bnd, edge, 0, 0, H, W)
        s1, dy, dx = best_offset(bnd, edge, H, W)
        if s1 - s0 < 0.03 or (dy == 0 and dx == 0):
            dy = dx = 0
            s1 = s0
        ys, xs = np.nonzero(m)
        yy = np.clip(ys + dy, 0, H - 1)
        xx = np.clip(xs + dx, 0, W - 1)
        aligned[yy, xx] = oid
        report[oid] = {'px': n, 'dy': int(dy), 'dx': int(dx),
                       'edge_agree_before': round(s0, 3),
                       'edge_agree_after': round(s1, 3)}

    np.savez_compressed(os.path.join(ROOT, 'tools/art-pipeline',
                                     f'_srcmasks_{room}-aligned.npz'), inst=aligned)
    moved = [r for r in report.values() if r['dy'] or r['dx']]
    mags = [max(abs(r['dy']), abs(r['dx'])) for r in moved]
    summary = {'objects': len(report), 'moved': len(moved),
               'median_shift': int(np.median(mags)) if mags else 0,
               'max_shift': int(np.max(mags)) if mags else 0,
               'mean_agree_before': round(float(np.mean(
                   [r['edge_agree_before'] for r in report.values()])), 3),
               'mean_agree_after': round(float(np.mean(
                   [r['edge_agree_after'] for r in report.values()])), 3)}
    json.dump({'room': room, 'summary': summary,
               'objects': {str(k): v for k, v in report.items()}},
              open(os.path.join(ROOT, 'docs/art-options',
                                f'realign-{room}-metrics.json'), 'w'), indent=1)

    rgb = np.asarray(Image.open(os.path.join(ROOT, SCENES[room])).convert('RGB'))
    f = aligned.astype(np.float32)
    k = np.ones((3, 3), np.uint8)
    edges2 = cv2.dilate(f, k) != cv2.erode(f, k)
    v = rgb.astype(np.float32) * 0.45
    v[edges2] = [80, 255, 120]
    o = Image.fromarray(v.clip(0, 255).astype(np.uint8))
    o.thumbnail((1400, 1400))
    o.save(os.path.join(ROOT, 'docs/art-options',
                        f'inst-edges-{room}-aligned.jpg'), quality=88)
    print(f'[{room}] {json.dumps(summary)}')


if __name__ == '__main__':
    for r in (sys.argv[1:] or ['night-bazaar']):
        run(r)
