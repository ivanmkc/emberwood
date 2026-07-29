#!/usr/bin/env python3
"""Evidence-driven part splitting: replay the estimator's evidence-
extraction loop, capture per-part spatial evidence masks, and split parts
whose evidence types are spatially disjoint.

Mixed mega-parts (e.g. part87: lanterns + aisle ground in one mask) defeat
the classifier because their aggregated vote signal mixes overhead and
ysort/ground evidence.  The previous Felzenszwalb approach (split_mixed_
parts.py) split by plate colour — a negative result: 0/17 gold-overhead
sub-parts converted.  This script instead uses the estimator's own
evidence: where occ_front pixels (overhead signature) and occ_behind /
under_behind pixels (ysort/ground signature) land *spatially* within a
part.  If those two clusters are vertically separated, a horizontal cut
produces sub-parts with cleaner per-type evidence.

Team-lead owns veo_layers_v4.py; this script lives in the synth3d agent's
file-ownership space and imports only module-level constants and utilities.
"""
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image
from scipy import stats as scipy_stats

import veo_layers_v4 as v4
import veo_z as vz

ROOM = 'night-bazaar'
TMP = os.environ.get('CLAUDE_JOB_DIR', '/tmp') + '/tmp/evidence_split'
MIN_EVIDENCE_PX = 30  # minimum total evidence pixels in a bucket to count


def _walker_groups(frame, vw):
    """Chroma-keyed walker silhouettes (replica of estimator's inner fn)."""
    rgb = frame[:, :, ::-1].astype(np.int16)
    keyed = (np.linalg.norm(rgb - v4.MAG, axis=2) < v4.KEY_R).astype(np.uint8)
    keyed = cv2.morphologyEx(keyed, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    merged = cv2.dilate(keyed, np.ones((15, 15), np.uint8))
    n, lab = cv2.connectedComponents(merged)
    groups = []
    for c in range(1, n):
        comp = (lab == c) & (keyed > 0)
        a = int(comp.sum())
        if v4.MIN_WALKER_PX <= a <= v4.MAX_WALKER_PX:
            groups.append(comp)
    return groups, keyed > 0


def extract_evidence(parts, ground, coll, plate_bgr, video_paths,
                     view_wh=(1200, 675)):
    """Run the estimator's evidence loop and return spatial evidence masks.

    Returns a dict mapping pid -> {bucket: 2D bool array in plate space}
    for each of the four evidence buckets.
    """
    vw, vh = view_wh
    plate_small = cv2.resize(plate_bgr, (1200, 900))
    sx, sy = plate_bgr.shape[1] / 1200, plate_bgr.shape[0] / 900
    pids = [int(p) for p in np.unique(parts) if p > 0]

    base_y, part_area = {}, {}
    for pid in pids:
        m = parts == pid
        base_y[pid] = int(np.nonzero(m)[0].max())
        part_area[pid] = int(m.sum())

    pk = np.ones((2 * v4.BOUNDARY_GUARD + 1,) * 2, np.uint8)
    pf = parts.astype(np.float32)
    near_edge = (cv2.dilate(pf, pk) != cv2.erode(pf, pk))

    ph, pw = parts.shape
    evid = {p: {b: np.zeros((ph, pw), bool)
                for b in ('occ_front', 'occ_behind', 'under_front', 'under_behind')}
            for p in pids}

    pm_small = cv2.resize((parts > 0).astype(np.uint8),
                          (1200, 900), interpolation=cv2.INTER_NEAREST)

    for it, mp4 in enumerate(video_paths, 1):
        cap = cv2.VideoCapture(mp4)
        frames = []
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            frames.append(cv2.resize(fr, (vw, vh)))
        cap.release()
        if not frames:
            continue
        bg = np.median(np.stack(frames[::6]), axis=0).astype(np.uint8)
        H, inl = vz.homography(bg, plate_small)
        if H is None or inl < 60:
            print(f'iter {it}: skipped (inliers {inl})')
            continue
        partsmask_v = cv2.warpPerspective(
            pm_small, H, (vw, vh),
            flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP) > 0

        # height model (simplified: use p90 constant)
        height_samples = []
        for fi in range(0, len(frames), v4.FRAME_STRIDE):
            for comp in _walker_groups(frames[fi], vw)[0]:
                ys = np.nonzero(comp)[0]
                height_samples.append(int(ys.max() - ys.min()))
        if not height_samples:
            print(f'iter {it}: no walkers')
            continue
        h_est = int(np.percentile(height_samples, 90))

        obs_count = 0
        for fi in range(0, len(frames), v4.FRAME_STRIDE):
            groups, keyed_all = _walker_groups(frames[fi], vw)
            static = np.abs(frames[fi].astype(np.int16) - bg).max(axis=2) < v4.STATIC_T
            occluder = static & partsmask_v & ~keyed_all
            for comp in groups:
                ys, xs = np.nonzero(comp)
                x0, x1 = int(xs.min()), int(xs.max())
                y0, y1 = int(ys.min()), int(ys.max())
                if x0 <= 2 or x1 >= vw - 3 or y1 >= vh - 3:
                    continue
                h_vis = y1 - y0
                trunc_below = trunc_above = False
                if h_vis >= v4.DEPTH_AWARE_TRUNC_FRAC * h_est:
                    feet_y = y1
                else:
                    probe = max(8, h_est // 3)
                    below = occluder[y1 + 1:y1 + 1 + probe, x0:x1 + 1].sum()
                    above = occluder[max(0, y0 - probe):y0, x0:x1 + 1].sum()
                    if below == 0 and above == 0:
                        feet_y, trunc_above = y1, True
                    elif below >= above:
                        feet_y, trunc_below = y0 + h_est, True
                    else:
                        feet_y, trunc_above = y1, True
                feet_y = min(feet_y, vh - 1)
                fx = float(np.median(xs[ys >= y1 - 2]))

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
                fpy = int(np.clip(fp2[1] * sy, 0, ph - 1))

                for kind, m_mask in (('under', comp), ('occ', occ)):
                    yy, xx = np.nonzero(m_mask)
                    if not len(yy):
                        continue
                    pts = cv2.perspectiveTransform(
                        np.float32(np.stack([xx, yy], 1)).reshape(-1, 1, 2),
                        H).reshape(-1, 2)
                    px = np.clip((pts[:, 0] * sx).astype(int), 0, pw - 1)
                    py = np.clip((pts[:, 1] * sy).astype(int), 0, ph - 1)
                    if kind == 'under':
                        keep = ~near_edge[py, px]
                        if not keep.any():
                            continue
                        px, py = px[keep], py[keep]
                    hit_ids = parts[py, px]
                    for pid in np.unique(hit_ids):
                        pid = int(pid)
                        if pid <= 0:
                            continue
                        side = 'front' if fpy > base_y[pid] else 'behind'
                        bucket = f'{kind}_{side}'
                        sel = hit_ids == pid
                        evid[pid][bucket][py[sel], px[sel]] = True
                obs_count += 1
        print(f'iter {it}: {obs_count} walker observations')

    return evid, base_y, part_area


def analyse_separation(evid, parts, base_y, part_area):
    """For each part, measure spatial separation between evidence types.

    Returns a list of parts with separable evidence, sorted by separation
    score (best first).  Separation is measured as the vertical distance
    between the centroid of "overhead" evidence (occ_front) and the centroid
    of "grounded" evidence (occ_behind + under_behind), normalised by the
    part's vertical span.
    """
    results = []
    for pid, buckets in evid.items():
        of_mask = buckets['occ_front']
        ob_mask = buckets['occ_behind']
        ub_mask = buckets['under_behind']
        uf_mask = buckets['under_front']

        overhead_px = int(of_mask.sum())
        grounded_px = int(ob_mask.sum()) + int(ub_mask.sum())
        total_px = overhead_px + grounded_px + int(uf_mask.sum())

        if overhead_px < MIN_EVIDENCE_PX or grounded_px < MIN_EVIDENCE_PX:
            continue

        m = parts == pid
        ys = np.nonzero(m)[0]
        vspan = int(ys.max() - ys.min())
        if vspan < 50:
            continue

        of_rows = np.nonzero(of_mask)[0]
        grounded_mask = ob_mask | ub_mask
        gr_rows = np.nonzero(grounded_mask)[0]

        of_centroid_y = float(np.mean(of_rows))
        gr_centroid_y = float(np.mean(gr_rows))
        separation = abs(of_centroid_y - gr_centroid_y)
        normed_sep = separation / max(1, vspan)

        overhead_above = of_centroid_y < gr_centroid_y

        of_cols = np.nonzero(of_mask)[1]
        gr_cols = np.nonzero(grounded_mask)[1]
        of_centroid_x = float(np.mean(of_cols))
        gr_centroid_x = float(np.mean(gr_cols))

        results.append({
            'pid': pid,
            'overhead_px': overhead_px,
            'grounded_px': grounded_px,
            'total_evid_px': total_px,
            'part_area': part_area.get(pid, 0),
            'vspan': vspan,
            'of_centroid': (round(of_centroid_y, 1), round(of_centroid_x, 1)),
            'gr_centroid': (round(gr_centroid_y, 1), round(gr_centroid_x, 1)),
            'separation_px': round(separation, 1),
            'normed_separation': round(normed_sep, 3),
            'overhead_above': overhead_above,
        })

    results.sort(key=lambda r: -r['normed_separation'])
    return results


def split_part(parts, pid, evid_buckets, base_y_pid, min_sub_area=500):
    """Split one part along the evidence boundary.

    Uses a horizontal cut at the row that best separates overhead evidence
    (occ_front) from grounded evidence (occ_behind + under_behind).  The
    cut is the midpoint between the two evidence centroids, constrained to
    lie within the part's bounding box.

    Returns (new_ids, modified_parts_array) or None if split is not viable.
    """
    m = parts == pid
    ys, xs = np.nonzero(m)
    y_min, y_max = int(ys.min()), int(ys.max())

    of_mask = evid_buckets['occ_front'] & m
    grounded_mask = (evid_buckets['occ_behind'] | evid_buckets['under_behind']) & m

    of_rows = np.nonzero(of_mask)[0]
    gr_rows = np.nonzero(grounded_mask)[0]

    if len(of_rows) == 0 or len(gr_rows) == 0:
        return None

    of_center = float(np.median(of_rows))
    gr_center = float(np.median(gr_rows))

    cut_row = int(round((of_center + gr_center) / 2))
    cut_row = max(y_min + 10, min(y_max - 10, cut_row))

    upper = m.copy()
    upper[cut_row:, :] = False
    lower = m.copy()
    lower[:cut_row, :] = False

    if upper.sum() < min_sub_area or lower.sum() < min_sub_area:
        return None

    return cut_row, upper, lower


def run(room=ROOM, video_glob=None, out_tag='evid'):
    """Full pipeline: extract evidence, analyse, split, write output."""
    os.makedirs(TMP, exist_ok=True)

    parts_path = os.path.join(v4.ROOT, f'tools/art-pipeline/_srcmasks_{room}-parts.npz')
    parts = np.load(parts_path)['inst']
    ground = np.asarray(Image.open(os.path.join(
        v4.ROOT, f'docs/art-options/magenta-ground-{room}-nowires.png')).convert('L')) > 127
    coll = np.asarray(Image.open(os.path.join(
        v4.ROOT, f'assets/rooms/{room}.collision.png')).convert('L')) > 127
    plate = cv2.imread(os.path.join(v4.ROOT, f'docs/art-options/rooms/{room}/plate.png'))

    if video_glob:
        import glob as gl
        video_paths = sorted(gl.glob(video_glob))
    else:
        video_paths = sorted(
            [os.path.join('/home/ivanmkc/.claude/jobs/92f6b395/tmp/veostab', f)
             for f in os.listdir('/home/ivanmkc/.claude/jobs/92f6b395/tmp/veostab')
             if f.endswith('_stab.mp4')])
    print(f'Videos: {len(video_paths)}')
    for v in video_paths:
        print(f'  {v}')

    print('\n--- Phase 1: Extract spatial evidence ---')
    evid, base_y, part_area = extract_evidence(parts, ground, coll, plate, video_paths)

    print('\n--- Phase 2: Analyse separation ---')
    separable = analyse_separation(evid, parts, base_y, part_area)
    print(f'Parts with both overhead and grounded evidence: {len(separable)}')
    for r in separable[:20]:
        print(f"  pid {r['pid']:4d}: overhead={r['overhead_px']:5d}px "
              f"grounded={r['grounded_px']:5d}px  sep={r['separation_px']:.0f}px "
              f"({r['normed_separation']:.3f} normed)  "
              f"{'overhead ABOVE' if r['overhead_above'] else 'overhead BELOW'}")

    # visualise evidence maps for top candidates
    vis_dir = os.path.join(TMP, 'evidence_maps')
    os.makedirs(vis_dir, exist_ok=True)
    for r in separable[:10]:
        pid = r['pid']
        m = parts == pid
        ys, xs = np.nonzero(m)
        y0, y1 = int(ys.min()), int(ys.max())
        x0, x1 = int(xs.min()), int(xs.max())
        pad = 20
        y0s, y1s = max(0, y0 - pad), min(plate.shape[0], y1 + pad)
        x0s, x1s = max(0, x0 - pad), min(plate.shape[1], x1 + pad)
        vis = plate[y0s:y1s, x0s:x1s].copy()
        # draw evidence in colour: red = occ_front, green = occ_behind, blue = under_behind
        for bucket, colour in [('occ_front', (0, 0, 255)),
                                ('occ_behind', (0, 255, 0)),
                                ('under_behind', (255, 0, 0)),
                                ('under_front', (0, 255, 255))]:
            bm = evid[pid][bucket][y0s:y1s, x0s:x1s]
            if bm.any():
                vis[bm] = colour
        # draw part outline
        contour_mask = m[y0s:y1s, x0s:x1s].astype(np.uint8)
        cnts, _ = cv2.findContours(contour_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(vis, cnts, -1, (255, 255, 255), 1)
        cv2.imwrite(os.path.join(vis_dir, f'pid{pid}_evidence.png'), vis)

    # split candidates with normed separation > threshold
    MIN_NORMED_SEP = 0.15
    candidates = [r for r in separable if r['normed_separation'] >= MIN_NORMED_SEP]
    print(f'\nSplit candidates (normed_sep >= {MIN_NORMED_SEP}): {len(candidates)}')

    if not candidates:
        print('No parts qualify for evidence-driven splitting.')
        summary = {
            'separable_parts': len(separable),
            'split_candidates': 0,
            'separable_details': separable[:20],
        }
        out_path = os.path.join(v4.ROOT, f'docs/art-options/split-evidence-{room}.json')
        json.dump(summary, open(out_path, 'w'), indent=1)
        print(f'wrote {out_path}')
        return summary

    print('\n--- Phase 3: Split parts ---')
    parts2 = parts.copy()
    max_id = int(parts.max())
    parent_map = {}
    splits = []
    for r in candidates:
        pid = r['pid']
        result = split_part(parts2, pid, evid[pid], base_y[pid])
        if result is None:
            print(f'  pid {pid}: split not viable (sub-part too small)')
            parent_map[pid] = [pid]
            continue
        cut_row, upper, lower = result
        id_upper = max_id + 1
        id_lower = max_id + 2
        max_id += 2
        parts2[upper] = id_upper
        parts2[lower] = id_lower
        parent_map[pid] = [id_upper, id_lower]
        splits.append({
            'old_pid': int(pid),
            'cut_row': int(cut_row),
            'new_upper': int(id_upper),
            'new_lower': int(id_lower),
            'upper_area': int(upper.sum()),
            'lower_area': int(lower.sum()),
            'overhead_above': r['overhead_above'],
            'separation_px': r['separation_px'],
            'normed_separation': r['normed_separation'],
        })
        print(f"  pid {pid}: cut at row {cut_row} -> "
              f"upper={id_upper} ({int(upper.sum())}px) "
              f"lower={id_lower} ({int(lower.sum())}px)")

    # parts not split: keep identity mapping
    for pid in [int(p) for p in np.unique(parts) if p > 0]:
        if pid not in parent_map:
            parent_map[pid] = [pid]

    # write output
    out_npz = os.path.join(v4.ROOT,
                           f'tools/art-pipeline/_srcmasks_{room}-parts3.npz')
    np.savez_compressed(out_npz, inst=parts2)
    print(f'wrote {out_npz}')

    n_new = int(len(np.unique(parts2)) - 1)
    summary = {
        'separable_parts': len(separable),
        'split_candidates': len(candidates),
        'splits': splits,
        'n_parts_before': int(len(np.unique(parts)) - 1),
        'n_parts_after': n_new,
        'parent_map': {str(k): [int(x) for x in v] for k, v in parent_map.items()},
        'separable_details': separable[:20],
    }
    out_json = os.path.join(v4.ROOT, f'docs/art-options/split-evidence-{room}.json')
    json.dump(summary, open(out_json, 'w'), indent=1)
    print(f'wrote {out_json}')

    return summary


if __name__ == '__main__':
    run()
