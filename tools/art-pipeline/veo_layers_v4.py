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
from scipy import stats as scipy_stats

import occprobe2_run as o2
import veo_z as vz

ROOT = o2.ROOT
ROOM = 'night-bazaar'
MAG = np.array([255, 0, 255], np.int16)
KEY_R = 90
MIN_VOTE_PX = 60
STATIC_T = 40
MIN_EVID = 3 * MIN_VOTE_PX   # base evidence gate (see opportunity scaling)
MIN_EVID_FLOOR, MIN_EVID_CAP = 90, 450   # opportunity-scaled bounds (math panel)
EVID_ALPHA = 0.10            # min_evid = alpha * sqrt(part_area) * walker_width
SIDE_MARGIN = 10             # kept for probe-path guidance docs
SOFT_MARGIN_CORE = 3.0       # hard-zero zone; soft ramp beyond (math panel #5)
BOUNDARY_GUARD = 3           # px: under-votes within this of a part edge are
                             # registration bleed, not evidence (dev finding)
MIN_BUCKET_FRAMES = 3        # temporal consensus: a vote bucket counts only
                             # with >=3 distinct frames (no single frame may
                             # classify a part — math panel, dev finding)
FRAME_STRIDE = 2             # sample every Nth frame; must be small enough
                             # that one genuine crossing yields >=3 samples
FEET_SIGMA_FRAC = 0.12       # feet uncertainty ~ boot height ~12% of walker
MIN_WALKER_PX, MAX_WALKER_PX = 120, 30000   # keyed-component size gate: the
# chroma contract means ONLY the suit can key, so the floor is set by far-
# depth perspective walkers (~10x23px), not by false-positive suppression
DEPTH_AWARE_MIN_SAMPLES = 8   # minimum (feet_y, height) pairs for a valid fit
DEPTH_AWARE_MIN_SLOPE = 0.02  # minimum |slope| before falling back to constant
DEPTH_AWARE_TRUNC_FRAC = 0.85 # silhouette/expected fraction below which truncation kicks in

# the layer vocabulary — rendering BEHAVIORS, shared with synth_layers_bench
GROUND, YSORT, OVERHEAD = 'ground', 'ysort', 'overhead'
COLLISION, COLLISION_PRIOR = 'collision', 'collision-prior'
FRONT, BEHIND = 'front', 'behind'

COL_MAP = {GROUND: (255, 80, 255), COLLISION: (255, 150, 40),
           COLLISION_PRIOR: (150, 150, 150), OVERHEAD: (80, 160, 255),
           YSORT: (60, 220, 120)}


def classify(v, blocks_pid, passes_through, min_evid=MIN_EVID):
    """One part's layer from its feet-conditioned vote counts.

    min_evid is opportunity-scaled per part (math panel #2): a tiny decal and
    a wall-sized part must not share one absolute pixel threshold."""
    of, ob = v['occ_front'], v['occ_behind']
    uf, ub = v['under_front'], v['under_behind']
    if of + ob + uf + ub == 0:
        return COLLISION if (blocks_pid and not passes_through) else COLLISION_PRIOR
    if of >= min_evid:
        # a standing object can NEVER occlude a walker in front of it —
        # solid occ_front is the unambiguous suspended signature
        return OVERHEAD
    ground_dom = 4 if blocks_pid else 2   # a blocking footprint is a strong
    if ub >= min_evid * (2 if blocks_pid else 1) and ub > ground_dom * (of + ob):
        return GROUND                     # prior — overriding it needs more
    if ob >= min_evid or (uf >= min_evid and ob > 0):
        return YSORT
    if uf >= min_evid:
        # front-only walkover is consistent with ground AND y-sort;
        # the collision prior decides (a non-blocker you walk over = ground)
        return YSORT if blocks_pid else GROUND
    return COLLISION if (blocks_pid and not passes_through) else COLLISION_PRIOR


DBG_PAD = 130                # crop margin around the walker in debug strips
DBG_CASES = ('occ-front', 'occ-behind')
TRACK_LINK_R = 80            # video px: feet within this radius join a track
TRACE_COLORS = [(255, 230, 60), (80, 255, 120), (90, 200, 255), (255, 120, 60),
                (230, 100, 255), (140, 255, 230)]


def _write_debug_strips(out_prefix, it, case, obs, view_wh):
    """Emit the 4-stage debugger strip for one tracked observation, straight
    from the estimator's own internal state (Ivan: artifacts must be rendered
    DURING algorithm iteration, not reconstructed after the fact)."""
    vw, vh = view_wh
    frame, keyed, occ = obs['frame'], obs['keyed'], obs['occ']
    x0, y0, x1, y1, feet_y, h_est, fx = obs['geom']
    cx0, cy0 = max(0, x0 - DBG_PAD), max(0, y0 - DBG_PAD)
    cx1, cy1 = min(vw, x1 + DBG_PAD), min(vh, y1 + DBG_PAD + 30)
    def crop(im):
        return im[cy0:cy1, cx0:cx1]
    base = f'{out_prefix}-iter{it}-dbg-{case}'
    cv2.imwrite(f'{base}-1frame.png', crop(frame))
    s2 = frame.copy()
    s2[keyed] = (0, 255, 0)
    cv2.imwrite(f'{base}-2keyed.png', crop(s2))
    s3 = frame.copy()
    cv2.rectangle(s3, (x0 - 2, feet_y - h_est), (x1 + 2, feet_y), (0, 255, 255), 2)
    cv2.circle(s3, (int(fx), feet_y), 5, (0, 0, 255), -1)
    cv2.imwrite(f'{base}-3box.png', crop(s3))
    s4 = frame.copy()
    s4[occ] = (0, 0, 255)
    cv2.imwrite(f'{base}-4occ.png', crop(s4))


def estimate(parts, ground, coll, plate_bgr, video_paths, out_prefix, view_wh=(1200, 675)):
    """Run the estimator. parts: int32 id map (plate space). ground: bool
    walkable mask. coll: bool (True = walkable) at parts resolution.
    plate_bgr: BGR plate. video_paths: list of mp4s (one iteration each).
    Writes <out_prefix>-iterN.jpg + <out_prefix>.json, plus per-iteration
    4-stage debugger strips (<out_prefix>-iterN-dbg-<case>-<stage>.png) for
    the strongest occ-front and occ-behind observations, rendered from the
    algorithm's live state at vote time; returns the result."""
    vw, vh = view_wh
    plate_small = cv2.resize(plate_bgr, (1200, 900))
    sx, sy = plate_bgr.shape[1] / 1200, plate_bgr.shape[0] / 900
    pids = [int(p) for p in np.unique(parts) if p > 0]
    base_y, blocks, part_area = {}, {}, {}
    for pid in pids:
        m = parts == pid
        base_y[pid] = int(np.nonzero(m)[0].max())
        part_area[pid] = int(m.sum())
        nong = m & ~ground
        # blocks = "has a blocking base": majority of the part's COLUMNS
        # contain blocked pixels. An area-fraction test fails footprint-band
        # objects (a tower blocks only at its base — tiny fraction of a tall
        # sprite, yet it definitely blocks)
        if nong.sum():
            cols = np.unique(np.nonzero(nong)[1])
            blocked = ~coll & nong
            bcols = np.unique(np.nonzero(blocked)[1]) if blocked.any() else []
            blocks[pid] = len(bcols) > 0.5 * len(cols)
        else:
            blocks[pid] = False

    # under-vote boundary guard: suit pixels within BOUNDARY_GUARD px of a
    # part edge are homography-registration bleed — a walker can never truly
    # be drawn over an overhead part, yet 2-3px misregistration makes
    # adjacent suit pixels land inside it and vote 'under'
    pk = np.ones((2 * BOUNDARY_GUARD + 1,) * 2, np.uint8)
    pf = parts.astype(np.float32)
    near_edge = (cv2.dilate(pf, pk) != cv2.erode(pf, pk))
    V = {p: {'occ_front': 0, 'occ_behind': 0, 'under_front': 0, 'under_behind': 0}
         for p in pids}
    F = {p: {'occ_front': set(), 'occ_behind': set(),
             'under_front': set(), 'under_behind': set()} for p in pids}
    feet_hits = {p: 0 for p in pids}
    # mixed-geometry self-diagnosis: a part whose mask spans far more than a
    # walker height (e.g. one segment covering lanterns AND aisle ground) has
    # no meaningful base anchor — the tool must SAY it cannot infer there
    # rather than emit a confident wrong answer (Ivan: foolproof means
    # knowing your own limits)
    part_vspan = {}
    ground_frac = {}
    for pid in pids:
        m_ = parts == pid
        ys_ = np.nonzero(m_)[0]
        part_vspan[pid] = int(ys_.max() - ys_.min())
        ground_frac[pid] = float(ground[m_].mean())

    # footprint-band evidence (Ivan's tower case): a walker occluded from
    # BEHIND a part at feet row Y proves row Y is walkable behind it. The
    # band top is a robust QUANTILE of these rows, not the raw max — a single
    # noisy feet reconstruction must not shrink the blocking band (math #4)
    behind_rows = {p: [] for p in pids}
    walker_widths = []      # video px, for opportunity-scaled thresholds
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

        # pass 1: build walker height model — either depth-aware h(feet_y)
        # or constant h_est depending on whether a robust linear fit succeeds.
        # Under perspective, walker height varies with screen-space depth
        # (near camera = tall, far = short). The constant model uses p90 of
        # all observed heights; the depth-aware model fits h(y) = slope*y + intercept
        # from (feet_y, height) pairs sampled from unoccluded frames.
        height_samples = []   # (feet_y, height) pairs
        for fi in range(0, len(frames), FRAME_STRIDE):
            for comp in walker_groups(frames[fi])[0]:
                ys, xs_ = np.nonzero(comp)
                h = int(ys.max() - ys.min())
                feet_y_sample = int(ys.max())
                height_samples.append((feet_y_sample, h))
                walker_widths.append(int(xs_.max() - xs_.min()))
        if not height_samples:
            records.append({'iteration': it, 'video': os.path.basename(mp4),
                            'skipped': 'no walker found'})
            continue
        all_heights = [s[1] for s in height_samples]
        h_est_const = int(np.percentile(all_heights, 90))

        # depth-aware fit on the UPPER ENVELOPE: per feet-row bin maxima.
        # Occlusion can only SHORTEN a silhouette, i.e. push samples below
        # the envelope — a p70 height filter biased the slope to half its
        # true value and let occlusion runs fake negative slopes (calibration
        # test vs the 3D camera's known horizon caught both)
        use_depth_aware = False
        h_slope = 0.0
        h_intercept = float(h_est_const)
        bins = {}
        for fy_, h_ in height_samples:
            b_ = fy_ // 20
            if h_ > bins.get(b_, (0, 0))[1]:
                bins[b_] = (fy_, h_)
        env = list(bins.values())
        if len(env) >= DEPTH_AWARE_MIN_SAMPLES:
            fy_arr = np.array([e[0] for e in env], np.float64)
            h_arr = np.array([e[1] for e in env], np.float64)
            if fy_arr.max() - fy_arr.min() > 30:
                ts = scipy_stats.theilslopes(h_arr, fy_arr)
                h_slope, h_intercept = float(ts[0]), float(ts[1])
                # physical gates: under any real camera over a ground plane,
                # height GROWS toward the viewer (slope > 0) and h(y) = 0 at
                # the horizon, which must lie ABOVE the observed walk area
                horizon_row = -h_intercept / h_slope if abs(h_slope) > 1e-6 else None
                # fit-quality gate: a true perspective envelope LIES on the
                # line; frame-edge partial silhouettes fill bins with junk
                # that fits badly (real-footage calibration finding)
                resid = np.abs(h_arr - (h_slope * fy_arr + h_intercept))
                tol = max(4.0, 0.08 * h_est_const)
                fit_ok = float((resid <= tol).mean()) >= 0.7
                plausible = (h_slope >= DEPTH_AWARE_MIN_SLOPE and
                             horizon_row is not None and
                             horizon_row < fy_arr.min() - 10 and fit_ok)
                if plausible:
                    use_depth_aware = True
                else:
                    h_slope, h_intercept = 0.0, float(h_est_const)

        def expected_height(feet_y_pos):
            """Walker height expected at a given screen-space feet position."""
            if use_depth_aware:
                return max(10, int(h_slope * feet_y_pos + h_intercept))
            return h_est_const

        h_est = h_est_const  # backward compat for debug strips

        # pass 2: feet-conditioned votes with truncation-aware occlusion
        dbg_best = {c: {'score': 0} for c in DBG_CASES}
        feet_obs = []   # (frame_idx, fx_video, feety_video, fpx_plate, fpy_plate)
        prev_feet = []  # per-track last feet (video px) for displacement weights
        for fi in range(0, len(frames), FRAME_STRIDE):
            groups, keyed_all = walker_groups(frames[fi])
            static = np.abs(frames[fi].astype(np.int16) - bg).max(axis=2) < STATIC_T
            occluder = static & partsmask_v & ~keyed_all
            for comp in groups:
                ys, xs = np.nonzero(comp)
                x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
                if x0 <= 2 or x1 >= vw - 3 or y1 >= vh - 3:
                    # walker clipped by the FRAME edge: the short silhouette
                    # is not occlusion — reconstruction here blamed innocent
                    # parts near the border (bazaar mat false positives)
                    continue
                h_vis = y1 - y0
                # depth-aware expected height at this screen position;
                # uses the linear model when perspective is significant,
                # falls back to the constant p90 model otherwise
                h_exp = expected_height(y1)
                trunc_below = trunc_above = False
                if h_vis >= DEPTH_AWARE_TRUNC_FRAC * h_exp:
                    feet_y = y1
                else:
                    probe = max(8, h_exp // 3)   # algo panel: 8px missed gaps
                    below = occluder[y1 + 1:y1 + 1 + probe, x0:x1 + 1].sum()
                    above = occluder[max(0, y0 - probe):y0, x0:x1 + 1].sum()
                    if below == 0 and above == 0:
                        # no adjacent occluder found: default to the SAFE
                        # anchor (visible bottom), never reconstruct blindly
                        feet_y = y1
                    elif below >= above:
                        # evaluate h at the RECONSTRUCTED feet, not the visible
                        # bottom — one fixed-point step (cv panel #1 bootstrap)
                        h_exp = expected_height(y0 + h_exp)
                        feet_y, trunc_below = y0 + h_exp, True
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
                        occ[max(0, feet_y - h_exp):col.min(), cx_] = True
                occ &= occluder

                fp2 = cv2.perspectiveTransform(
                    np.float32([[[fx, float(feet_y)]]]), H).reshape(2)
                fpy = int(np.clip(fp2[1] * sy, 0, parts.shape[0] - 1))
                fpx = int(np.clip(fp2[0] * sx, 0, parts.shape[1] - 1))
                feet_obs.append((fi, fx, float(feet_y), fpx, fpy))
                # displacement weight: consecutive observations of a dwelling
                # walker are NOT independent evidence (math panel #1) — weight
                # by feet displacement since the last observation of this track
                disp = None
                best_j = None
                for j, (pfx, pfy) in enumerate(prev_feet):
                    d = ((fx - pfx) ** 2 + (feet_y - pfy) ** 2) ** 0.5
                    if d < TRACK_LINK_R and (disp is None or d < disp):
                        disp, best_j = d, j
                if best_j is None:
                    prev_feet.append([fx, feet_y])
                    w_disp = 1.0
                else:
                    w_disp = min(1.0, disp / max(1.0, 0.5 * h_exp))
                    prev_feet[best_j] = [fx, feet_y]
                pid_at_feet = int(parts[fpy, fpx])
                if pid_at_feet > 0 and not ground[fpy, fpx]:
                    feet_hits[pid_at_feet] += 1
                    # feet INSIDE the part's mask above its base = that row
                    # is walkable behind/through it (tower-shaft case)
                    if fpy < base_y[pid_at_feet] - SIDE_MARGIN:
                        behind_rows[pid_at_feet].append(fpy)
                occ_px_by_side = {FRONT: 0, BEHIND: 0}
                for kind, m in (('under', comp), ('occ', occ)):
                    yy, xx = np.nonzero(m)
                    if not len(yy):
                        continue
                    pts = cv2.perspectiveTransform(
                        np.float32(np.stack([xx, yy], 1)).reshape(-1, 1, 2), H).reshape(-1, 2)
                    px = np.clip((pts[:, 0] * sx).astype(int), 0, parts.shape[1] - 1)
                    py = np.clip((pts[:, 1] * sy).astype(int), 0, parts.shape[0] - 1)
                    if kind == 'under':
                        keep = ~near_edge[py, px]
                        if not keep.any():
                            continue
                        px, py = px[keep], py[keep]
                    ids, cts = np.unique(parts[py, px], return_counts=True)
                    for pid, ct in zip(ids, cts):
                        pid = int(pid)
                        if pid <= 0 or ct < MIN_VOTE_PX:
                            continue
                        # soft base margin (math panel #5): hard-zero only in
                        # the 3px core, linear ramp scaled to part size
                        sigma_base = max(5.0, 0.01 * part_area[pid] ** 0.5,
                                         FEET_SIGMA_FRAC * h_exp * sy)
                        w_side = min(1.0, max(
                            0.0, (abs(fpy - base_y[pid]) - SOFT_MARGIN_CORE) / sigma_base))
                        if w_side <= 0.0:
                            continue
                        side = FRONT if fpy > base_y[pid] else BEHIND
                        if os.environ.get('V4_DEBUG_PID') == str(pid):
                            print(f'DBG pid={pid} it={it} fi={fi} {kind}_{side} '
                                  f'ct={ct} fpy={fpy} base={base_y[pid]} '
                                  f'wd={w_disp:.2f} ws={w_side:.2f} feet_v={feet_y}')
                        V[pid][f'{kind}_{side}'] += int(ct * w_disp * w_side)
                        F[pid][f'{kind}_{side}'].add((it, fi))
                        if kind == 'occ':
                            occ_px_by_side[side] += int(ct)
                            if side == BEHIND:
                                # occluded from behind at feet row fpy: the
                                # blocking base band starts below this row
                                behind_rows[pid].append(fpy)
                # track the strongest observation per debug case AT VOTE TIME
                for case, side in zip(DBG_CASES, (FRONT, BEHIND)):
                    if occ_px_by_side[side] > dbg_best[case]['score']:
                        dbg_best[case] = {
                            'score': occ_px_by_side[side], 'fi': fi,
                            'frame': frames[fi].copy(), 'keyed': keyed_all.copy(),
                            'comp': comp, 'occ': occ,
                            'geom': (x0, y0, x1, y1, int(feet_y), h_exp, fx)}

        dbg_meta = {}
        for case in DBG_CASES:
            if dbg_best[case]['score'] > 0:
                _write_debug_strips(out_prefix, it, case, dbg_best[case], (vw, vh))
                dbg_meta[case] = {'frame': dbg_best[case]['fi'],
                                  'occ_px': dbg_best[case]['score']}
        med_w_plate = (np.median(walker_widths) * sx) if walker_widths else 30.0
        def min_evid_for(pid):
            return float(np.clip(EVID_ALPHA * part_area[pid] ** 0.5 * med_w_plate,
                                 MIN_EVID_FLOOR, MIN_EVID_CAP))
        def consensus_votes(pid):
            # temporal consensus: buckets fed by fewer than MIN_BUCKET_FRAMES
            # distinct frames are treated as noise. occ_front is EXEMPT: it is
            # the axiom-bearing bucket (a standing object can never occlude a
            # walker in front) and is already quadruple-gated (chroma key,
            # static background, parts mask, boundary guard) — zeroing it let
            # suspended objects with behind-side occlusion masquerade as ysort
            return {b: (V[pid][b] if b == 'occ_front'
                        or len(F[pid][b]) >= MIN_BUCKET_FRAMES else 0)
                    for b in V[pid]}
        layers = {pid: classify(consensus_votes(pid), blocks[pid],
                                feet_hits[pid] >= 3, min_evid_for(pid))
                  for pid in pids}
        prev = records[-1].get('layers', {}) if records else {}
        changes = [f'part{p}: {prev[str(p)]} -> {l}' for p, l in layers.items()
                   if prev.get(str(p)) not in (None, l)]
        counts = {}
        for l in layers.values():
            counts[l] = counts.get(l, 0) + 1
        # link feet observations into per-walker tracks (Ivan: trace the
        # feet of each character on the board maps)
        tracks = []          # each: list of (frame, fpx_plate, fpy_plate)
        open_tracks = []     # (last_frame, last_fx_video, last_fy_video, points)
        for fi_, fx_, fy_, fpx_, fpy_ in feet_obs:
            best_t, best_d = None, TRACK_LINK_R
            for t in open_tracks:
                if fi_ - t[0] > 16:
                    continue
                d = ((fx_ - t[1]) ** 2 + (fy_ - t[2]) ** 2) ** 0.5
                if d < best_d:
                    best_t, best_d = t, d
            if best_t is None:
                best_t = [fi_, fx_, fy_, []]
                open_tracks.append(best_t)
            best_t[0], best_t[1], best_t[2] = fi_, fx_, fy_
            best_t[3].append((fi_, fpx_, fpy_))
        # keep ALL fragments for the trace visualization — occlusion and
        # far-depth size dropouts fragment tracks, and discarding short
        # fragments hid whole walk segments from the board maps
        tracks = [t[3] for t in open_tracks if len(t[3]) >= 2]
        dots = [t[3][0] for t in open_tracks if len(t[3]) == 1]

        b = plate_bgr[:, :, ::-1].astype(np.float32) * 0.30
        b[ground] = b[ground] * 0.55 + np.array((255, 80, 255), np.float32) * 0.225
        for pid in pids:
            m = parts == pid   # paint the full part: class color wins over ground tint
            b[m] = b[m] * 0.35 + np.array(COL_MAP[layers[pid]], np.float32) * 0.65
        arr = b.clip(0, 255).astype(np.uint8)
        tracks.sort(key=lambda tr: tr[0][0])
        for ti, tr in enumerate(tracks):
            col = TRACE_COLORS[ti % len(TRACE_COLORS)]
            pts = np.array([(p[1], p[2]) for p in tr], np.int32).reshape(-1, 1, 2)
            cv2.polylines(arr, [pts], False, col, 3)
            for _, px_, py_ in tr:
                cv2.circle(arr, (px_, py_), 4, col, -1)
            cv2.circle(arr, (tr[0][1], tr[0][2]), 9, col, 2)          # start ring
            cv2.circle(arr, (tr[-1][1], tr[-1][2]), 9, (255, 255, 255), 2)  # end
            # dashed bridge to the next fragment: the walker was hidden
            # (occluded or below the far-depth size floor) between the two
            if ti + 1 < len(tracks):
                nxt = tracks[ti + 1]
                a = np.array([tr[-1][1], tr[-1][2]], float)
                bpt = np.array([nxt[0][1], nxt[0][2]], float)
                d = np.linalg.norm(bpt - a)
                if 0 < d < 500:
                    n_seg = max(2, int(d / 18))
                    for k in range(0, n_seg, 2):
                        p0 = a + (bpt - a) * k / n_seg
                        p1 = a + (bpt - a) * min(1, (k + 1) / n_seg)
                        cv2.line(arr, tuple(p0.astype(int)), tuple(p1.astype(int)),
                                 col, 1, cv2.LINE_AA)
        for _, px_, py_ in dots:
            cv2.circle(arr, (px_, py_), 4, (255, 255, 255), -1)
        img = Image.fromarray(arr)
        img.thumbnail((1400, 1400))
        img.save(f'{out_prefix}-iter{it}.jpg', quality=86)
        records.append({'iteration': it, 'video': os.path.basename(mp4),
                        'projection': {'depth_aware': use_depth_aware,
                                       'height_slope': round(h_slope, 4),
                                       'h_const': h_est_const},
                        'counts': counts, 'changes': changes[:14], 'debug': dbg_meta,
                        'tracks': [[(int(f), int(x), int(y)) for f, x, y in tr]
                                   for tr in tracks],
                        'layers': {str(k): v for k, v in layers.items()}})
        print(f'iter {it}: {counts}, {len(changes)} changes, {len(tracks)} feet tracks')

    # footprint-band estimate (tower case): robust adaptive quantile of the
    # behind-feet rows — approaches the max as observations grow but stays
    # bounded away from single outliers (math panel #4)
    # under-blocking is UNSAFE (players clip into bases) while over-blocking
    # is invisible — so the aggregate leans conservative: fewer than 5
    # observations yields NO estimate (sparse evidence can be falsified by
    # probes that ignore collision, e.g. Veo walkers), else the 25th
    # percentile of behind-rows (3D-bench finding: the adaptive ~p80 quantile
    # under-blocked bimodal shallow+deep observation mixes)
    footprint_top = {}
    for p in pids:
        obs = sorted(behind_rows[p])
        if len(obs) < 5:
            footprint_top[str(p)] = None
        else:
            footprint_top[str(p)] = int(np.percentile(obs, 25)) + 1
    # walker height in plate px ~ 2x median keyed width (suit aspect ~0.5)
    walker_h_plate = float(np.median(walker_widths) * 2.0 * sy) if walker_widths else 90.0
    unreliable = {str(p): 'mixed-geometry (span %.1fx walker height)' % (
                      part_vspan[p] / walker_h_plate)
                  for p in pids if part_vspan[p] > 2.5 * walker_h_plate}
    result = {'votes': {str(p): V[p] for p in pids},
              'base_y': {str(p): base_y[p] for p in pids},
              'unreliable': unreliable,
              'footprint_top': footprint_top,
              'behind_rows': {str(p): sorted(behind_rows[p])[-40:] for p in pids
                              if behind_rows[p]},
              'iterations': records}
    json.dump(result, open(f'{out_prefix}.json', 'w'), indent=1)
    return result


def main():
    """Run the estimator on the default ROOM's production magenta-walker videos."""
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
