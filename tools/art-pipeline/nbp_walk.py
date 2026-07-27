#!/usr/bin/env python3
"""NBP walkability mask: second flat-repaint pass, binary green/red.

Layered on top of the class mask: walkability is a gameplay judgment (bridge
decks and stairs ARE walkable structure; upper wall bands are floor-colored
but not standable). Gates:
  1. snap purity (2 colors) >= 0.85
  2. walkable fraction 0.20..0.70
  3. edge alignment vs source Canny >= 0.5
  4. cross-containment: walkable pixels must lie inside the class mask's
     floor-or-structure regions (>= 0.80) — walkability is a SUBSET judgment
     (bridge decks/stairs are walkable structure; background floor is not
     walkable), so symmetric IoU is the wrong test.
"""
import io
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image
from google import genai
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATE = os.path.join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor.png')
OUT = os.path.join(ROOT, 'docs', 'art-options')

PROMPT = (
    'Repaint this EXACT image as a binary WALKABILITY map for a top-down game. Keep every '
    'silhouette and position PIXEL-IDENTICAL — do not move or redraw anything. Use exactly two '
    'flat colors, no shading, no outlines:\n'
    '- pure green #00FF00: ground a walking character can actually stand on — plaza plating, bare '
    'ground, the metal grate, the bridge deck, staircases, doorway thresholds\n'
    '- pure red #FF0000: everything else — building walls and roofs, background/upper wall '
    'surfaces, all objects and props, glass tanks, the pylon, water, railings, people and robots, '
    'pipes and thick cables lying on the ground\n'
    'Every pixel must be exactly green or red.'
)


def main():
    client = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
    src = Image.open(PLATE).convert('RGB')
    seg_in = src.copy()
    seg_in.thumbnail((1200, 1200))

    mask_img = None
    for attempt in range(3):
        resp = client.models.generate_content(
            model='gemini-3-pro-image',
            contents=[seg_in, PROMPT],
            config=types.GenerateContentConfig(
                image_config=types.ImageConfig(aspect_ratio='4:3', image_size='2K'),
            ),
        )
        for part in (resp.parts or []):
            if part.inline_data is not None:
                mask_img = Image.open(io.BytesIO(part.inline_data.data)).convert('RGB')
        if mask_img is not None:
            break
        print(f'empty response, retry {attempt + 1}')
    if mask_img is None:
        sys.exit('NBP returned no walkability image')

    mask_img = mask_img.resize(src.size, Image.NEAREST)
    m = np.asarray(mask_img).astype(np.int16)
    dg = np.linalg.norm(m - np.array([0, 255, 0], np.int16), axis=2)
    dr = np.linalg.norm(m - np.array([255, 0, 0], np.int16), axis=2)
    walk = dg < dr
    pure = (np.minimum(dg, dr) < 100).mean()
    frac = float(walk.mean())

    sg = cv2.Canny(cv2.cvtColor(np.asarray(src), cv2.COLOR_RGB2GRAY), 60, 140)
    mg = cv2.Canny((walk * 255).astype(np.uint8), 60, 140)
    sgd = cv2.dilate(sg, np.ones((9, 9), np.uint8))
    edge_agree = float((sgd[mg > 0] > 0).mean()) if (mg > 0).any() else 0.0

    # cross-containment vs class mask: walkable ⊆ floor ∪ walkable-structure
    cls = np.asarray(Image.open(os.path.join(OUT, 'nbp-mask.png')).convert('RGB')
                     .resize(src.size, Image.NEAREST)).astype(np.int16)
    floor = np.linalg.norm(cls - np.array([0, 255, 0], np.int16), axis=2) < 90
    struct = np.linalg.norm(cls - np.array([255, 0, 255], np.int16), axis=2) < 90  # props
    build = np.linalg.norm(cls - np.array([255, 0, 0], np.int16), axis=2) < 90     # buildings (stairs/bridge live here)
    contain = float((walk & (floor | struct | build)).sum() / max(1, walk.sum()))

    metrics = {'snap_purity': round(float(pure), 3), 'walk_fraction': round(frac, 3),
               'edge_alignment': round(edge_agree, 3), 'containment': round(contain, 3),
               'pass': bool(pure >= 0.85 and 0.20 <= frac <= 0.70 and edge_agree >= 0.5 and contain >= 0.80)}
    print(json.dumps(metrics, indent=1))
    json.dump(metrics, open(os.path.join(OUT, 'nbp-walk-metrics.json'), 'w'))

    Image.fromarray((walk * 255).astype(np.uint8)).save(os.path.join(OUT, 'nbp-walk.png'))
    blend = np.asarray(src).astype(np.float32).copy()
    blend[~walk] = blend[~walk] * 0.45 + np.array([255, 40, 40], np.float32) * 0.55
    blend[walk] = blend[walk] * 0.75 + np.array([40, 255, 90], np.float32) * 0.25
    bi = Image.fromarray(blend.clip(0, 255).astype(np.uint8))
    bi.thumbnail((1400, 1400), Image.LANCZOS)
    bi.save(os.path.join(OUT, 'nbp-walk-on-source.jpg'), quality=86)
    sys.exit(0 if metrics['pass'] else 1)


if __name__ == '__main__':
    main()
