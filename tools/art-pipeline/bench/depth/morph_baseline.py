"""Morphological baseline for object footprints.

Uses the NBP class mask to derive footprints via distance transform:
for each non-floor instance (connected component), the footprint is the
base band where the instance contacts or nearly contacts the floor plane.

No learning required — pure classic CV on the class mask.

Usage:
  python morph_baseline.py --repo /path/to/emberwood
"""
import argparse
import json
import os
import time

import cv2
import numpy as np

SCENES = {
    "anchorroom": {
        "plate": "docs/art-options/nbp-scifi-anchor-clean.png",
        "mask": "docs/art-options/nbp-mask.png",
        "collision": "assets/rooms/anchorroom.collision.png",
    },
    "night-bazaar": {
        "plate": "docs/art-options/rooms/night-bazaar/plate.png",
        "mask": "docs/art-options/rooms/night-bazaar/nbp-mask.png",
        "collision": "assets/rooms/night-bazaar.collision.png",
    },
    "plaza-market-inside": {
        "plate": "docs/art-options/rooms/plaza-market-inside/plate.png",
        "mask": "docs/art-options/rooms/plaza-market-inside/nbp-mask.png",
        "collision": "assets/rooms/plaza-market-inside.collision.png",
    },
}

FLOOR_BGR = [0, 255, 0]
WALL_BGR = [0, 0, 255]

OUT_DIR = "docs/art-options/bench/depth"


def is_floor(pixel_bgr):
    return np.all(pixel_bgr == FLOOR_BGR, axis=-1)


def derive_morph_footprints(mask_bgr):
    """Derive footprints from class mask using morphological distance transform.

    For each non-floor, non-wall connected component:
    1. Compute the distance from every pixel to the nearest floor pixel
    2. The footprint = base band of the component (bottom portion near floor)
       where distance to floor is small
    """
    h, w = mask_bgr.shape[:2]

    floor = is_floor(mask_bgr)
    wall = np.all(mask_bgr == WALL_BGR, axis=-1)
    non_floor = ~floor & ~wall

    floor_dist = cv2.distanceTransform(
        (~floor).astype(np.uint8), cv2.DIST_L2, 5
    )

    nlabels, labels, stats, _ = cv2.connectedComponentsWithStats(
        non_floor.astype(np.uint8), connectivity=8
    )

    footprint = np.zeros((h, w), dtype=np.uint8)

    for i in range(1, nlabels):
        area = stats[i, cv2.CC_STAT_AREA]
        if area < 100:
            continue

        comp_mask = labels == i
        y_coords, x_coords = np.where(comp_mask)
        y_base = np.max(y_coords)
        y_top = np.min(y_coords)
        comp_height = y_base - y_top + 1

        band_height = max(int(0.3 * comp_height), 10)
        band_top = max(0, y_base - band_height)

        band_mask = np.zeros((h, w), dtype=bool)
        band_mask[band_top:y_base + 1, :] = True
        band_mask &= comp_mask

        x_min = np.min(x_coords)
        x_max = np.max(x_coords)

        near_floor = floor_dist < max(20, 0.1 * comp_height)
        base_contact = band_mask & near_floor

        if np.sum(base_contact) > 10:
            footprint[base_contact] = 255
        else:
            footprint[band_mask] = 255

    return footprint


def derive_morph_walk(mask_bgr):
    """Derive walkability from class mask — floor class with morphological cleanup."""
    floor = is_floor(mask_bgr).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    floor = cv2.morphologyEx(floor, cv2.MORPH_CLOSE, kernel)
    return floor


def overlay_on_source(source_bgr, mask, color=(0, 255, 0), alpha=0.4):
    vis = source_bgr.copy()
    mask_bool = mask > 127
    overlay = vis.copy()
    overlay[mask_bool] = color
    return cv2.addWeighted(vis, 1 - alpha, overlay, alpha, 0)


def run(repo):
    os.makedirs(os.path.join(repo, OUT_DIR), exist_ok=True)
    all_metrics = []

    for scene, paths in SCENES.items():
        print(f"\n=== {scene} ===")
        mask_bgr = cv2.imread(os.path.join(repo, paths["mask"]))
        source_bgr = cv2.imread(os.path.join(repo, paths["plate"]))

        t0 = time.time()
        fp = derive_morph_footprints(mask_bgr)
        fp_time = time.time() - t0

        walk = derive_morph_walk(mask_bgr)
        walk_time = time.time() - t0 - fp_time

        cv2.imwrite(os.path.join(repo, OUT_DIR, f"morph-baseline-{scene}-mask.png"), fp)
        on_src_fp = overlay_on_source(source_bgr, fp, color=(0, 0, 255), alpha=0.5)
        cv2.imwrite(os.path.join(repo, OUT_DIR, f"morph-baseline-{scene}-on-source.jpg"), on_src_fp)

        cv2.imwrite(os.path.join(repo, OUT_DIR, f"morph-walk-{scene}-mask.png"), walk)
        on_src_walk = overlay_on_source(source_bgr, walk, color=(0, 255, 0), alpha=0.4)
        cv2.imwrite(os.path.join(repo, OUT_DIR, f"morph-walk-{scene}-on-source.jpg"), on_src_walk)

        fp_frac = np.mean(fp > 127)
        walk_frac = np.mean(walk > 127)
        print(f"  footprint: {fp_frac*100:.1f}% of image, time={fp_time:.2f}s")
        print(f"  walk: {walk_frac*100:.1f}% of image, time={walk_time:.2f}s")

        metrics_fp = {
            "method": "morph-baseline",
            "scene": scene,
            "runtime_s": round(fp_time, 3),
            "notes": (
                f"Morphological footprints from NBP class mask. "
                f"Non-floor components: base band (30% height) near floor "
                f"(distance transform < max(20, 10% height)). "
                f"Coverage: {fp_frac*100:.1f}%."
            ),
        }
        with open(os.path.join(repo, OUT_DIR, f"morph-baseline-{scene}-metrics.json"), "w") as f:
            json.dump(metrics_fp, f, indent=2)
        all_metrics.append(metrics_fp)

        metrics_walk = {
            "method": "morph-walk",
            "scene": scene,
            "runtime_s": round(walk_time, 3),
            "notes": (
                f"Walkability from NBP class mask floor class + morphological close. "
                f"Coverage: {walk_frac*100:.1f}%."
            ),
        }
        with open(os.path.join(repo, OUT_DIR, f"morph-walk-{scene}-metrics.json"), "w") as f:
            json.dump(metrics_walk, f, indent=2)
        all_metrics.append(metrics_walk)

    return all_metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()
    run(args.repo)
