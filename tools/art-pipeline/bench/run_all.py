#!/usr/bin/env python3
"""Orchestrator: run all benchmark methods on all 3 focus scenes and collect results.

Collects existing v2 (dense NBP), v3 (per-object xray), v4 (geometric) masks
from their standard locations, runs new methods (A4 amodal, B4 consensus,
perspective A/B), evaluates everything, and writes results.json.

Usage: run_all.py [--scene anchorroom] [--skip-consensus] [--skip-gen]
"""
import json
import os
import sys
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
BENCH = os.path.join(ROOT, 'tools', 'art-pipeline', 'bench')
SCENES = ['anchorroom', 'night-bazaar', 'plaza-market-inside']


def resolve_existing_masks(room):
    """Find existing collision/walkability masks from v2, v3, v4 pipelines."""
    masks = {}

    # A1: dense NBP occupancy (v2 = nbp_footprint.py output)
    if room == 'anchorroom':
        fp = os.path.join(ROOT, 'docs', 'art-options', 'nbp-footprint.png')
        walk = os.path.join(ROOT, 'docs', 'art-options', 'nbp-walk.png')
    else:
        base = os.path.join(ROOT, 'docs', 'art-options', 'rooms', room)
        fp = os.path.join(base, 'nbp-footprint.png')
        walk = os.path.join(base, 'nbp-walk.png')

    if os.path.exists(walk):
        masks['A1-dense-walk'] = walk
    if os.path.exists(fp):
        masks['A1-dense-footprint'] = fp

    # Shipped collision
    col = os.path.join(ROOT, 'assets', 'rooms', f'{room}.collision.png')
    if os.path.exists(col):
        masks['shipped-collision'] = col

    # A2: per-object xray (v3)
    v3_col = os.path.join(ROOT, 'docs', 'art-options', 'v3', room, 'collision-v3.png')
    if os.path.exists(v3_col):
        masks['A2-v3-xray'] = v3_col

    # A3: geometric (v4)
    v4_col = os.path.join(ROOT, 'docs', 'art-options', 'v4', room, 'collision-v4.png')
    if os.path.exists(v4_col):
        masks['A3-v4-geometric'] = v4_col
    v4_ng = os.path.join(ROOT, 'docs', 'art-options', 'v4', room, 'collision-v4-nogrid.png')
    if os.path.exists(v4_ng):
        masks['A3-v4-nogrid'] = v4_ng

    # A4: amodal (from this bench run)
    amodal = os.path.join(ROOT, 'docs', 'art-options', 'bench', 'prompt', room, 'amodal-collision.png')
    if os.path.exists(amodal):
        masks['A4-amodal'] = amodal

    # Depth agent masks (A5/A6)
    for suffix in ['depth-walk', 'depth-footprint', 'depth-collision',
                   'footprints-pretrained', 'morph-baseline']:
        p = os.path.join(ROOT, 'docs', 'art-options', 'bench', 'depth', room, f'{suffix}.png')
        if os.path.exists(p):
            masks[f'depth-{suffix}'] = p

    return masks


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--scene', nargs='*', default=SCENES)
    ap.add_argument('--skip-consensus', action='store_true')
    ap.add_argument('--skip-gen', action='store_true')
    ap.add_argument('--skip-perspective', action='store_true')
    args = ap.parse_args()

    scenes = args.scene
    all_results = {}

    for room in scenes:
        print(f'\n{"="*60}\n  SCENE: {room}\n{"="*60}')
        out = os.path.join(ROOT, 'docs', 'art-options', 'bench', 'prompt', room)
        os.makedirs(out, exist_ok=True)

        # B4: N-roll consensus (ground truth)
        consensus_path = os.path.join(out, 'consensus-walk.png')
        if not args.skip_consensus and not os.path.exists(consensus_path):
            print('\n--- Running N-roll consensus ---')
            subprocess.run([sys.executable, os.path.join(BENCH, 'nroll_consensus.py'),
                            room, '--rolls', '5'], check=False)

        # A4: amodal footprints
        amodal_path = os.path.join(out, 'amodal-collision.png')
        if not args.skip_gen and not os.path.exists(amodal_path):
            print('\n--- Running amodal footprints ---')
            subprocess.run([sys.executable, os.path.join(BENCH, 'amodal_footprints.py'),
                            room], check=False)

        # C: perspective A/B
        persp_path = os.path.join(out, 'perspective-metrics.json')
        if not args.skip_perspective and not os.path.exists(persp_path):
            print('\n--- Running perspective A/B ---')
            subprocess.run([sys.executable, os.path.join(BENCH, 'perspective_ab.py'),
                            room], check=False)

        # Evaluate all available masks
        masks = resolve_existing_masks(room)
        print(f'\nFound {len(masks)} masks to evaluate: {list(masks.keys())}')

        sys.path.insert(0, BENCH)
        from evaluate import evaluate_method, pairwise_forced_choice, load_mask
        from PIL import Image

        room_results = {'methods': {}, 'pairwise': {}}

        plate_p = os.path.join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor-clean.png') if room == 'anchorroom' else os.path.join(ROOT, 'docs', 'art-options', 'rooms', room, 'plate.png')

        for method_name, mask_path in masks.items():
            print(f'\n  Evaluating: {method_name}')
            m = evaluate_method(room, method_name, mask_path, out_dir=out)
            room_results['methods'][method_name] = m

        # Pairwise comparisons (subset of interesting pairs)
        interesting_pairs = []
        method_names = list(masks.keys())
        for i, a in enumerate(method_names):
            for b in method_names[i + 1:]:
                if any(x in a or x in b for x in ['A1', 'A2', 'A3', 'A4', 'shipped']):
                    interesting_pairs.append((a, b))

        if interesting_pairs and os.path.exists(plate_p):
            src = Image.open(plate_p).convert('RGB')
            W, H = src.size
            for name_a, name_b in interesting_pairs[:6]:
                print(f'\n  Pairwise: {name_a} vs {name_b}')
                mask_a = load_mask(masks[name_a], W, H)
                mask_b = load_mask(masks[name_b], W, H)
                pw = pairwise_forced_choice(src, mask_a, mask_b, name_a, name_b)
                room_results['pairwise'][f'{name_a}_vs_{name_b}'] = pw

        # Load perspective results if available
        if os.path.exists(os.path.join(out, 'perspective-metrics.json')):
            with open(os.path.join(out, 'perspective-metrics.json')) as f:
                room_results['perspective'] = json.load(f)

        # Load consensus metrics if available
        if os.path.exists(os.path.join(out, 'consensus-metrics.json')):
            with open(os.path.join(out, 'consensus-metrics.json')) as f:
                room_results['consensus'] = json.load(f)

        all_results[room] = room_results

    # Write combined results
    results_path = os.path.join(ROOT, 'tools', 'art-pipeline', 'bench', 'results.json')
    with open(results_path, 'w') as f:
        json.dump(all_results, f, indent=2)
    print(f'\nResults written to {results_path}')

    # Print summary table
    print('\n' + '=' * 80)
    print('RESULTS SUMMARY')
    print('=' * 80)
    header = f'{"Method":<25} {"Room":<22} {"IoU":<8} {"Canny":<8} {"Reach":<8} {"Walk%":<8}'
    print(header)
    print('-' * 80)
    for room, rd in all_results.items():
        for method, m in rd.get('methods', {}).items():
            iou = m.get('iou_vs_consensus', '-')
            canny = m.get('canny_edge_alignment', '-')
            reach = m.get('config_space_reach_frac', '-')
            walk = m.get('walk_frac', '-')
            iou_s = f'{iou:.3f}' if isinstance(iou, float) else str(iou)
            canny_s = f'{canny:.3f}' if isinstance(canny, float) else str(canny)
            reach_s = f'{reach:.3f}' if isinstance(reach, float) else str(reach)
            walk_s = f'{walk:.3f}' if isinstance(walk, float) else str(walk)
            print(f'{method:<25} {room:<22} {iou_s:<8} {canny_s:<8} {reach_s:<8} {walk_s:<8}')


if __name__ == '__main__':
    main()
