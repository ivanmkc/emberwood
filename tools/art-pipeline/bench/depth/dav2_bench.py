"""Depth Anything V2 benchmark for walkability + footprint masks.

Runs DAv2-Small via HuggingFace transformers pipeline on 3 scenes.
Derives two masks per scene:
  davi2-walk:      floor-plane walkability (pixels consistent with ground depth ramp)
  davi2-footprint: above-plane object footprints projected down as base bands

Usage:
  python dav2_bench.py --repo /path/to/emberwood
"""
import argparse
import json
import os
import time

import cv2
import numpy as np
from PIL import Image

SCENES = {
    "anchorroom": "docs/art-options/nbp-scifi-anchor-clean.png",
    "night-bazaar": "docs/art-options/rooms/night-bazaar/plate.png",
    "plaza-market-inside": "docs/art-options/rooms/plaza-market-inside/plate.png",
}

COLLISION_MASKS = {
    "anchorroom": "assets/rooms/anchorroom.collision.png",
    "night-bazaar": "assets/rooms/night-bazaar.collision.png",
    "plaza-market-inside": "assets/rooms/plaza-market-inside.collision.png",
}

OUT_DIR = "docs/art-options/bench/depth"


def load_depth_pipeline():
    from transformers import pipeline
    return pipeline(
        "depth-estimation",
        model="depth-anything/Depth-Anything-V2-Small-hf",
        device="cpu",
    )


def get_depth_map(pipe, img_pil):
    result = pipe(img_pil)
    depth = np.array(result["depth"])
    if depth.dtype == np.uint8:
        depth = depth.astype(np.float32)
    elif depth.dtype == np.uint16:
        depth = depth.astype(np.float32) / 256.0
    else:
        depth = depth.astype(np.float32)
    if depth.max() > depth.min():
        depth = (depth - depth.min()) / (depth.max() - depth.min())
    return depth


def derive_walk_mask(depth, collision_path, repo):
    """Floor-plane walkability from depth.

    Under the fixed axis-aligned 3/4 camera, the ground plane produces a
    smooth depth ramp: depth increases roughly linearly with y (things
    further from the camera = higher y = larger depth).  We fit a linear
    model depth ~ a*y + b over known-floor samples (taken from the shipped
    walk mask's largest walkable region), then threshold residuals using
    the MAD (median absolute deviation) of floor residuals.
    """
    h, w = depth.shape

    floor_samples = _get_floor_samples(collision_path, repo, h, w)
    if floor_samples is None or len(floor_samples) < 100:
        y_coords = np.arange(h).reshape(-1, 1).repeat(w, axis=1)
        floor_samples = np.column_stack([
            y_coords.ravel(),
            depth.ravel(),
            np.tile(np.arange(w), h),
        ])

    ys = floor_samples[:, 0].astype(np.float64)
    xs = floor_samples[:, 2].astype(np.float64)
    ds_vals = np.array([depth[int(y), int(x)] for y, x in zip(ys, xs)], dtype=np.float64)

    a, b = np.polyfit(ys, ds_vals, 1)

    y_grid = np.arange(h, dtype=np.float64).reshape(-1, 1).repeat(w, axis=1)
    expected = a * y_grid + b
    residual = np.abs(depth.astype(np.float64) - expected)

    floor_residuals = np.array([residual[int(y), int(x)]
                                for y, x in zip(ys, xs)])
    mad = np.median(np.abs(floor_residuals - np.median(floor_residuals)))
    threshold = np.median(floor_residuals) + 2.5 * max(mad, 0.01)

    walk = (residual < threshold).astype(np.uint8) * 255
    return walk


def _get_floor_samples(collision_path, repo, target_h, target_w):
    """Extract floor pixel coords from the shipped collision mask."""
    cpath = os.path.join(repo, collision_path)
    if not os.path.exists(cpath):
        return None
    cmask = cv2.imread(cpath, cv2.IMREAD_GRAYSCALE)
    if cmask is None:
        return None
    cmask = cv2.resize(cmask, (target_w, target_h), interpolation=cv2.INTER_NEAREST)
    walkable = cmask > 127

    nlabels, labels, stats, _ = cv2.connectedComponentsWithStats(
        walkable.astype(np.uint8), connectivity=8
    )
    if nlabels < 2:
        return None
    largest = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
    floor_ys, floor_xs = np.where(labels == largest)

    if len(floor_ys) > 50000:
        idx = np.random.default_rng(42).choice(len(floor_ys), 50000, replace=False)
        floor_ys = floor_ys[idx]
        floor_xs = floor_xs[idx]

    return np.column_stack([floor_ys, np.zeros(len(floor_ys)), floor_xs])


def derive_footprint_mask(depth, walk_mask):
    """Object footprints: above-plane blobs projected down as base bands.

    For each connected above-plane component (not on the walk mask),
    compute its bounding box and project a footprint band:
      footprint band y-range = [yBase - k*height, yBase]
    where yBase = bottom of the blob and k controls the depth factor.
    """
    h, w = depth.shape
    above_plane = (walk_mask < 128).astype(np.uint8)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    above_plane = cv2.morphologyEx(above_plane, cv2.MORPH_CLOSE, kernel)
    above_plane = cv2.morphologyEx(above_plane, cv2.MORPH_OPEN, kernel)

    nlabels, labels, stats, _ = cv2.connectedComponentsWithStats(
        above_plane, connectivity=8
    )

    footprint = np.zeros((h, w), dtype=np.uint8)
    k = 0.25

    for i in range(1, nlabels):
        area = stats[i, cv2.CC_STAT_AREA]
        if area < 200:
            continue
        x0 = stats[i, cv2.CC_STAT_LEFT]
        y0 = stats[i, cv2.CC_STAT_TOP]
        bw = stats[i, cv2.CC_STAT_WIDTH]
        bh = stats[i, cv2.CC_STAT_HEIGHT]

        y_base = y0 + bh
        band_height = max(int(k * bh), 8)
        y_top = max(0, y_base - band_height)

        footprint[y_top:min(y_base, h), x0:x0 + bw] = 255

    return footprint


def overlay_on_source(source_img, mask, color=(0, 255, 0), alpha=0.4):
    """Overlay a binary mask on the source image."""
    vis = np.array(source_img).copy()
    if vis.ndim == 2:
        vis = cv2.cvtColor(vis, cv2.COLOR_GRAY2BGR)
    elif vis.shape[2] == 4:
        vis = vis[:, :, :3]
    mask_bool = mask > 127
    overlay = vis.copy()
    overlay[mask_bool] = color
    return cv2.addWeighted(vis, 1 - alpha, overlay, alpha, 0)


def run(repo):
    pipe = load_depth_pipeline()
    os.makedirs(os.path.join(repo, OUT_DIR), exist_ok=True)

    all_metrics = []

    for scene, rel_path in SCENES.items():
        print(f"\n=== {scene} ===")
        img_path = os.path.join(repo, rel_path)
        img_pil = Image.open(img_path).convert("RGB")
        source_np = np.array(img_pil)

        t0 = time.time()
        depth = get_depth_map(pipe, img_pil)
        depth_time = time.time() - t0
        print(f"  depth inference: {depth_time:.1f}s, shape={depth.shape}")

        depth_vis = (depth * 255).astype(np.uint8)
        cv2.imwrite(
            os.path.join(repo, OUT_DIR, f"davi2-{scene}-depth.png"),
            depth_vis,
        )

        t1 = time.time()
        walk = derive_walk_mask(depth, COLLISION_MASKS[scene], repo)
        walk_time = time.time() - t1

        walk_resized = cv2.resize(walk, (source_np.shape[1], source_np.shape[0]),
                                   interpolation=cv2.INTER_NEAREST)
        cv2.imwrite(
            os.path.join(repo, OUT_DIR, f"davi2-walk-{scene}-mask.png"),
            walk_resized,
        )
        on_source = overlay_on_source(source_np, walk_resized, color=(0, 255, 0))
        cv2.imwrite(
            os.path.join(repo, OUT_DIR, f"davi2-walk-{scene}-on-source.jpg"),
            cv2.cvtColor(on_source, cv2.COLOR_RGB2BGR),
        )
        metrics_walk = {
            "method": "davi2-walk",
            "scene": scene,
            "runtime_s": round(depth_time + walk_time, 2),
            "notes": (
                f"DAv2-Small CPU inference {depth_time:.1f}s + ramp fit {walk_time:.1f}s. "
                f"Linear depth~y ramp fitted over shipped collision mask floor samples, "
                f"residual threshold at 1.5x P90 of floor residuals."
            ),
        }
        with open(os.path.join(repo, OUT_DIR, f"davi2-walk-{scene}-metrics.json"), "w") as f:
            json.dump(metrics_walk, f, indent=2)
        all_metrics.append(metrics_walk)
        print(f"  walk mask done ({walk_time:.1f}s)")

        t2 = time.time()
        fp = derive_footprint_mask(depth, walk)
        fp_time = time.time() - t2

        fp_resized = cv2.resize(fp, (source_np.shape[1], source_np.shape[0]),
                                 interpolation=cv2.INTER_NEAREST)
        cv2.imwrite(
            os.path.join(repo, OUT_DIR, f"davi2-footprint-{scene}-mask.png"),
            fp_resized,
        )
        on_source_fp = overlay_on_source(source_np, fp_resized, color=(255, 0, 0))
        cv2.imwrite(
            os.path.join(repo, OUT_DIR, f"davi2-footprint-{scene}-on-source.jpg"),
            cv2.cvtColor(on_source_fp, cv2.COLOR_RGB2BGR),
        )
        metrics_fp = {
            "method": "davi2-footprint",
            "scene": scene,
            "runtime_s": round(depth_time + fp_time, 2),
            "notes": (
                f"DAv2-Small + above-plane blob projection (k=0.25 height). "
                f"Connected components on non-walk regions, footprint = base band."
            ),
        }
        with open(os.path.join(repo, OUT_DIR, f"davi2-footprint-{scene}-metrics.json"), "w") as f:
            json.dump(metrics_fp, f, indent=2)
        all_metrics.append(metrics_fp)
        print(f"  footprint mask done ({fp_time:.1f}s)")

    return all_metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()
    metrics = run(args.repo)
    print("\n--- All metrics ---")
    for m in metrics:
        print(f"  {m['method']} / {m['scene']}: {m['runtime_s']}s")
