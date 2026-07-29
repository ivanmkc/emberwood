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

def _load_scenes():
    """Build SCENES dict from room_bundles.json (data-driven, not hardcoded)."""
    manifest = os.path.join(ROOT, 'tools/art-pipeline/room_bundles.json')
    with open(manifest) as f:
        bundles = json.load(f)
    scenes = {}
    for room, info in bundles.items():
        plate_rel = info.get('plate', f'docs/art-options/rooms/{room}/plate.png')
        scenes[room] = (plate_rel, room)
    return scenes


SCENES = _load_scenes()


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
        for attempt in range(6):
            try:
                r = await client.aio.models.generate_content(
                    model=RATER_MODEL, contents=[im, PROMPT])
                t = (r.text or '').strip().upper()
                if OVERHEAD.upper() in t:
                    return OVERHEAD
                if GROUNDED.upper() in t:
                    return GROUNDED
            except (genai_errors.APIError, ValueError, OSError) as e:
                backoff = min(60, 5 * (2 ** attempt))
                if '429' in str(e) or 'quota' in str(e).lower():
                    backoff = min(120, 10 * (2 ** attempt))
                await asyncio.sleep(backoff)
        return None


async def main(room):
    """Rate one room's parts and emit overhead assets.

    Returns a result dict for sweep accumulation, or None on error.
    """
    if room not in SCENES:
        print(f'[{room}] not in SCENES manifest — skipping')
        return None
    plate_rel, asset = SCENES[room]
    plate_path = os.path.join(ROOT, plate_rel)
    if not os.path.exists(plate_path):
        print(f'[{room}] plate missing: {plate_rel}')
        return None
    plate = np.asarray(Image.open(plate_path).convert('RGB'))

    parts_path = os.path.join(ROOT, 'tools/art-pipeline',
                              f'_srcmasks_{room}-parts.npz')
    if not os.path.exists(parts_path):
        print(f'[{room}] parts mask missing')
        return None
    parts = np.load(parts_path)['inst']

    jpg_path = os.path.join(ROOT, 'assets', 'rooms', f'{asset}.jpg')
    if not os.path.exists(jpg_path):
        print(f'[{room}] room asset JPG missing: {jpg_path}')
        return None

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

    room_img = np.asarray(Image.open(jpg_path).convert('RGB'))
    alpha = np.zeros(parts.shape, bool)
    for k in unanimous:
        alpha |= parts == int(k)
    a_small = np.asarray(Image.fromarray((alpha * 255).astype(np.uint8))
                         .resize((room_img.shape[1], room_img.shape[0]),
                                 Image.Resampling.NEAREST))
    alpha_px = int((a_small > 0).sum())
    rgba = np.dstack([room_img, a_small])
    Image.fromarray(rgba, 'RGBA').save(os.path.join(
        ROOT, 'assets', 'rooms', f'{asset}.overhead.png'))
    ov = room_img.astype(np.float32) * 0.4
    ov[a_small > 0] = room_img.astype(np.float32)[a_small > 0] * 0.3 + \
        np.array([80, 160, 255], np.float32) * 0.7
    Image.fromarray(ov.clip(0, 255).astype(np.uint8)).save(os.path.join(
        ROOT, 'docs/art-options', f'overhead-gold-{room}-preview.jpg'), quality=88)
    print(f'  shipped assets/rooms/{asset}.overhead.png ({alpha_px} alpha px)')

    return {'parts_rated': len(pids), 'unanimous_overhead_count': len(unanimous),
            'agreement': agreement, 'alpha_px': alpha_px}


async def sweep(rooms, report_path=None):
    """Run tri-rater on a list of rooms, accumulating a sweep report.

    Stops and flags any room whose pairwise agreement drops below 0.85.
    Returns the sweep report dict.
    """
    if report_path is None:
        report_path = os.path.join(ROOT, 'docs/art-options/trirater-sweep-report.json')
    if os.path.exists(report_path):
        with open(report_path) as f:
            report = json.load(f)
    else:
        report = {'rooms': {}, 'flagged': []}

    for room in rooms:
        if room in report['rooms']:
            print(f'[{room}] already in report — skipping')
            continue
        print(f'\n=== {room} ===')
        result = await main(room)
        if result is None:
            report['rooms'][room] = {'status': 'error'}
            continue

        min_agree = min(result['agreement'].values())
        entry = {
            'parts_rated': result['parts_rated'],
            'unanimous_overhead': result['unanimous_overhead_count'],
            'agreement': result['agreement'],
            'alpha_px': result['alpha_px'],
            'status': 'shipped' if min_agree >= 0.85 else 'FLAGGED'
        }
        report['rooms'][room] = entry

        if min_agree < 0.85:
            report['flagged'].append(room)
            print(f'  *** FLAGGED: agreement {min_agree:.2f} < 0.85 — stopping')
            json.dump(report, open(report_path, 'w'), indent=1)
            return report

        json.dump(report, open(report_path, 'w'), indent=1)

    print(f'\nSweep complete: {len(report["rooms"])} rooms')
    json.dump(report, open(report_path, 'w'), indent=1)
    return report


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--sweep':
        focus = {'anchorroom', 'night-bazaar', 'plaza-market-inside'}
        rooms = [r for r in SCENES if r not in focus]
        asyncio.run(sweep(rooms))
    else:
        asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else 'plaza-market-inside'))
