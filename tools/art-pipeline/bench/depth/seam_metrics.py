"""Seam continuity metrics across room boundaries.

Given two room plates and their collision masks sharing an edge, compute:
  (a) Color/luminance histogram distance in mirrored strips along the seam
  (b) Edge-continuation rate: Canny edges reaching the seam that continue
      within +/-3px on the other side
  (c) Walkable-strip alignment: overlap/Jaccard of walkable intervals at
      the seam from each room's collision mask

CLI:
  python seam_metrics.py --plate-a plate_a.png --plate-b plate_b.png \
      --coll-a coll_a.png --coll-b coll_b.png \
      --edge-a w --edge-b e \
      --out-dir docs/art-options/bench/depth/ \
      --label anchor-bazaar

Edge convention: the --edge-a flag says which edge of plate A is the seam
(w/e/n/s). --edge-b is the matching edge of plate B (usually opposite).

Outputs:
  <label>-seam-metrics.json
  <label>-seam-crop.jpg  (side-by-side strip crop)
"""
import argparse
import json
import os

import cv2
import numpy as np


STRIP_WIDTH = 32  # pixels of each plate to compare at the seam


def _extract_strip(img, edge, width=STRIP_WIDTH):
    """Extract a vertical or horizontal strip from the edge of an image."""
    h, w_img = img.shape[:2]
    if edge == "w":
        return img[:, :width]
    elif edge == "e":
        return img[:, w_img - width:]
    elif edge == "n":
        return img[:width, :]
    elif edge == "s":
        return img[h - width:, :]
    raise ValueError(f"Unknown edge: {edge}")


def _extract_seam_line(img, edge):
    """Extract the single-pixel line at the seam edge."""
    h, w = img.shape[:2]
    if edge == "w":
        return img[:, 0]
    elif edge == "e":
        return img[:, w - 1]
    elif edge == "n":
        return img[0, :]
    elif edge == "s":
        return img[h - 1, :]
    raise ValueError(f"Unknown edge: {edge}")


def _is_horizontal_edge(edge):
    return edge in ("n", "s")


def color_histogram_distance(strip_a, strip_b):
    """Chi-squared distance between color histograms of two strips.

    Also computes luminance histogram distance separately.
    """
    results = {}

    for name, sa, sb in [("bgr", strip_a, strip_b)]:
        hists_a = []
        hists_b = []
        for c in range(3):
            ha = cv2.calcHist([sa], [c], None, [64], [0, 256])
            hb = cv2.calcHist([sb], [c], None, [64], [0, 256])
            cv2.normalize(ha, ha)
            cv2.normalize(hb, hb)
            hists_a.append(ha)
            hists_b.append(hb)

        chi2_per_channel = []
        for ha, hb in zip(hists_a, hists_b):
            d = cv2.compareHist(ha, hb, cv2.HISTCMP_CHISQR)
            chi2_per_channel.append(d)
        results["color_chi2_per_channel"] = [round(d, 4) for d in chi2_per_channel]
        results["color_chi2_mean"] = round(float(np.mean(chi2_per_channel)), 4)

    gray_a = cv2.cvtColor(strip_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(strip_b, cv2.COLOR_BGR2GRAY)
    ha = cv2.calcHist([gray_a], [0], None, [64], [0, 256])
    hb = cv2.calcHist([gray_b], [0], None, [64], [0, 256])
    cv2.normalize(ha, ha)
    cv2.normalize(hb, hb)
    results["luma_chi2"] = round(float(cv2.compareHist(ha, hb, cv2.HISTCMP_CHISQR)), 4)

    lab_a = cv2.cvtColor(strip_a, cv2.COLOR_BGR2LAB)
    lab_b = cv2.cvtColor(strip_b, cv2.COLOR_BGR2LAB)
    mean_a = np.mean(lab_a.reshape(-1, 3), axis=0)
    mean_b = np.mean(lab_b.reshape(-1, 3), axis=0)
    results["mean_lab_delta"] = round(float(np.linalg.norm(mean_a - mean_b)), 2)

    return results


def edge_continuation_rate(plate_a, plate_b, edge_a, edge_b, tolerance=3):
    """Fraction of Canny edge pixels at the seam that continue on the other side.

    For each edge pixel on plate_a's seam line, check if there's an edge pixel
    on plate_b's seam line within +/-tolerance pixels along the seam axis.
    """
    gray_a = cv2.cvtColor(plate_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(plate_b, cv2.COLOR_BGR2GRAY)

    edges_a = cv2.Canny(gray_a, 50, 150)
    edges_b = cv2.Canny(gray_b, 50, 150)

    line_a = _extract_seam_line(edges_a, edge_a)
    line_b = _extract_seam_line(edges_b, edge_b)

    if len(line_a) != len(line_b):
        min_len = min(len(line_a), len(line_b))
        line_a = line_a[:min_len]
        line_b = line_b[:min_len]

    n = len(line_a)
    edge_positions_a = np.where(line_a > 0)[0]
    edge_positions_b = set(np.where(line_b > 0)[0].tolist())

    if len(edge_positions_a) == 0:
        return {
            "edge_continuation_rate": 0.0,
            "n_edge_pixels_a": 0,
            "n_edge_pixels_b": len(edge_positions_b),
            "n_continued": 0,
        }

    continued = 0
    for pos in edge_positions_a:
        for offset in range(-tolerance, tolerance + 1):
            if (pos + offset) in edge_positions_b:
                continued += 1
                break

    rate = continued / len(edge_positions_a)

    edge_positions_b_list = np.where(line_b > 0)[0]
    continued_b = 0
    edge_positions_a_set = set(edge_positions_a.tolist())
    for pos in edge_positions_b_list:
        for offset in range(-tolerance, tolerance + 1):
            if (pos + offset) in edge_positions_a_set:
                continued_b += 1
                break
    rate_b = continued_b / len(edge_positions_b_list) if len(edge_positions_b_list) > 0 else 0

    return {
        "edge_continuation_rate_a_to_b": round(rate, 4),
        "edge_continuation_rate_b_to_a": round(rate_b, 4),
        "edge_continuation_rate_mean": round((rate + rate_b) / 2, 4),
        "n_edge_pixels_a": int(len(edge_positions_a)),
        "n_edge_pixels_b": int(len(edge_positions_b_list)),
        "n_continued_a_to_b": int(continued),
        "n_continued_b_to_a": int(continued_b),
    }


def walkable_strip_alignment(coll_a, coll_b, edge_a, edge_b):
    """Overlap/Jaccard of walkable intervals at the seam line.

    Extracts the walkable (white) pixels along the seam line from each
    collision mask and computes their Jaccard similarity.
    """
    line_a = _extract_seam_line(coll_a, edge_a)
    line_b = _extract_seam_line(coll_b, edge_b)

    if len(line_a) != len(line_b):
        min_len = min(len(line_a), len(line_b))
        line_a = line_a[:min_len]
        line_b = line_b[:min_len]

    walk_a = line_a > 127
    walk_b = line_b > 127

    inter = np.sum(walk_a & walk_b)
    union = np.sum(walk_a | walk_b)
    jaccard = inter / union if union > 0 else 0.0

    intervals_a = _find_intervals(walk_a)
    intervals_b = _find_intervals(walk_b)

    return {
        "walkable_jaccard": round(jaccard, 4),
        "walkable_fraction_a": round(float(np.mean(walk_a)), 4),
        "walkable_fraction_b": round(float(np.mean(walk_b)), 4),
        "n_walk_intervals_a": len(intervals_a),
        "n_walk_intervals_b": len(intervals_b),
        "walk_intervals_a": intervals_a[:10],
        "walk_intervals_b": intervals_b[:10],
    }


def _find_intervals(mask_1d):
    """Find contiguous True intervals in a 1D boolean array."""
    intervals = []
    in_interval = False
    start = 0
    for i, v in enumerate(mask_1d):
        if v and not in_interval:
            start = i
            in_interval = True
        elif not v and in_interval:
            intervals.append([int(start), int(i - 1)])
            in_interval = False
    if in_interval:
        intervals.append([int(start), int(len(mask_1d) - 1)])
    return intervals


def make_seam_crop(plate_a, plate_b, edge_a, edge_b, strip_width=64):
    """Create a side-by-side seam crop visualization."""
    strip_a = _extract_strip(plate_a, edge_a, strip_width)
    strip_b = _extract_strip(plate_b, edge_b, strip_width)

    if _is_horizontal_edge(edge_a):
        ha = strip_a.shape[0]
        hb = strip_b.shape[0]
        w = min(strip_a.shape[1], strip_b.shape[1])
        strip_a = strip_a[:, :w]
        strip_b = strip_b[:, :w]
        divider = np.zeros((2, w, 3), dtype=np.uint8)
        divider[:, :] = [0, 0, 255]
        if edge_a == "s":
            crop = np.vstack([strip_a, divider, strip_b])
        else:
            crop = np.vstack([strip_b, divider, strip_a])
    else:
        h = min(strip_a.shape[0], strip_b.shape[0])
        strip_a = strip_a[:h]
        strip_b = strip_b[:h]
        divider = np.zeros((h, 2, 3), dtype=np.uint8)
        divider[:, :] = [0, 0, 255]
        if edge_a == "e":
            crop = np.hstack([strip_a, divider, strip_b])
        else:
            crop = np.hstack([strip_b, divider, strip_a])

    return crop


def score_seam(plate_a_path, plate_b_path, coll_a_path, coll_b_path,
               edge_a, edge_b, out_dir, label):
    """Run all seam metrics and save outputs."""
    plate_a = cv2.imread(plate_a_path)
    plate_b = cv2.imread(plate_b_path)
    coll_a = cv2.imread(coll_a_path, cv2.IMREAD_GRAYSCALE)
    coll_b = cv2.imread(coll_b_path, cv2.IMREAD_GRAYSCALE)

    if plate_a is None or plate_b is None:
        return {"error": "Could not load plates"}
    if coll_a is None or coll_b is None:
        return {"error": "Could not load collision masks"}

    strip_a = _extract_strip(plate_a, edge_a)
    strip_b = _extract_strip(plate_b, edge_b)

    results = {
        "label": label,
        "plate_a": plate_a_path,
        "plate_b": plate_b_path,
        "edge_a": edge_a,
        "edge_b": edge_b,
        "plate_a_shape": list(plate_a.shape[:2]),
        "plate_b_shape": list(plate_b.shape[:2]),
    }

    results["color_histogram"] = color_histogram_distance(strip_a, strip_b)
    results["edge_continuation"] = edge_continuation_rate(
        plate_a, plate_b, edge_a, edge_b
    )
    results["walkable_alignment"] = walkable_strip_alignment(
        coll_a, coll_b, edge_a, edge_b
    )

    os.makedirs(out_dir, exist_ok=True)

    json_path = os.path.join(out_dir, f"{label}-seam-metrics.json")
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)

    crop = make_seam_crop(plate_a, plate_b, edge_a, edge_b)
    crop_path = os.path.join(out_dir, f"{label}-seam-crop.jpg")
    cv2.imwrite(crop_path, crop)

    return results


KNOWN_SEAMS = [
    {
        "label": "anchor-bazaar",
        "plate_a": "docs/art-options/nbp-scifi-anchor-clean.png",
        "plate_b": "docs/art-options/rooms/night-bazaar/plate.png",
        "coll_a": "assets/rooms/anchorroom.collision.png",
        "coll_b": "assets/rooms/night-bazaar.collision.png",
        "edge_a": "w",
        "edge_b": "e",
    },
]


def run(repo, out_dir=None):
    if out_dir is None:
        out_dir = os.path.join(repo, "docs/art-options/bench/depth")

    all_results = {}
    for seam in KNOWN_SEAMS:
        label = seam["label"]
        print(f"\n=== Seam: {label} ===")
        r = score_seam(
            os.path.join(repo, seam["plate_a"]),
            os.path.join(repo, seam["plate_b"]),
            os.path.join(repo, seam["coll_a"]),
            os.path.join(repo, seam["coll_b"]),
            seam["edge_a"],
            seam["edge_b"],
            out_dir,
            label,
        )
        all_results[label] = r

        ch = r.get("color_histogram", {})
        ec = r.get("edge_continuation", {})
        wa = r.get("walkable_alignment", {})
        print(f"  Color chi2 mean: {ch.get('color_chi2_mean', 'N/A')}")
        print(f"  Luma chi2: {ch.get('luma_chi2', 'N/A')}")
        print(f"  LAB delta: {ch.get('mean_lab_delta', 'N/A')}")
        print(f"  Edge continuation (mean): {ec.get('edge_continuation_rate_mean', 'N/A')}")
        print(f"  Walk Jaccard: {wa.get('walkable_jaccard', 'N/A')}")
        print(f"  Walk frac A: {wa.get('walkable_fraction_a', 'N/A')}, "
              f"B: {wa.get('walkable_fraction_b', 'N/A')}")

    return all_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--repo", help="Run all known seams from repo root")
    group.add_argument("--plate-a", help="Path to plate A")

    parser.add_argument("--plate-b")
    parser.add_argument("--coll-a")
    parser.add_argument("--coll-b")
    parser.add_argument("--edge-a", default="w")
    parser.add_argument("--edge-b", default="e")
    parser.add_argument("--out-dir", default="docs/art-options/bench/depth")
    parser.add_argument("--label", default="seam")
    args = parser.parse_args()

    if args.repo:
        run(args.repo)
    elif args.plate_a:
        r = score_seam(
            args.plate_a, args.plate_b,
            args.coll_a, args.coll_b,
            args.edge_a, args.edge_b,
            args.out_dir, args.label,
        )
        print(json.dumps(r, indent=2))
    else:
        parser.print_help()
