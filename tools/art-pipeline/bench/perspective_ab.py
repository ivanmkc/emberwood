#!/usr/bin/env python3
"""C: Perspective conditioning A/B experiment.

Three conditions, each generated 3 times per scene:
  C1: prompt-only (scene gen with perspective constraint in text only)
  C2: drawn 16px grid + "verticals vertical, no diagonal vanishing lines"
  C3: outpaint-from-anchor-edge (use the anchor's right edge as a seed)

Scored with an edge-orientation histogram detector: fraction of long straight
edges within 5 degrees of horizontal or vertical (axis-aligned = 1.0).

Usage: perspective_ab.py <room>
"""
import io
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw
from google import genai
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
client = genai.Client(vertexai=True, project='adk-coding-agents', location='global')

ANCHOR_PLATE = os.path.join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor-clean.png')

SCENE_DESCS = {
    'anchorroom': 'A bustling sci-fi harbor plaza with pylons, glass tanks, cargo crates, market stalls, and a walkable bridge. Flat 3/4 top-down view.',
    'night-bazaar': 'A neon-lit night market in a sci-fi city, narrow alleys with food stalls, hanging lanterns, steam vents, and crowds. Flat 3/4 top-down view.',
    'plaza-market-inside': 'Interior of a sci-fi market hall with vendor booths, display cases, shelving units, crates of goods, overhead lighting rigs. Flat 3/4 top-down view.',
}

BASE_PROMPT = (
    'Generate a game scene image in the style of the game Eastward — detailed pixel art, '
    'rich colors, carefully placed objects. The scene: {desc}\n'
    'PERSPECTIVE RULE: axis-aligned straight-on 3/4 top-down view. Buildings are flat front '
    'elevations ("stage-set flat"). NO rotation, NO isometric, NO diagonal vanishing lines. '
    'All verticals must be perfectly vertical. All horizontals must be perfectly horizontal.'
)

GRID_EXTRA = (
    '\nA reference grid is drawn on the input image at 16px pitch. Use it to keep all '
    'verticals EXACTLY vertical and all horizontals EXACTLY horizontal. No diagonal vanishing '
    'lines whatsoever. The grid shows the expected alignment — match it.'
)


def gen_image(contents, size='2K'):
    for _ in range(3):
        try:
            resp = client.models.generate_content(
                model='gemini-3-pro-image', contents=contents,
                config=types.GenerateContentConfig(
                    image_config=types.ImageConfig(aspect_ratio='4:3', image_size=size)))
            for part in (resp.parts or []):
                if part.inline_data is not None:
                    return Image.open(io.BytesIO(part.inline_data.data)).convert('RGB')
        except Exception:
            pass
    return None


def draw_grid(w, h, pitch=16):
    img = Image.new('RGB', (w, h), (40, 40, 40))
    draw = ImageDraw.Draw(img)
    for x in range(0, w, pitch):
        color = (100, 100, 100) if (x // pitch) % 4 != 0 else (255, 255, 0)
        width = 1 if (x // pitch) % 4 != 0 else 2
        draw.line([(x, 0), (x, h)], fill=color, width=width)
    for y in range(0, h, pitch):
        color = (100, 100, 100) if (y // pitch) % 4 != 0 else (255, 255, 0)
        width = 1 if (y // pitch) % 4 != 0 else 2
        draw.line([(0, y), (w, y)], fill=color, width=width)
    return img


def orientation_score(img_pil, threshold_deg=5):
    """Fraction of long straight edges within threshold_deg of H/V."""
    gray = cv2.cvtColor(np.asarray(img_pil), cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 50, minLineLength=30, maxLineGap=5)
    if lines is None or len(lines) == 0:
        return 1.0, 0
    aligned = 0
    total = len(lines)
    for line in lines:
        x1, y1, x2, y2 = line[0]
        angle = np.degrees(np.arctan2(abs(y2 - y1), abs(x2 - x1)))
        if angle <= threshold_deg or angle >= (90 - threshold_deg):
            aligned += 1
    return round(aligned / total, 3), total


def run_condition_c1(room, desc, out, n=3):
    """C1: prompt-only scene generation."""
    results = []
    for i in range(n):
        prompt = BASE_PROMPT.format(desc=desc)
        img = gen_image([prompt])
        if img is None:
            results.append({'roll': i, 'status': 'failed'})
            continue
        img.save(os.path.join(out, f'c1-prompt-{i}.jpg'), quality=88)
        score, n_lines = orientation_score(img)
        results.append({'roll': i, 'status': 'ok', 'orient_score': score, 'n_lines': n_lines})
        print(f'  C1 roll {i}: orient={score}, lines={n_lines}')
    return results


def run_condition_c2(room, desc, out, n=3):
    """C2: drawn grid + perspective constraint."""
    grid = draw_grid(640, 480, pitch=16)
    grid.save(os.path.join(out, 'c2-grid-input.png'))
    results = []
    for i in range(n):
        prompt = BASE_PROMPT.format(desc=desc) + GRID_EXTRA
        img = gen_image([grid, prompt])
        if img is None:
            results.append({'roll': i, 'status': 'failed'})
            continue
        img.save(os.path.join(out, f'c2-grid-{i}.jpg'), quality=88)
        score, n_lines = orientation_score(img)
        results.append({'roll': i, 'status': 'ok', 'orient_score': score, 'n_lines': n_lines})
        print(f'  C2 roll {i}: orient={score}, lines={n_lines}')
    return results


def run_condition_c3(room, desc, out, n=3):
    """C3: outpaint from anchor edge."""
    if not os.path.exists(ANCHOR_PLATE):
        print('  C3: anchor plate not found, skipping')
        return [{'roll': i, 'status': 'skipped'} for i in range(n)]

    anchor = Image.open(ANCHOR_PLATE).convert('RGB')
    aw, ah = anchor.size
    edge_strip = anchor.crop((aw - 64, 0, aw, ah))

    results = []
    for i in range(n):
        prompt = (
            f'Continue this scene to the RIGHT. The left edge of the new image must '
            f'seamlessly continue from this strip (matching colors, perspective, ground '
            f'level). The scene continues as: {desc}\n'
            f'CRITICAL: maintain the EXACT SAME flat 3/4 top-down perspective. All verticals '
            f'stay vertical. All horizontals stay horizontal. No vanishing lines.'
        )
        img = gen_image([edge_strip, prompt])
        if img is None:
            results.append({'roll': i, 'status': 'failed'})
            continue
        img.save(os.path.join(out, f'c3-outpaint-{i}.jpg'), quality=88)
        score, n_lines = orientation_score(img)
        results.append({'roll': i, 'status': 'ok', 'orient_score': score, 'n_lines': n_lines})
        print(f'  C3 roll {i}: orient={score}, lines={n_lines}')
    return results


def main():
    room = sys.argv[1] if len(sys.argv) > 1 else 'anchorroom'
    desc = SCENE_DESCS.get(room, f'A sci-fi game scene ({room}). Flat 3/4 top-down view.')

    out = os.path.join(ROOT, 'docs', 'art-options', 'bench', 'prompt', room)
    os.makedirs(out, exist_ok=True)

    print(f'=== Perspective A/B for {room} ===')

    anchor_score, anchor_lines = 0.0, 0
    if os.path.exists(ANCHOR_PLATE):
        anchor_img = Image.open(ANCHOR_PLATE).convert('RGB')
        anchor_score, anchor_lines = orientation_score(anchor_img)
        print(f'Anchor baseline: orient={anchor_score}, lines={anchor_lines}')

    print('--- C1: prompt-only ---')
    c1 = run_condition_c1(room, desc, out)

    print('--- C2: drawn grid ---')
    c2 = run_condition_c2(room, desc, out)

    print('--- C3: outpaint-from-edge ---')
    c3 = run_condition_c3(room, desc, out)

    def mean_score(results):
        scores = [r['orient_score'] for r in results if r.get('status') == 'ok']
        return round(sum(scores) / max(len(scores), 1), 3) if scores else None

    metrics = {
        'room': room,
        'anchor_baseline': {'orient_score': anchor_score, 'n_lines': anchor_lines},
        'C1_prompt_only': {'mean_orient': mean_score(c1), 'rolls': c1},
        'C2_drawn_grid': {'mean_orient': mean_score(c2), 'rolls': c2},
        'C3_outpaint': {'mean_orient': mean_score(c3), 'rolls': c3},
    }
    with open(os.path.join(out, 'perspective-metrics.json'), 'w') as f:
        json.dump(metrics, f, indent=2)

    print(f'\nPerspective A/B done:')
    print(f'  Anchor baseline: {anchor_score}')
    print(f'  C1 prompt-only:  {mean_score(c1)}')
    print(f'  C2 drawn-grid:   {mean_score(c2)}')
    print(f'  C3 outpaint:     {mean_score(c3)}')


if __name__ == '__main__':
    main()
