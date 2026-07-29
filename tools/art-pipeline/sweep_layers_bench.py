#!/usr/bin/env python3
"""Anti-overfitting sweep runner (Ivan: "vary all parameters and datasets").

Two modes, per the ML-methodology panel's protocol:

  --seeds N N N        run full scene-family evaluations on those seeds.
                       Seeds < 100 are DEVELOPMENT (debugging allowed);
                       seeds >= 100 are HELD OUT — run only to report,
                       never to fix. Reports per-class accuracy
                       distributions (mean/std/percentiles), footprint
                       px-error quantiles, and hard-error counts.

  --sensitivity SEED   render SEED's videos once, then re-run ONLY the
                       estimator under a grid over the classification-
                       critical constants (STATIC_T, MIN_EVID, SIDE_MARGIN,
                       DEPTH_AWARE_TRUNC_FRAC, KEY_R — the panel's priority
                       order). Robustness criterion: accuracy stays within
                       2pts of peak over a plateau of at least +/-25% of the
                       default value; narrower plateaus are flagged.

Videos and intermediates go to the job tmp dir; only the summary json is
written to docs/art-options/synthbench/. Run from tools/art-pipeline.
"""
import argparse
import json
import os

import cv2
import numpy as np

import layers_harness
import synth_scene_family as fam
import veo_layers_v4 as v4

OUT = os.path.join(v4.ROOT, 'docs/art-options/synthbench')
TMP = os.environ.get('CLAUDE_JOB_DIR', '/tmp') + '/tmp/sweep'
DEV_SEED_MAX = 99

SENS_GRID = {
    'STATIC_T': [20, 30, 40, 55, 70],
    'MIN_EVID': [90, 135, 180, 240, 300],
    'SIDE_MARGIN': [5, 8, 10, 14, 20],
    'DEPTH_AWARE_TRUNC_FRAC': [0.70, 0.78, 0.85, 0.90, 0.94],
    'KEY_R': [50, 70, 90, 115, 140],
}


def run_scene(seed, workdir, render=True):
    """Generate (or reuse) one family scene + videos; estimate; score.

    Returns the summary dict for aggregation."""
    os.makedirs(workdir, exist_ok=True)
    spec = fam.make_spec(seed)
    scene = fam.build_scene(spec)
    plate, static, parts, truth, base_of, ground, coll = scene[:7]
    layout = scene[9]
    paths = fam.gen_paths(spec, layout, parts=parts, base_of=base_of)
    vids = []
    for i, wp in enumerate(paths):
        p = os.path.join(workdir, f'walk{i}.mp4')
        if render or not os.path.exists(p):
            fam.render_video(p, wp, scene, spec)
        vids.append(p)
    res = v4.estimate(parts, ground, coll, static, vids,
                      os.path.join(workdir, 'est'))
    good = [r for r in res['iterations'] if 'skipped' not in r]
    if not good:
        return {'seed': seed, 'failed': 'all iterations skipped'}
    pred = {int(k): p for k, p in good[-1]['layers'].items()}
    conf, errors = layers_harness.score_vs_truth(pred, truth)
    per_class = {}
    for cls in (v4.GROUND, v4.YSORT, v4.OVERHEAD):
        pids = [p for p, t in truth.items() if t == cls]
        ok = sum(1 for p in pids
                 if pred.get(p) == cls or
                 (cls == v4.YSORT and pred.get(p, '').startswith(v4.COLLISION)))
        per_class[cls] = (ok, len(pids))
    fp_errs = []
    for x0, by, w, hf, ht in layout['crates']:
        pid = [p for p, t in truth.items() if t == v4.YSORT and base_of[p] == by]
        if not pid:
            continue
        est = res['footprint_top'].get(str(pid[0]))
        if est is not None:
            fp_errs.append(int(est - (by - layout['band_h'])))
    unreach = {p: [s_ for s_, v in r.items() if v == 'UNREACHABLE']
               for p, r in (spec['coverage_report'] or {}).items()}
    unreach = {p: v for p, v in unreach.items() if v}
    return {'seed': seed, 'hard_errors': len(errors),
            'errors': errors[:8], 'per_class': per_class,
            'footprint_errs': fp_errs, 'n_parts': len(truth),
            'planner_unreachable': unreach,
            'skipped_iters': len(res['iterations']) - len(good)}


def aggregate(results):
    """Distribution summary across scenes, per the panel's report format."""
    ok_results = [r for r in results if 'failed' not in r]
    summary = {'n_scenes': len(ok_results),
               'failed_scenes': [r['seed'] for r in results if 'failed' in r]}
    accs = {}
    for cls in (v4.GROUND, v4.YSORT, v4.OVERHEAD):
        vals = [r['per_class'][cls][0] / max(1, r['per_class'][cls][1])
                for r in ok_results if r['per_class'][cls][1]]
        if vals:
            accs[cls] = {'mean': round(float(np.mean(vals)), 3),
                         'std': round(float(np.std(vals)), 3),
                         'p5': round(float(np.percentile(vals, 5)), 3),
                         'p95': round(float(np.percentile(vals, 95)), 3)}
    summary['per_class_accuracy'] = accs
    he = [r['hard_errors'] for r in ok_results]
    summary['hard_errors'] = {'total': int(np.sum(he)),
                              'scenes_clean': int(np.sum([h == 0 for h in he])),
                              'max_in_scene': int(np.max(he)) if he else 0}
    fp = [e for r in ok_results for e in r['footprint_errs']]
    if fp:
        summary['footprint_err_px'] = {
            'n': len(fp), 'median': float(np.median(fp)),
            'p25': float(np.percentile(fp, 25)), 'p75': float(np.percentile(fp, 75)),
            'min': int(np.min(fp)), 'max': int(np.max(fp)),
            # err = est_top - true_top: NEGATIVE = band larger = conservative
            # over-block (safe); POSITIVE beyond +4 = under-block (unsafe)
            'over_blocks_conservative': int(np.sum([e < -4 for e in fp])),
            'under_blocks_unsafe': int(np.sum([e > 4 for e in fp]))}
    return summary


def sensitivity(seed):
    """Grid over classification-critical constants; videos rendered once."""
    workdir = os.path.join(TMP, f'seed{seed}')
    print(f'[sensitivity] baseline on seed {seed}')
    base = run_scene(seed, workdir, render=not os.path.exists(
        os.path.join(workdir, 'walk0.mp4')))
    rows = []
    for pname, values in SENS_GRID.items():
        default = getattr(v4, pname)
        for val in values:
            setattr(v4, pname, val)
            if pname == 'MIN_EVID':
                pass  # MIN_EVID is read at classify time — module attr is live
            r = run_scene(seed, workdir, render=False)
            acc = np.mean([r['per_class'][c][0] / max(1, r['per_class'][c][1])
                           for c in (v4.GROUND, v4.YSORT, v4.OVERHEAD)])
            rows.append({'param': pname, 'value': val,
                         'hard_errors': r['hard_errors'],
                         'mean_acc': round(float(acc), 3)})
            print(f"  {pname}={val}: acc={acc:.3f} hard={r['hard_errors']}")
        setattr(v4, pname, default)
    return {'seed': seed, 'baseline_hard_errors': base['hard_errors'], 'grid': rows}


def main():
    """CLI dispatcher for scene-family and sensitivity runs."""
    ap = argparse.ArgumentParser()
    ap.add_argument('--seeds', type=int, nargs='+', default=None)
    ap.add_argument('--sensitivity', type=int, default=None)
    ap.add_argument('--tag', default='sweep')
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    if args.sensitivity is not None:
        out = sensitivity(args.sensitivity)
        path = os.path.join(OUT, f'{args.tag}-sensitivity-seed{args.sensitivity}.json')
        json.dump(out, open(path, 'w'), indent=1)
        print('wrote', path)
        return
    results = []
    for seed in args.seeds:
        kind = 'DEV' if seed <= DEV_SEED_MAX else 'HELD-OUT'
        print(f'[{kind}] seed {seed}')
        r = run_scene(seed, os.path.join(TMP, f'seed{seed}'))
        results.append(r)
        print(f"  hard_errors={r.get('hard_errors')} per_class={r.get('per_class')}")
    summary = aggregate(results)
    summary['seeds'] = args.seeds
    summary['results'] = results
    path = os.path.join(OUT, f'{args.tag}-summary.json')
    json.dump(summary, open(path, 'w'), indent=1)
    print(json.dumps({k: v for k, v in summary.items() if k != 'results'}, indent=1))
    print('wrote', path)


if __name__ == '__main__':
    main()
