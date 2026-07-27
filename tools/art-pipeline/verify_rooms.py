#!/usr/bin/env python3
"""LLM verification sweep (per direction: use the latest Gemini generously).

For every built room, gemini-3.1-pro judges the collision overlay against the
plate: does the walkable/blocked split respect the painted scene (streets
green, buildings red, object bases red with bodies free, water red, no green
on roofs/walls, no big obviously-walkable area left red)? Median-of-3.
Writes docs/art-options/rooms/<room>/verify.json + a summary table.
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
_tl = threading.local()


def cli():
    if not hasattr(_tl, 'c'):
        _tl.c = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
    return _tl.c


PROMPT = (
    'Image 1: a painted top-down game scene. Image 2: the same scene tinted by its collision '
    'mask — GREEN tint = ground the player can walk on (reachable), RED tint = blocked, '
    'YELLOW = walkable but unreachable. Judge whether the collision respects the scene. '
    'Return JSON only: {'
    '"score": 1-10 (overall correctness of the walkable/blocked split), '
    '"green_on_nonfloor": "none|minor|major" (green on roofs, walls, water, object bodies that '
    'should block at their base ONLY counts if the green is at the base/footprint area), '
    '"red_on_floor": "none|minor|major" (large obviously-walkable floor areas left red), '
    '"unreachable_area": "none|minor|major" (yellow or clearly separated green areas the player '
    'apparently cannot reach), '
    '"worst_defect": "one short sentence naming the single worst defect and WHERE it is"}'
)


def judge(room):
    art = os.path.join(ROOT, 'docs', 'art-options', 'rooms', room)
    prev = os.path.join(art, 'collision-preview.jpg')
    plate = os.path.join(art, 'plate-preview.jpg')
    if room == 'anchorroom':
        prev = os.path.join(ROOT, 'docs', 'art-options', 'final-collision-on-source.jpg')
        plate = os.path.join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor.png')
    if not (os.path.exists(prev) and os.path.exists(plate)):
        return room, None
    p1 = Image.open(plate).convert('RGB')
    p1.thumbnail((1000, 1000))
    p2 = Image.open(prev).convert('RGB')
    p2.thumbnail((1000, 1000))
    votes = []
    for _ in range(3):
        try:
            r = cli().models.generate_content(
                model='gemini-3.1-pro-preview',
                contents=[p1, p2, PROMPT],
                config=types.GenerateContentConfig(max_output_tokens=2048),
            )
            t = r.text or ''
            st = t.find('{')
            if st >= 0:
                v, _ = json.JSONDecoder().raw_decode(t[st:])
                votes.append(v)
        except Exception:  # noqa: BLE001
            pass
    if not votes:
        return room, None
    sev = {'none': 0, 'minor': 1, 'major': 2}
    med = lambda k: sorted(v.get(k, 0) for v in votes)[len(votes) // 2]  # noqa: E731
    worst = max(votes, key=lambda v: sev.get(v.get('green_on_nonfloor', 'none'), 0)
                + sev.get(v.get('red_on_floor', 'none'), 0)
                + sev.get(v.get('unreachable_area', 'none'), 0))
    out = {'score': med('score'),
           'green_on_nonfloor': worst.get('green_on_nonfloor'),
           'red_on_floor': worst.get('red_on_floor'),
           'unreachable_area': worst.get('unreachable_area'),
           'worst_defect': worst.get('worst_defect')}
    if room != 'anchorroom':
        json.dump(out, open(os.path.join(art, 'verify.json'), 'w'), indent=1)
    return room, out


def main():
    rooms = sys.argv[1:]
    if not rooms:
        cfg = json.load(open(os.path.join(ROOT, 'tools', 'art-pipeline', 'rooms.json')))
        rooms = ['anchorroom'] + [r for r in cfg['rooms']
                                  if os.path.exists(os.path.join(ROOT, 'assets', 'rooms', f'{r}.collision.png'))]
    with ThreadPoolExecutor(max_workers=4) as ex:
        for room, v in ex.map(judge, rooms):
            if v is None:
                print(f'{room:14s}  NO VERDICT')
            else:
                print(f'{room:14s}  score {v["score"]}  green-bad:{v["green_on_nonfloor"]:6s} '
                      f'red-bad:{v["red_on_floor"]:6s} unreach:{v["unreachable_area"]:6s} | {v["worst_defect"]}')


if __name__ == '__main__':
    main()
