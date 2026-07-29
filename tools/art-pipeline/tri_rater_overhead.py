#!/usr/bin/env python3
"""Tri-rater overhead labeling — the validated production path for the
OVERHEAD (occludes, no collision) layer. Three independent VLM raters label
every part crop as overhead (suspended: character walks UNDER it) or
grounded; only UNANIMOUS overhead parts ship. Bazaar validation: fused
models P<=0.56 alone, tri-rater unanimity 0.90-0.94 pairwise agreement.

Output: docs/art-options/z-source-validation-<room>.json (same schema as the
bazaar/anchor gold files) + assets/rooms/<asset>.overhead.png where alpha =
unanimous parts and RGB comes from the SHIPPED ROOM ASSET itself, so a
misregistered mask cannot paint a ghost (identical pixels are invisible).
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
OVERHEAD, GROUNDED = 'overhead', 'grounded'   # the rater label vocabulary
RATER_MODEL = 'gemini-3.1-pro-preview'
N_RATERS = 3
MIN_PART_PX = 900          # below this a part is too small to judge or matter
PAD = 90                   # context pixels around the part crop
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

SCENES = {
 'night-bazaar': ('docs/art-options/rooms/night-bazaar/plate.png', 'night-bazaar'),
 'anchorroom': ('docs/art-options/rooms/anchorroom/plate.png', 'anchorroom'),
 'plaza-market-inside': ('docs/art-options/rooms/plaza-market-inside/plate.png',
                         'plaza-market-inside'),
}


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


async def main(room):
    plate_rel, asset = SCENES[room]
    plate = np.asarray(Image.open(os.path.join(ROOT, plate_rel)).convert('RGB'))
    parts = np.load(os.path.join(ROOT, 'tools/art-pipeline',
                                 f'_srcmasks_{room}-parts.npz'))['inst']
    pids = [int(p) for p in np.unique(parts) if p > 0
            and (parts == p).sum() >= MIN_PART_PX]
    print(f'[{room}] rating {len(pids)} parts x {N_RATERS} raters')

    client = genai.Client(vertexai=True, project='adk-coding-agents',
                          location='global')
    crops = {pid: part_crop(plate, parts == pid) for pid in pids}
    raters = {}
    for ri in range(1, N_RATERS + 1):
        res = await asyncio.gather(*[rate(client, crops[p]) for p in pids])
        raters[f'R{ri}'] = {str(p): v for p, v in zip(pids, res) if v}
        n_over = sum(1 for v in res if v == OVERHEAD)
        print(f'  R{ri}: {n_over} overhead / {len(pids)}')

    keys = [str(p) for p in pids]
    def agree(a, b):
        common = [k for k in keys if k in raters[a] and k in raters[b]]
        if not common:
            return 0.0
        return round(sum(raters[a][k] == raters[b][k] for k in common) / len(common), 2)
    agreement = {'12': agree('R1', 'R2'), '13': agree('R1', 'R3'), '23': agree('R2', 'R3')}
    unanimous = [k for k in keys
                 if all(raters[f'R{i}'].get(k) == OVERHEAD for i in range(1, N_RATERS + 1))]
    gold = {k: (OVERHEAD if k in unanimous else GROUNDED) for k in keys}
    out = {'room': room, 'raters': raters, 'gold': gold,
           'unanimous_overhead': unanimous, 'agreement': agreement}
    json.dump(out, open(os.path.join(
        ROOT, 'docs/art-options', f'z-source-validation-{room}.json'), 'w'), indent=1)
    print(f'  unanimous overhead: {len(unanimous)} parts, agreement {agreement}')

    room_img = np.asarray(Image.open(os.path.join(
        ROOT, 'assets', 'rooms', f'{asset}.jpg')).convert('RGB'))
    alpha = np.zeros(parts.shape, bool)
    for k in unanimous:
        alpha |= parts == int(k)
    a_small = np.asarray(Image.fromarray((alpha * 255).astype(np.uint8))
                         .resize((room_img.shape[1], room_img.shape[0]),
                                 Image.Resampling.NEAREST))
    rgba = np.dstack([room_img, a_small])
    Image.fromarray(rgba, 'RGBA').save(os.path.join(
        ROOT, 'assets', 'rooms', f'{asset}.overhead.png'))
    ov = room_img.astype(np.float32) * 0.4
    ov[a_small > 0] = room_img.astype(np.float32)[a_small > 0] * 0.3 + \
        np.array([80, 160, 255], np.float32) * 0.7
    Image.fromarray(ov.clip(0, 255).astype(np.uint8)).save(os.path.join(
        ROOT, 'docs/art-options', f'overhead-gold-{room}-preview.jpg'), quality=88)
    print(f'  shipped assets/rooms/{asset}.overhead.png '
          f'({int((a_small > 0).sum())} alpha px)')


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else 'plaza-market-inside'))
