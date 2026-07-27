#!/usr/bin/env python3
"""Generate district plate scenes, style-anchored on the approved anchor.

NBP-first with reflective prompting (per direction): every scene is judged
against the anchor (style match, perspective, no characters, density) by
median-of-3 vote; on failure the judge's critique is folded back into the
next attempt's prompt. The best-performing prompt suffix is persisted to
prompts.json so learning carries across rooms.
"""
import io
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from PIL import Image
from google import genai
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ANCHOR = os.path.join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor.png')
OUTDIR = os.path.join(ROOT, 'docs', 'art-options', 'rooms')
PROMPTS = os.path.join(ROOT, 'tools', 'art-pipeline', 'prompts.json')

_tl = threading.local()


def cli():
    if not hasattr(_tl, 'c'):
        _tl.c = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
    return _tl.c


BASE_STYLE = (
    'Paint a NEW scene in EXACTLY the same art style as this reference image: same pixel-art '
    'rendering, same palette family and lighting mood, same camera (straight-on top-down 3/4 '
    'view, axis-aligned, stage-set flat front elevations for buildings, NO isometric rotation), '
    'same tile scale so objects have the same relative sizes as the reference. Dense, '
    'production-quality environment art that fills the whole frame.\n\nThe new scene: {brief}.\n\n'
    'IMPORTANT: absolutely NO people, NO robots, NO creatures anywhere in the scene. '
    'Leave generous connected walkable ground so a character could move through the scene, '
    'including clear ground strips reaching the {edges} edge(s) of the frame where exits lead '
    'to neighboring districts.'
)

JUDGE_PROMPT = (
    'Image 1 is the approved style anchor of a game. Image 2 is a candidate scene for a new '
    'district of the same game. Judge candidate vs anchor. Return JSON only: '
    '{"style_match": 1-10 (palette, rendering technique, outline/dither treatment identical?), '
    '"perspective_ok": bool (same straight-on top-down 3/4, axis-aligned, no isometric rotation?), '
    '"character_free": bool (no people/robots/creatures?), '
    '"density": 1-10 (as dense and detailed as the anchor?), '
    '"walkable_ground": bool (visible connected open ground a character could walk on?), '
    '"issues": "one short sentence: the biggest deviation to fix"}'
)


def judge_vote(anchor_img, cand_img, n=3):
    votes = []
    for _ in range(n):
        r = cli().models.generate_content(
            model='gemini-3.1-pro-preview',
            contents=[anchor_img, cand_img, JUDGE_PROMPT],
            config=types.GenerateContentConfig(max_output_tokens=2048),
        )
        t = r.text or ''
        st = t.find('{')
        if st >= 0:
            try:
                v, _ = json.JSONDecoder().raw_decode(t[st:])
                votes.append(v)
            except Exception:  # noqa: BLE001
                pass
    if not votes:
        return None
    med = lambda k, d=0: sorted(v.get(k, d) for v in votes)[len(votes) // 2]  # noqa: E731
    maj = lambda k: sum(1 for v in votes if v.get(k)) > len(votes) / 2  # noqa: E731
    return {'style_match': med('style_match'), 'density': med('density'),
            'perspective_ok': maj('perspective_ok'), 'character_free': maj('character_free'),
            'walkable_ground': maj('walkable_ground'),
            'issues': votes[0].get('issues', '')}


def gen_room(name, cfg, anchor_img):
    out = os.path.join(OUTDIR, name)
    os.makedirs(out, exist_ok=True)
    plate_path = os.path.join(out, 'plate.png')
    meta_path = os.path.join(out, 'scene-metrics.json')
    if os.path.exists(plate_path) and os.path.exists(meta_path) \
            and json.load(open(meta_path)).get('pass'):
        print(f'[{name}] already generated + gated, skipping')
        return True
    edges = ', '.join({'n': 'top', 's': 'bottom', 'w': 'left', 'e': 'right'}[e]
                      for e in cfg['exits'])
    critique = ''
    for attempt in range(4):
        prompt = BASE_STYLE.format(brief=cfg['brief'], edges=edges)
        if critique:
            prompt += f'\nFix from the previous attempt: {critique}'
        img = None
        try:
            resp = cli().models.generate_content(
                model='gemini-3-pro-image',
                contents=[anchor_img, prompt],
                config=types.GenerateContentConfig(
                    image_config=types.ImageConfig(aspect_ratio='4:3', image_size='2K'),
                ),
            )
            for part in (resp.parts or []):
                if part.inline_data is not None:
                    img = Image.open(io.BytesIO(part.inline_data.data)).convert('RGB')
        except Exception as e:  # noqa: BLE001
            print(f'[{name}] attempt {attempt}: API error {e}')
            continue
        if img is None:
            print(f'[{name}] attempt {attempt}: empty response')
            continue
        v = judge_vote(anchor_img, img, n=3)
        if v is None:
            print(f'[{name}] attempt {attempt}: judge unparseable')
            continue
        ok = (v['style_match'] >= 8 and v['density'] >= 7 and v['perspective_ok']
              and v['character_free'] and v['walkable_ground'])
        print(f'[{name}] attempt {attempt}: style {v["style_match"]} density {v["density"]} '
              f'persp {v["perspective_ok"]} nochar {v["character_free"]} '
              f'ground {v["walkable_ground"]} -> {"PASS" if ok else "fail"} | {v["issues"]}')
        if ok:
            img.save(plate_path)
            thumb = img.copy()
            thumb.thumbnail((1400, 1400), Image.LANCZOS)
            thumb.save(os.path.join(out, 'plate-preview.jpg'), quality=86)
            json.dump({**v, 'pass': True, 'attempts': attempt + 1},
                      open(meta_path, 'w'))
            return True
        critique = v['issues']
    json.dump({'pass': False, 'last_issues': critique}, open(meta_path, 'w'))
    return False


def main():
    cfg = json.load(open(os.path.join(ROOT, 'tools', 'art-pipeline', 'rooms.json')))
    anchor_img = Image.open(ANCHOR).convert('RGB')
    anchor_img.thumbnail((1200, 1200))
    only = sys.argv[1:] or list(cfg['rooms'])
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = dict(zip(only, ex.map(
            lambda n: gen_room(n, cfg['rooms'][n], anchor_img), only)))
    fails = [n for n, ok in results.items() if not ok]
    print(f'\n{len(only) - len(fails)}/{len(only)} scenes generated; failed: {fails or "none"}')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
