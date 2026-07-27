#!/usr/bin/env python3
"""Add a missing doorway to a parent scene via masked inpainting: Gemini
picks the best wall location, NBP paints an open doorway there (patch-local
magenta fill), judge-gated; the door rect is recorded into doors.json.

Usage: edit_door.py <parent> <interior>
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
AP = os.path.join(ROOT, 'tools', 'art-pipeline')
client = genai.Client(vertexai=True, project='adk-coding-agents', location='global')


def main():
    parent, interior = sys.argv[1], sys.argv[2]
    cfg = json.load(open(os.path.join(AP, 'rooms.json')))
    title = cfg['interiors'][interior]['title']
    art = os.path.join(ROOT, 'docs', 'art-options', 'rooms', parent)
    plate_p = os.path.join(art, 'plate.png')
    src = Image.open(plate_p).convert('RGB')
    W, H = src.size
    thumb = src.copy()
    thumb.thumbnail((1100, 1100))

    r = client.models.generate_content(
        model='gemini-3.1-pro-preview',
        contents=[thumb,
                  f'Where is the BEST place to add a doorway leading into "{title}" in this '
                  'scene? It must be on a wall or structure face that a walking character can '
                  'reach from the open ground in front of it (door bottom at ground level). '
                  'Return JSON only: {"box_2d": [ymin,xmin,ymax,xmax] normalized 0-1000 for a '
                  'door-sized opening, "why": "short"}'],
        config=types.GenerateContentConfig(max_output_tokens=1024),
    )
    t = r.text or ''
    st = t.find('{')
    loc, _ = json.JSONDecoder().raw_decode(t[st:])
    ymin, xmin, ymax, xmax = loc['box_2d']
    x0, y0 = int(xmin / 1000 * W), int(ymin / 1000 * H)
    x1, y1 = int(xmax / 1000 * W), int(ymax / 1000 * H)
    print(f'[{parent}] door site for {interior}: {x0},{y0}..{x1},{y1} ({loc.get("why", "")})')

    plate_np = np.asarray(src).copy()
    pad = 90
    cx0, cy0 = max(0, x0 - pad), max(0, y0 - pad)
    cx1, cy1 = min(W, x1 + pad), min(H, y1 + pad)
    crop = plate_np[cy0:cy1, cx0:cx1].copy()
    m = np.zeros(crop.shape[:2], bool)
    m[y0 - cy0:y1 - cy0, x0 - cx0:x1 - cx0] = True
    fill = crop.copy()
    fill[m] = (255, 0, 255)

    def nearest_aspect(w, h):
        opts = {'1:1': 1.0, '4:3': 4 / 3, '3:4': 3 / 4, '16:9': 16 / 9, '9:16': 9 / 16}
        return min(opts, key=lambda kk: abs(opts[kk] - w / h))

    prompt = (
        f'The flat magenta region marks where to paint a DOORWAY into "{title}" in this '
        'pixel-art game scene. Paint inside the magenta region an inviting enterable doorway at '
        'ground level — a door frame with a slightly open or shadowed interior, a small sign or '
        'lamp beside it — matching the surrounding wall material, palette, outlines and lighting '
        'EXACTLY. Keep every non-magenta pixel EXACTLY identical to the input.'
    )
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
                      'Does this crop contain a plausible enterable doorway at ground level, '
                      'well blended with the surrounding pixel-art (no seams, no style break)? '
                      'Return JSON only: {"door": bool, "blended": bool, "issues": "short"}'],
            config=types.GenerateContentConfig(max_output_tokens=1024),
        )
        tt = jr.text or ''
        stt = tt.find('{')
        v = {}
        if stt >= 0:
            try:
                v, _ = json.JSONDecoder().raw_decode(tt[stt:])
            except Exception:  # noqa: BLE001
                pass
        print(f'[{parent}] attempt {attempt}: door={v.get("door")} blended={v.get("blended")} {v.get("issues", "")}')
        if v.get('door') and v.get('blended'):
            plate_np[cy0:cy1, cx0:cx1] = cand
            Image.fromarray(plate_np).save(plate_p)
            pv = Image.fromarray(plate_np)
            pv.thumbnail((1400, 1400), Image.LANCZOS)
            pv.save(os.path.join(art, 'plate-preview.jpg'), quality=86)
            doors = json.load(open(os.path.join(AP, 'doors.json')))
            rect = [round(x0 / W * 640), round(y0 / H * 448),
                    round(x1 / W * 640), round(y1 / H * 448)]
            doors.setdefault(parent, [])
            doors[parent] = [d for d in doors[parent] if d['to'] != interior]
            doors[parent].append({'to': interior, 'rect': rect, 'what': 'painted doorway'})
            json.dump(doors, open(os.path.join(AP, 'doors.json'), 'w'), indent=1)
            print(f'[{parent}] doorway painted + recorded at {rect}')
            return
    sys.exit(f'[{parent}] could not paint doorway')


if __name__ == '__main__':
    main()
