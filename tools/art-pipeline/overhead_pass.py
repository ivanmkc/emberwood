#!/usr/bin/env python3
"""Overhead mask pass (separate mask, per Ivan): suspended-in-air elements —
wires strung overhead, hanging lanterns, overhangs, awnings, jutting signs.
5 purity-gated rolls -> per-pixel majority."""
import io, json, os, threading
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image
from google import genai
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tl = threading.local()
def cli():
    if not hasattr(_tl, 'c'):
        _tl.c = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
    return _tl.c

PROMPT = (
 'Repaint this EXACT image, keeping every silhouette PIXEL-IDENTICAL, as an OVERHEAD/IN-THE-AIR '
 'map. Two flat colors only:\n'
 '- pure cyan #00FFFF: ONLY elements suspended IN THE AIR above the ground — EXAMPLES: wires and '
 'cables STRUNG overhead between buildings, hanging lanterns and lamps on strings, awnings and '
 'canopies, roof overhangs and eaves jutting over the street, signs jutting out from walls, '
 'bridges/catwalks passing OVERHEAD. A walking character would pass UNDER these.\n'
 '- pure black #000000: EVERYTHING else — the ground and floors, walls, buildings themselves, '
 'all objects STANDING ON the ground (tanks, stalls, machines, crates), cables lying flat ON '
 'the floor (those are step-over, not overhead), water.\n'
 'NO dithering, NO gradients, hard boundaries.'
)

SCENES = {
 'anchorroom': 'docs/art-options/nbp-scifi-anchor-clean.png',
 'night-bazaar': 'docs/art-options/rooms/night-bazaar/plate.png',
 'plaza-market-inside': 'docs/art-options/rooms/plaza-market-inside/plate.png',
}

def one_roll(seg_in, W, H):
    try:
        r = cli().models.generate_content(model='gemini-3-pro-image', contents=[seg_in, PROMPT],
            config=types.GenerateContentConfig(image_config=types.ImageConfig(aspect_ratio='4:3', image_size='2K')))
        for p in (r.parts or []):
            if p.inline_data is not None:
                img = Image.open(io.BytesIO(p.inline_data.data)).convert('RGB')
                m = np.asarray(img.resize((W, H), Image.NEAREST)).astype(np.int16)
                dc = np.linalg.norm(m - np.array([0,255,255], np.int16), axis=2)
                dk = np.linalg.norm(m, axis=2)
                cand = dc < dk
                pure = float((np.minimum(dc, dk) < 110).mean())
                frac = float(cand.mean())
                if pure >= 0.72 and frac <= 0.45:
                    return cand
                print(f'  roll rejected (purity {pure:.2f}, frac {frac:.2f})')
    except Exception as e:
        print('  roll error', e)
    return None

def run(room):
    src = Image.open(SCENES[room]).convert('RGB'); W, H = src.size
    seg_in = src.copy(); seg_in.thumbnail((1200, 1200))
    votes = np.zeros((H, W), np.int32); accepted = 0; tries = 0
    while accepted < 5 and tries < 12:
        tries += 1
        c = one_roll(seg_in, W, H)
        if c is not None:
            votes += c; accepted += 1
    if accepted < 3:
        print(f'[{room}] only {accepted} rolls — abort'); return
    over = votes > accepted / 2
    Image.fromarray((over*255).astype(np.uint8)).save(f'docs/art-options/overheadmask-{room}.png')
    b = np.asarray(src).astype(np.float32)
    v = b*0.30; v[over] = b[over]*0.25 + np.array([0,220,255],np.float32)*0.75
    o = Image.fromarray(v.clip(0,255).astype(np.uint8)); o.thumbnail((1400,1400), Image.LANCZOS)
    o.save(f'docs/art-options/overheadmask-{room}.jpg', quality=86)
    json.dump({'rolls_accepted': accepted, 'overhead_frac': round(float(over.mean()),4)},
              open(f'docs/art-options/overheadmask-{room}-metrics.json','w'), indent=1)
    print(f'[{room}] rolls {accepted}, overhead {over.mean():.2%}')

if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=3) as ex:
        list(ex.map(run, list(SCENES)))
