#!/usr/bin/env python3
"""Part-level breakdown of the consensus instance map (Ivan: "needs way more
breakdown into smaller parts").

Level 1 = consensus instances (identity + class, drift-free). Level 2 = every
instance larger than ~1.5 character-areas is subdivided by Felzenszwalb
regions computed on the PLATE inside the instance mask — parts inherit perfect
alignment by construction. Tiny fragments merge into their largest neighbor
until every part is at least MIN_PART px, so parts land at roughly character
scale — the resolution the z-probes actually need (a stall's canopy and
counter get different parts, hence different z evidence).

Outputs: _srcmasks_<room>-parts.npz (part ids + parent instance mapping),
parts-<room>-metrics.json, docs/art-options/segmap-parts-<room>.jpg.
"""
import colorsys
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image
from skimage.segmentation import felzenszwalb

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCENES = {
 'night-bazaar': 'docs/art-options/rooms/night-bazaar/plate.png',
 'anchorroom': 'docs/art-options/nbp-scifi-anchor-clean.png',
 'plaza-market-inside': 'docs/art-options/rooms/plaza-market-inside/plate.png',
}
CHAR_AREA = 80 * 176
SPLIT_ABOVE = int(CHAR_AREA * 1.5)   # instances bigger than this get subdivided
MIN_PART = 3000                       # merge fragments below this into neighbors
FELZ_SCALE, FELZ_SIGMA, FELZ_MINSIZE = 300, 0.8, 400


def subdivide(plate, mask):
    """Felzenszwalb inside one instance; returns local part labels (0=outside)."""
    ys, xs = np.nonzero(mask)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    crop = plate[y0:y1, x0:x1]
    sub = mask[y0:y1, x0:x1]
    seg = felzenszwalb(crop, scale=FELZ_SCALE, sigma=FELZ_SIGMA,
                       min_size=FELZ_MINSIZE) + 1
    seg[~sub] = 0
    # merge small parts into their largest touching neighbor
    while True:
        ids, cts = np.unique(seg[seg > 0], return_counts=True)
        small = [i for i, c in zip(ids, cts) if c < MIN_PART]
        if not small or len(ids) <= 1:
            break
        merged_any = False
        for sid in small:
            m = seg == sid
            ring = cv2.dilate(m.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
            nb = seg[ring & ~m & (seg > 0)]
            if len(nb):
                vals, vc = np.unique(nb, return_counts=True)
                seg[m] = vals[vc.argmax()]
                merged_any = True
        if not merged_any:
            break
    out = np.zeros_like(mask, dtype=np.int32)
    out[y0:y1, x0:x1] = seg
    return out


def run(room):
    plate = np.asarray(Image.open(os.path.join(ROOT, SCENES[room])).convert('RGB'))
    npz = os.path.join(ROOT, 'tools/art-pipeline', f'_srcmasks_{room}-aligned2.npz')
    if not os.path.exists(npz):
        npz = os.path.join(ROOT, 'tools/art-pipeline', f'_srcmasks_{room}-aligned.npz')
    inst = np.load(npz)['inst']

    parts = np.zeros_like(inst, dtype=np.int32)
    parent = {}
    next_id = 1
    n_split = 0
    for oid in np.unique(inst):
        if oid == 0:
            continue
        m = inst == oid
        area = int(m.sum())
        if area <= SPLIT_ABOVE:
            parts[m] = next_id
            parent[next_id] = int(oid)
            next_id += 1
            continue
        local = subdivide(plate, m)
        n_local = 0
        for pid in np.unique(local[local > 0]):
            parts[local == pid] = next_id
            parent[next_id] = int(oid)
            next_id += 1
            n_local += 1
        n_split += 1 if n_local > 1 else 0

    np.savez_compressed(os.path.join(
        ROOT, 'tools/art-pipeline', f'_srcmasks_{room}-parts.npz'), inst=parts)
    json.dump({'room': room, 'instances': int(len(np.unique(inst)) - 1),
               'parts': int(next_id - 1), 'instances_subdivided': n_split,
               'parent': {str(k): v for k, v in parent.items()}},
              open(os.path.join(ROOT, 'docs/art-options',
                                f'parts-{room}-metrics.json'), 'w'), indent=1)

    ov = plate.astype(np.float32) * 0.35
    for pid in np.unique(parts[parts > 0]):
        h = (int(pid) * 0.61803) % 1.0
        r, g, b = colorsys.hsv_to_rgb(h, 0.85, 1.0)
        m = parts == pid
        ov[m] = plate.astype(np.float32)[m] * 0.30 + \
            np.array([r * 255, g * 255, b * 255], np.float32) * 0.70
    f = parts.astype(np.float32)
    k = np.ones((3, 3), np.uint8)
    edges = (cv2.dilate(f, k) != cv2.erode(f, k)) & (parts > 0)
    ov[edges] = [10, 10, 10]
    o = Image.fromarray(ov.clip(0, 255).astype(np.uint8))
    o.thumbnail((1400, 1400))
    o.save(os.path.join(ROOT, 'docs/art-options', f'segmap-parts-{room}.jpg'), quality=88)
    print(f'[{room}] {len(np.unique(inst)) - 1} instances -> {next_id - 1} parts '
          f'({n_split} subdivided)')


if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else 'night-bazaar')
