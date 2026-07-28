"""Evaluate all depth-bench method masks against ground truth.

Computes IoU against:
  1. 5-roll consensus walk mask (if available from lit-bench-prompt)
  2. Shipped collision mask (always available)

Writes per-scene metrics into each method's metrics.json and
produces docs/art-options/bench/depth/summary.json.

Usage:
  python evaluate.py --repo /path/to/emberwood
"""
import argparse
import json
import os

import cv2
import numpy as np

SCENES = ["anchorroom", "night-bazaar", "plaza-market-inside"]

METHODS_WALK = {
    "davi2-walk": "davi2-walk-{scene}-mask.png",
    "morph-walk": "morph-walk-{scene}-mask.png",
}

METHODS_FOOTPRINT = {
    "davi2-footprint": "davi2-footprint-{scene}-mask.png",
    "morph-baseline": "morph-baseline-{scene}-mask.png",
    "niantic-footprints": "niantic-{scene}-mask.png",
}

COLLISION_MASKS = {
    "anchorroom": "assets/rooms/anchorroom.collision.png",
    "night-bazaar": "assets/rooms/night-bazaar.collision.png",
    "plaza-market-inside": "assets/rooms/plaza-market-inside.collision.png",
}

CONSENSUS_MASKS = {
    "anchorroom": "docs/art-options/bench/prompt/anchorroom/consensus-walk.png",
}

BENCH_DIR = "docs/art-options/bench/depth"
PERSP_FILE = "persp-scores.json"


def iou(mask_a, mask_b):
    a = mask_a > 127
    b = mask_b > 127
    inter = np.sum(a & b)
    union = np.sum(a | b)
    return round(inter / union, 4) if union > 0 else 0.0


def precision_recall(pred, gt):
    p = pred > 127
    g = gt > 127
    tp = np.sum(p & g)
    fp = np.sum(p & ~g)
    fn = np.sum(~p & g)
    prec = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0
    rec = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0
    return prec, rec


def load_and_resize(path, target_hw):
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    if img.shape != target_hw:
        img = cv2.resize(img, (target_hw[1], target_hw[0]),
                         interpolation=cv2.INTER_NEAREST)
    return img


def run(repo):
    summary = {"methods": {}, "scenes": {}, "perspective": {}}
    bench_dir = os.path.join(repo, BENCH_DIR)

    for scene in SCENES:
        print(f"\n=== {scene} ===")
        coll_path = os.path.join(repo, COLLISION_MASKS[scene])
        coll = cv2.imread(coll_path, cv2.IMREAD_GRAYSCALE)
        if coll is None:
            print(f"  WARNING: no collision mask at {coll_path}")
            continue
        target_hw = coll.shape

        cons = None
        cons_label = "shipped-collision"
        if scene in CONSENSUS_MASKS:
            cons_path = os.path.join(repo, CONSENSUS_MASKS[scene])
            cons = load_and_resize(cons_path, target_hw)
            if cons is not None:
                cons_label = "5-roll-consensus"

        gt = cons if cons is not None else coll
        scene_results = {"ground_truth": cons_label}

        all_methods = {}
        all_methods.update(METHODS_WALK)
        all_methods.update(METHODS_FOOTPRINT)

        for method, pattern in all_methods.items():
            mask_path = os.path.join(bench_dir, pattern.format(scene=scene))
            if not os.path.exists(mask_path):
                print(f"  {method}: MISSING {mask_path}")
                continue

            pred = load_and_resize(mask_path, target_hw)
            if pred is None:
                continue

            iou_vs_gt = iou(pred, gt)
            iou_vs_coll = iou(pred, coll)
            prec, rec = precision_recall(pred, gt)
            coverage = round(np.mean(pred > 127), 4)

            result = {
                "iou_vs_gt": iou_vs_gt,
                "gt_type": cons_label,
                "iou_vs_collision": iou_vs_coll,
                "precision": prec,
                "recall": rec,
                "coverage": coverage,
            }
            scene_results[method] = result
            print(f"  {method}: IoU={iou_vs_gt:.3f} (vs {cons_label}), "
                  f"IoU_coll={iou_vs_coll:.3f}, P={prec:.3f} R={rec:.3f}")

            metrics_path = os.path.join(bench_dir,
                                         pattern.format(scene=scene)
                                         .replace("-mask.png", "-metrics.json"))
            if os.path.exists(metrics_path):
                with open(metrics_path) as f:
                    m = json.load(f)
                m["iou_vs_gt"] = iou_vs_gt
                m["gt_type"] = cons_label
                m["iou_vs_collision"] = iou_vs_coll
                m["precision"] = prec
                m["recall"] = rec
                with open(metrics_path, "w") as f:
                    json.dump(m, f, indent=2)

        summary["scenes"][scene] = scene_results

    persp_path = os.path.join(bench_dir, PERSP_FILE)
    if os.path.exists(persp_path):
        with open(persp_path) as f:
            summary["perspective"] = json.load(f)

    for method in list(METHODS_WALK) + list(METHODS_FOOTPRINT):
        ious = []
        for scene in SCENES:
            if scene in summary["scenes"] and method in summary["scenes"][scene]:
                ious.append(summary["scenes"][scene][method]["iou_vs_gt"])
        if ious:
            summary["methods"][method] = {
                "mean_iou": round(np.mean(ious), 4),
                "per_scene_iou": {s: summary["scenes"][s].get(method, {}).get("iou_vs_gt")
                                   for s in SCENES},
            }

    niantic_data = {}
    for scene in SCENES:
        m_path = os.path.join(bench_dir, f"niantic-{scene}-metrics.json")
        if os.path.exists(m_path):
            with open(m_path) as f:
                niantic_data[scene] = json.load(f)
    if niantic_data:
        summary["methods"]["niantic-footprints"] = {
            "mean_iou": round(np.mean([
                summary["scenes"].get(s, {}).get("niantic-footprints", {}).get("iou_vs_gt", 0)
                for s in SCENES
            ]), 4),
            "per_scene": niantic_data,
            "verdict": "Catastrophic domain-gap failure on pixel art",
        }

    out_path = os.path.join(bench_dir, "summary.json")
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nWrote {out_path}")

    print("\n=== SUMMARY TABLE ===")
    print(f"{'Method':<25} {'anchor':>10} {'bazaar':>10} {'plaza':>10} {'mean':>10}")
    print("-" * 68)
    for method in summary["methods"]:
        m = summary["methods"][method]
        iou_map = m.get("per_scene_iou", {})
        vals = [iou_map.get(s) if isinstance(iou_map.get(s), (int, float)) else None
                for s in SCENES]
        vals_str = [f"{v:.3f}" if v is not None else "N/A" for v in vals]
        print(f"{method:<25} {vals_str[0]:>10} {vals_str[1]:>10} {vals_str[2]:>10} "
              f"{m['mean_iou']:>10.3f}")

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()
    run(args.repo)
