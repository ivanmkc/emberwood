#!/usr/bin/env python3
"""Calibration + sensitivity suite for the occlusion-probe gates (Ivan: "Test
out your hypotheses"). Every empirical threshold is either (a) re-derived from
measured distributions in saved raw rolls, or (b) shown to be non-load-bearing
via a verdict-stability sweep.

H1 thresholds are measurable:
  - off-bbox noise fraction distribution  -> noise budget (gate)
  - speckle blob sizes vs on-instance blob sizes -> min_px per constraint
  - shadow apron mean-diff distribution   -> shadow gate
H2 gates are reject-gates, not estimators:
  - object verdict table recomputed under 27 threshold combos (DIFF_T x min_px
    x concordance, each at ~±50%) -> count verdict flips
H3 snap radius non-load-bearing:
  - magenta raw rolls re-snapped at radius 90..150 -> pairwise IoU
"""
import glob
import json
import os

import cv2
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW = os.path.expanduser('~/.claude/jobs/92f6b395/tmp/proberaw')
MAGRAW = os.path.expanduser('~/.claude/jobs/92f6b395/tmp/magraw')
ROOM = 'night-bazaar'
PLATE = os.path.join(ROOT, 'docs/art-options/rooms/night-bazaar/plate.png')


def load_probes():
    out = []
    for f in sorted(glob.glob(os.path.join(RAW, 'probe_*.npz'))):
        z = np.load(f)
        out.append({'adiff': z['adiff'], 'bbox': z['bbox'], 'marker': z['marker'],
                    'origin': z['origin'], 'tag': os.path.basename(f)[6:-4]})
    return out


def column_fill(vis, bx0, by0, bx1, by1):
    vb = vis[by0:by1, bx0:bx1]
    fill = np.zeros_like(vb)
    for c in range(vb.shape[1]):
        rs = np.nonzero(vb[:, c])[0]
        if len(rs) >= 2 and rs[-1] - rs[0] >= 8:
            fill[rs[0]:rs[-1] + 1, c] = True
    return fill, vb


def masks_at(p, T):
    bx0, by0, bx1, by1 = p['bbox']
    diff = p['adiff'] > T
    bbox = np.zeros_like(diff)
    bbox[by0:by1, bx0:bx1] = True
    vis = diff & bbox
    fill, vb = column_fill(vis, bx0, by0, bx1, by1)
    occ = np.zeros_like(diff)
    occ[by0:by1, bx0:bx1] = fill & ~vb
    return diff, bbox, vis, occ


def main():
    probes = load_probes()
    inst = np.load(os.path.join(ROOT, 'tools/art-pipeline', f'_srcmasks_{ROOM}.npz'))['inst']
    meta = json.load(open(os.path.join(ROOT, 'assets/rooms', f'{ROOM}.instances.json')))
    blocking = {o['id']: o.get('label', '?') for o in meta['instances'] if o.get('blocking')}
    R = {'n_probes': len(probes)}

    # H1a: off-bbox noise fraction at DIFF_T=42
    noise = []
    for p in probes:
        diff, bbox, _, _ = masks_at(p, 42)
        noise.append(float((diff & ~bbox).sum() / max(1, (~bbox).sum())))
    R['offbbox_noise'] = {'per_probe': [round(n, 4) for n in noise],
                          'p50': round(float(np.median(noise)), 4),
                          'max': round(float(np.max(noise)), 4),
                          'current_budget': 0.08,
                          'recommended_budget': round(float(np.max(noise)) * 1.5 + 0.01, 3)}

    # H1b: speckle vs on-instance blob sizes (inside column-fill holes)
    speckle, oninst = [], []
    for p in probes:
        _, _, _, occ = masks_at(p, 42)
        oy0, ox0 = p['origin'][1], p['origin'][0]
        n, lab = cv2.connectedComponents(occ.astype(np.uint8))
        for i in range(1, n):
            comp = lab == i
            sz = int(comp.sum())
            ys, xs = np.nonzero(comp)
            gys, gxs = np.clip(ys + oy0, 0, inst.shape[0]-1), np.clip(xs + ox0, 0, inst.shape[1]-1)
            ids = inst[gys, gxs]
            on = sum(1 for v in ids if v in blocking) / max(1, len(ids))
            (oninst if on >= 0.6 else speckle).append(sz)
    def pct(a):
        return {} if not a else {'n': len(a), 'p50': int(np.median(a)),
                                 'p90': int(np.percentile(a, 90)), 'max': int(np.max(a))}
    R['blob_sizes'] = {'speckle': pct(speckle), 'on_instance': pct(oninst),
                       'current_min_px': 50}

    # H1c: shadow apron
    aprons = []
    for p in probes:
        bx0, by0, bx1, by1 = p['bbox']
        H_, W_ = p['adiff'].shape
        a0, a1 = min(H_, by1), min(H_, by1 + 20)
        ax0, ax1 = max(0, bx0 - 30), min(W_, bx1 + 30)
        if a1 > a0:
            aprons.append(float(p['adiff'][a0:a1, ax0:ax1].mean()))
    R['shadow_apron'] = {'per_probe_mean': [round(a, 1) for a in aprons],
                         'p50': round(float(np.median(aprons)), 1),
                         'max': round(float(np.max(aprons)), 1), 'current_gate': 25}

    # H1d: DIFF_T sensitivity of visible px
    curve = {}
    for T in (30, 36, 42, 50, 60):
        v = [int(masks_at(p, T)[2].sum()) for p in probes]
        curve[T] = int(np.median(v))
    R['difft_visible_median'] = curve

    # H2: verdict stability sweep (27 combos)
    def verdicts(T, min_px, conc):
        cons = {}
        for p in probes:
            _, _, vis, occ = masks_at(p, T)
            oy0, ox0 = p['origin'][1], p['origin'][0]
            gy = int(p['marker'][1] + oy0)
            for kind, m in (('occ', occ), ('vis', vis)):
                ys, xs = np.nonzero(m)
                if not len(ys):
                    continue
                ids, cts = np.unique(inst[np.clip(ys+oy0,0,inst.shape[0]-1),
                                          np.clip(xs+ox0,0,inst.shape[1]-1)], return_counts=True)
                for oid, ct in zip(ids, cts):
                    if oid in blocking and ct >= min_px:
                        cons.setdefault(int(oid), []).append((kind, gy))
        out = {}
        for oid, cc in cons.items():
            behind = sorted(g for k, g in cc if k == 'occ')
            front = sorted(g for k, g in cc if k == 'vis')
            def bound(vals, hi=False):
                if len(vals) >= 2:
                    vals2 = vals[::-1] if not hi else vals
                    for i in range(len(vals2) - 1):
                        if abs(vals2[i] - vals2[i+1]) <= conc:
                            return vals2[i+1]
                    return vals2[0]
                return None
            lo, hi = bound(behind), bound(front, hi=True)
            out[oid] = ('overhead' if hi is None and lo is not None else
                        'no-ev' if lo is None and hi is None else
                        'ysort' if (lo is None or hi is None or lo < hi) else 'contradiction')
        return out
    base = verdicts(42, 50, 20)
    flips, combos = {}, 0
    for T in (30, 42, 60):
        for mp in (25, 50, 100):
            for cw in (10, 20, 40):
                combos += 1
                v = verdicts(T, mp, cw)
                for oid in set(base) | set(v):
                    if base.get(oid) != v.get(oid):
                        flips[oid] = flips.get(oid, 0) + 1
    R['verdict_stability'] = {
        'objects_with_verdicts': len(base),
        'baseline': {str(k): f'{blocking.get(k,"?")}:{v}' for k, v in sorted(base.items())},
        'combos_tested': combos,
        'objects_ever_flipping': len(flips),
        'flip_counts': {f'{blocking.get(k,"?")}({k})': v for k, v in sorted(flips.items())}}

    # H3: magenta snap-radius sweep on raw rolls
    raws = sorted(glob.glob(os.path.join(MAGRAW, 'raw_*.png')))
    if raws:
        plate = np.asarray(Image.open(PLATE).convert('RGB')).astype(np.int16)
        Hp, Wp = plate.shape[:2]
        MAG = np.array([255, 0, 255], np.int16)
        stab = {}
        masks = {}
        for r in (90, 110, 120, 130, 150):
            ms = []
            for f in raws[:3]:
                img = np.asarray(Image.open(f).convert('RGB').resize((Wp, Hp), Image.NEAREST)).astype(np.int16)
                near = np.linalg.norm(img - MAG, axis=2) < r
                changed = np.abs(img - plate).max(axis=2) > 42
                ms.append(near & changed)
            masks[r] = ms
            stab[r] = round(float(np.mean([m.mean() for m in ms])), 4)
        ious = {}
        for r in (90, 110, 130, 150):
            iou = np.mean([float((masks[120][i] & masks[r][i]).sum()) /
                           max(1.0, float((masks[120][i] | masks[r][i]).sum()))
                           for i in range(len(raws[:3]))])
            ious[f'120_vs_{r}'] = round(float(iou), 4)
        R['snap_radius'] = {'area_frac_by_radius': stab, 'iou_vs_120': ious,
                            'n_raw_rolls': len(raws[:3])}

    out = os.path.join(ROOT, 'docs/art-options/calibration-report.json')
    json.dump(R, open(out, 'w'), indent=1)
    print(json.dumps(R, indent=1))


if __name__ == '__main__':
    main()
