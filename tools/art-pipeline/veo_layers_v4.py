#!/usr/bin/env python3
"""Feet-conditioned layer estimator (Ivan: "whether something occludes
depends on where the character is standing"). Occlusion is relative for
STANDING objects — y-sort by base anchor: character in front (feet south of
base) draws over, behind draws under. Only SUSPENDED objects occlude
regardless of feet position. Every observation is conditioned on walker
feet vs the part's base:

  occ   & feet in FRONT  -> OVERHEAD evidence (occludes even from in front)
  occ   & feet BEHIND    -> Y-SORT evidence (normal standing occluder)
  under & feet BEHIND    -> GROUND evidence (flat: never occludes)
  under & feet in FRONT  -> weak (consistent with ground AND y-sort)

v3's "conflict" class was the y-sort signature misread as noise. Walkers are
magenta-keyed (non-walker animation cannot vote); occluder holes must match
the static background (smoke in front of the walker cannot vote).

The core is `estimate(...)` so the synthetic vetting bench
(synth_layers_bench.py) runs the IDENTICAL code path on procedurally
generated videos with known ground truth.
"""
import glob
import json
import os

import cv2
import numpy as np
from PIL import Image

import occprobe2_run as o2
import veo_z as vz

ROOT = o2.ROOT
ROOM = 'night-bazaar'
MAG = np.array([255, 0, 255], np.int16)
KEY_R = 90
MIN_VOTE_PX = 60
STATIC_T = 40
MIN_EVID = 3 * MIN_VOTE_PX   # pixels of a vote class before it may classify
SIDE_MARGIN = 10             # plate px: |feet - base| below this = ambiguous
MIN_WALKER_PX, MAX_WALKER_PX = 400, 30000   # keyed-component size gate

# the layer vocabulary — rendering BEHAVIORS, shared with synth_layers_bench
GROUND, YSORT, OVERHEAD = 'ground', 'ysort', 'overhead'
COLLISION, COLLISION_PRIOR = 'collision', 'collision-prior'
FRONT, BEHIND = 'front', 'behind'

COL_MAP = {GROUND: (255, 80, 255), COLLISION: (255, 150, 40),
           COLLISION_PRIOR: (150, 150, 150), OVERHEAD: (80, 160, 255),
           YSORT: (60, 220, 120)}


def classify(v, blocks_pid, passes_through):
    """One part's layer from its feet-conditioned vote counts."""
    of, ob = v['occ_front'], v['occ_behind']
    uf, ub = v['under_front'], v['under_behind']
    if of + ob + uf + ub == 0:
        return COLLISION if (blocks_pid and not passes_through) else COLLISION_PRIOR
    if of >= MIN_EVID:
        # a standing object can NEVER occlude a walker in front of it —
        # solid occ_front is the unambiguous suspended signature
        return OVERHEAD
    if ub >= MIN_EVID and of + ob < MIN_EVID:
        return GROUND
    if ob >= MIN_EVID or (uf >= MIN_EVID and ob > 0):
        return YSORT
    if uf >= MIN_EVID:
        # front-only walkover is consistent with ground AND y-sort;
        # the collision prior decides (a non-blocker you walk over = ground)
        return YSORT if blocks_pid else GROUND
    return COLLISION if (blocks_pid and not passes_through) else COLLISION_PRIOR


def estimate(parts, ground, coll, plate_bgr, video_paths, out_prefix, view_wh=(1200, 675)):
    """Run the estimator. parts: int32 id map (plate space). ground: bool
    walkable mask. coll: bool (True = walkable) at parts resolution.
    plate_bgr: BGR plate. video_paths: list of mp4s (one iteration each).
    Writes <out_prefix>-iterN.jpg + <out_prefix>.json; returns the result."""
    vw, vh = view_wh
    plate_small = cv2.resize(plate_bgr, (1200, 900))
    sx, sy = plate_bgr.shape[1] / 1200, plate_bgr.shape[0] / 900
    pids = [int(p) for p in np.unique(parts) if p > 0]
    base_y, blocks = {}, {}
    for pid in pids:
        m = parts == pid
        base_y[pid] = int(np.nonzero(m)[0].max())
        nong = m & ~ground
        blocks[pid] = bool(nong.sum() and (~coll[nong]).mean() > 0.5)

    V = {p: {'occ_front': 0, 'occ_behind': 0, 'under_front': 0, 'under_behind': 0}
         for p in pids}
    feet_hits = {p: 0 for p in pids}
    records = []
    for it, mp4 in enumerate(video_paths, 1):
        cap = cv2.VideoCapture(mp4)
        frames = []
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            frames.append(cv2.resize(fr, (vw, vh)))
        cap.release()
        bg = np.median(np.stack(frames[::6]), axis=0).astype(np.uint8)
        H, inl = vz.homography(bg, plate_small)
        print(f'iter {it}: inliers {inl}')
        if H is None or inl < 60:
            records.append({'iteration': it, 'video': os.path.basename(mp4),
                            'skipped': f'registration ({inl})'})
            continue
        # object mask warped into VIDEO space: which pixels belong to any part
        pm_small = cv2.resize((parts > 0).astype(np.uint8),
                              (1200, 900), interpolation=cv2.INTER_NEAREST)
        partsmask_v = cv2.warpPerspective(
            pm_small, H, (vw, vh),
            flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP) > 0

        def walker_groups(frame):
            """Merged walker silhouettes (a wire/pole across the suit splits
            the keyed mask — group nearby components into one walker)."""
            rgb = frame[:, :, ::-1].astype(np.int16)
            keyed = (np.linalg.norm(rgb - MAG, axis=2) < KEY_R).astype(np.uint8)
            keyed = cv2.morphologyEx(keyed, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            merged = cv2.dilate(keyed, np.ones((15, 15), np.uint8))
            n, lab = cv2.connectedComponents(merged)
            groups = []
            for c in range(1, n):
                comp = (lab == c) & (keyed > 0)
                a = int(comp.sum())
                if MIN_WALKER_PX <= a <= MAX_WALKER_PX:
                    groups.append(comp)
            return groups, keyed > 0

        # pass 1: expected walker height = 90th pct of silhouette heights
        heights = []
        for fi in range(0, len(frames), 4):
            for comp in walker_groups(frames[fi])[0]:
                ys = np.nonzero(comp)[0]
                heights.append(int(ys.max() - ys.min()))
        if not heights:
            records.append({'iteration': it, 'video': os.path.basename(mp4),
                            'skipped': 'no walker found'})
            continue
        h_est = int(np.percentile(heights, 90))

        # pass 2: feet-conditioned votes with truncation-aware occlusion
        for fi in range(0, len(frames), 4):
            groups, keyed_all = walker_groups(frames[fi])
            static = np.abs(frames[fi].astype(np.int16) - bg).max(axis=2) < STATIC_T
            occluder = static & partsmask_v & ~keyed_all
            for comp in groups:
                ys, xs = np.nonzero(comp)
                x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
                h_vis = y1 - y0
                # anchor feet at the un-truncated end: if the silhouette is
                # short AND static object pixels sit right below its bottom,
                # the walker is cut off from below -> true feet = top + h_est
                trunc_below = trunc_above = False
                if h_vis >= 0.85 * h_est:
                    feet_y = y1
                else:
                    below = occluder[y1 + 1:y1 + 9, x0:x1 + 1].sum()
                    above = occluder[max(0, y0 - 8):y0, x0:x1 + 1].sum()
                    if below >= above:
                        feet_y, trunc_below = y0 + h_est, True
                    else:
                        feet_y, trunc_above = y1, True
                feet_y = min(feet_y, vh - 1)
                fx = float(np.median(xs[ys >= y1 - 2]))
                # occlusion evidence is PER-COLUMN: interior gaps between the
                # column's keyed pixels, plus the truncated continuation on
                # the cut side — never pixels merely BESIDE the walker
                occ = np.zeros_like(comp)
                for cx_ in range(x0, x1 + 1):
                    col = np.nonzero(comp[:, cx_])[0]
                    if not len(col):
                        continue
                    occ[col.min():col.max() + 1, cx_] = ~comp[col.min():col.max() + 1, cx_]
                    if trunc_below:
                        occ[col.max() + 1:feet_y + 1, cx_] = True
                    if trunc_above:
                        occ[max(0, feet_y - h_est):col.min(), cx_] = True
                occ &= occluder

                fp2 = cv2.perspectiveTransform(
                    np.float32([[[fx, float(feet_y)]]]), H).reshape(2)
                fpy = int(np.clip(fp2[1] * sy, 0, parts.shape[0] - 1))
                fpx = int(np.clip(fp2[0] * sx, 0, parts.shape[1] - 1))
                pid_at_feet = int(parts[fpy, fpx])
                if pid_at_feet > 0 and not ground[fpy, fpx]:
                    feet_hits[pid_at_feet] += 1
                for kind, m in (('under', comp), ('occ', occ)):
                    yy, xx = np.nonzero(m)
                    if not len(yy):
                        continue
                    pts = cv2.perspectiveTransform(
                        np.float32(np.stack([xx, yy], 1)).reshape(-1, 1, 2), H).reshape(-1, 2)
                    px = np.clip((pts[:, 0] * sx).astype(int), 0, parts.shape[1] - 1)
                    py = np.clip((pts[:, 1] * sy).astype(int), 0, parts.shape[0] - 1)
                    ids, cts = np.unique(parts[py, px], return_counts=True)
                    for pid, ct in zip(ids, cts):
                        pid = int(pid)
                        if pid <= 0 or ct < MIN_VOTE_PX:
                            continue
                        if abs(fpy - base_y[pid]) <= SIDE_MARGIN:
                            continue          # too close to the base to judge
                        side = FRONT if fpy > base_y[pid] else BEHIND
                        V[pid][f'{kind}_{side}'] += int(ct)

        layers = {pid: classify(V[pid], blocks[pid], feet_hits[pid] >= 3)
                  for pid in pids}
        prev = records[-1].get('layers', {}) if records else {}
        changes = [f'part{p}: {prev[str(p)]} -> {l}' for p, l in layers.items()
                   if prev.get(str(p)) not in (None, l)]
        counts = {}
        for l in layers.values():
            counts[l] = counts.get(l, 0) + 1
        b = plate_bgr[:, :, ::-1].astype(np.float32) * 0.30
        b[ground] = b[ground] * 0.55 + np.array((255, 80, 255), np.float32) * 0.225
        for pid in pids:
            m = (parts == pid) & ~ground
            b[m] = b[m] * 0.35 + np.array(COL_MAP[layers[pid]], np.float32) * 0.65
        img = Image.fromarray(b.clip(0, 255).astype(np.uint8))
        img.thumbnail((1400, 1400))
        img.save(f'{out_prefix}-iter{it}.jpg', quality=86)
        records.append({'iteration': it, 'video': os.path.basename(mp4),
                        'counts': counts, 'changes': changes[:14],
                        'layers': {str(k): v for k, v in layers.items()}})
        print(f'iter {it}: {counts}, {len(changes)} changes')

    result = {'votes': {str(p): V[p] for p in pids},
              'base_y': {str(p): base_y[p] for p in pids},
              'iterations': records}
    json.dump(result, open(f'{out_prefix}.json', 'w'), indent=1)
    return result


def main():
    parts = np.load(os.path.join(ROOT, f'tools/art-pipeline/_srcmasks_{ROOM}-parts.npz'))['inst']
    ground = np.asarray(Image.open(os.path.join(
        ROOT, f'docs/art-options/magenta-ground-{ROOM}-nowires.png')).convert('L')) > 127
    coll = np.asarray(Image.open(os.path.join(
        ROOT, f'assets/rooms/{ROOM}.collision.png')).convert('L').resize(
        (parts.shape[1], parts.shape[0]), Image.Resampling.NEAREST)) > 127
    plate = cv2.imread(os.path.join(ROOT, f'docs/art-options/rooms/{ROOM}/plate.png'))
    vids = sorted(glob.glob('/home/ivanmkc/.claude/jobs/92f6b395/tmp/veostab/mwalk*_stab.mp4'))
    estimate(parts, ground, coll, plate, vids,
             os.path.join(ROOT, f'docs/art-options/veo-layersv4-{ROOM}'))


if __name__ == '__main__':
    main()
