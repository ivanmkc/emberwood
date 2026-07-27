#!/usr/bin/env python3
"""Gemini vision judge for pipeline gates.

Usage as a library:
    from judge import judge_image
    verdict = judge_image([img_path, ...], rubric_name, context="...")

Model discipline: newest available 3-series pro (never 2.5), thinking low,
max_output_tokens >= 2048, tolerant JSON parsing via raw_decode.
"""
import json
import sys

from PIL import Image
from google import genai
from google.genai import types

_client = None
_model = None


def client_and_model():
    global _client, _model
    if _client is None:
        _client = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
        names = [m.name.split('/')[-1] for m in _client.models.list()]
        for cand in ['gemini-3.1-pro-preview', 'gemini-3.1-pro', 'gemini-3-pro',
                     'gemini-3.1-flash', 'gemini-3-flash-preview', 'gemini-3-flash']:
            if cand in names:
                _model = cand
                break
        if _model is None:
            raise SystemExit('no 3-series judge model available: ' + ','.join(names[:20]))
    return _client, _model


RUBRICS = {
    'asset': (
        'You are judging ONE isolated game-asset sprite (shown on a checker or plain background) '
        'against a style-anchor scene (first image = anchor, second = asset). Rate strictly. '
        'Return JSON only: {"style_match": 1-10 (palette/pixel-density/lighting affinity with anchor), '
        '"perspective_ok": bool (front-on JRPG 3/4; facades parallel to frame bottom; NO isometric rotation, '
        'NO two visible faces on buildings), "single_object": bool (exactly one object, no scene fragments), '
        '"silhouette_clean": bool (no leftover key-color fringe, no background patches), '
        '"theme_fit": 1-10 (futuristic sci-fi settlement), "issues": "short text"}'
    ),
    'tile': (
        'You are judging a TERRAIN TILE preview: the image shows one texture tiled 4x4 '
        '(first image = style anchor scene, second = the tiled preview). Rate strictly. '
        'Return JSON only: {"style_match": 1-10, "flat_plan_view": bool (straight-down ground texture, '
        'no perspective, no objects), "tileable": 1-10 (10 = no visible seams or obvious repetition grid), '
        '"readability": 1-10 (would read as this terrain in-game at small scale), "issues": "short text"}'
    ),
    'character': (
        'You are judging a CHARACTER SPRITE for a 2D top-down JRPG (first image = style anchor, '
        'second = sprite image, possibly multiple directions side by side). Return JSON only: '
        '{"style_match": 1-10, "proportions_ok": bool (taller JRPG proportions like Eastward, not chibi), '
        '"single_character": bool, "directions_consistent": bool (if multiple frames: same character, '
        'outfit and palette in all), "silhouette_clean": bool, "theme_fit": 1-10, "issues": "short text"}'
    ),
    'creature': (
        'You are judging a CREATURE/ROBOT SPRITE for a 2D top-down sci-fi JRPG (first image = style '
        'anchor, second = sprite). The creature\'s intended design is given in the context — judge '
        'whether it executes THAT design well in the anchor\'s pixel-art style; do NOT penalize '
        'non-humanoid shapes. Return JSON only: {"style_match": 1-10, "single_creature": bool, '
        '"silhouette_clean": bool, "theme_fit": 1-10, "reads_as_design": bool (recognizable as the '
        'intended design), "issues": "short text"}'
    ),
    'ui': (
        'You are auditing the UI/HUD of a 2D pixel-art RPG screenshot (single image). Judge ONLY '
        'interface elements: HUD (hearts/currency/quest icons), dialogue box, overlays, title text, '
        'readability and visual cohesion with a dusk sci-fi pixel-art game. Return JSON only: '
        '{"readability": 1-10, "hierarchy": 1-10 (does the eye find the important thing first), '
        '"cohesion": 1-10 (UI feels part of the game\'s art style, not placeholder), '
        '"polish": 1-10, "top_issues": ["max 4 short concrete issues ordered by impact"]}'
    ),
    'facing': (
        'The image shows several separate character sprites of the SAME character in a row on a '
        'checker background, numbered 0..N-1 left to right. For each sprite classify which way the '
        'character faces: "down" (front, facing the viewer), "up" (back of head/backpack, facing '
        'away), "left" (profile looking left), "right" (profile looking right). Return JSON only: '
        '{"facings": ["down", "up", ...] (one per sprite, left to right), "notes": "short text"}'
    ),
    'screenshot': (
        'You are judging an IN-GAME SCREENSHOT of a 2D top-down sci-fi RPG aiming for the Eastward look '
        '(first image = target style anchor, second = actual game screenshot). Return JSON only: '
        '{"style_score": 1-10 (how close to the anchor mood: dusk grade, glows, density), '
        '"perspective_ok": bool, "composition_issues": "short text — overlaps, scale errors, artifacts", '
        '"regressions": "short text — anything that looks broken or placeholder"}'
    ),
}


def judge_image(paths, rubric, context=''):
    cl, model = client_and_model()
    imgs = []
    for p in paths:
        im = Image.open(p)
        im.thumbnail((1024, 1024))
        imgs.append(im)
    prompt = RUBRICS[rubric] + (f'\nContext: {context}' if context else '')
    resp = cl.models.generate_content(
        model=model,
        contents=imgs + [prompt],
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_level='low'),
            max_output_tokens=4096,
        ),
    )
    text = resp.text or ''
    start = text.find('{')
    if start < 0:
        return {'_parse_error': text[:200]}
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
        return obj
    except Exception as e:  # noqa: BLE001
        return {'_parse_error': f'{e}: {text[:200]}'}


def judge_vote(paths, rubric, context='', n=3):
    """Median-of-n judging: numeric fields -> median, bool fields -> majority.
    Kills single-sample flip-flops on borderline items."""
    votes = [judge_image(paths, rubric, context) for _ in range(n)]
    votes = [v for v in votes if '_parse_error' not in v]
    if not votes:
        return {'_parse_error': 'all samples failed'}
    out = {'_votes': votes}
    keys = set().union(*[v.keys() for v in votes])
    for k in keys:
        vals = [v[k] for v in votes if k in v]
        if not vals:
            continue
        if isinstance(vals[0], bool):
            out[k] = sum(1 for v in vals if v) * 2 > len(vals)
        elif isinstance(vals[0], (int, float)):
            vals.sort()
            out[k] = vals[len(vals) // 2]
        else:
            out[k] = vals[0]
    return out


if __name__ == '__main__':
    rubric = sys.argv[1]
    paths = sys.argv[2:]
    print(json.dumps(judge_image(paths, rubric), indent=1))
