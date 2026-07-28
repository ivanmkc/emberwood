#!/usr/bin/env python3
"""Per-part semantic height query (Ivan): for each z-relevant part, ask two
VLMs (gemini-3.1-pro-preview + gemini-3.5-flash — newest Flash on models.list;
no 3.6 exists on this project) what the part is and how high its BOTTOM edge
sits: on_ground / below_head / above_head. above_head => occlude-not-block.
Batched 6 parts per image (distinct outline colors + numbers)."""
import json
import os
import threading

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOM = 'night-bazaar'
MODELS = ['gemini-3.1-pro-preview', 'gemini-3.5-flash']
COLS = [(255,60,60),(60,120,255),(255,220,40),(60,255,120),(255,60,255),(0,235,235)]
_tl = threading.local()
def cli():
    c = getattr(_tl, 'c', None)
    if c is None:
        c = _tl.c = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
    return c

Q = ('This pixel-art market scene has %d outlined parts, each numbered with a colored outline. '
     'For EACH numbered part, identify it and judge how high its BOTTOM edge sits relative to a '
     'person standing on the ground at that spot. Answer STRICT JSON array only: '
     '[{"n": <number>, "label": "<short name>", "bottom_height": "on_ground" | "below_head" | '
     '"above_head"}]. "above_head" means the lowest visible pixel of the part hangs higher than '
     'a standing person\'s head (like an awning, hanging sign or roof edge); "on_ground" means '
     'it rests on the floor.')

def main():
    parts = np.load(os.path.join(ROOT, f'tools/art-pipeline/_srcmasks_{ROOM}-parts.npz'))['inst']
    pmeta = json.load(open(os.path.join(ROOT, f'docs/art-options/parts-{ROOM}-metrics.json')))
    imeta = json.load(open(os.path.join(ROOT, f'docs/art-options/occprobe2-instances-{ROOM}-aligned.json')))
    iblock = {o['id'] for o in imeta['instances'] if o.get('blocking')}
    parent = {int(k): v for k, v in pmeta['parent'].items()}
    plate = Image.open(os.path.join(ROOT, f'docs/art-options/rooms/{ROOM}/plate.png')).convert('RGB')
    walk = np.asarray(Image.open(os.path.join(
        ROOT, f'docs/art-options/magenta-ground-{ROOM}-nowires.png')).convert('L')) > 127
    near_walk = cv2.dilate(walk.astype(np.uint8), np.ones((61,61),np.uint8)) > 0

    todo = []
    for pid, par in parent.items():
        if par not in iblock: continue
        m = parts == pid
        if m.sum() < 1500: continue
        if not (m & near_walk).any(): continue
        todo.append(pid)
    print(f'{len(todo)} z-relevant parts to query')
    batches = [todo[i:i+6] for i in range(0, len(todo), 6)]

    results = {m: {} for m in MODELS}
    for bi, batch in enumerate(batches):
        img = plate.copy()
        img.thumbnail((1200, 1200))
        sc = img.width / plate.width
        dr = ImageDraw.Draw(img)
        for k, pid in enumerate(batch):
            m = (parts == pid)
            b = cv2.dilate(m.astype(np.uint8), np.ones((3,3),np.uint8)) > 0
            edge = b & ~cv2.erode(m.astype(np.uint8), np.ones((3,3),np.uint8)).astype(bool)
            ys, xs = np.nonzero(edge)
            arr = np.asarray(img).copy()
            py = np.clip((ys*sc).astype(int), 0, img.height-1)
            px = np.clip((xs*sc).astype(int), 0, img.width-1)
            arr[py, px] = COLS[k]
            img = Image.fromarray(arr)
            dr = ImageDraw.Draw(img)
            cy, cx = int(ys.mean()*sc), int(xs.mean()*sc)
            dr.rectangle([cx-11, cy-9, cx+13, cy+9], fill=(0,0,0))
            dr.text((cx-8, cy-7), str(k+1), fill=COLS[k])
        for model in MODELS:
            try:
                r = cli().models.generate_content(model=model, contents=[img, Q % len(batch)])
                t = r.text or ''
                arr = json.loads(t[t.index('['): t.rindex(']')+1])
                for e in arr:
                    k = int(e.get('n', 0)) - 1
                    if 0 <= k < len(batch):
                        results[model][batch[k]] = {'label': e.get('label',''),
                                                    'h': e.get('bottom_height','')}
            except (genai_errors.APIError, ValueError, KeyError, TypeError) as e:
                print(f'  batch {bi} {model}: {e}')
        print(f'batch {bi+1}/{len(batches)} done')

    fused = {}
    for pid in todo:
        a = results[MODELS[0]].get(pid, {}).get('h')
        b = results[MODELS[1]].get(pid, {}).get('h')
        fused[pid] = {'pro': results[MODELS[0]].get(pid), 'flash': results[MODELS[1]].get(pid),
                      'agree_above_head': a == 'above_head' and b == 'above_head',
                      'any_above_head': 'above_head' in (a, b)}
    n_agree = sum(1 for v in fused.values() if v['agree_above_head'])
    print(f'above_head agreement (both models): {n_agree}/{len(todo)}')
    json.dump({'room': ROOM, 'models': MODELS, 'parts': {str(k): v for k, v in fused.items()}},
              open(os.path.join(ROOT, f'docs/art-options/height-query-{ROOM}.json'), 'w'), indent=1)

    b_img = np.asarray(plate).astype(np.float32) * 0.32
    for pid, v in fused.items():
        m = parts == pid
        col = (80,170,255) if v['agree_above_head'] else \
              (255,220,40) if v['any_above_head'] else (150,150,150)
        b_img[m] = b_img[m]*0.40 + np.array(col, np.float32)*0.60
    o = Image.fromarray(b_img.clip(0,255).astype(np.uint8)); o.thumbnail((1400,1400))
    o.save(os.path.join(ROOT, f'docs/art-options/height-query-zmap-{ROOM}.jpg'), quality=86)

if __name__ == '__main__':
    main()
