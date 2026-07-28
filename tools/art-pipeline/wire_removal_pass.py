#!/usr/bin/env python3
"""Pre-processing pass (Ivan): remove ALL cables and wires from the plate —
lying on the ground AND strung overhead — so magenta v4 sees a clean scene.
Wires get re-added as a post-processing/render layer later.

Best-of-N: each roll is gated on changed-fraction sanity (wires are thin:
0.5%..22% of pixels may change) and judged (wires gone? anything else
altered?); the accepted roll with the least off-target change wins.
Output: docs/art-options/rooms/<room>/plate-nowires.png + comparison jpg.
"""
import io
import json
import os
import random
import sys
import time

import numpy as np
from PIL import Image
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
N_CANDIDATES = 3
CHANGE_MIN, CHANGE_MAX = 0.005, 0.22

PROMPT = (
 'Edit this EXACT image: REMOVE every free-hanging wire, cable and hose from the scene — '
 'cables lying on the ground, hoses snaking across the floor, wires strung overhead between '
 'poles, buildings or walls, drooping cable runs, and the strings that lanterns hang from '
 '(keep the lanterns themselves, now unattached). Fill in whatever was behind each removed '
 'wire seamlessly in the same pixel-art style: ground texture, wall, awning, sky. '
 'Keep EVERY other pixel exactly identical — same objects, same colors, same lighting. '
 'Do NOT remove: pipes attached to machines or walls, railings, poles, posts, signs, lanterns.'
)

JUDGE_Q = (
 'Compare these two pixel-art images (first = original, second = edited). Answer JSON only: '
 '{"wires_removed": bool (are the ground cables and overhead wires gone in the second?), '
 '"objects_intact": bool (are all NON-wire objects — stalls, crates, lanterns, signs, awnings '
 '— still present and unchanged?), "artifacts": [list of visible editing artifacts or '
 'unintended changes, empty if none]}'
)


def judge(client, src, gen):
    try:
        r = client.models.generate_content(model='gemini-3.1-pro-preview',
                                           contents=[src, gen, JUDGE_Q])
        t = r.text or ''
        return json.loads(t[t.index('{'): t.rindex('}') + 1])
    except (genai_errors.APIError, ValueError, OSError) as e:
        return {'error': str(e)}


def run(room):
    art = os.path.join(ROOT, 'docs', 'art-options', 'rooms', room)
    src = Image.open(os.path.join(art, 'plate.png')).convert('RGB')
    W, H = src.size
    src_arr = np.asarray(src).astype(np.int16)
    seg_in = src.copy()
    seg_in.thumbnail((1200, 1200))

    client = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
    best = None
    tries = 0
    while (best is None or best['n'] < N_CANDIDATES) and tries < 8:
        tries += 1
        try:
            r = client.models.generate_content(model='gemini-3-pro-image',
                contents=[seg_in, PROMPT],
                config=types.GenerateContentConfig(image_config=types.ImageConfig(
                    aspect_ratio='4:3', image_size='2K')))
            img = None
            for p in (r.parts or []):
                if p.inline_data is not None:
                    img = Image.open(io.BytesIO(p.inline_data.data)).convert('RGB') \
                               .resize((W, H), Image.LANCZOS)
            if img is None:
                continue
            changed = float((np.abs(np.asarray(img).astype(np.int16) - src_arr)
                             .max(axis=2) > 42).mean())
            if not (CHANGE_MIN <= changed <= CHANGE_MAX):
                print(f'  roll rejected (changed {changed:.2%})')
                continue
            j = judge(client, seg_in, img)
            ok = j.get('wires_removed') and j.get('objects_intact')
            print(f'  roll changed {changed:.2%}, judge wires_removed='
                  f'{j.get("wires_removed")} intact={j.get("objects_intact")} '
                  f'artifacts={j.get("artifacts", [])}')
            if not ok:
                continue
            cand = {'img': img, 'changed': changed, 'judge': j,
                    'n': (best['n'] + 1) if best else 1}
            if best is None or changed < best['changed']:
                cand['n'] = max(cand['n'], best['n'] + 1) if best else 1
                best = cand
            else:
                best['n'] += 1
        except (genai_errors.APIError, OSError, ValueError) as e:
            print('  roll error', e)
            time.sleep(4 * random.uniform(0.5, 1.5))
    if best is None:
        sys.exit(f'FATAL: no accepted wire-removal roll in {tries} tries')

    best['img'].save(os.path.join(art, 'plate-nowires.png'))
    side = Image.new('RGB', (W, H // 2))
    side.paste(src.resize((W // 2, H // 2), Image.LANCZOS), (0, 0))
    side.paste(best['img'].resize((W // 2, H // 2), Image.LANCZOS), (W // 2, 0))
    side.thumbnail((1400, 1400), Image.LANCZOS)
    side.save(os.path.join(ROOT, 'docs', 'art-options',
                           f'nowires-compare-{room}.jpg'), quality=86)
    json.dump({'changed_frac': round(best['changed'], 4),
               'judge': best['judge'], 'candidates_seen': best['n']},
              open(os.path.join(ROOT, 'docs', 'art-options',
                                f'nowires-{room}-metrics.json'), 'w'), indent=1)
    print(f'[{room}] plate-nowires.png written (changed {best["changed"]:.2%})')


if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else 'night-bazaar')
