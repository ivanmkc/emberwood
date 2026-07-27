#!/usr/bin/env python3
"""Locate each interior's entry door in its parent exterior scene (Gemini
box detection), producing door exits for the room registry.

Output: tools/art-pipeline/doors.json =
  {parent: [{to: interior, rect: [logical x0,y0,x1,y1], what}]}
"""
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

from PIL import Image
from google import genai
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AP = os.path.join(ROOT, 'tools', 'art-pipeline')
_tl = threading.local()


def cli():
    if not hasattr(_tl, 'c'):
        _tl.c = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
    return _tl.c


def parent_plate(parent):
    if parent == 'anchorroom':
        clean = os.path.join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor-clean.png')
        return clean if os.path.exists(clean) else \
            os.path.join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor.png')
    return os.path.join(ROOT, 'docs', 'art-options', 'rooms', parent, 'plate.png')


def probe(parent, wants):
    img = Image.open(parent_plate(parent)).convert('RGB')
    img.thumbnail((1100, 1100))
    out = []
    for interior, title in wants:
        prompt = (
            f'Find the doorway/entrance in this scene that would lead into "{title}". Pick the '
            'single most plausible enterable doorway (an open or closed door, entry gap, or '
            'entrance threshold a walking character could step into). Return JSON only: '
            '{"exists": bool, "box_2d": [ymin,xmin,ymax,xmax] normalized 0-1000 of the DOORWAY '
            'opening itself (not the whole building), "what": "short"}'
        )
        got = None
        for _ in range(3):
            try:
                r = cli().models.generate_content(
                    model='gemini-3.1-pro-preview',
                    contents=[img, prompt],
                    config=types.GenerateContentConfig(max_output_tokens=1024),
                )
                t = r.text or ''
                st = t.find('{')
                if st >= 0:
                    got, _ = json.JSONDecoder().raw_decode(t[st:])
                    break
            except Exception:  # noqa: BLE001
                pass
        if not got or not got.get('exists') or 'box_2d' not in got:
            print(f'[{parent}] no door found for {interior}')
            continue
        ymin, xmin, ymax, xmax = got['box_2d']
        rect = [round(xmin / 1000 * 640), round(ymin / 1000 * 448),
                round(xmax / 1000 * 640), round(ymax / 1000 * 448)]
        out.append({'to': interior, 'rect': rect, 'what': got.get('what', '')})
        print(f'[{parent}] door -> {interior}: {rect} ({got.get("what", "")})')
    return parent, out


def main():
    cfg = json.load(open(os.path.join(AP, 'rooms.json')))
    byparent = {}
    for interior, ic in cfg.get('interiors', {}).items():
        byparent.setdefault(ic['parent'], []).append((interior, ic['title']))
    with ThreadPoolExecutor(max_workers=4) as ex:
        res = dict(ex.map(lambda kv: probe(*kv), byparent.items()))
    json.dump(res, open(os.path.join(AP, 'doors.json'), 'w'), indent=1)
    total = sum(len(v) for v in res.values())
    print(f'doors.json: {total} doors across {len(res)} parents')


if __name__ == '__main__':
    main()
