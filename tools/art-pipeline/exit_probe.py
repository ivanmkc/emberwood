#!/usr/bin/env python3
"""LLM exit placement: for each required exit edge, Gemini locates where the
painted scene actually has a passage touching that edge (road, gap, doorway,
stair, alley). segment_room carves toward that point — never the geometric
edge center through a wall.

Output: docs/art-options/rooms/<room>/exit-probe.json
  {edge: {"lo": <logical>, "hi": <logical>} | null}
"""
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from PIL import Image
from google import genai
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AP = os.path.join(ROOT, 'tools', 'art-pipeline')
_tl = threading.local()
EDGE_NAME = {'n': 'TOP', 's': 'BOTTOM', 'w': 'LEFT', 'e': 'RIGHT'}


def cli():
    if not hasattr(_tl, 'c'):
        _tl.c = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
    return _tl.c


def probe(room, edges, plate_path):
    img = Image.open(plate_path).convert('RGB')
    img.thumbnail((1100, 1100))
    out = {}
    for edge in edges:
        prompt = (
            f'Look at the {EDGE_NAME[edge]} edge of this top-down game scene. Is there a place '
            'where a walking character could plausibly LEAVE the scene across that edge — a road, '
            'path, alley, gap between buildings, doorway, stair, dock walkway or open ground '
            'touching that edge? Pick the SINGLE best one. Return JSON only: '
            '{"exists": bool, "box_2d": [ymin,xmin,ymax,xmax] normalized 0-1000 of the passage '
            'where it meets the edge, "what": "short description"}'
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
            out[edge] = None
            print(f'[{room}] edge {edge}: NO passage found')
            continue
        ymin, xmin, ymax, xmax = got['box_2d']
        if edge in ('n', 's'):
            lo, hi = round(xmin / 1000 * 640), round(xmax / 1000 * 640)
        else:
            lo, hi = round(ymin / 1000 * 448), round(ymax / 1000 * 448)
        out[edge] = {'lo': lo, 'hi': hi, 'what': got.get('what', '')}
        print(f'[{room}] edge {edge}: {lo}..{hi} ({got.get("what", "")})')
    od = os.path.join(ROOT, 'docs', 'art-options', 'rooms', room)
    os.makedirs(od, exist_ok=True)
    json.dump(out, open(os.path.join(od, 'exit-probe.json'), 'w'), indent=1)
    return room


def main():
    cfg = json.load(open(os.path.join(AP, 'rooms.json')))
    jobs = []
    for room, rc in cfg['rooms'].items():
        p = os.path.join(ROOT, 'docs', 'art-options', 'rooms', room, 'plate.png')
        if os.path.exists(p):
            jobs.append((room, sorted(rc['exits']), p))
    for room, rc in cfg.get('anchors', {}).items():
        p = os.path.join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor.png')
        jobs.append((room, sorted(rc['exits']), p))
    only = set(sys.argv[1:])
    if only:
        jobs = [j for j in jobs if j[0] in only]
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(lambda j: probe(*j), jobs))


if __name__ == '__main__':
    main()
