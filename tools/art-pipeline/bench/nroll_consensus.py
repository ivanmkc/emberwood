#!/usr/bin/env python3
"""B4: N-roll majority-vote walkability consensus.

Generates N independent NBP walkability rolls (same walk-v2 prompt, each a
fresh seed), gates each on snap purity, and computes per-pixel majority vote.
The consensus mask serves as pseudo-ground-truth for IoU scoring of every
other walkability/collision method.

Usage: nroll_consensus.py <room> [--rolls 5]
"""
import io
import json
import os
import sys
import threading

import cv2
import numpy as np
from PIL import Image
from google import genai
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
AP = os.path.join(ROOT, 'tools', 'art-pipeline')

WALK_PROMPT = (
    'Repaint this EXACT image as a binary WALKABILITY map for a top-down game. Keep every '
    'silhouette and position PIXEL-IDENTICAL — do not move or redraw anything. Use exactly two '
    'flat colors, no shading, no outlines:\n'
    '- pure green #00FF00: every surface at the walking character\'s ground level — plaza '
    'plating, bare ground, metal grates and deck floors, bridge decks, boardwalks, platforms, '
    'staircases, doorway thresholds, interior floors. If the scene is set ON rooftops or '
    'catwalks, those roof/deck surfaces ARE the walkable ground: green. FLAT markings ON the '
    'ground are still ground: stains, scorch marks, oil spills, puddles, painted signs and '
    'chevrons, cracks, manhole covers, shadows — all green. Cables, hoses and thin pipes LYING '
    'FLAT ON the floor can be stepped over: green\n'
    '- pure red #FF0000: everything else — building walls and roofs, background/upper wall '
    'surfaces above or below the walking level, all 3D objects and props that rise from the '
    'ground (glass tanks, pylons, machines, crates, benches), deep water, railings, '
    'pipes and thick cables lying on the ground\n'
    'Every pixel must be EXACTLY pure green #00FF00 or pure red #FF0000 — absolutely NO '
    'dithering, NO anti-aliasing, NO gradients, hard 1-pixel boundaries.'
)

MIN_PURITY = 0.80

_tl = threading.local()


def cli():
    if not hasattr(_tl, 'c'):
        _tl.c = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
    return _tl.c


def resolve_plate(room):
    if room == 'anchorroom':
        return os.path.join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor-clean.png')
    return os.path.join(ROOT, 'docs', 'art-options', 'rooms', room, 'plate.png')


def single_roll(seg_in, W, H):
    """Generate a single walkability roll. Returns boolean mask (True=walkable) or None."""
    for _ in range(3):
        try:
            resp = cli().models.generate_content(
                model='gemini-3-pro-image',
                contents=[seg_in, WALK_PROMPT],
                config=types.GenerateContentConfig(
                    image_config=types.ImageConfig(aspect_ratio='4:3', image_size='2K')),
            )
            for part in (resp.parts or []):
                if part.inline_data is not None:
                    img = Image.open(io.BytesIO(part.inline_data.data)).convert('RGB')
                    arr = np.asarray(img.resize((W, H), Image.NEAREST)).astype(np.int16)
                    dg = np.linalg.norm(arr - np.array([0, 255, 0], np.int16), axis=2)
                    dr = np.linalg.norm(arr - np.array([255, 0, 0], np.int16), axis=2)
                    green = dg < dr
                    purity = (np.minimum(dg, dr) < 90).mean()
                    if purity >= MIN_PURITY:
                        return green, purity, img
                    print(f'  purity {purity:.3f} < {MIN_PURITY}, retrying')
        except Exception as e:
            print(f'  roll error: {e}')
    return None, 0.0, None


def main():
    room = sys.argv[1] if len(sys.argv) > 1 else 'anchorroom'
    n_rolls = 5
    for i, a in enumerate(sys.argv):
        if a == '--rolls' and i + 1 < len(sys.argv):
            n_rolls = int(sys.argv[i + 1])

    plate_p = resolve_plate(room)
    if not os.path.exists(plate_p):
        sys.exit(f'plate not found: {plate_p}')

    out = os.path.join(ROOT, 'docs', 'art-options', 'bench', 'prompt', room)
    os.makedirs(out, exist_ok=True)

    src = Image.open(plate_p).convert('RGB')
    W, H = src.size
    seg_in = src.copy()
    seg_in.thumbnail((1200, 1200))

    print(f'=== N-roll consensus for {room} ({n_rolls} rolls) ===')
    votes = np.zeros((H, W), dtype=np.int32)
    accepted = 0
    per_roll = []

    for r in range(n_rolls * 2):
        if accepted >= n_rolls:
            break
        green, purity, raw_img = single_roll(seg_in, W, H)
        if green is None:
            print(f'[roll {r}] failed')
            continue
        votes += green.astype(np.int32)
        accepted += 1
        per_roll.append({'roll': r, 'purity': round(purity, 3),
                         'walk_frac': round(float(green.mean()), 3)})
        if raw_img is not None:
            raw_img.resize((W, H), Image.NEAREST).save(
                os.path.join(out, f'walk-roll-{accepted - 1}.png'))
        print(f'[roll {r}] accepted ({accepted}/{n_rolls}), '
              f'purity={purity:.3f}, walk_frac={green.mean():.3f}')

    if accepted < 3:
        sys.exit(f'only {accepted} rolls accepted, need >= 3')

    consensus = votes > (accepted / 2)
    agreement = np.maximum(votes, accepted - votes) / accepted
    mean_agreement = float(agreement.mean())

    Image.fromarray((consensus * 255).astype(np.uint8)).save(
        os.path.join(out, 'consensus-walk.png'))

    b = np.asarray(src).astype(np.float32)
    ov = b.copy()
    ov[consensus] = ov[consensus] * 0.5 + np.array([40, 255, 90], np.float32) * 0.5
    ov[~consensus] = ov[~consensus] * 0.5 + np.array([255, 40, 40], np.float32) * 0.5
    Image.fromarray(ov.clip(0, 255).astype(np.uint8)).save(
        os.path.join(out, 'consensus-on-source.jpg'), quality=88)

    agreement_map = (agreement * 255).clip(0, 255).astype(np.uint8)
    Image.fromarray(agreement_map).save(os.path.join(out, 'consensus-agreement.png'))

    metrics = {
        'room': room,
        'rolls_attempted': r + 1,
        'rolls_accepted': accepted,
        'walk_frac': round(float(consensus.mean()), 3),
        'mean_agreement': round(mean_agreement, 3),
        'per_roll': per_roll,
    }
    with open(os.path.join(out, 'consensus-metrics.json'), 'w') as f:
        json.dump(metrics, f, indent=2)

    print(f'\nconsensus done: {accepted} rolls, walk_frac={consensus.mean():.3f}, '
          f'agreement={mean_agreement:.3f}')
    return consensus, metrics


if __name__ == '__main__':
    main()
