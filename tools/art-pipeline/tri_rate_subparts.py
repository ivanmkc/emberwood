#!/usr/bin/env python3
"""Tri-rater overhead labeling for newly split sub-parts only.

Reuses the tri_rater_overhead machinery (prompt, rate function, crop) but
only rates the NEW sub-parts from split_mixed_parts.py.  Old untouched
parts keep their existing gold labels.
"""
import asyncio
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image
from google import genai
from google.genai import errors as genai_errors

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OVERHEAD, GROUNDED = 'overhead', 'grounded'
RATER_MODEL = 'gemini-3.1-pro-preview'
N_RATERS = 3
MIN_PART_PX = 900
PAD = 90
SEM = asyncio.Semaphore(8)

PROMPT = (
 'You see a pixel-art game scene crop. The object outlined in cyan is one part '
 'of the scene. Question: is this part SUSPENDED above walking height — an '
 'awning, canopy, hanging sign, overhead wire/lantern, roof edge, doorway '
 'lintel — something a game character would walk UNDER (it should be drawn '
 'over the character)? Or is it GROUNDED — standing on / lying on the floor, '
 'a wall at ground level, furniture, crates, stalls (bases), machines? '
 'Answer with exactly one word: OVERHEAD or GROUNDED.'
)


def part_crop(plate, mask):
    ys, xs = np.nonzero(mask)
    y0 = max(0, ys.min() - PAD); y1 = min(plate.shape[0], ys.max() + PAD)
    x0 = max(0, xs.min() - PAD); x1 = min(plate.shape[1], xs.max() + PAD)
    crop = plate[y0:y1, x0:x1].copy()
    sub = mask[y0:y1, x0:x1]
    edge = cv2.dilate(sub.astype(np.uint8), np.ones((5, 5), np.uint8)) > sub
    crop[edge] = (0, 255, 255)
    im = Image.fromarray(crop)
    im.thumbnail((640, 640))
    return im


async def rate(client, im):
    async with SEM:
        for _ in range(4):
            try:
                r = await client.aio.models.generate_content(
                    model=RATER_MODEL, contents=[im, PROMPT])
                t = (r.text or '').strip().upper()
                if OVERHEAD.upper() in t:
                    return OVERHEAD
                if GROUNDED.upper() in t:
                    return GROUNDED
            except (genai_errors.APIError, ValueError, OSError):
                await asyncio.sleep(5)
        return None


async def main(room='night-bazaar'):
    plate = np.asarray(Image.open(os.path.join(
        ROOT, 'docs/art-options/rooms', room, 'plate.png')).convert('RGB'))
    parts2 = np.load(os.path.join(
        ROOT, 'tools/art-pipeline', f'_srcmasks_{room}-parts2.npz'))['inst']
    split = json.load(open(os.path.join(
        ROOT, 'docs/art-options', f'split-mixed-{room}.json')))
    parent_map = split['parent_map']

    new_sub_pids = []
    for old_pid, new_pids in parent_map.items():
        if new_pids != [int(old_pid)]:
            new_sub_pids.extend(new_pids)

    ratable = [p for p in new_sub_pids
               if int((parts2 == p).sum()) >= MIN_PART_PX]
    print(f'[{room}] {len(new_sub_pids)} new sub-parts, '
          f'{len(ratable)} ratable (>= {MIN_PART_PX}px)')

    client = genai.Client(vertexai=True, project='adk-coding-agents',
                          location='global')
    crops = {pid: part_crop(plate, parts2 == pid) for pid in ratable}

    raters = {}
    for ri in range(1, N_RATERS + 1):
        res = await asyncio.gather(*[rate(client, crops[p]) for p in ratable])
        raters[f'R{ri}'] = {str(p): v for p, v in zip(ratable, res) if v}
        n_over = sum(1 for v in res if v == OVERHEAD)
        print(f'  R{ri}: {n_over} overhead / {len(ratable)}')

    keys = [str(p) for p in ratable]
    def agree(a, b):
        common = [k for k in keys if k in raters[a] and k in raters[b]]
        if not common:
            return 0.0
        return round(sum(raters[a][k] == raters[b][k]
                         for k in common) / len(common), 2)

    agreement = {'12': agree('R1', 'R2'), '13': agree('R1', 'R3'),
                 '23': agree('R2', 'R3')}
    unanimous_over = [k for k in keys
                      if all(raters[f'R{i}'].get(k) == OVERHEAD
                             for i in range(1, N_RATERS + 1))]
    gold = {k: (OVERHEAD if k in unanimous_over else GROUNDED) for k in keys}
    too_small = [p for p in new_sub_pids
                 if int((parts2 == p).sum()) < MIN_PART_PX]

    disagreed = [k for k in keys
                 if len(set(raters[f'R{i}'].get(k) for i in range(1, N_RATERS + 1))) > 1]

    out = {
        'room': room,
        'sub_parts_rated': len(ratable),
        'sub_parts_too_small': len(too_small),
        'raters': raters,
        'gold': gold,
        'unanimous_overhead': unanimous_over,
        'disagreed': disagreed,
        'agreement': agreement,
    }
    out_path = os.path.join(ROOT, 'docs/art-options',
                            f'z-source-validation-{room}-parts2.json')
    json.dump(out, open(out_path, 'w'), indent=1)
    print(f'  unanimous overhead: {len(unanimous_over)} sub-parts')
    print(f'  disagreed: {len(disagreed)} sub-parts')
    print(f'  agreement: {agreement}')
    print(f'  wrote {out_path}')


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else 'night-bazaar'))
