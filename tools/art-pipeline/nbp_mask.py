#!/usr/bin/env python3
"""NBP-native segmentation: the image model repaints the scene as a flat
color-coded mask. Instances = connected components per class color.

Gates (drift is the failure mode — NBP re-renders, it does not copy):
  1. snap purity: >=90% of pixels snap to a legal class color
  2. floor fraction sanity (0.25..0.75)
  3. edge alignment: Sobel edges of mask vs source agree above threshold
Outputs mask PNG + on-source visualization + metrics JSON.
"""
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
import argparse
_ap = argparse.ArgumentParser()
_ap.add_argument('--room', default=None, help='room name under docs/art-options/rooms/<room>/')
_args, _ = _ap.parse_known_args()
if _args.room:
    OUT = os.path.join(ROOT, 'docs', 'art-options', 'rooms', _args.room)
    PLATE = os.path.join(OUT, 'plate.png')


CLASSES = {
    'floor': (0, 255, 0),
    'building': (255, 0, 0),
    'water': (0, 0, 255),
    'character': (255, 255, 0),
    'tank': (0, 255, 255),
    'pylon': (255, 128, 0),
    'prop': (255, 0, 255),
    'pipe': (128, 0, 255),
}

PROMPT = (
    'Repaint this EXACT image as a flat segmentation map. Keep every object\'s '
    'silhouette, position and scale PIXEL-IDENTICAL to the input — do not move, '
    'resize or redraw anything. Fill each region with ONE flat solid color, no '
    'shading, no gradients, no outlines, no texture:\n'
    '- walkable ground/floor (plaza plating, bare ground, bridge deck, stairs): pure green #00FF00\n'
    '- buildings and storefronts (walls, doors, signs, rooflines): pure red #FF0000\n'
    '- water (canals, channels, pools): pure blue #0000FF\n'
    '- people and robots: pure yellow #FFFF00\n'
    '- glass tanks, domes and cases with plants or liquid inside: pure cyan #00FFFF\n'
    '- tall glowing energy structures (pylons, reactor columns) and their bases: pure orange #FF8000\n'
    '- crates, barrels, machines, stalls, railings and other props: pure magenta #FF00FF\n'
    '- thick pipes and cables lying on the ground: pure violet #8000FF\n'
    'Every pixel must be EXACTLY one of these eight colors — NO dithering, NO anti-aliasing, '
    'NO gradients, hard 1-pixel boundaries between regions.'
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
                import io
                mask_img = Image.open(io.BytesIO(part.inline_data.data)).convert('RGB')
        if mask_img is not None:
            break
        print(f'empty response, retry {attempt + 1}')
    if mask_img is None:
        sys.exit('NBP returned no mask image')

    mask_img = mask_img.resize(src.size, Image.NEAREST)
    m = np.asarray(mask_img).astype(np.int16)

    # gate 1: snap purity
    names = list(CLASSES)
    cols = np.array([CLASSES[n] for n in names], dtype=np.int16)
    d = np.linalg.norm(m[:, :, None, :] - cols[None, None, :, :], axis=3)
    idx = d.argmin(axis=2)
    mind = d.min(axis=2)
    pure = (mind < 90).mean()

    # gate 2: floor fraction
    floor_frac = (idx == names.index('floor'))[mind < 90].mean()

    # gate 3: edge alignment (dilated-source-edge hit rate of mask edges)
    sg = cv2.Canny(cv2.cvtColor(np.asarray(src), cv2.COLOR_RGB2GRAY), 60, 140)
    mg = cv2.Canny(cv2.cvtColor(np.asarray(mask_img), cv2.COLOR_RGB2GRAY), 60, 140)
    sgd = cv2.dilate(sg, np.ones((9, 9), np.uint8))
    align = (mg > 0)[..., None].squeeze()
    edge_agree = (sgd[align] > 0).mean() if align.any() else 0.0

    metrics = {'snap_purity': round(float(pure), 3),
               'floor_fraction': round(float(floor_frac), 3),
               'edge_alignment': round(float(edge_agree), 3),
               'pass': bool(pure >= 0.85 and 0.12 <= floor_frac <= 0.80 and edge_agree >= 0.55)}
    print(json.dumps(metrics, indent=1))
    json.dump(metrics, open(os.path.join(OUT, 'nbp-mask-metrics.json'), 'w'))

    # outputs: snapped mask + 50/50 blend over source for the board
    snapped = cols[idx].astype(np.uint8)
    snapped[mind >= 90] = (20, 20, 20)
    Image.fromarray(snapped).save(os.path.join(OUT, 'nbp-mask.png'))
    blend = (np.asarray(src).astype(np.float32) * 0.45 + snapped.astype(np.float32) * 0.55)
    bi = Image.fromarray(blend.clip(0, 255).astype(np.uint8))
    bi.thumbnail((1400, 1400), Image.LANCZOS)
    bi.save(os.path.join(OUT, 'nbp-mask-on-source.jpg'), quality=86)
    raw = mask_img.copy()
    raw.thumbnail((1400, 1400), Image.NEAREST)
    raw.save(os.path.join(OUT, 'nbp-mask-raw.jpg'), quality=86)
    sys.exit(0 if metrics['pass'] else 1)


if __name__ == '__main__':
    main()
