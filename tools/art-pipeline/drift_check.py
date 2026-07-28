#!/usr/bin/env python3
"""Drift detector: flag when VLM roll distributions shift from baseline.

Reads any *-metrics.json that contains roll_fracs (per-roll area fractions)
or per_roll arrays, compares the median accepted-roll fraction against stored
baselines in drift-baselines.json, and exits non-zero with a loud message
when the median shifts >2x from the baseline (in either direction).

Usage:
    python3 drift_check.py <metrics-file> <room> <arm>
    python3 drift_check.py docs/art-options/wires-signs-gpt-night-bazaar-metrics.json night-bazaar gpt

The <arm> selects which baseline to compare against (e.g. "nbp", "gpt",
"nbp_consensus"). The baseline file lives at tools/art-pipeline/drift-baselines.json.

Exit codes:
    0 — within 2x of baseline (no drift detected)
    1 — drift detected (median shifted >2x)
    2 — missing baseline or malformed metrics (cannot compare)
"""
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASELINES_PATH = os.path.join(SCRIPT_DIR, 'drift-baselines.json')
DRIFT_FACTOR = 2.0


def load_baselines():
    if not os.path.exists(BASELINES_PATH):
        print(f'FATAL: no baseline file at {BASELINES_PATH}', file=sys.stderr)
        sys.exit(2)
    return json.load(open(BASELINES_PATH))


def extract_roll_fracs(metrics):
    """Extract per-roll area fractions from a metrics dict."""
    if 'roll_fracs' in metrics:
        return metrics['roll_fracs']
    if 'per_roll' in metrics:
        fracs = []
        for r in metrics['per_roll']:
            if isinstance(r, dict) and 'walk_frac' in r:
                fracs.append(r['walk_frac'])
            elif isinstance(r, (int, float)):
                fracs.append(r)
        if fracs:
            return fracs
    return None


def median(vals):
    s = sorted(vals)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def check(metrics_path, room, arm):
    baselines = load_baselines()

    if room not in baselines:
        print(f'WARNING: no baseline for room "{room}" — skipping drift check',
              file=sys.stderr)
        return 2
    if arm not in baselines[room]:
        print(f'WARNING: no baseline for arm "{arm}" in room "{room}" — '
              f'available: {list(baselines[room].keys())}', file=sys.stderr)
        return 2

    baseline = baselines[room][arm]['baseline_median_frac']

    if not os.path.exists(metrics_path):
        print(f'FATAL: metrics file not found: {metrics_path}', file=sys.stderr)
        return 2

    metrics = json.load(open(metrics_path))
    roll_fracs = extract_roll_fracs(metrics)
    if not roll_fracs:
        print(f'WARNING: no roll_fracs/per_roll in {metrics_path} — '
              'cannot check drift', file=sys.stderr)
        return 2

    current_median = median(roll_fracs)
    ratio = current_median / baseline if baseline > 0 else float('inf')
    inv_ratio = baseline / current_median if current_median > 0 else float('inf')
    max_ratio = max(ratio, inv_ratio)

    if max_ratio > DRIFT_FACTOR:
        direction = 'UP' if ratio > DRIFT_FACTOR else 'DOWN'
        print(f'DRIFT DETECTED [{room}/{arm}]: median roll frac shifted '
              f'{direction} by {max_ratio:.1f}x\n'
              f'  baseline: {baseline:.4f}\n'
              f'  current:  {current_median:.4f}\n'
              f'  ratio:    {max_ratio:.1f}x (threshold: {DRIFT_FACTOR}x)\n'
              f'  roll_fracs: {[round(f, 4) for f in roll_fracs]}\n'
              f'  ACTION: investigate before consuming this mask — the VLM '
              f'may have shifted.',
              file=sys.stderr)
        return 1

    print(f'OK [{room}/{arm}]: median {current_median:.4f} vs baseline '
          f'{baseline:.4f} (ratio {max_ratio:.2f}x, within {DRIFT_FACTOR}x)')
    return 0


def main():
    if len(sys.argv) < 4:
        print(f'Usage: {sys.argv[0]} <metrics-file> <room> <arm>',
              file=sys.stderr)
        print(f'Example: {sys.argv[0]} '
              'docs/art-options/wires-signs-gpt-night-bazaar-metrics.json '
              'night-bazaar gpt', file=sys.stderr)
        sys.exit(2)

    metrics_path = sys.argv[1]
    room = sys.argv[2]
    arm = sys.argv[3]
    sys.exit(check(metrics_path, room, arm))


if __name__ == '__main__':
    main()
