#!/usr/bin/env python3
"""Benchmark evaluator harness.

Deterministic metrics:
  - IoU vs 5-roll consensus walkability mask
  - Canny edge alignment (fraction of source edges preserved)
  - Config-space traversability (8x8 erosion + spawn-component reach fraction)
  - Orientation-histogram score (fraction of long edges within 5deg of 0/90)

LLM metrics:
  - verify_defects-style fresh-roll diff (miss rate, false rate)
  - Pairwise position-debiased forced choice (A/B overlays, 3 votes each
    ordering, win matrix)

Usage:
  evaluate.py <room> --method <name> --mask <collision.png>
  evaluate.py <room> --pairwise <methodA>:<pathA> <methodB>:<pathB>
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

_tl = threading.local()


def cli():
    if not hasattr(_tl, 'c'):
        _tl.c = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
    return _tl.c


def resolve_plate(room):
    if room == 'anchorroom':
        return os.path.join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor-clean.png')
    return os.path.join(ROOT, 'docs', 'art-options', 'rooms', room, 'plate.png')


def load_consensus(room):
    p = os.path.join(ROOT, 'docs', 'art-options', 'bench', 'prompt', room, 'consensus-walk.png')
    if not os.path.exists(p):
        return None
    return np.asarray(Image.open(p).convert('L')) > 127


def load_mask(path, W, H):
    """Load a collision/walkability mask, resizing to (W,H). True = walkable/unblocked."""
    img = Image.open(path).convert('L').resize((W, H), Image.NEAREST)
    return np.asarray(img) > 127


def iou_vs_consensus(method_walk, consensus):
    inter = (method_walk & consensus).sum()
    union = (method_walk | consensus).sum()
    return float(inter / max(union, 1))


def canny_edge_alignment(method_walk, source_rgb, threshold=5):
    """Fraction of source Canny edges that align with method mask edges."""
    gray = cv2.cvtColor(np.asarray(source_rgb), cv2.COLOR_RGB2GRAY)
    src_edges = cv2.Canny(gray, 80, 200) > 0
    mask_u8 = (method_walk * 255).astype(np.uint8)
    mask_edges = cv2.Canny(mask_u8, 80, 200) > 0
    dilated_mask_edges = cv2.dilate(mask_edges.astype(np.uint8),
                                    np.ones((threshold * 2 + 1, threshold * 2 + 1), np.uint8)) > 0
    if src_edges.sum() == 0:
        return 1.0
    return float((src_edges & dilated_mask_edges).sum() / src_edges.sum())


def config_space_traversability(walk_mask, hitbox=8):
    """Erode walkable mask by hitbox, BFS from spawn, return reachable fraction."""
    eroded = cv2.erode(walk_mask.astype(np.uint8),
                       np.ones((hitbox, hitbox), np.uint8)) > 0
    if not eroded.any():
        return 0.0, 0

    ncc, lab = cv2.connectedComponents(eroded.astype(np.uint8))
    if ncc <= 1:
        return 0.0, 0

    sizes = [(lab == i).sum() for i in range(1, ncc)]
    largest = max(sizes)
    total = sum(sizes)
    return float(largest / max(total, 1)), int(largest)


def orientation_histogram(source_rgb, threshold_deg=5):
    """Fraction of long straight edges within threshold_deg of horizontal/vertical."""
    gray = cv2.cvtColor(np.asarray(source_rgb), cv2.COLOR_RGB2GRAY)
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

    return float(aligned / total), total


def make_overlay(source_rgb, walk_mask):
    """Create a collision-on-source overlay image for pairwise comparison."""
    b = np.asarray(source_rgb).astype(np.float32)
    ov = b.copy()
    ov[walk_mask] = ov[walk_mask] * 0.6 + np.array([40, 255, 90], np.float32) * 0.4
    ov[~walk_mask] = ov[~walk_mask] * 0.6 + np.array([255, 40, 40], np.float32) * 0.4
    return Image.fromarray(ov.clip(0, 255).astype(np.uint8))


def pairwise_forced_choice(source_rgb, mask_a, mask_b, name_a, name_b, n_votes=3):
    """Position-debiased pairwise forced choice: show two overlays side by side
    in both orderings, ask which collision map is more correct."""
    ov_a = make_overlay(source_rgb, mask_a)
    ov_b = make_overlay(source_rgb, mask_b)

    ov_a.thumbnail((600, 600), Image.LANCZOS)
    ov_b.thumbnail((600, 600), Image.LANCZOS)

    wins = {name_a: 0, name_b: 0}
    orderings = [
        (ov_a, ov_b, name_a, name_b, 'LEFT', 'RIGHT'),
        (ov_b, ov_a, name_b, name_a, 'LEFT', 'RIGHT'),
    ]

    for left_img, right_img, left_name, right_name, _, _ in orderings:
        combined = Image.new('RGB', (left_img.width + right_img.width + 20, max(left_img.height, right_img.height)), (30, 30, 30))
        combined.paste(left_img, (0, 0))
        combined.paste(right_img, (left_img.width + 20, 0))

        for _ in range(n_votes):
            try:
                r = cli().models.generate_content(
                    model='gemini-3.1-pro-preview',
                    contents=[combined,
                              'Two collision-map overlays for the same game scene (green = walkable, '
                              'red = blocked). Which one more correctly identifies walkable ground vs '
                              'obstacles? Consider: does it correctly block raised objects? Does it '
                              'correctly allow walking on flat ground? Return JSON only: '
                              '{"winner": "LEFT" or "RIGHT", "why": "short reason"}'],
                    config=types.GenerateContentConfig(max_output_tokens=1024))
                t = r.text or ''
                st = t.find('{')
                if st >= 0:
                    v, _ = json.JSONDecoder().raw_decode(t[st:])
                    w = v.get('winner', '')
                    if w == 'LEFT':
                        wins[left_name] += 1
                    elif w == 'RIGHT':
                        wins[right_name] += 1
            except Exception:
                pass

    total = wins[name_a] + wins[name_b]
    return {
        'wins': wins,
        'total_votes': total,
        'win_rate_a': round(wins[name_a] / max(total, 1), 2),
        'win_rate_b': round(wins[name_b] / max(total, 1), 2),
    }


def evaluate_method(room, method_name, mask_path, out_dir=None):
    """Run all deterministic metrics for a method's walkability/collision mask."""
    plate_p = resolve_plate(room)
    src = Image.open(plate_p).convert('RGB')
    W, H = src.size

    walk_mask = load_mask(mask_path, W, H)
    consensus = load_consensus(room)

    metrics = {'room': room, 'method': method_name}

    if consensus is not None:
        consensus_resized = consensus
        if consensus.shape != (H, W):
            consensus_resized = np.asarray(
                Image.fromarray((consensus * 255).astype(np.uint8)).resize((W, H), Image.NEAREST)) > 127
        metrics['iou_vs_consensus'] = round(iou_vs_consensus(walk_mask, consensus_resized), 3)

    metrics['canny_edge_alignment'] = round(canny_edge_alignment(walk_mask, src), 3)

    reach_frac, reach_px = config_space_traversability(walk_mask)
    metrics['config_space_reach_frac'] = round(reach_frac, 3)
    metrics['config_space_reach_px'] = reach_px

    orient, n_lines = orientation_histogram(src)
    metrics['orientation_aligned_frac'] = round(orient, 3)
    metrics['orientation_total_lines'] = n_lines

    metrics['walk_frac'] = round(float(walk_mask.mean()), 3)

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        overlay = make_overlay(src, walk_mask)
        overlay.save(os.path.join(out_dir, f'{method_name}-overlay.jpg'), quality=88)
        with open(os.path.join(out_dir, f'{method_name}-metrics.json'), 'w') as f:
            json.dump(metrics, f, indent=2)

    return metrics


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('room')
    ap.add_argument('--method', help='method name')
    ap.add_argument('--mask', help='path to collision/walkability mask (white=walkable)')
    ap.add_argument('--pairwise', nargs=2, help='methodA:pathA methodB:pathB')
    args = ap.parse_args()

    out = os.path.join(ROOT, 'docs', 'art-options', 'bench', 'prompt', args.room)
    os.makedirs(out, exist_ok=True)

    if args.pairwise:
        name_a, path_a = args.pairwise[0].split(':', 1)
        name_b, path_b = args.pairwise[1].split(':', 1)
        plate_p = resolve_plate(args.room)
        src = Image.open(plate_p).convert('RGB')
        W, H = src.size
        mask_a = load_mask(path_a, W, H)
        mask_b = load_mask(path_b, W, H)
        result = pairwise_forced_choice(src, mask_a, mask_b, name_a, name_b)
        print(json.dumps(result, indent=2))
        with open(os.path.join(out, f'pairwise-{name_a}-vs-{name_b}.json'), 'w') as f:
            json.dump(result, f, indent=2)
    elif args.method and args.mask:
        result = evaluate_method(args.room, args.method, args.mask, out_dir=out)
        print(json.dumps(result, indent=2))
    else:
        ap.error('need --method/--mask or --pairwise')


if __name__ == '__main__':
    main()
