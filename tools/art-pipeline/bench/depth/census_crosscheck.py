"""Census-completeness cross-check: DAv2 depth blobs vs v3/v4 census.

Compares above-floor depth blobs (from DAv2) against the census colored
overlay masks. Reports blobs with no census overlap as candidate missed
objects, with bounding boxes and a census-miss-rate per scene.

Usage:
  python census_crosscheck.py --repo /path/to/emberwood
"""
import argparse
import json
import os

import cv2
import numpy as np

SCENES = {
    "anchorroom": {
        "plate": "docs/art-options/nbp-scifi-anchor-clean.png",
        "depth_walk_mask": "docs/art-options/bench/depth/davi2-walk-{scene}-mask.png",
        "census_v3": [
            "docs/art-options/v3/anchorroom/census-r0.jpg",
            "docs/art-options/v3/anchorroom/census-r1.jpg",
            "docs/art-options/v3/anchorroom/census-r2.jpg",
            "docs/art-options/v3/anchorroom/census-r3.jpg",
        ],
        "census_v4": [
            "docs/art-options/v4/anchorroom/census-r0.jpg",
            "docs/art-options/v4/anchorroom/census-r1.jpg",
            "docs/art-options/v4/anchorroom/census-r2.jpg",
            "docs/art-options/v4/anchorroom/census-r3.jpg",
        ],
    },
    "night-bazaar": {
        "plate": "docs/art-options/rooms/night-bazaar/plate.png",
        "depth_walk_mask": "docs/art-options/bench/depth/davi2-walk-{scene}-mask.png",
        "census_v3": [],
        "census_v4": [],
    },
    "plaza-market-inside": {
        "plate": "docs/art-options/rooms/plaza-market-inside/plate.png",
        "depth_walk_mask": "docs/art-options/bench/depth/davi2-walk-{scene}-mask.png",
        "census_v3": [],
        "census_v4": [],
    },
}

OUT_DIR = "docs/art-options/bench/depth"

MIN_BLOB_AREA = 500  # minimum area for a depth blob to be considered


def extract_census_mask(census_img, plate_img):
    """Extract tinted regions by comparing census overlay to the source plate.

    The census overlays color-tint detected objects. We find pixels where the
    color difference from the source is large (indicating tinting).
    """
    h_c, w_c = census_img.shape[:2]
    h_p, w_p = plate_img.shape[:2]

    plate_resized = cv2.resize(plate_img, (w_c, h_c), interpolation=cv2.INTER_AREA)

    diff = cv2.absdiff(census_img.astype(np.int16), plate_resized.astype(np.int16))
    diff = np.abs(diff).astype(np.uint8)
    diff_gray = np.max(diff, axis=2)

    _, tinted = cv2.threshold(diff_gray, 25, 255, cv2.THRESH_BINARY)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    tinted = cv2.morphologyEx(tinted, cv2.MORPH_CLOSE, kernel)
    tinted = cv2.morphologyEx(tinted, cv2.MORPH_OPEN, kernel)

    return tinted


def get_depth_blobs(walk_mask_path, min_area=MIN_BLOB_AREA):
    """Extract above-floor connected components from DAv2 walk mask.

    Above-floor = pixels NOT in the walk mask (dark in the mask).
    """
    walk = cv2.imread(walk_mask_path, cv2.IMREAD_GRAYSCALE)
    if walk is None:
        return None, []

    above_floor = (walk < 128).astype(np.uint8)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    above_floor = cv2.morphologyEx(above_floor, cv2.MORPH_CLOSE, kernel)
    above_floor = cv2.morphologyEx(above_floor, cv2.MORPH_OPEN, kernel)

    nlabels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        above_floor, connectivity=8
    )

    blobs = []
    for i in range(1, nlabels):
        area = stats[i, cv2.CC_STAT_AREA]
        if area < min_area:
            continue
        blobs.append({
            "label_id": i,
            "x": int(stats[i, cv2.CC_STAT_LEFT]),
            "y": int(stats[i, cv2.CC_STAT_TOP]),
            "w": int(stats[i, cv2.CC_STAT_WIDTH]),
            "h": int(stats[i, cv2.CC_STAT_HEIGHT]),
            "area": int(area),
            "cx": round(float(centroids[i][0]), 1),
            "cy": round(float(centroids[i][1]), 1),
        })

    return labels, blobs


def crosscheck_scene(repo, scene, scene_cfg):
    """Cross-check depth blobs vs census for one scene."""
    walk_mask_path = os.path.join(
        repo, scene_cfg["depth_walk_mask"].format(scene=scene)
    )
    plate_path = os.path.join(repo, scene_cfg["plate"])

    labels, blobs = get_depth_blobs(walk_mask_path)
    if labels is None:
        return {"error": f"No walk mask at {walk_mask_path}"}

    plate = cv2.imread(plate_path)
    if plate is None:
        return {"error": f"No plate at {plate_path}"}

    target_h, target_w = labels.shape

    combined_census = np.zeros((target_h, target_w), dtype=np.uint8)
    census_versions_used = []

    for version in ["census_v4", "census_v3"]:
        paths = scene_cfg.get(version, [])
        valid_paths = [p for p in paths if os.path.exists(os.path.join(repo, p))]
        if not valid_paths:
            continue

        census_versions_used.append(version)
        for cpath in valid_paths:
            census_img = cv2.imread(os.path.join(repo, cpath))
            if census_img is None:
                continue
            tinted = extract_census_mask(census_img, plate)
            tinted_resized = cv2.resize(
                tinted, (target_w, target_h), interpolation=cv2.INTER_NEAREST
            )
            combined_census = np.maximum(combined_census, tinted_resized)

    if not census_versions_used:
        return {
            "scene": scene,
            "n_depth_blobs": len(blobs),
            "census_available": False,
            "notes": "No census masks available for this scene",
        }

    missed = []
    covered = []
    for blob in blobs:
        blob_mask = labels == blob["label_id"]
        blob_mask_resized = blob_mask.astype(np.uint8)

        overlap = np.sum(blob_mask_resized & (combined_census > 127))
        blob_area = np.sum(blob_mask_resized)
        overlap_fraction = overlap / blob_area if blob_area > 0 else 0

        blob["census_overlap_fraction"] = round(overlap_fraction, 3)

        if overlap_fraction < 0.1:
            missed.append(blob)
        else:
            covered.append(blob)

    miss_rate = len(missed) / len(blobs) if blobs else 0.0

    vis = plate.copy()
    if vis.shape[:2] != (target_h, target_w):
        vis = cv2.resize(vis, (target_w, target_h))

    for blob in covered:
        x, y, w, h = blob["x"], blob["y"], blob["w"], blob["h"]
        cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 255, 0), 2)

    for blob in missed:
        x, y, w, h = blob["x"], blob["y"], blob["w"], blob["h"]
        cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 0, 255), 3)
        cv2.putText(vis, "MISS", (x, y - 5), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (0, 0, 255), 2)

    out_dir = os.path.join(repo, OUT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    vis_path = os.path.join(out_dir, f"census-crosscheck-{scene}-on-source.jpg")
    cv2.imwrite(vis_path, vis)

    result = {
        "scene": scene,
        "census_versions": census_versions_used,
        "n_depth_blobs": len(blobs),
        "n_covered": len(covered),
        "n_missed": len(missed),
        "census_miss_rate": round(miss_rate, 3),
        "missed_blobs": [
            {k: v for k, v in b.items() if k != "label_id"}
            for b in missed
        ],
    }

    json_path = os.path.join(out_dir, f"census-crosscheck-{scene}-metrics.json")
    with open(json_path, "w") as f:
        json.dump(result, f, indent=2)

    return result


def run(repo):
    all_results = {}
    for scene, cfg in SCENES.items():
        print(f"\n=== {scene} ===")
        r = crosscheck_scene(repo, scene, cfg)
        all_results[scene] = r

        if "error" in r:
            print(f"  ERROR: {r['error']}")
        elif not r.get("census_available", True):
            print(f"  No census available — {r['n_depth_blobs']} depth blobs found")
        else:
            print(f"  Depth blobs: {r['n_depth_blobs']}")
            print(f"  Covered by census: {r['n_covered']}")
            print(f"  Missed (no census overlap): {r['n_missed']}")
            print(f"  Census miss rate: {r['census_miss_rate']:.1%}")
            if r["missed_blobs"]:
                for b in r["missed_blobs"][:5]:
                    print(f"    MISS: box=({b['x']},{b['y']},{b['w']}x{b['h']}), "
                          f"area={b['area']}, overlap={b['census_overlap_fraction']}")

    summary_path = os.path.join(repo, OUT_DIR, "census-crosscheck-summary.json")
    with open(summary_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nWrote {summary_path}")

    return all_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()
    run(args.repo)
