#!/usr/bin/env python3
"""Reproducible night-bazaar collision from the magenta-nowires consensus:
device-res mask -> close pinholes -> declared-exit bands from the shipped
collision -> east-corridor borrow -> config-space lane widening (17px device
= the engine's 8x8 hitbox) -> spawn component. One deterministic build."""
import json
import os

import cv2
import numpy as np
from PIL import Image
from skimage.morphology import skeletonize

import sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOM = sys.argv[1] if len(sys.argv) > 1 else 'night-bazaar'
K = 17

mag = np.asarray(Image.open(os.path.join(
    ROOT, f'docs/art-options/magenta-ground-{ROOM}-nowires.png')).convert('L')) > 127
bak = os.path.join(ROOT, f'docs/art-options/collision-backup-{ROOM}.png')
cur = os.path.join(ROOT, f'assets/rooms/{ROOM}.collision.png')
if not os.path.exists(bak):
    import shutil
    shutil.copy(cur, bak)
old = np.asarray(Image.open(bak).convert('L')) > 127
H, W = old.shape
walk = cv2.resize(mag.astype(np.uint8), (W, H), interpolation=cv2.INTER_AREA) > 0
walk = cv2.morphologyEx(walk.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)) > 0
inst = json.load(open(os.path.join(ROOT, f'assets/rooms/{ROOM}.instances.json')))
for e in inst.get('exits', []):
    x0, y0, x1, y1 = [v * 2 for v in e['rect']]
    if e['edge'] == 'n': y1 = min(y1, 36)
    if e['edge'] == 'w': x1 = min(x1, 36)
    if e['edge'] == 'e': x0 = max(x0, W - 36)
    walk[y0:y1, x0:x1] |= old[y0:y1, x0:x1]
def band_of(e):
    x0, y0, x1, y1 = [v * 2 for v in e['rect']]
    if e['edge'] == 'n': y1 = min(y1, 36)
    if e['edge'] == 's': y0 = max(y0, H - 36)
    if e['edge'] == 'w': x1 = min(x1, 36)
    if e['edge'] == 'e': x0 = max(x0, W - 36)
    return x0, y0, x1, y1

def reachable(w, e):
    n2, lab2 = cv2.connectedComponents(w.astype(np.uint8))
    sid2 = lab2[sy, sx]
    x0, y0, x1, y1 = band_of(e)
    return bool((lab2[y0:y1, x0:x1] == sid2).any())

sx, sy = [v * 2 for v in inst['spawn']]
# generic corridor borrow: any exit band unreachable from spawn borrows the
# SHIPPED collision 400px inward along the exit rect (evidence, not carving)
for e in inst.get('exits', []):
    if reachable(walk, e):
        continue
    x0, y0, x1, y1 = [v * 2 for v in e['rect']]
    if e['edge'] == 'e':   walk[y0:y1, W - 400:] |= old[y0:y1, W - 400:]
    elif e['edge'] == 'w': walk[y0:y1, :400] |= old[y0:y1, :400]
    elif e['edge'] == 'n': walk[:400, x0:x1] |= old[:400, x0:x1]
    elif e['edge'] == 's': walk[H - 400:, x0:x1] |= old[H - 400:, x0:x1]
    print(f'borrowed old corridor for unreachable {e["edge"]} exit')
if ROOM == 'night-bazaar':
    walk[80:200, 1080:1180] |= old[80:200, 1080:1180]  # located north pinch

free = cv2.erode(walk.astype(np.uint8), np.ones((K, K), np.uint8)) > 0
covered = cv2.dilate(free.astype(np.uint8), np.ones((K, K), np.uint8)) > 0
skel = skeletonize(walk & ~covered)
widened = cv2.dilate(skel.astype(np.uint8), np.ones((K + 2, K + 2), np.uint8)) > 0
walk = walk | (widened & (cv2.dilate(walk.astype(np.uint8), np.ones((11, 11), np.uint8)) > 0))

pre_frac = float(walk.mean())
n, lab = cv2.connectedComponents(walk.astype(np.uint8))
comp = lab == lab[sy, sx]
if float(comp.mean()) < 0.5 * pre_frac:
    # spawn sits in a sliver (e.g. doorway threshold magenta won't paint):
    # bridge with shipped collision around the spawn, then re-pick
    # mirror the engine's openBorderStrip: carve the exit-mouth stub inward
    # from the door rect until it meets painted floor (interiors keep door
    # mouths closed on disk; the engine opens them at load)
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    main = lab == int(np.argmax(sizes))   # carve must reach the MAIN floor,
    e = min(inst['exits'], key=lambda ex: abs(ex['rect'][0]*2 - sx) + abs(ex['rect'][1]*2 - sy))
    ex0, ey0, ex1, ey1 = [v * 2 for v in e['rect']]
    if e['edge'] in ('s', 'n'):
        rng = range(ey0, -1, -4) if e['edge'] == 's' else range(ey1, H, 4)
        hit = None
        for yy in rng:
            band = main[yy, ex0:ex1]
            if band.mean() > 0.4:
                hit = yy
                break
        if hit is None:
            raise SystemExit('FATAL: no floor within reach of door stub')
        ylo, yhi = (hit, min(H, ey1 + 4)) if e['edge'] == 's' else (max(0, ey0 - 4), hit)
        walk[ylo:yhi, ex0:ex1] = True
    else:
        rng = range(ex0, -1, -4) if e['edge'] == 'e' else range(ex1, W, 4)
        hit = None
        for xx in rng:
            if main[ey0:ey1, xx].mean() > 0.4:
                hit = xx
                break
        if hit is None:
            raise SystemExit('FATAL: no floor within reach of door stub')
        xlo, xhi = (hit, min(W, ex1 + 4)) if e['edge'] == 'e' else (max(0, ex0 - 4), hit)
        walk[ey0:ey1, xlo:xhi] = True
    print(f'spawn sliver: carved {e["edge"]}-door mouth stub to floor (engine-mirror)')
    n, lab = cv2.connectedComponents(walk.astype(np.uint8))
    comp = lab == lab[sy, sx]
walk = comp
# audit fix: a borrowed corridor can be dropped by the spawn-component step if
# it only connected through another borrowed region — verify AFTER selection
for e in inst.get('exits', []):
    if not reachable(walk, e):
        raise SystemExit(f'FATAL: exit {e["edge"]} unreachable after spawn-component '
                         '(borrow was disconnected) — needs manual corridor')
Image.fromarray((walk * 255).astype(np.uint8)).save(
    os.path.join(ROOT, f'assets/rooms/{ROOM}.collision.png'))
print('rebuilt: walk frac', round(float(walk.mean()), 3), '| all exits verified post-component')
