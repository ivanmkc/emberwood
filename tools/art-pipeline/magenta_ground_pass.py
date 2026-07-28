#!/usr/bin/env python3
"""Magenta-ground pass (Ivan): tell NBP the ground is painted pink-magenta and
keep everything else photo-identical. Two signals fall out:
 - magenta pixels = ground (walkability candidate, cross-check vs consensus walk)
 - unpainted pixels CROSSING magenta regions = things in front of the ground
   plane (wires, poles, hanging stuff) — free occlusion evidence.
Unlike the two-color abstraction passes, the scene stays intact, so detection
is (near-magenta) AND (changed vs plate).
"""
import io
import json
import os
import random
import time
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tl = threading.local()


def cli():
    c = getattr(_tl, 'c', None)
    if c is None:
        c = _tl.c = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
    return c


PROMPT = (
 'Repaint this EXACT image: paint EVERY WALKABLE SURFACE flat pure magenta #FF00FF. '
 'RUGS, CARPETS AND MATS ARE WALKABLE SURFACES AND MUST BE FULLY PAINTED MAGENTA — do NOT '
 'preserve their pattern; they disappear completely under opaque magenta paint, exactly like '
 'the floor around them. Also paint: the ground, floors, cables and wires lying on the floor, '
 'hoses, flat debris, stains, thresholds, doorway floors, low flat platforms, AND small gaps '
 'a person could easily step over or walk across: holes in floor grates, drain grates and '
 'drain slots, narrow cracks and seams between floor plates, shallow channels — paint those '
 'magenta too, since walking over them is easy. '
 'Every other pixel must stay EXACTLY identical to the input: walls, buildings, stalls, '
 'counters, crates, shelves, plants, awnings, signs, lanterns, hanging wires, deep water, '
 'wide chasms or pits too large to step across. '
 'Anything STANDING UPRIGHT on the floor or HANGING ABOVE it must remain unpainted and must '
 'cover/overlap the magenta paint behind it. '
 'Flat magenta only — NO gradients, NO transparency, NO magenta anywhere except walkable surfaces.'
)

SCENES = {
 'anchorroom': 'docs/art-options/nbp-scifi-anchor-clean.png',
 'night-bazaar': 'docs/art-options/rooms/night-bazaar/plate.png',
 'night-bazaar-nowires': 'docs/art-options/rooms/night-bazaar/plate-nowires.png',
 'anchorroom-nowires': 'docs/art-options/rooms/anchorroom/plate-nowires.png',
 'plaza-market-inside': 'docs/art-options/rooms/plaza-market-inside/plate.png',
}
WALK_REF = {  # consensus-walk reference per scene, where one exists
 'anchorroom': 'anchorroom', 'night-bazaar': 'night-bazaar',
 'night-bazaar-nowires': 'night-bazaar', 'anchorroom-nowires': 'anchorroom', 'plaza-market-inside': 'plaza-market-inside',
}
MAG = np.array([255, 0, 255], np.int16)


def one_roll(seg_in, plate_arr, W, H):
    try:
        r = cli().models.generate_content(model='gemini-3-pro-image', contents=[seg_in, PROMPT],
            config=types.GenerateContentConfig(image_config=types.ImageConfig(
                aspect_ratio='4:3', image_size='2K')))
        for p in (r.parts or []):
            if p.inline_data is not None:
                img = Image.open(io.BytesIO(p.inline_data.data)).convert('RGB')
                raw_dir = os.environ.get('MAG_RAW_DIR')
                if raw_dir:
                    os.makedirs(raw_dir, exist_ok=True)
                    img.save(os.path.join(raw_dir,
                        f'raw_{threading.get_ident()}_{np.random.randint(10**9)}.png'))
                m = np.asarray(img.resize((W, H), Image.NEAREST)).astype(np.int16)
                near_mag = np.linalg.norm(m - MAG, axis=2) < 120
                changed = np.abs(m - plate_arr).max(axis=2) > 42
                cand = near_mag & changed
                frac = float(cand.mean())
                # sanity: ground should be a large but not dominant region, and
                # the rest of the scene should be mostly unchanged
                offmask_change = float((changed & ~near_mag).mean())
                if 0.10 <= frac <= 0.75 and offmask_change <= 0.25:
                    return cand
                print(f'  roll rejected (ground {frac:.2f}, off-mask change {offmask_change:.2f})')
    except (genai_errors.APIError, OSError, ValueError) as e:
        print('  roll error', e)
        time.sleep(4 * random.uniform(0.5, 1.5))  # transient-burst backoff
    return None


def run(room):
    src = Image.open(os.path.join(ROOT, SCENES[room])).convert('RGB')
    W, H = src.size
    plate_arr = np.asarray(src).astype(np.int16)
    seg_in = src.copy()
    seg_in.thumbnail((1200, 1200))
    votes = np.zeros((H, W), np.int32)
    accepted = 0
    tries = 0
    while accepted < 5 and tries < 12:
        tries += 1
        c = one_roll(seg_in, plate_arr, W, H)
        if c is not None:
            votes += c
            accepted += 1
    if accepted < 3:
        print(f'[{room}] only {accepted} rolls — abort')
        return
    ground = votes > accepted / 2

    walk = np.asarray(Image.open(os.path.join(
        ROOT, 'docs', 'art-options', 'bench', 'prompt', WALK_REF[room],
        'consensus-walk.png')).convert('L').resize((W, H), Image.NEAREST)) > 127
    inter = float((ground & walk).sum())
    iou = inter / max(1.0, float((ground | walk).sum()))

    out = os.path.join(ROOT, 'docs', 'art-options')
    Image.fromarray((ground * 255).astype(np.uint8)).save(
        os.path.join(out, f'magenta-ground-{room}.png'))
    b = np.asarray(src).astype(np.float32)
    v = b * 0.30
    v[ground] = b[ground] * 0.25 + np.array([255, 60, 255], np.float32) * 0.75
    only_walk = walk & ~ground   # walk says yes, magenta says no — disagreement view
    v[only_walk] = b[only_walk] * 0.35 + np.array([255, 220, 60], np.float32) * 0.65
    o = Image.fromarray(v.clip(0, 255).astype(np.uint8))
    o.thumbnail((1400, 1400), Image.LANCZOS)
    o.save(os.path.join(out, f'magenta-ground-{room}.jpg'), quality=86)
    json.dump({'rolls_accepted': accepted, 'ground_frac': round(float(ground.mean()), 4),
               'iou_vs_consensus_walk': round(iou, 4)},
              open(os.path.join(out, f'magenta-ground-{room}-metrics.json'), 'w'), indent=1)
    print(f'[{room}] rolls {accepted}, ground {ground.mean():.2%}, IoU vs walk {iou:.3f}')


if __name__ == '__main__':
    rooms = sys.argv[1:] or list(SCENES)
    with ThreadPoolExecutor(max_workers=3) as ex:
        list(ex.map(run, rooms))
