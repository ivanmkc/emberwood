#!/usr/bin/env python3
"""NBP defect verification v2: an INDEPENDENT fresh walkability roll per room
(same walk-v2 prompt, new seed) diffed deterministically against the shipped
collision. NBP supplies the second opinion; code does the pixel comparison —
the free-form "paint the defects" variant over-flagged (it repainted ground
rather than diffing the tint).

  missed_walkable = fresh-roll green  AND shipped-blocked   (opened 11px)
  false_walkable  = shipped-walkable AND fresh-roll red
                    minus liberated walk-behind bodies       (opened 11px)
Outputs defect masks/overlays/metrics per room + ranked fix queue.
"""

import io
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image
from google import genai
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AP = os.path.join(ROOT, 'tools', 'art-pipeline')
_tl = threading.local()


def cli():
    if not hasattr(_tl, 'c'):
        _tl.c = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
    return _tl.c


def check(room):
    import cv2
    import importlib.util
    art = os.path.join(ROOT, 'docs', 'art-options', 'rooms', room)
    plate = os.path.join(art, 'plate.png')
    suffix = ''
    if room == 'anchorroom':
        art = os.path.join(ROOT, 'docs', 'art-options')
        plate = os.path.join(art, 'nbp-scifi-anchor-clean.png')
        suffix = '-anchorroom'
    colp = os.path.join(ROOT, 'assets', 'rooms', f'{room}.collision.png')
    if not (os.path.exists(plate) and os.path.exists(colp)):
        return room, None
    src = Image.open(plate).convert('RGB')
    W, H = src.size
    seg_in = src.copy()
    seg_in.thumbnail((1200, 1200))
    # fresh independent walkability roll (walk-v2 prompt, new seed)
    spec = importlib.util.spec_from_file_location('nbw', os.path.join(AP, 'nbp_walk.py'))
    nbw = importlib.util.module_from_spec(spec)
    import sys as _sys
    argv0 = _sys.argv
    _sys.argv = ['nbp_walk.py']
    spec.loader.exec_module(nbw)
    _sys.argv = argv0
    fresh = None
    for _ in range(2):
        img = None
        try:
            resp = cli().models.generate_content(
                model='gemini-3-pro-image',
                contents=[seg_in, nbw.PROMPT],
                config=types.GenerateContentConfig(
                    image_config=types.ImageConfig(aspect_ratio='4:3', image_size='2K')),
            )
            for part in (resp.parts or []):
                if part.inline_data is not None:
                    img = Image.open(io.BytesIO(part.inline_data.data)).convert('RGB')
        except Exception:  # noqa: BLE001
            continue
        if img is None:
            continue
        m = np.asarray(img.resize((W, H), Image.NEAREST)).astype(np.int16)
        dg = np.linalg.norm(m - np.array([0, 255, 0], np.int16), axis=2)
        dr = np.linalg.norm(m - np.array([255, 0, 0], np.int16), axis=2)
        if float((np.minimum(dg, dr) < 100).mean()) >= 0.75:
            fresh = dg < dr
            break
    if fresh is None:
        return room, None
    shipped = np.asarray(Image.open(colp).convert('L').resize((W, H), Image.NEAREST)) > 127
    k = np.ones((11, 11), np.uint8)
    missed = cv2.morphologyEx((fresh & ~shipped).astype(np.uint8), cv2.MORPH_OPEN, k).astype(bool)
    false_w = (shipped & ~fresh)
    # exclude liberated walk-behind bodies: blocked-object pixels above their
    # bases are intentionally walkable hidden floor
    fpp = os.path.join(art, 'nbp-footprint.png') if room != 'anchorroom' else         os.path.join(ROOT, 'docs', 'art-options', 'nbp-footprint.png')
    if os.path.exists(fpp):
        fp = np.asarray(Image.open(fpp).convert('L').resize((W, H), Image.NEAREST)) > 127
        body = (~fresh) & ~fp  # fresh-red minus footprint = upper bodies etc.
        false_w = false_w & ~cv2.dilate(body.astype(np.uint8) * 0, k).astype(bool) | (false_w & fp)
        # keep only false-walk ON footprint/ground-contact areas
        false_w = false_w & cv2.dilate(fp.astype(np.uint8), k).astype(bool)
    false_w = cv2.morphologyEx(false_w.astype(np.uint8), cv2.MORPH_OPEN, k).astype(bool)
    met = {'missed_walkable_frac': round(float(missed.mean()), 4),
           'false_walkable_frac': round(float(false_w.mean()), 4)}
    met['defect_frac'] = round(met['missed_walkable_frac'] + met['false_walkable_frac'], 4)
    plate_np = np.asarray(src).astype(np.float32)
    blend = plate_np * 0.55
    blend[missed] = blend[missed] * 0.3 + np.array([255, 128, 0], np.float32) * 0.7
    blend[false_w] = blend[false_w] * 0.3 + np.array([255, 0, 255], np.float32) * 0.7
    ov = Image.fromarray(blend.clip(0, 255).astype(np.uint8))
    ov.thumbnail((1400, 1400), Image.LANCZOS)
    ov.save(os.path.join(art, f'defect-on-source{suffix}.jpg'), quality=86)
    json.dump(met, open(os.path.join(art, f'defect-metrics{suffix}.json'), 'w'))
    return room, met


def main():
    cfg = json.load(open(os.path.join(AP, 'rooms.json')))
    rooms = sys.argv[1:] or (['anchorroom'] + list(cfg['rooms']) + list(cfg['interiors']))
    results = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for room, met in ex.map(check, rooms):
            if met is None:
                print(f'{room:20s} NO VERDICT (drifted/failed rolls)')
            else:
                print(f'{room:20s} defects {met["defect_frac"]:.3%} '
                      f'(missed-walk {met["missed_walkable_frac"]:.3%}, '
                      f'false-walk {met["false_walkable_frac"]:.3%})')
                results.append((met['defect_frac'], room))
    results.sort(reverse=True)
    print('\nfix queue (defect_frac > 2%):',
          [f'{r} ({f:.1%})' for f, r in results if f > 0.02] or 'none')


if __name__ == '__main__':
    main()
