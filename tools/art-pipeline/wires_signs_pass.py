#!/usr/bin/env python3
"""Overhead mask pass (separate mask, per Ivan): suspended-in-air elements —
wires strung overhead, hanging lanterns, overhangs, awnings, jutting signs.
5 purity-gated rolls -> per-pixel majority."""
import io, json, os, threading
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tl = threading.local()
def cli():
    if getattr(_tl, 'c', None) is None:
        _tl.c = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
    return _tl.c

PROMPT = (
 'Repaint this EXACT image, keeping every silhouette PIXEL-IDENTICAL, as an OVERHEAD WIRES AND '
 'SIGNS map. Two flat colors only:\n'
 '- pure cyan #00FFFF: ONLY two kinds of things: (1) WIRES and CABLES strung OVERHEAD in the '
 'air, running between buildings, poles or walls above head height; (2) SIGNS mounted or '
 'hanging OVERHEAD, such as neon signboards on walls above door height, shop signs jutting out '
 'from buildings, and hanging sign panels.\n'
 '- pure black #000000: absolutely EVERYTHING else, including ground, floors, walls, buildings, '
 'awnings, canopies, roofs, lanterns, all standing objects, cables lying on the floor, and '
 'water. If it is not an overhead wire/cable or an overhead sign, it is black.\n'
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
                cand = (dc < dk) & (dc < 110)
                pure = float((np.minimum(dc, dk) < 110).mean())
                frac = float(cand.mean())
                if pure >= 0.72 and frac <= 0.20:
                    return cand
                print(f'  roll rejected (purity {pure:.2f}, frac {frac:.2f})')
    except (genai_errors.APIError, OSError, ValueError) as e:
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
    def emit(mask, suffix):
        Image.fromarray((mask*255).astype(np.uint8)).save(f'docs/art-options/wires-signs-{room}{suffix}.png')
        b = np.asarray(src).astype(np.float32)
        v = b*0.30; v[mask] = b[mask]*0.25 + np.array([0,220,255],np.float32)*0.75
        o = Image.fromarray(v.clip(0,255).astype(np.uint8)); o.thumbnail((1400,1400), Image.LANCZOS)
        o.save(f'docs/art-options/wires-signs-{room}{suffix}.jpg', quality=86)
        return float(mask.mean())

    # strict majority erodes thin wires under positional jitter (panel-
    # modeled); emit a 2-of-N union view alongside for comparison
    maj = emit(votes > accepted / 2, '')
    un2 = emit(votes >= 2, '-union2')
    json.dump({'rolls_accepted': accepted, 'overhead_frac': round(maj, 4),
               'union2_frac': round(un2, 4)},
              open(f'docs/art-options/wires-signs-{room}-metrics.json','w'), indent=1)
    print(f'[{room}] rolls {accepted}, majority {maj:.2%}, union2 {un2:.2%}')

if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=3) as ex:
        list(ex.map(run, list(SCENES)))
