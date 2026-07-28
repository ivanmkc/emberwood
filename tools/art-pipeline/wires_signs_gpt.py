#!/usr/bin/env python3
"""GPT-Image-2 arm of the wires+signs overhead pass (Ivan: "Try GPT two image").

NBP rolls on night-bazaar are confidently over-inclusive (purity 0.95+ but
52-57% coverage — it reads every awning/banner as a "sign"). Same prompt and
snap/gate/consensus logic as wires_signs_pass.py, but rolls come from
gpt-image-2 via the OpenAI images.edit endpoint. Rolls are accepted on purity
alone; area fraction is recorded per roll and judged at the end so an
over-paint outcome is evidence, not a silent abort.
"""
import base64
import io
import json
import os
import random
import sys
import time
import urllib.request
import urllib.error

import numpy as np
import openai
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FRAC_CAP = 0.20  # same sanity cap the NBP arm uses; advisory here

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


def _load_openai_key():
    key = os.environ.get('OPENAI_API_KEY')
    if key:
        return key
    env_path = os.path.expanduser('~/agent-generator/.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith('OPENAI_API_KEY='):
                    return line.strip().split('=', 1)[1]
    return None


def one_roll(client, plate_buf, W, H):
    for attempt in range(3):
        try:
            plate_buf.seek(0)
            r = client.images.edit(
                model='gpt-image-2',
                image=('plate.png', plate_buf, 'image/png'),
                prompt=PROMPT,
                size='1024x1024',
            )
            d = r.data[0] if r.data else None
            if d is None:
                continue
            if d.b64_json:
                img_bytes = base64.b64decode(d.b64_json)
            else:
                img_bytes = urllib.request.urlopen(d.url).read()
            img = Image.open(io.BytesIO(img_bytes)).convert('RGB')
            m = np.asarray(img.resize((W, H), Image.NEAREST)).astype(np.int16)
            dc = np.linalg.norm(m - np.array([0, 255, 255], np.int16), axis=2)
            dk = np.linalg.norm(m, axis=2)
            # per-pixel purity (panel): impure pixels default to black
            # rather than snapping to whichever pole is nearer
            cand = (dc < dk) & (dc < 110)
            pure = float((np.minimum(dc, dk) < 110).mean())
            frac = float(cand.mean())
            print(f'  roll purity {pure:.2f}, frac {frac:.2f}'
                  f'{"" if frac <= FRAC_CAP else "  (over NBP cap)"}')
            if pure >= 0.72:
                return cand, frac
            print('  roll rejected (purity)')
        except (openai.OpenAIError, urllib.error.URLError, OSError, ValueError) as e:
            print(f'  GPT attempt {attempt} error: {e}')
            time.sleep(min(2 * (2 ** attempt) * random.uniform(0.5, 1.5), 32))
    return None, None


def run(room, n_rolls=5):
    key = _load_openai_key()
    if not key:
        sys.exit('FATAL: no OPENAI_API_KEY')
    client = openai.OpenAI(api_key=key)

    src = Image.open(os.path.join(ROOT, SCENES[room])).convert('RGB')
    W, H = src.size
    thumb = src.copy()
    thumb.thumbnail((1024, 1024))
    buf = io.BytesIO()
    thumb.save(buf, format='PNG')

    roll_dir = os.environ.get('GPT_ROLL_DIR')
    votes = np.zeros((H, W), np.int32)
    fracs = []
    accepted = 0
    tries = 0
    while accepted < n_rolls and tries < 10:
        tries += 1
        cand, frac = one_roll(client, buf, W, H)
        if cand is not None:
            votes += cand
            fracs.append(frac)
            accepted += 1
            if roll_dir:
                os.makedirs(roll_dir, exist_ok=True)
                Image.fromarray((cand * 255).astype(np.uint8)).save(
                    os.path.join(roll_dir, f'{room}-roll{accepted}.png'))
    if accepted < 3:
        print(f'[{room}] only {accepted} rolls — abort')
        return

    def emit(mask, suffix):
        out = os.path.join(ROOT, 'docs', 'art-options')
        Image.fromarray((mask * 255).astype(np.uint8)).save(
            os.path.join(out, f'wires-signs-gpt-{room}{suffix}.png'))
        b = np.asarray(src).astype(np.float32)
        v = b * 0.30
        v[mask] = b[mask] * 0.25 + np.array([0, 220, 255], np.float32) * 0.75
        o = Image.fromarray(v.clip(0, 255).astype(np.uint8))
        o.thumbnail((1400, 1400), Image.LANCZOS)
        o.save(os.path.join(out, f'wires-signs-gpt-{room}{suffix}.jpg'), quality=86)
        return float(mask.mean())

    # strict majority erodes thin wires (rolls jitter by a few px), so also
    # emit a 2-of-N union view for comparison
    maj_frac = emit(votes > accepted / 2, '')
    un2_frac = emit(votes >= 2, '-union2')
    json.dump({'arm': 'gpt-image-2', 'rolls_accepted': accepted,
               'roll_fracs': [round(f, 4) for f in fracs],
               'overhead_frac': round(maj_frac, 4),
               'union2_frac': round(un2_frac, 4),
               'nbp_frac_cap': FRAC_CAP},
              open(os.path.join(ROOT, 'docs', 'art-options',
                                f'wires-signs-gpt-{room}-metrics.json'), 'w'), indent=1)
    print(f'[{room}] gpt-image-2: rolls {accepted}, roll fracs '
          f'{[round(f, 2) for f in fracs]}, majority {maj_frac:.2%}, '
          f'union2 {un2_frac:.2%}')


if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else 'night-bazaar')
