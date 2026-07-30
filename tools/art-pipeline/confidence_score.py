#!/usr/bin/env python3
"""Per-part confidence scoring for the feet-conditioned layer estimator.

Reads estimator output JSON + parts mask, computes:
  - evidence ratio: winning bucket votes / opportunity-scaled min_evid
  - vote margin: winning vs second-best bucket (normalized)
  - entropy: Shannon entropy of the 4-bucket distribution
  - coverage tier: 'well-evidenced', 'under-evidenced', 'unvisited', 'dont-care'

The dont-care tier identifies parts whose pixels never overlap the player
sprite's screen-space extent at any reachable walkable position.  Their
layer classification cannot affect rendering, so they are excluded from
the coverage denominator.

Usage:
  python confidence_score.py <estimator.json> <parts_mask.npz> [--walker-width 30]
"""
import json
import math

import cv2
import numpy as np
from scipy import ndimage

EVID_ALPHA = 0.10
MIN_EVID_FLOOR, MIN_EVID_CAP = 90, 450
BUCKETS = ('occ_front', 'occ_behind', 'under_front', 'under_behind')
WELL_EVIDENCED_RATIO = 2.0
UNDER_EVIDENCED_RATIO = 0.5


def compute_observation_zone(walkable_mask, walker_w=30, walker_h=70):
    """Compute the screen-space region reachable by any player sprite position.

    Uses the largest connected walkable component (reachable from spawn),
    then dilates by the walker sprite box anchored at the feet (bottom-center).
    Returns a boolean mask of the same shape as walkable_mask.
    """
    labeled, n = ndimage.label(walkable_mask)
    if n > 1:
        sizes = ndimage.sum(walkable_mask, labeled, range(1, n + 1))
        biggest = int(np.argmax(sizes)) + 1
        reachable = labeled == biggest
    else:
        reachable = walkable_mask

    kernel = np.ones((walker_h, walker_w), dtype=np.uint8)
    anchor = (walker_w // 2, walker_h - 1)
    dilated = cv2.dilate(reachable.astype(np.uint8) * 255, kernel, anchor=anchor)
    return dilated > 0


def compute_dont_care(parts_mask, observation_zone, pid_strs):
    """Return the set of pid_strs whose part pixels have zero overlap with
    the observation zone.  These parts can never affect rendering because
    the player sprite never occupies that screen region."""
    dc = set()
    for pid_str in pid_strs:
        part = parts_mask == int(pid_str)
        if (part & observation_zone).sum() == 0:
            dc.add(pid_str)
    return dc


def min_evid_for(part_area, walker_w_plate):
    return float(np.clip(EVID_ALPHA * part_area ** 0.5 * walker_w_plate,
                         MIN_EVID_FLOOR, MIN_EVID_CAP))


def bucket_entropy(votes):
    total = sum(votes[b] for b in BUCKETS)
    if total == 0:
        return 0.0
    probs = [votes[b] / total for b in BUCKETS if votes[b] > 0]
    return -sum(p * math.log2(p) for p in probs)


def score_part(votes, part_area, walker_w_plate, layer, unreliable=False,
               has_blocker=False):
    """Score one part. Returns a dict with confidence metrics.

    has_blocker: True if the part physically blocks (wall, crate with collision).
    Parts classified as 'collision' by their blocker, with no vote evidence,
    are treated as 'structural' (correct by physical evidence) rather than
    'unvisited' — a walker might reclassify them, but the conservative default
    is reasonable.
    """
    threshold = min_evid_for(part_area, walker_w_plate)
    counts = {b: votes[b] for b in BUCKETS}
    total = sum(counts.values())
    sorted_buckets = sorted(BUCKETS, key=lambda b: counts[b], reverse=True)
    winner = sorted_buckets[0]
    runner_up = sorted_buckets[1]
    winner_votes = counts[winner]
    runner_votes = counts[runner_up]

    evidence_ratio = winner_votes / threshold if threshold > 0 else 0.0
    margin = (winner_votes - runner_votes) / max(1, winner_votes + runner_votes)
    entropy = bucket_entropy(votes)

    if total == 0:
        if has_blocker and layer == 'collision':
            tier = 'structural'
        else:
            tier = 'unvisited'
    elif evidence_ratio >= WELL_EVIDENCED_RATIO and margin >= 0.5:
        tier = 'well-evidenced'
    elif evidence_ratio >= UNDER_EVIDENCED_RATIO:
        tier = 'under-evidenced' if margin < 0.5 else 'adequate'
    else:
        tier = 'under-evidenced'

    if unreliable:
        tier = 'unreliable'

    return {
        'layer': layer,
        'evidence_ratio': round(evidence_ratio, 3),
        'margin': round(margin, 3),
        'entropy': round(entropy, 3),
        'winner_bucket': winner,
        'winner_votes': winner_votes,
        'total_votes': total,
        'threshold': round(threshold, 1),
        'tier': tier,
    }


def score_room(estimator_json, parts_mask, walker_w_plate=None,
               ground_mask=None, coll_mask=None, walkable_mask=None,
               walker_w=30, walker_h=70):
    """Score all parts in a room. Returns {pid_str: score_dict}.

    If ground_mask and coll_mask are provided, computes has_blocker per part
    (part has non-ground pixels with collision barriers). Otherwise falls back
    to inferring blockers from the layer classification.

    If walkable_mask is provided, computes the observation zone and marks
    parts with zero sprite overlap as dont-care (tier='dont-care').
    """
    with open(estimator_json) as f:
        data = json.load(f)

    if isinstance(parts_mask, str):
        parts_mask = np.load(parts_mask)['inst']

    votes = data['votes']
    unreliable_set = set(data.get('unreliable', {}).keys())
    last_iter = data['iterations'][-1] if data['iterations'] else {}
    layers = last_iter.get('layers', {})

    obs_zone = None
    dont_care_set = set()
    if walkable_mask is not None:
        obs_zone = compute_observation_zone(walkable_mask, walker_w, walker_h)
        dont_care_set = compute_dont_care(parts_mask, obs_zone, votes.keys())

    part_areas = {}
    blockers = {}
    for pid_str in votes:
        pid = int(pid_str)
        m = parts_mask == pid
        part_areas[pid_str] = int(m.sum())
        if ground_mask is not None and coll_mask is not None:
            nong = m & ~ground_mask
            blocked = ~coll_mask & nong
            blockers[pid_str] = bool(blocked.any())
        else:
            blockers[pid_str] = layers.get(pid_str) == 'collision'

    if walker_w_plate is None:
        walker_w_plate = 30.0

    scores = {}
    for pid_str in votes:
        if pid_str in dont_care_set:
            scores[pid_str] = {
                'layer': layers.get(pid_str, 'collision-prior'),
                'evidence_ratio': 0.0, 'margin': 0.0, 'entropy': 0.0,
                'winner_bucket': 'n/a', 'winner_votes': 0,
                'total_votes': sum(votes[pid_str][b] for b in BUCKETS),
                'threshold': 0.0, 'tier': 'dont-care',
            }
            continue

        layer = layers.get(pid_str, 'collision-prior')
        scores[pid_str] = score_part(
            votes[pid_str],
            part_areas[pid_str],
            walker_w_plate,
            layer,
            unreliable=(pid_str in unreliable_set),
            has_blocker=blockers.get(pid_str, False),
        )

    return scores


def summarize(scores):
    """Aggregate confidence scores into a room-level summary.

    When dont-care parts are present, reports both the raw classified_pct
    (all parts in denominator) and relevant_classified_pct (dont-care
    excluded from the denominator).  The relevant metric is the one that
    matters for coverage budgeting.
    """
    tiers = {}
    for s in scores.values():
        tiers[s['tier']] = tiers.get(s['tier'], 0) + 1

    total = len(scores)
    well = tiers.get('well-evidenced', 0)
    adequate = tiers.get('adequate', 0)
    under = tiers.get('under-evidenced', 0)
    unvisited = tiers.get('unvisited', 0)
    unreliable = tiers.get('unreliable', 0)
    structural = tiers.get('structural', 0)
    dont_care = tiers.get('dont-care', 0)

    classified = well + adequate + structural
    relevant = total - dont_care
    ratios = [s['evidence_ratio'] for s in scores.values()
              if s['tier'] not in ('unvisited', 'unreliable', 'structural', 'dont-care')]
    margins = [s['margin'] for s in scores.values()
               if s['tier'] not in ('unvisited', 'unreliable', 'structural', 'dont-care')]

    result = {
        'total_parts': total,
        'well_evidenced': well,
        'adequate': adequate,
        'structural': structural,
        'under_evidenced': under,
        'unvisited': unvisited,
        'unreliable': unreliable,
        'dont_care': dont_care,
        'relevant_parts': relevant,
        'classified_pct': round(100 * classified / max(1, total), 1),
        'relevant_classified_pct': round(100 * classified / max(1, relevant), 1),
        'median_evidence_ratio': round(float(np.median(ratios)), 3) if ratios else 0.0,
        'median_margin': round(float(np.median(margins)), 3) if margins else 0.0,
    }
    return result


def under_evidenced_pids(scores):
    """Return pids that need more evidence.

    Excludes dont-care parts (player can't interact with them) along
    with unreliable and already-classified parts.
    """
    return [pid for pid, s in scores.items()
            if s['tier'] in ('unvisited', 'under-evidenced')]


if __name__ == '__main__':
    import argparse
    from PIL import Image

    parser = argparse.ArgumentParser()
    parser.add_argument('estimator_json')
    parser.add_argument('parts_mask_npz')
    parser.add_argument('--walker-width', type=float, default=30.0)
    parser.add_argument('--collision-png', help='collision mask for dont-care computation')
    args = parser.parse_args()

    parts = np.load(args.parts_mask_npz)['inst']
    walkable = None
    if args.collision_png:
        walkable = np.asarray(
            Image.open(args.collision_png).convert('L')
            .resize((parts.shape[1], parts.shape[0]),
                    Image.Resampling.NEAREST)) > 127

    scores = score_room(args.estimator_json, parts, args.walker_width,
                        walkable_mask=walkable)
    summary = summarize(scores)
    print(json.dumps(summary, indent=2))

    needs_work = under_evidenced_pids(scores)
    if needs_work:
        print(f'\n{len(needs_work)} parts need more evidence: {needs_work[:20]}')
