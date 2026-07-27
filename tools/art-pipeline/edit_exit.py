#!/usr/bin/env python3
"""Open a missing exit passage in a plate via patch-local masked inpainting
(kidsgame recipe): magenta-mark a strip reaching the edge, NBP paints a
walkable opening (alley gap, catwalk, doorway) continuing to the frame edge;
paste back ONLY inside the magenta mask. Judge-gated, then the room's masks
must be regenerated.

Usage: edit_exit.py <room> <edge:n|s|w|e>
"""
import io
import json
import os
import sys

import numpy as np
from PIL import Image
from google import genai
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
client = genai.Client(vertexai=True, project='adk-coding-agents', location='global')


def main():
    room, edge = sys.argv[1], sys.argv[2]
    art = os.path.join(ROOT, 'docs', 'art-options', 'rooms', room)
    plate_p = os.path.join(art, 'plate.png')
    src = Image.open(plate_p).convert('RGB')
    W, H = src.size
    walk = np.asarray(Image.open(os.path.join(art, 'nbp-walk.png')).convert('L')
                      .resize((W, H), Image.NEAREST)) > 127

    # choose the opening position: the edge-parallel slot with the most
    # walkable ground within reach of the edge
    span = int(64 / 640 * W)          # opening width ~64 logical px
    depth = int(110 / 448 * H)        # how far inward the passage runs
    if edge in ('w', 'e'):
        band = walk[:, :depth * 2] if edge == 'w' else walk[:, -depth * 2:]
        score = band.sum(axis=1).astype(float)
        k = np.ones(span)
        conv = np.convolve(score, k, 'same')
        conv[:H // 6] = 0
        conv[-H // 6:] = 0
        c = int(conv.argmax())
        y0, y1 = max(0, c - span // 2), min(H, c + span // 2)
        x0, x1 = (0, depth) if edge == 'w' else (W - depth, W)
    else:
        band = walk[:depth * 2, :] if edge == 'n' else walk[-depth * 2:, :]
        score = band.sum(axis=0).astype(float)
        conv = np.convolve(score, np.ones(span), 'same')
        conv[:W // 6] = 0
        conv[-W // 6:] = 0
        c = int(conv.argmax())
        x0, x1 = max(0, c - span // 2), min(W, c + span // 2)
        y0, y1 = (0, depth) if edge == 'n' else (H - depth, H)

    plate_np = np.asarray(src).copy()
    pad = 90
    cx0, cy0 = max(0, x0 - pad), max(0, y0 - pad)
    cx1, cy1 = min(W, x1 + pad), min(H, y1 + pad)
    crop = plate_np[cy0:cy1, cx0:cx1].copy()
    m = np.zeros(crop.shape[:2], bool)
    m[y0 - cy0:y1 - cy0, x0 - cx0:x1 - cx0] = True
    fill = crop.copy()
    fill[m] = (255, 0, 255)
    edge_name = {'n': 'top', 's': 'bottom', 'w': 'left', 'e': 'right'}[edge]
    prompt = (
        'The flat magenta region marks a passage to be opened in this pixel-art game scene. '
        f'Paint INSIDE the magenta region a walkable opening that lets a character exit across '
        f'the {edge_name} edge of the image: an alley gap between the structures, an open '
        'walkway, or a doorway-sized corridor of clear ground, continuing the surrounding art '
        'style, floor material, palette and lighting EXACTLY. The passage floor must reach the '
        f'{edge_name} edge. Keep every non-magenta pixel EXACTLY identical to the input.'
    )

    def nearest_aspect(w, h):
        opts = {'1:1': 1.0, '4:3': 4 / 3, '3:4': 3 / 4, '16:9': 16 / 9, '9:16': 9 / 16}
        return min(opts, key=lambda kk: abs(opts[kk] - w / h))

    for attempt in range(3):
        patch = None
        resp = client.models.generate_content(
            model='gemini-3-pro-image',
            contents=[Image.fromarray(fill), prompt],
            config=types.GenerateContentConfig(
                image_config=types.ImageConfig(
                    aspect_ratio=nearest_aspect(cx1 - cx0, cy1 - cy0), image_size='1K'),
            ),
        )
        for part in (resp.parts or []):
            if part.inline_data is not None:
                patch = Image.open(io.BytesIO(part.inline_data.data)).convert('RGB')
        if patch is None:
            continue
        patch = np.asarray(patch.resize((cx1 - cx0, cy1 - cy0), Image.LANCZOS))
        cand = crop.copy()
        cand[m] = patch[m]
        jr = client.models.generate_content(
            model='gemini-3.1-pro-preview',
            contents=[Image.fromarray(cand),
                      f'Does this game-scene crop contain a plausible walkable passage of clear '
                      f'ground reaching the {edge_name} edge, well blended with the surrounding '
                      'pixel-art (no seams, no style break)? '
                      'Return JSON only: {"passage": bool, "blended": bool, "issues": "short"}'],
            config=types.GenerateContentConfig(max_output_tokens=1024),
        )
        t = jr.text or ''
        st = t.find('{')
        v = {}
        if st >= 0:
            try:
                v, _ = json.JSONDecoder().raw_decode(t[st:])
            except Exception:  # noqa: BLE001
                pass
        print(f'[{room}:{edge}] attempt {attempt}: passage={v.get("passage")} '
              f'blended={v.get("blended")} {v.get("issues", "")}')
        if v.get('passage') and v.get('blended'):
            plate_np[cy0:cy1, cx0:cx1] = cand
            Image.fromarray(plate_np).save(plate_p)
            pv = Image.fromarray(plate_np)
            pv.thumbnail((1400, 1400), Image.LANCZOS)
            pv.save(os.path.join(art, 'plate-preview.jpg'), quality=86)
            print(f'[{room}:{edge}] passage opened at {x0},{y0}..{x1},{y1} (src px)')
            return
    sys.exit(f'[{room}:{edge}] could not open passage')


if __name__ == '__main__':
    main()
