#!/usr/bin/env python3
"""Composite A/B z-judgment (Ivan): for each contested part, render the player
character at a real standing spot whose bbox overlaps the part, in BOTH
z-orders — char-over-part vs part-over-char — and ask gemini-3.5-flash which
composite is physically correct. Side order is randomized per part (seeded)
to kill left/right bias. Third independent z-source for the fusion."""
import json
import os
import random
import threading

import cv2
import numpy as np
from PIL import Image
from google import genai
from google.genai import errors as genai_errors

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOM = 'night-bazaar'
MODEL = 'gemini-3.5-flash'
CHAR_W, CHAR_H = 80, 176
WIN = 460
_tl = threading.local()
def cli():
    c = getattr(_tl, 'c', None)
    if c is None:
        c = _tl.c = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
    return c

Q = ('Two renderings of the same pixel-art scene with a villager standing at the same spot. '
     'In one, the outlined object is drawn IN FRONT of the villager (covering him); in the '
     'other, the villager is drawn in front of the object. Based on real-world depth (where '
     'his feet are on the ground vs where the object sits or hangs), which rendering is '
     'physically correct? Answer STRICT JSON only: {"correct": "left" | "right"}')


def main():
    rng = random.Random(7)
    parts = np.load(os.path.join(ROOT, f'tools/art-pipeline/_srcmasks_{ROOM}-parts.npz'))['inst']
    hq = json.load(open(os.path.join(ROOT, f'docs/art-options/height-query-{ROOM}.json')))['parts']
    vz = json.load(open(os.path.join(ROOT, f'docs/art-options/veo-z-{ROOM}.json')))['objects']
    plate = np.asarray(Image.open(os.path.join(
        ROOT, f'docs/art-options/rooms/{ROOM}/plate.png')).convert('RGB'))
    walk = np.asarray(Image.open(os.path.join(
        ROOT, f'docs/art-options/magenta-ground-{ROOM}-nowires.png')).convert('L')) > 127
    sprite = Image.open(os.path.join(ROOT, 'assets/chars/player-down.png')).convert('RGBA')
    sprite = np.asarray(sprite.resize((sprite.width * 4, sprite.height * 4), Image.NEAREST))
    sh, sw = sprite.shape[:2]
    H, W = parts.shape

    targets = [int(p) for p, v in hq.items()
               if v['any_above_head'] or vz.get(p, {}).get('verdict') == 'contradiction']
    print(f'{len(targets)} contested/overhead-candidate parts')

    def render(feet, part_mask, char_front):
        img = plate.copy()
        fx, fy = feet
        x0, y0 = fx - sw // 2, fy - sh
        a = sprite[:, :, 3:] / 255.0
        xs0, ys0 = max(0, x0), max(0, y0)
        xs1, ys1 = min(W, x0 + sw), min(H, y0 + sh)
        sub = img[ys0:ys1, xs0:xs1].astype(np.float32)
        sp = sprite[ys0 - y0:ys1 - y0, xs0 - x0:xs1 - x0]
        al = sp[:, :, 3:] / 255.0
        img[ys0:ys1, xs0:xs1] = (sub * (1 - al) + sp[:, :, :3] * al).astype(np.uint8)
        if not char_front:
            img[part_mask] = plate[part_mask]
        return img

    results = {}
    for i, pid in enumerate(targets):
        m = parts == pid
        ys, xs = np.nonzero(m)
        # standing spot: walkable feet whose char bbox overlaps the part most
        best, bestov = None, 0
        for fy in range(min(H - 8, ys.max() + 8), min(H - 8, ys.max() + 260), 14):
            for fx in range(max(CHAR_W, xs.min()), min(W - CHAR_W, xs.max() + 1), 20):
                if not walk[fy, fx]:
                    continue
                ov = int(m[max(0, fy - CHAR_H):fy, fx - CHAR_W // 2:fx + CHAR_W // 2].sum())
                if ov > bestov:
                    best, bestov = (fx, fy), ov
        if best is None or bestov < 400:
            continue
        A = render(best, m, True)
        B = render(best, m, False)
        flip = rng.random() < 0.5
        L, R = (B, A) if flip else (A, B)
        cx, cy = best
        x0, y0 = np.clip(cx - WIN // 2, 0, W - WIN), np.clip(cy - int(WIN * 0.7), 0, H - WIN)
        side = np.concatenate([L[y0:y0 + WIN, x0:x0 + WIN],
                               np.full((WIN, 8, 3), 255, np.uint8),
                               R[y0:y0 + WIN, x0:x0 + WIN]], axis=1)
        # outline the part in both halves for reference
        try:
            r = cli().models.generate_content(model=MODEL,
                                              contents=[Image.fromarray(side), Q])
            t = r.text or ''
            ans = json.loads(t[t.index('{'): t.rindex('}') + 1]).get('correct')
            part_over_char = (ans == 'left') == flip if ans in ('left', 'right') else None
            # left==B when flip: part-over-char correct <=> answer picked B side
            results[pid] = {'part_over_char': part_over_char, 'overlap_px': bestov}
        except (genai_errors.APIError, ValueError, KeyError) as e:
            print(f'  part {pid}: {e}')
        if (i + 1) % 10 == 0:
            print(f'{i + 1}/{len(targets)} judged')
    n_over = sum(1 for v in results.values() if v['part_over_char'])
    print(f'composite A/B: {len(results)} judged, part-over-char {n_over}')
    json.dump({'room': ROOM, 'model': MODEL,
               'parts': {str(k): v for k, v in results.items()}},
              open(os.path.join(ROOT, f'docs/art-options/composite-ab-{ROOM}.json'), 'w'),
              indent=1)


if __name__ == '__main__':
    main()
