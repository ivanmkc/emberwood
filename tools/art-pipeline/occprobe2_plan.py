#!/usr/bin/env python3
"""P0 of the multi-char occlusion experiment: deterministic probe-position
planning. For every blocking instance, find walkable positions BEHIND it
(character should be occluded) and IN FRONT of it (character should cover it),
then greedy set-cover to a minimal probe set with >=2 behind + >=1 front pairs
per coverable object. Pure numpy — no API calls. Emits the probe plan json,
a coverage report, and a position overlay for the board.
"""
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCENES = {
 'anchorroom': 'docs/art-options/nbp-scifi-anchor-clean.png',
 'night-bazaar': 'docs/art-options/rooms/night-bazaar/plate.png',
 'plaza-market-inside': 'docs/art-options/rooms/plaza-market-inside/plate.png',
}
CHAR_W, CHAR_H = 80, 176
GRID = 32          # candidate stride (plate px)
FRONT_MARGIN = 16  # gy must exceed object base by this to count as "front"
FRONT_MAX = 220    # and be within this range so the char actually overlaps it
MIN_OVERLAP = 350  # px of instance mask inside char bbox to count as a pair
BEHIND, FRONT = 'behind', 'front'  # categorical pair kinds (single source)


def char_bbox(x, y, W, H):
    return (max(0, x - CHAR_W // 2), max(0, y - CHAR_H), min(W, x + CHAR_W // 2), min(H, y + 6))


def run(room):
    plate = Image.open(os.path.join(ROOT, SCENES[room])).convert('RGB')
    W, H = plate.size
    inst = np.load(os.path.join(ROOT, 'tools', 'art-pipeline', f'_srcmasks_{room}.npz'))['inst']
    meta = json.load(open(os.path.join(ROOT, 'assets', 'rooms', f'{room}.instances.json')))
    walk = np.asarray(Image.open(os.path.join(
        ROOT, 'docs', 'art-options', 'bench', 'prompt', room, 'consensus-walk.png'))
        .convert('L').resize((W, H), Image.NEAREST)) > 127
    magp = os.path.join(ROOT, 'docs', 'art-options', f'magenta-ground-{room}.png')
    if os.path.exists(magp):
        mag = np.asarray(Image.open(magp).convert('L')) > 127
        stand = walk & mag  # both methods agree the character can stand here
    else:
        stand = walk
    # only the FEET need walkable ground (16px pad), not the full char width
    stand = cv2.erode(stand.astype(np.uint8), np.ones((6, 16), np.uint8)) > 0

    objs = {}
    for o in meta.get('instances', []):
        if not o.get('blocking'):
            continue
        m = inst == o['id']
        if m.sum() < 400:
            continue
        rows = np.where(m.any(axis=1))[0]
        objs[o['id']] = {'label': o.get('label', str(o['id'])), 'mask': m,
                         'top': int(rows[0]), 'base': int(rows[-1])}

    # candidate positions on a coarse grid
    cands = [(x, y) for y in range(CHAR_H + 8, H - 8, GRID)
             for x in range(CHAR_W, W - CHAR_W, GRID) if stand[y, x]]

    # pair table: candidate -> {(obj_id, 'behind'|'front')}
    pair_of = []
    for (x, y) in cands:
        bx0, by0, bx1, by1 = char_bbox(x, y, W, H)
        pairs = set()
        for oid, o in objs.items():
            ov = int(o['mask'][by0:by1, bx0:bx1].sum())
            if ov < MIN_OVERLAP:
                continue
            if y < o['base']:
                pairs.add((oid, BEHIND))
            elif o['base'] + FRONT_MARGIN < y <= o['base'] + FRONT_MAX:
                pairs.add((oid, FRONT))
        pair_of.append(pairs)

    need = {}
    for oid in objs:
        need[(oid, BEHIND)] = 2
        need[(oid, FRONT)] = 1

    chosen = []
    remaining = {k: v for k, v in need.items()}
    used = set()
    while any(v > 0 for v in remaining.values()):
        best, bestgain = None, 0
        for i, pairs in enumerate(pair_of):
            if i in used:
                continue
            gain = sum(1 for p in pairs if remaining.get(p, 0) > 0)
            if gain > bestgain:
                best, bestgain = i, gain
        if best is None or bestgain == 0:
            break
        used.add(best)
        chosen.append(best)
        for p in pair_of[best]:
            if remaining.get(p, 0) > 0:
                remaining[p] -= 1

    cov = {}
    for oid, o in objs.items():
        got_b = need[(oid, BEHIND)] - remaining[(oid, BEHIND)]
        got_f = need[(oid, FRONT)] - remaining[(oid, FRONT)]
        cov[oid] = {'label': o['label'], 'behind': got_b, 'front': got_f,
                    'full': got_b >= 2 and got_f >= 1,
                    'partial': (got_b + got_f) > 0}
    full = sum(1 for c in cov.values() if c['full'])
    part = sum(1 for c in cov.values() if c['partial'] and not c['full'])
    none = sum(1 for c in cov.values() if not c['partial'])

    probes = [{'pos': list(cands[i]),
               'pairs': sorted([[oid, kind] for oid, kind in pair_of[i]])}
              for i in chosen]
    out = os.path.join(ROOT, 'docs', 'art-options')
    json.dump({'room': room, 'objects_blocking': len(objs), 'probes': probes,
               'coverage': {str(k): v for k, v in cov.items()},
               'summary': {'probes': len(probes), 'full': full,
                           'partial': part, 'uncovered': none}},
              open(os.path.join(out, f'occprobe2-plan-{room}.json'), 'w'), indent=1)

    vis = plate.copy()
    dr = ImageDraw.Draw(vis)
    for i in chosen:
        x, y = cands[i]
        kinds = {k for _, k in pair_of[i]}
        col = (0, 255, 120) if kinds == {FRONT} else \
              (255, 80, 80) if kinds == {BEHIND} else (255, 220, 40)
        dr.ellipse([x - 10, y - 10, x + 10, y + 10], outline=col, width=4)
        bx0, by0, bx1, by1 = char_bbox(x, y, W, H)
        dr.rectangle([bx0, by0, bx1, by1], outline=col, width=2)
    vis.thumbnail((1400, 1400), Image.LANCZOS)
    vis.save(os.path.join(out, f'occprobe2-plan-{room}.jpg'), quality=86)
    print(f'[{room}] {len(objs)} blocking objects, {len(probes)} probes -> '
          f'full {full}, partial {part}, uncovered {none}')


if __name__ == '__main__':
    for r in (sys.argv[1:] or list(SCENES)):
        run(r)
