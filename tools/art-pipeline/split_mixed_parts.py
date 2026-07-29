#!/usr/bin/env python3
"""Re-subdivide vertically tall parts that mix suspended and grounded content.

Parts spanning >2.5 walker heights (225 plate px) are re-split via
Felzenszwalb on the plate inside the mask, using finer parameters than
segment_parts.py (~4x lower FELZ_MINSIZE and MIN_PART).  Non-tall parts
keep their original ids unchanged (gold comparability preserved BY
CONSTRUCTION).

Outputs:
  _srcmasks_<room>-parts2.npz  — new part-id map
  split-mixed-<room>.json      — parent mapping + split stats
"""
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image
from skimage.segmentation import felzenszwalb

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WALKER_H = 90
TALL_THRESH = 2.5 * WALKER_H

FELZ_SCALE = 300
FELZ_SIGMA = 0.8
FELZ_MINSIZE = 100     # ~4x lower than segment_parts.py (400)
MIN_PART = 750          # ~4x lower than segment_parts.py (3000)


def subdivide_fine(plate, mask):
    """Felzenszwalb inside one part with finer params; returns local labels."""
    ys, xs = np.nonzero(mask)
    y0, y1 = ys.min(), ys.max() + 1
    x0, x1 = xs.min(), xs.max() + 1
    crop = plate[y0:y1, x0:x1]
    sub = mask[y0:y1, x0:x1]
    seg = felzenszwalb(crop, scale=FELZ_SCALE, sigma=FELZ_SIGMA,
                       min_size=FELZ_MINSIZE) + 1
    seg[~sub] = 0
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
    plate_path = os.path.join(ROOT, 'docs/art-options/rooms', room, 'plate.png')
    plate = np.asarray(Image.open(plate_path).convert('RGB'))
    npz_path = os.path.join(ROOT, 'tools/art-pipeline',
                            f'_srcmasks_{room}-parts.npz')
    parts = np.load(npz_path)['inst']

    pids = sorted([int(p) for p in np.unique(parts) if p > 0])
    max_id = max(pids)
    next_id = max_id + 1

    parts2 = parts.copy()
    parent_map = {}
    split_stats = []

    for pid in pids:
        m = parts == pid
        rows = np.any(m, axis=1)
        ys = np.where(rows)[0]
        vspan = ys[-1] - ys[0] + 1
        if vspan <= TALL_THRESH:
            parent_map[pid] = [pid]
            continue
        local = subdivide_fine(plate, m)
        local_ids = sorted([int(i) for i in np.unique(local) if i > 0])
        if len(local_ids) <= 1:
            parent_map[pid] = [pid]
            continue
        new_pids = []
        for lid in local_ids:
            sub_mask = local == lid
            parts2[sub_mask] = next_id
            new_pids.append(next_id)
            next_id += 1
        parts2[m & (local == 0)] = 0
        parent_map[pid] = new_pids
        sub_areas = [int((parts2 == np_).sum()) for np_ in new_pids]
        split_stats.append({
            'old_pid': int(pid), 'vspan': int(vspan),
            'n_sub': len(new_pids), 'new_pids': [int(x) for x in new_pids],
            'sub_areas': sub_areas
        })
        print(f'  pid {pid}: vspan={vspan}px -> {len(new_pids)} sub-parts '
              f'{new_pids}')

    out_npz = os.path.join(ROOT, 'tools/art-pipeline',
                           f'_srcmasks_{room}-parts2.npz')
    np.savez_compressed(out_npz, inst=parts2)

    out_json = os.path.join(ROOT, 'docs/art-options',
                            f'split-mixed-{room}.json')
    summary = {
        'room': room,
        'original_parts': len(pids),
        'tall_threshold_px': int(TALL_THRESH),
        'parts_split': len(split_stats),
        'new_total_parts': int(next_id - 1),
        'new_sub_parts': int(next_id - 1 - len(pids)),
        'parent_map': {str(k): [int(x) for x in v] for k, v in parent_map.items()},
        'splits': split_stats,
    }
    json.dump(summary, open(out_json, 'w'), indent=1)

    print(f'\n[{room}] {len(pids)} parts, {len(split_stats)} split '
          f'-> {next_id - 1} total ({next_id - 1 - len(pids)} new sub-parts)')
    print(f'  wrote {out_npz}')
    print(f'  wrote {out_json}')
    return summary


if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else 'night-bazaar')
