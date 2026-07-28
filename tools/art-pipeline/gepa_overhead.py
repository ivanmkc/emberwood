#!/usr/bin/env python3
"""GEPA-style reflective optimization of the overhead-mask prompt.

Candidate = prompt string. Metric per candidate (K=2 rolls, train scenes only):
  precision = judge-classified suspended fraction over sampled mask components
  recall    = 1 - missed_suspended/(covered+missed)  (judge on full overlay)
  sanity    = fraction in [0.03, 0.35] else score 0
  score     = precision * recall (harmonic-ish product), mean over train scenes
Train: anchorroom, night-bazaar. HOLDOUT: plaza-market-inside (final eval only).
Reflection: judge's misclassified components -> 3.1-pro rewrites the prompt.
3 generations, 2 mutations/gen, early stop at precision>=0.85 & recall>=0.85.
Winner -> 5-roll consensus on ALL scenes incl. holdout, overlays for the board.
"""
import io, json, os, sys, threading
import numpy as np, cv2
from PIL import Image
from google import genai
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tl = threading.local()
def cli():
    if not hasattr(_tl, 'c'):
        _tl.c = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
    return _tl.c

SCENES = {
 'anchorroom': 'docs/art-options/nbp-scifi-anchor-clean.png',
 'night-bazaar': 'docs/art-options/rooms/night-bazaar/plate.png',
 'plaza-market-inside': 'docs/art-options/rooms/plaza-market-inside/plate.png',
}
TRAIN = ['anchorroom', 'night-bazaar']
HOLDOUT = 'plaza-market-inside'

SEED = (
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

def roll(prompt, room):
    src = Image.open(os.path.join(ROOT, SCENES[room])).convert('RGB'); W, H = src.size
    seg = src.copy(); seg.thumbnail((1200, 1200))
    try:
        r = cli().models.generate_content(model='gemini-3-pro-image', contents=[seg, prompt],
            config=types.GenerateContentConfig(image_config=types.ImageConfig(aspect_ratio='4:3', image_size='2K')))
        for p in (r.parts or []):
            if p.inline_data is not None:
                img = Image.open(io.BytesIO(p.inline_data.data)).convert('RGB')
                m = np.asarray(img.resize((W, H), Image.NEAREST)).astype(np.int16)
                dc = np.linalg.norm(m - np.array([0,255,255], np.int16), axis=2)
                dk = np.linalg.norm(m, axis=2)
                cand = dc < dk
                if float((np.minimum(dc, dk) < 110).mean()) >= 0.70:
                    return cand, src
    except Exception as e:
        print('  roll err', e, file=sys.stderr)
    return None, None

def ask(contents, tok=2048):
    for _ in range(3):
        try:
            r = cli().models.generate_content(model='gemini-3.1-pro-preview', contents=contents,
                config=types.GenerateContentConfig(max_output_tokens=tok))
            t = r.text or ''
            st = min([i for i in (t.find('['), t.find('{')) if i >= 0], default=-1)
            if st >= 0:
                return json.JSONDecoder().raw_decode(t[st:])[0]
        except Exception:
            pass
    return None

def eval_candidate(prompt, rooms, K=2):
    per_scene, feedback = [], []
    for room in rooms:
        masks = []
        for _ in range(K + 1):
            c, src = roll(prompt, room)
            if c is not None:
                masks.append((c, src))
            if len(masks) == K:
                break
        if not masks:
            per_scene.append(0.0); feedback.append(f'{room}: no valid rolls'); continue
        votes = np.sum([m for m, _ in masks], axis=0)
        mask = votes > len(masks) / 2
        src = masks[0][1]
        frac = float(mask.mean())
        if not (0.03 <= frac <= 0.35):
            per_scene.append(0.0); feedback.append(f'{room}: area fraction {frac:.2f} out of sane range [0.03,0.35]'); continue
        # precision: classify sampled components
        n, lab, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
        order = np.argsort(-stats[1:, cv2.CC_STAT_AREA]) + 1
        sus, tot, wrongs = 0, 0, []
        b = np.asarray(src)
        for ci in order[:8]:
            x, y, w, h = stats[ci, [cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT]]
            pad = 40
            crop = b[max(0,y-pad):y+h+pad, max(0,x-pad):x+w+pad].copy()
            comp = (lab == ci)[max(0,y-pad):y+h+pad, max(0,x-pad):x+w+pad]
            edge = cv2.dilate(comp.astype(np.uint8), np.ones((5,5),np.uint8)).astype(bool) & ~comp
            crop[edge] = (0, 255, 255)
            v = ask([Image.fromarray(crop),
                     'The cyan-outlined region: is that element SUSPENDED IN THE AIR above the '
                     'ground (strung wire, hanging lamp, awning, overhang), or does it STAND ON / '
                     'lie on the ground, or is it ground/wall itself? '
                     'Return JSON only: {"class": "suspended"|"standing"|"ground", "what": "short"}'])
            if v:
                tot += 1
                if v.get('class') == 'suspended':
                    sus += 1
                else:
                    wrongs.append(f"{v.get('what','?')} ({v.get('class')})")
        precision = sus / tot if tot else 0.0
        # recall: missed suspended elements
        ov = b.astype(np.float32) * 0.35
        ov[mask] = b[mask].astype(np.float32) * 0.3 + np.array([0,220,255], np.float32) * 0.7
        ovi = Image.fromarray(ov.clip(0,255).astype(np.uint8)); ovi.thumbnail((1100,1100))
        v = ask([ovi, 'Cyan marks detected suspended/overhead elements. List obvious SUSPENDED '
                      'elements (strung wires, hanging lamps, awnings, overhangs) NOT covered by '
                      'cyan (max 5). Return JSON only: {"missed": ["...", ...]}'])
        missed = len((v or {}).get('missed', []))
        recall = sus / max(1, sus + missed)
        score = precision * recall
        per_scene.append(score)
        feedback.append(f'{room}: precision {precision:.2f} (false: {"; ".join(wrongs[:4]) or "none"}), '
                        f'missed suspended: {(v or {}).get("missed", [])[:3]}, area {frac:.2f}')
    return float(np.mean(per_scene)), feedback

def reflect(prompt, feedback):
    v = ask(['You are optimizing an image-editing instruction. Current instruction:\n---\n' + prompt +
             '\n---\nEvaluator feedback (false positives = things wrongly marked as suspended; '
             'missed = suspended things not marked):\n' + '\n'.join(feedback) +
             '\nRewrite the instruction to fix these specific failures. Keep the same two-color '
             'output contract (pure cyan #00FFFF / pure black #000000) and the pixel-identical '
             'constraint. Be surgical: add discriminative criteria (e.g., attachment points, '
             'shadows cast on ground below, gap of visible ground beneath) and negative examples '
             'matching the false positives. Return JSON only: {"prompt": "..."}'], tok=4096)
    return (v or {}).get('prompt')

def main():
    log = []
    best_p, (best_s, fb) = SEED, (None, None)
    best_s, fb = eval_candidate(SEED, TRAIN)
    log.append({'gen': 0, 'score': best_s, 'feedback': fb})
    print(f'gen0 seed score {best_s:.3f}'); [print('  ', f) for f in fb]
    for gen in range(1, 4):
        muts = []
        for _ in range(2):
            m = reflect(best_p, fb)
            if m and len(m) > 200:
                muts.append(m)
        improved = False
        for mi, m in enumerate(muts):
            s, f2 = eval_candidate(m, TRAIN)
            log.append({'gen': gen, 'mut': mi, 'score': s, 'feedback': f2})
            print(f'gen{gen} mut{mi} score {s:.3f}'); [print('  ', x) for x in f2]
            if s > best_s:
                best_p, best_s, fb, improved = m, s, f2, True
        if best_s >= 0.72 or not improved:
            pass
        if best_s >= 0.85:
            break
    json.dump({'best_prompt': best_p, 'best_train_score': best_s, 'log': log},
              open('docs/art-options/gepa-overhead-result.json', 'w'), indent=1)
    print('BEST train score', best_s)
    # HOLDOUT eval + final 5-roll consensus on all scenes with the winner
    hs, hfb = eval_candidate(best_p, [HOLDOUT])
    print('HOLDOUT score', hs); [print('  ', x) for x in hfb]
    for room in SCENES:
        votes, acc, tries = None, 0, 0
        W = H = None
        while acc < 5 and tries < 10:
            tries += 1
            c, src = roll(best_p, room)
            if c is None: continue
            if votes is None:
                votes = np.zeros(c.shape, np.int32)
            votes += c; acc += 1
        if acc < 3:
            print(room, 'consensus failed'); continue
        over = votes > acc / 2
        src = Image.open(os.path.join(ROOT, SCENES[room])).convert('RGB')
        Image.fromarray((over*255).astype(np.uint8)).save(f'docs/art-options/overheadmask-{room}.png')
        b = np.asarray(src).astype(np.float32)
        v = b*0.30; v[over] = b[over]*0.25 + np.array([0,220,255],np.float32)*0.75
        o = Image.fromarray(v.clip(0,255).astype(np.uint8)); o.thumbnail((1400,1400), Image.LANCZOS)
        o.save(f'docs/art-options/overheadmask-{room}.jpg', quality=86)
        json.dump({'rolls_accepted': acc, 'overhead_frac': round(float(over.mean()),4),
                   'method': 'gepa-optimized', 'train_score': best_s, 'holdout_score': hs},
                  open(f'docs/art-options/overheadmask-{room}-metrics.json','w'), indent=1)
        print(f'[{room}] FINAL consensus: rolls {acc}, overhead {over.mean():.2%}')

if __name__ == '__main__':
    main()
