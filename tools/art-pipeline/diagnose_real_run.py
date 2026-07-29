#!/usr/bin/env python3
"""Error triage for a real-scene run vs gold: every disagreement is
categorized so 'our bug' is separated from 'Veo violated the contract'
(no pass-behind coverage) and from 'segmentation limit' (mixed parts).
Usage: diagnose_real_run.py <run json> <gold json> <parts npz>"""
import json
import sys

import numpy as np

CATS = ('MIXED-GEOMETRY (segmentation limit)',
        'NO-EVIDENCE (Veo coverage limit — prior held)',
        'CONFLICTING EVIDENCE (inspect)',
        'CLEAN-EVIDENCE WRONG (our inference bug)')


def main(run_path, gold_path, parts_npz):
    """Categorize gold disagreements for a run."""
    res = json.load(open(run_path))
    gold = json.load(open(gold_path))['gold']
    parts = np.load(parts_npz)['inst']
    last = [r for r in res['iterations'] if 'skipped' not in r][-1]
    pred = last['layers']
    unreliable = res.get('unreliable', {})
    walker_h = 90.0
    cats = {c: [] for c in CATS}
    tp = fp = fn = tn = 0
    for pid, g in gold.items():
        p = pred.get(pid)
        if p is None:
            continue
        po = p == 'overhead'
        go = g == 'overhead'
        if go and po: tp += 1
        elif not go and not po: tn += 1
        else:
            if go: fn += 1
            else: fp += 1
            v = res['votes'][pid]
            tot = sum(v.values())
            ys_ = np.nonzero(parts == int(pid))[0]
            vspan = int(ys_.max() - ys_.min()) if len(ys_) else 0
            if pid in unreliable or vspan > 2.5 * walker_h:
                cats[CATS[0]].append((pid, g, p, v))
            elif tot == 0:
                cats[CATS[1]].append((pid, g, p, v))
            elif min(v['occ_front'] + v['under_front'],
                     v['occ_behind'] + v['under_behind']) > 0.3 * tot:
                cats[CATS[2]].append((pid, g, p, v))
            else:
                cats[CATS[3]].append((pid, g, p, v))
    print(f'overhead vs gold: P={tp/max(1,tp+fp):.2f} R={tp/max(1,tp+fn):.2f} '
          f'(tp {tp} fp {fp} fn {fn} tn {tn})')
    for c in CATS:
        print(f'\n{c}: {len(cats[c])}')
        for pid, g, p, v in cats[c][:10]:
            print(f'  part {pid}: gold={g} pred={p} votes={v}')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3])
