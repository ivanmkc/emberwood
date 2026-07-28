"""Perspective detectors for axis-aligned 3/4 camera verification.

Two detectors:
  (a) Edge-orientation histogram: LSD or HoughLinesP long segments,
      fraction within 5 degrees of 0/90 = axis-alignment score.
  (b) Vanishing-point RANSAC on off-axis segments: axis-aligned scenes
      have VPs at or near infinity.

Outputs persp-scores.json with per-image results.

Usage:
  python perspective.py --repo /path/to/emberwood
  # or import and call: score_image(path) -> dict
"""
import argparse
import json
import math
import os

import cv2
import numpy as np


def _detect_segments(gray):
    """Detect line segments using LSD (preferred) or HoughLinesP fallback."""
    try:
        lsd = cv2.createLineSegmentDetector(0)
        lines, widths, precs, nfas = lsd.detect(gray)
        if lines is None:
            return np.empty((0, 4))
        return lines.reshape(-1, 4)
    except Exception:
        pass

    edges = cv2.Canny(gray, 50, 150)
    raw = cv2.HoughLinesP(edges, 1, np.pi / 180, 50,
                          minLineLength=30, maxLineGap=10)
    if raw is None:
        return np.empty((0, 4))
    return raw.reshape(-1, 4).astype(np.float64)


def _segment_length(seg):
    return math.hypot(seg[2] - seg[0], seg[3] - seg[1])


def _segment_angle(seg):
    """Angle in degrees [0, 180) from horizontal."""
    dx = seg[2] - seg[0]
    dy = seg[3] - seg[1]
    angle = math.degrees(math.atan2(abs(dy), abs(dx)))
    return angle


def edge_orientation_score(segments, angle_tolerance=5.0, min_length=20):
    """Fraction of segment length within angle_tolerance of 0 or 90 degrees.

    Returns (score, histogram_dict).
    score: 0..1, higher = more axis-aligned.
    """
    total_len = 0.0
    aligned_len = 0.0
    bins = {"horizontal": 0.0, "vertical": 0.0, "diagonal": 0.0}

    for seg in segments:
        length = _segment_length(seg)
        if length < min_length:
            continue
        total_len += length
        angle = _segment_angle(seg)

        if angle <= angle_tolerance or angle >= (90 - angle_tolerance):
            aligned_len += length
            if angle <= angle_tolerance:
                bins["horizontal"] += length
            else:
                bins["vertical"] += length
        elif abs(angle - 90) <= angle_tolerance:
            aligned_len += length
            bins["vertical"] += length
        else:
            bins["diagonal"] += length

    score = aligned_len / total_len if total_len > 0 else 0.0

    if total_len > 0:
        bins = {k: round(v / total_len, 3) for k, v in bins.items()}

    return round(score, 4), bins


def vanishing_point_ransac(segments, img_shape, min_length=30,
                           angle_tolerance=10.0, n_iter=500):
    """RANSAC vanishing point estimation on off-axis segments.

    For axis-aligned scenes, VPs should be at or near infinity (large distance
    from image center).

    Returns dict with vp_distance (px from center), vp_coords, n_offaxis_segments.
    """
    h, w = img_shape[:2]
    cx, cy = w / 2, h / 2

    offaxis = []
    for seg in segments:
        length = _segment_length(seg)
        if length < min_length:
            continue
        angle = _segment_angle(seg)
        if angle_tolerance < angle < (90 - angle_tolerance):
            offaxis.append(seg)

    if len(offaxis) < 3:
        return {
            "vp_distance": float("inf"),
            "vp_coords": None,
            "n_offaxis_segments": len(offaxis),
            "notes": "Too few off-axis segments for RANSAC; scene is strongly axis-aligned",
        }

    offaxis = np.array(offaxis)

    def line_from_segment(seg):
        x1, y1, x2, y2 = seg
        a = y2 - y1
        b = x1 - x2
        c = x2 * y1 - x1 * y2
        return np.array([a, b, c], dtype=np.float64)

    lines = np.array([line_from_segment(s) for s in offaxis])

    best_inliers = 0
    best_vp = None
    rng = np.random.default_rng(42)

    for _ in range(n_iter):
        i, j = rng.choice(len(lines), 2, replace=False)
        l1, l2 = lines[i], lines[j]
        cross = np.cross(l1, l2)
        if abs(cross[2]) < 1e-10:
            continue
        vp = cross[:2] / cross[2]

        inliers = 0
        for k, seg in enumerate(offaxis):
            mx, my = (seg[0] + seg[2]) / 2, (seg[1] + seg[3]) / 2
            dx_seg = seg[2] - seg[0]
            dy_seg = seg[3] - seg[1]
            dx_vp = vp[0] - mx
            dy_vp = vp[1] - my
            len_seg = math.hypot(dx_seg, dy_seg)
            len_vp = math.hypot(dx_vp, dy_vp)
            if len_seg < 1 or len_vp < 1:
                continue
            cos_angle = abs(dx_seg * dx_vp + dy_seg * dy_vp) / (len_seg * len_vp)
            cos_angle = min(cos_angle, 1.0)
            angle_diff = math.degrees(math.acos(cos_angle))
            if angle_diff < 15:
                inliers += 1

        if inliers > best_inliers:
            best_inliers = inliers
            best_vp = vp

    if best_vp is None:
        return {
            "vp_distance": float("inf"),
            "vp_coords": None,
            "n_offaxis_segments": len(offaxis),
            "notes": "RANSAC failed to find consistent VP",
        }

    dist = math.hypot(best_vp[0] - cx, best_vp[1] - cy)
    diag = math.hypot(w, h)

    return {
        "vp_distance": round(dist, 1),
        "vp_distance_normalized": round(dist / diag, 3),
        "vp_coords": [round(best_vp[0], 1), round(best_vp[1], 1)],
        "n_offaxis_segments": len(offaxis),
        "n_inliers": best_inliers,
        "notes": (
            f"VP at {dist:.0f}px from center ({dist/diag:.2f}x diagonal). "
            f"{'Near infinity — strongly axis-aligned.' if dist / diag > 2 else 'VP is close — perspective detected.'}"
        ),
    }


def score_image(path):
    """Score a single image for axis-alignment and VP distance.

    Returns dict with axis_alignment_score, orientation_bins, vp_result.
    """
    img = cv2.imread(path)
    if img is None:
        return {"error": f"Could not load {path}"}

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    segments = _detect_segments(gray)

    align_score, bins = edge_orientation_score(segments)
    vp = vanishing_point_ransac(segments, img.shape)

    return {
        "path": path,
        "n_segments": len(segments),
        "axis_alignment_score": align_score,
        "orientation_bins": bins,
        "vp": vp,
    }


BENCH_SCENES = {
    "anchorroom": "docs/art-options/nbp-scifi-anchor-clean.png",
    "night-bazaar": "docs/art-options/rooms/night-bazaar/plate.png",
    "plaza-market-inside": "docs/art-options/rooms/plaza-market-inside/plate.png",
}


def run(repo):
    results = {}

    for name, rel in BENCH_SCENES.items():
        path = os.path.join(repo, rel)
        print(f"  {name}: ", end="", flush=True)
        r = score_image(path)
        r["scene"] = name
        results[name] = r
        print(f"align={r['axis_alignment_score']}, "
              f"VP dist={r['vp']['vp_distance']}, "
              f"off-axis={r['vp']['n_offaxis_segments']}")

    prompt_dir = os.path.join(repo, "docs/art-options/bench/prompt/perspective")
    if os.path.isdir(prompt_dir):
        for fn in sorted(os.listdir(prompt_dir)):
            if fn.lower().endswith((".png", ".jpg", ".jpeg")):
                path = os.path.join(prompt_dir, fn)
                name = os.path.splitext(fn)[0]
                print(f"  [prompt] {name}: ", end="", flush=True)
                r = score_image(path)
                r["scene"] = f"prompt/{name}"
                results[f"prompt/{name}"] = r
                print(f"align={r['axis_alignment_score']}, "
                      f"VP dist={r['vp']['vp_distance']}")

    out_path = os.path.join(repo, "docs/art-options/bench/depth", "persp-scores.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nWrote {out_path}")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()
    run(args.repo)
