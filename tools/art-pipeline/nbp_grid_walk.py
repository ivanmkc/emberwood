#!/usr/bin/env python3
"""Grid-cell walkability (fallback, per direction): draw the logical tile
grid ON the plate and have NBP flood each cell green/red. Quantized but
drift-proof — the grid is part of the input, so layout can't wander.

Writes nbp-walk.png (cell-resolution, upscaled) + metrics with method=grid.
Usage: nbp_grid_walk.py --room <room>
"""
import argparse
import io
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw
from google import genai
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GW, GH = 40, 28  # logical 16px tiles

ap = argparse.ArgumentParser()
ap.add_argument('--room', required=True)
args, _ = ap.parse_known_args()
OUT = os.path.join(ROOT, 'docs', 'art-options', 'rooms', args.room)
PLATE = os.path.join(OUT, 'plate.png')

client = genai.Client(vertexai=True, project='adk-coding-agents', location='global')


def main():
    src = Image.open(PLATE).convert('RGB')
    W, H = src.size
    gridded = src.copy()
    d = ImageDraw.Draw(gridded)
    for gx in range(1, GW):
        x = round(gx * W / GW)
        d.line([(x, 0), (x, H)], fill=(255, 255, 255), width=2)
    for gy in range(1, GH):
        y = round(gy * H / GH)
        d.line([(0, y), (W, y)], fill=(255, 255, 255), width=2)
    seg_in = gridded.copy()
    seg_in.thumbnail((1400, 1400))

    prompt = (
        f'This game scene has a {GW}x{GH} grid drawn over it in white lines. Repaint the image '
        'so that EVERY grid cell is flooded with ONE solid color:\n'
        '- pure green #00FF00 if a walking character could stand on the ground at the CENTER of '
        'that cell (open floor, grates, decks, thresholds, flat floor markings)\n'
        '- pure red #FF0000 otherwise (walls, furniture, machines, counters, water, anything '
        'that rises from the floor at that cell center)\n'
        'Keep the grid alignment EXACT: each output cell must be uniform. No other colors.'
    )
    for attempt in range(3):
        img = None
        resp = client.models.generate_content(
            model='gemini-3-pro-image',
            contents=[seg_in, prompt],
            config=types.GenerateContentConfig(
                image_config=types.ImageConfig(aspect_ratio='4:3', image_size='2K'),
            ),
        )
        for part in (resp.parts or []):
            if part.inline_data is not None:
                img = Image.open(io.BytesIO(part.inline_data.data)).convert('RGB')
        if img is None:
            continue
        m = np.asarray(img.resize((W, H), Image.NEAREST)).astype(np.int16)
        dg = np.linalg.norm(m - np.array([0, 255, 0], np.int16), axis=2)
        dr = np.linalg.norm(m - np.array([255, 0, 0], np.int16), axis=2)
        cells = np.zeros((GH, GW), bool)
        purity_acc = []
        for gy in range(GH):
            for gx in range(GW):
                y0, y1 = round(gy * H / GH), round((gy + 1) * H / GH)
                x0, x1 = round(gx * W / GW), round((gx + 1) * W / GW)
                cg = dg[y0:y1, x0:x1]
                cr = dr[y0:y1, x0:x1]
                green = (cg < cr).mean()
                cells[gy, gx] = green > 0.5
                purity_acc.append(float((np.minimum(cg, cr) < 110).mean()))
        purity = float(np.mean(purity_acc))
        frac = float(cells.mean())
        walk = np.kron(cells, np.ones((int(np.ceil(H / GH)), int(np.ceil(W / GW))), bool))[:H, :W]
        met = {'method': 'grid', 'snap_purity': round(purity, 3),
               'walk_fraction': round(frac, 3), 'edge_alignment': 1.0, 'containment': 1.0,
               'pass': bool(purity >= 0.75 and 0.10 <= frac <= 0.80)}
        print(json.dumps(met))
        if met['pass']:
            Image.fromarray((walk * 255).astype(np.uint8)).save(os.path.join(OUT, 'nbp-walk.png'))
            json.dump(met, open(os.path.join(OUT, 'nbp-walk-metrics.json'), 'w'))
            blend = np.asarray(src).astype(np.float32).copy()
            blend[~walk] = blend[~walk] * 0.45 + np.array([255, 40, 40], np.float32) * 0.55
            blend[walk] = blend[walk] * 0.75 + np.array([40, 255, 90], np.float32) * 0.25
            bi = Image.fromarray(blend.clip(0, 255).astype(np.uint8))
            bi.thumbnail((1400, 1400), Image.LANCZOS)
            bi.save(os.path.join(OUT, 'nbp-walk-on-source.jpg'), quality=86)
            return
    sys.exit('grid walk failed all attempts')


if __name__ == '__main__':
    main()
