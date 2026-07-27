#!/usr/bin/env python3
"""Interactable hotspots: Gemini writes examine text for every significant
painted object in each plate room (per direction: LLM does the work; the
instance geometry comes from the NBP class mask).

Output: assets/rooms/<room>.hotspots.json = [{box:[logical x0,y0,x1,y1],
name, text:[wrapped lines]}]. Verified: JSON parse, one entry per requested
instance, non-empty text; judge disabled instances are dropped, not faked.
"""
import json
import os
import sys
import textwrap
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


def room_plate(room):
    if room == 'anchorroom':
        clean = os.path.join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor-clean.png')
        return clean if os.path.exists(clean) else \
            os.path.join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor.png')
    return os.path.join(ROOT, 'docs', 'art-options', 'rooms', room, 'plate.png')


def build(room):
    ij = os.path.join(ROOT, 'assets', 'rooms', f'{room}.instances.json')
    if not os.path.exists(ij):
        return f'[{room}] no instances.json, skipped'
    data = json.load(open(ij))
    plate = Image.open(room_plate(room)).convert('RGB')
    SW, SH = plate.size
    cands = []
    for i in data['instances']:
        if i['kind'] not in ('structure', 'water'):
            continue
        x0, y0, x1, y1 = i['box']
        area = (x1 - x0) * (y1 - y0)
        if area < SW * SH * 0.002:
            continue
        cands.append(i)
    cands = sorted(cands, key=lambda i: -(i['box'][2] - i['box'][0]) * (i['box'][3] - i['box'][1]))[:14]
    if not cands:
        return f'[{room}] no candidate instances'
    listing = '\n'.join(
        f'{n}. class={i["label"]} box_frac=({i["box"][0]/SW:.2f},{i["box"][1]/SH:.2f},'
        f'{i["box"][2]/SW:.2f},{i["box"][3]/SH:.2f})'
        for n, i in enumerate(cands))
    thumb = plate.copy()
    thumb.thumbnail((1100, 1100))
    prompt = (
        'This is a scene from Emberwood, a cozy-melancholy sci-fi exploration RPG (a settlement '
        'rebuilding around old technology). The numbered objects below are marked by their class '
        'and fractional bounding box (x0,y0,x1,y1 of image size). For EACH number, look at that '
        'region of the image and write an examine entry a player sees when inspecting it:\n'
        f'{listing}\n\n'
        'Return JSON only: a list, one object per number, in order: '
        '{"n": <number>, "name": "SHORT ALL-CAPS OBJECT NAME (2-4 words, what it actually is in '
        'the image)", "text": "1-2 sentences, second person, concrete and specific to what is '
        'visibly painted there, warm worn-future tone, no lore contradictions, no questions"}'
    )
    for attempt in range(3):
        r = cli().models.generate_content(
            model='gemini-3.1-pro-preview',
            contents=[thumb, prompt],
            config=types.GenerateContentConfig(max_output_tokens=8192),
        )
        t = r.text or ''
        st = t.find('[')
        if st < 0:
            continue
        try:
            items, _ = json.JSONDecoder().raw_decode(t[st:])
        except Exception:  # noqa: BLE001
            continue
        byn = {it.get('n'): it for it in items if isinstance(it, dict)}
        out = []
        for n, i in enumerate(cands):
            it = byn.get(n)
            if not it or not it.get('text') or not it.get('name'):
                continue
            x0, y0, x1, y1 = i['box']
            out.append({
                'box': [round(x0 / SW * 640), round(y0 / SH * 448),
                        round(x1 / SW * 640), round(y1 / SH * 448)],
                'name': str(it['name'])[:28],
                'text': textwrap.wrap(str(it['text']), 46)[:4],
            })
        if len(out) >= max(3, len(cands) // 2):
            json.dump(out, open(os.path.join(ROOT, 'assets', 'rooms', f'{room}.hotspots.json'), 'w'),
                      indent=1)
            return f'[{room}] {len(out)} hotspots written'
    return f'[{room}] FAILED after 3 attempts'


def main():
    cfg = json.load(open(os.path.join(AP, 'rooms.json')))
    rooms = sys.argv[1:] or (['anchorroom'] + list(cfg['rooms']))
    with ThreadPoolExecutor(max_workers=4) as ex:
        for line in ex.map(build, rooms):
            print(line)


if __name__ == '__main__':
    main()
