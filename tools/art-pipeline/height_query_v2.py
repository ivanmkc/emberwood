#!/usr/bin/env python3
"""Height query v2: one ZOOMED crop per part (identical presentation to the
gold labelers, who reached 0.90 pairwise agreement) instead of six outlines on
a downscaled full scene. Scored vs 3-rater gold with a tune/holdout split.
Re-entry bar for shipping: >=0.8 precision on the holdout half."""
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
from PIL import Image
from google import genai
from google.genai import errors as genai_errors

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOM = 'night-bazaar'
MODELS = ['gemini-3.1-pro-preview', 'gemini-3.5-flash']
_tl = threading.local()
def cli():
    c = getattr(_tl, 'c', None)
    if c is None:
        c = _tl.c = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
    return c

Q = ('Pixel-art night-market scene, oblique top-down view. ONE part is outlined in red. '
     'If a person stood on the ground at that spot: is the outlined part hanging clearly ABOVE '
     'their head (they would walk UNDER it — awning canopies, hanging signs, strung lanterns, '
     'roof rims), or is it GROUNDED (resting on/attached at or below head height — crates, '
     'counters, poles, stalls, shelves, walls)? Answer STRICT JSON only: '
     '{"label": "overhead" | "grounded"}')


def main():
    V = json.load(open(os.path.join(ROOT, f'docs/art-options/z-source-validation-{ROOM}.json')))
    gold = V['gold']
    parts = np.load(os.path.join(ROOT, f'tools/art-pipeline/_srcmasks_{ROOM}-parts.npz'))['inst']
    plate = np.asarray(Image.open(os.path.join(ROOT, f'docs/art-options/rooms/{ROOM}/plate.png')).convert('RGB'))
    H, W = parts.shape
    ids = sorted(gold, key=int)

    def crop_of(pid):
        m = parts == int(pid)
        ys, xs = np.nonzero(m)
        cy, cx = int(ys.mean()), int(xs.mean())
        x0 = int(np.clip(cx - 260, 0, W - 520)); y0 = int(np.clip(cy - 260, 0, H - 520))
        c = plate[y0:y0+520, x0:x0+520].copy()
        sub = m[y0:y0+520, x0:x0+520]
        edge = cv2.dilate(sub.astype(np.uint8), np.ones((3,3),np.uint8)).astype(bool) & ~sub
        c[edge] = [255, 40, 40]
        return Image.fromarray(c)

    results = {m: {} for m in MODELS}
    def work(args):
        pid, model = args
        img = crop_of(pid)
        try:
            r = cli().models.generate_content(model=model, contents=[img, Q])
            t = r.text or ''
            lab = json.loads(t[t.index('{'): t.rindex('}')+1]).get('label')
            if lab in ('overhead', 'grounded'):
                results[model][pid] = lab
        except (genai_errors.APIError, ValueError, KeyError) as e:
            pass
    jobs = [(pid, m) for pid in ids for m in MODELS]
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(work, jobs))

    out = {'room': ROOM, 'models': MODELS, 'answers': results, 'scores': {}}
    tune = ids[::2]; hold = ids[1::2]
    for m in MODELS:
        for split, subset in (('tune', tune), ('holdout', hold), ('all', ids)):
            tp=fp=fn=tn=0
            for pid in subset:
                p = results[m].get(pid)
                if p is None: continue
                g = gold[pid]
                if p=='overhead' and g=='overhead': tp+=1
                elif p=='overhead': fp+=1
                elif g=='overhead': fn+=1
                else: tn+=1
            prec = tp/max(1,tp+fp); rec = tp/max(1,tp+fn)
            out['scores'][f'{m}:{split}'] = {'precision': round(prec,2), 'recall': round(rec,2),
                                             'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn}
            print(f'{m:24s} {split:7s} P={prec:.2f} R={rec:.2f} (tp{tp} fp{fp} fn{fn} tn{tn})')
    # both-agree on zoomed crops
    for split, subset in (('tune', tune), ('holdout', hold)):
        tp=fp=fn=tn=0
        for pid in subset:
            a = results[MODELS[0]].get(pid); b2 = results[MODELS[1]].get(pid)
            if a is None or b2 is None: continue
            p = 'overhead' if (a=='overhead' and b2=='overhead') else 'grounded'
            g = gold[pid]
            if p=='overhead' and g=='overhead': tp+=1
            elif p=='overhead': fp+=1
            elif g=='overhead': fn+=1
            else: tn+=1
        prec = tp/max(1,tp+fp); rec = tp/max(1,tp+fn)
        out['scores'][f'both-agree:{split}'] = {'precision': round(prec,2), 'recall': round(rec,2)}
        print(f'{"both-agree":24s} {split:7s} P={prec:.2f} R={rec:.2f}')
    json.dump(out, open(os.path.join(ROOT, f'docs/art-options/height-v2-{ROOM}.json'), 'w'), indent=1)

if __name__ == '__main__':
    main()
