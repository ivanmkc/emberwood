#!/usr/bin/env python3
"""Second pass on consensus walkability: identify + segment STEP-OVER
elements (wires/cables/flat things lying ON the ground) that must not block.
5 purity-gated rolls -> per-pixel majority (consensus, per Ivan). Outputs per
scene: stepover mask, updated 2-color walk (consensus ∪ stepover), a
highlight view, and VLM-named examples of what was found."""
import io, json, os, sys, threading
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
 'Repaint this EXACT image, keeping every silhouette PIXEL-IDENTICAL, as a STEP-OVER map. '
 'Two flat colors only:\n'
 '- pure orange #FF8000: ONLY thin/flat objects LYING ON the walkable ground that a walking '
 'character can simply STEP OVER — EXAMPLES: thick power cables snaking across the floor, '
 'hoses and wires running along the street, flat pipes lying on the ground, planks or boards '
 'flat on the floor, shallow debris or rags lying flat. They touch the ground along their '
 'whole length and rise only a few centimeters.\n'
 '- pure black #000000: EVERYTHING else — open floor itself, walls, buildings, all standing '
 'objects (tanks, stalls, machines, crates, barrels), railings, water, and anything hanging '
 'or elevated (overhead wires strung in the air are NOT step-over — black).\n'
 'NO dithering, NO gradients, hard boundaries.'
)

SCENES = {
 'anchorroom': ('docs/art-options/nbp-scifi-anchor-clean.png', 'docs/art-options/bench/prompt/anchorroom/consensus-walk.png'),
 'night-bazaar': ('docs/art-options/rooms/night-bazaar/plate.png', 'docs/art-options/bench/prompt/night-bazaar/consensus-walk.png'),
 'plaza-market-inside': ('docs/art-options/rooms/plaza-market-inside/plate.png', 'docs/art-options/bench/prompt/plaza-market-inside/consensus-walk.png'),
}

def one_roll(seg_in, W, H):
    try:
        r = cli().models.generate_content(model='gemini-3-pro-image', contents=[seg_in, PROMPT],
            config=types.GenerateContentConfig(image_config=types.ImageConfig(aspect_ratio='4:3', image_size='2K')))
        for p in (r.parts or []):
            if p.inline_data is not None:
                img = Image.open(io.BytesIO(p.inline_data.data)).convert('RGB')
                m = np.asarray(img.resize((W, H), Image.NEAREST)).astype(np.int16)
                do = np.linalg.norm(m - np.array([255,128,0], np.int16), axis=2)
                dk = np.linalg.norm(m, axis=2)
                cand = do < dk
                pure = float((np.minimum(do, dk) < 110).mean())
                frac = float(cand.mean())
                if pure >= 0.72 and frac <= 0.20:  # step-over is sparse by nature
                    return cand
                print(f'  roll rejected (purity {pure:.2f}, frac {frac:.2f})')
    except Exception as e:
        print('  roll error', e)
    return None

def run(room):
    plate_p, cons_p = SCENES[room]
    src = Image.open(plate_p).convert('RGB'); W, H = src.size
    seg_in = src.copy(); seg_in.thumbnail((1200, 1200))
    votes = np.zeros((H, W), np.int32); accepted = 0; tries = 0
    while accepted < 5 and tries < 12:
        tries += 1
        c = one_roll(seg_in, W, H)
        if c is not None:
            votes += c; accepted += 1
    if accepted < 3:
        print(f'[{room}] only {accepted} rolls — abort'); return room, None
    stepover = votes > accepted / 2
    cons = np.asarray(Image.open(cons_p).convert('L').resize((W, H), Image.NEAREST)) > 127
    found = stepover & ~cons  # what the second pass RESCUES (was blocked)
    walk2 = cons | stepover
    Image.fromarray((stepover*255).astype(np.uint8)).save(f'docs/art-options/stepover-{room}.png')
    b = np.asarray(src).astype(np.float32)
    # updated 2-color
    v = b.copy(); v[walk2] = v[walk2]*0.72 + np.array([40,255,90],np.float32)*0.28
    v[~walk2] = v[~walk2]*0.5 + np.array([255,40,40],np.float32)*0.5
    o = Image.fromarray(v.clip(0,255).astype(np.uint8)); o.thumbnail((1400,1400), Image.LANCZOS)
    o.save(f'docs/art-options/consensus2-walk-{room}.jpg', quality=86)
    # highlight view: rescued step-over in orange over 2-color base
    v2 = b.copy(); v2[cons] = v2[cons]*0.75 + np.array([40,255,90],np.float32)*0.25
    v2[~walk2] = v2[~walk2]*0.55 + np.array([255,40,40],np.float32)*0.45
    v2[found] = np.array([255,140,0], np.float32)
    o2 = Image.fromarray(v2.clip(0,255).astype(np.uint8)); o2.thumbnail((1400,1400), Image.LANCZOS)
    o2.save(f'docs/art-options/stepover-found-{room}.jpg', quality=86)
    # examples via VLM
    hl = Image.fromarray(v2.clip(0,255).astype(np.uint8)); hl.thumbnail((1100,1100))
    ex = []
    if int(found.sum()) < 500:
        ex = ['none found']
    else:
      try:
        r = cli().models.generate_content(model='gemini-3.1-pro-preview',
            contents=[hl, 'The ORANGE highlights mark step-over elements found on the ground. '
                          'Name each distinct one briefly (max 6). Return JSON only: {"examples": ["...", ...]}'],
            config=types.GenerateContentConfig(max_output_tokens=1024))
        t = r.text or ''; st = t.find('{')
        if st >= 0:
            ex = json.JSONDecoder().raw_decode(t[st:])[0].get('examples', [])
      except Exception:
        pass
    met = {'rolls_accepted': accepted, 'stepover_frac': round(float(stepover.mean()),4),
           'rescued_px': int(found.sum()), 'examples': ex}
    json.dump(met, open(f'docs/art-options/stepover-{room}-metrics.json','w'), indent=1)
    print(f'[{room}] rolls {accepted}, stepover {stepover.mean():.2%}, rescued {int(found.sum())}px, examples: {ex}')
    return room, met

if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=3) as ex:
        for room, met in ex.map(run, list(SCENES)):
            pass
