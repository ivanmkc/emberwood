#!/usr/bin/env python3
"""Paint numbered walking waypoints on a plate image for Veo.

Given a plate PNG and a list of coverage-planner paths, paints numbered
circle markers along each path so Veo can see where walkers should go.
The markers are painted in a contrasting color with a number label.

Usage:
  python waypoint_paint.py <plate.png> <paths.json> <output.png>

paths.json is a list of segments: [{"y": int, "x0": int, "x1": int, "pid": int, "side": str}, ...]
or the merged format from plan_coverage_paths: [[[x0,y0],[x1,y1]], ...]
"""
import json
import os
import sys

import cv2
import numpy as np


MARKER_RADIUS = 14
MARKER_COLOR = (0, 200, 255)
MARKER_OUTLINE = (0, 0, 0)
LABEL_COLOR = (0, 0, 0)
FONT = cv2.FONT_HERSHEY_SIMPLEX
FONT_SCALE = 0.5
FONT_THICKNESS = 2
ARROW_COLOR = (255, 180, 0)
ARROW_THICKNESS = 2

WAYPOINT_SPACING = 80


def paint_waypoints(plate_bgr, paths, spacing=WAYPOINT_SPACING):
    """Paint numbered waypoints along each path on the plate image.

    Args:
        plate_bgr: BGR plate image (will be copied, not mutated)
        paths: list of paths, each a list of [x,y] waypoints
        spacing: pixels between consecutive waypoint markers

    Returns:
        painted: BGR image with waypoints, markers: list of (n, x, y)
    """
    painted = plate_bgr.copy()
    markers = []
    n = 1

    for path in paths:
        if len(path) < 2:
            continue

        pts = np.array(path, dtype=np.float64)
        total_len = 0.0
        seg_lens = []
        for i in range(len(pts) - 1):
            d = np.linalg.norm(pts[i + 1] - pts[i])
            seg_lens.append(d)
            total_len += d

        if total_len < spacing:
            cx, cy = int(pts[0][0] + pts[-1][0]) // 2, int(pts[0][1] + pts[-1][1]) // 2
            _draw_marker(painted, n, cx, cy)
            markers.append((n, cx, cy))
            n += 1
            continue

        n_markers = max(2, int(total_len / spacing) + 1)
        target_dists = np.linspace(0, total_len, n_markers)
        cumul = 0.0
        seg_i = 0
        for td in target_dists:
            while seg_i < len(seg_lens) - 1 and cumul + seg_lens[seg_i] < td:
                cumul += seg_lens[seg_i]
                seg_i += 1
            frac = (td - cumul) / max(1e-6, seg_lens[seg_i])
            frac = min(1.0, max(0.0, frac))
            px = pts[seg_i] * (1 - frac) + pts[seg_i + 1] * frac
            cx, cy = int(px[0]), int(px[1])
            _draw_marker(painted, n, cx, cy)
            markers.append((n, cx, cy))
            n += 1

        for i in range(len(path) - 1):
            _draw_arrow(painted, path[i], path[i + 1])

    return painted, markers


def _draw_marker(img, number, cx, cy):
    cv2.circle(img, (cx, cy), MARKER_RADIUS + 2, MARKER_OUTLINE, -1)
    cv2.circle(img, (cx, cy), MARKER_RADIUS, MARKER_COLOR, -1)
    text = str(number)
    (tw, th), _ = cv2.getTextSize(text, FONT, FONT_SCALE, FONT_THICKNESS)
    cv2.putText(img, text, (cx - tw // 2, cy + th // 2),
                FONT, FONT_SCALE, LABEL_COLOR, FONT_THICKNESS)


def _draw_arrow(img, p0, p1):
    x0, y0 = int(p0[0]), int(p0[1])
    x1, y1 = int(p1[0]), int(p1[1])
    cv2.arrowedLine(img, (x0, y0), (x1, y1), ARROW_COLOR, ARROW_THICKNESS,
                    tipLength=0.08)


def paths_from_coverage_planner(merged_paths):
    """Convert plan_coverage_paths merged output to the format expected here."""
    return [[(int(p[0]), int(p[1])) for p in seg] for seg in merged_paths]


def paint_targeted_paths(plate_bgr, parts_mask, base_y_map, target_pids,
                         walker_w, walker_h, collision_bands):
    """Generate and paint coverage paths for specific under-evidenced parts.

    This is the entry point for the closed loop: given which parts need
    more evidence, compute coverage paths and paint them.
    """
    from synth_scene_family import plan_coverage_paths

    merged, report = plan_coverage_paths(
        parts_mask, base_y_map, walker_w, walker_h, collision_bands)

    target_set = set(int(p) for p in target_pids)
    filtered = []
    for seg in merged:
        if any(int(m.get('pid', 0)) in target_set
               for m in seg.get('members', [seg])):
            filtered.append([(seg['x0'], seg['y']), (seg['x1'], seg['y'])]
                            if isinstance(seg, dict) else seg)

    if not filtered:
        filtered = [seg for seg in merged]

    painted, markers = paint_waypoints(plate_bgr, filtered)
    return painted, markers, report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('plate')
    parser.add_argument('paths_json')
    parser.add_argument('output')
    args = parser.parse_args()

    plate = cv2.imread(args.plate)
    with open(args.paths_json) as f:
        paths = json.load(f)

    painted, markers = paint_waypoints(plate, paths)
    cv2.imwrite(args.output, painted)
    print(f'Painted {len(markers)} waypoints on {args.output}')
    for n, x, y in markers:
        print(f'  #{n}: ({x}, {y})')
