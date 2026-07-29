#!/usr/bin/env python3
"""Plug-in-play entry point for the layer estimator (Ivan: "we can later
pass it the game renders instead of the synthetic data and it should work
exactly the same way").

Everything is passed as FILES — no Python required to swap the video
source. The same command works for the 2D synthetic bench, the 3D bench,
real Veo videos, or captures of the actual game engine:

  python3 layers_harness.py \
      --parts scene-parts.npz --ground ground.png --collision coll.png \
      --plate plate.png --videos 'captures/*.mp4' --out out/run1 \
      [--truth truth.json] [--view 1200x675]

THE VIDEO-SOURCE CONTRACT (what any producer — Veo, synthetic, or the game
engine — must satisfy):
  1. The walker wears a flat pure-magenta (#FF00FF) suit; pixels within
     color distance 90 count as walker. (In the game engine: recolor the
     player sprite.) Heads/boots need not be magenta.
  2. The camera is completely static (or the video is pre-stabilized).
  3. Non-walker animation (smoke, flicker) is fine — the chroma key plus
     the static-background gate keep it voteless.
  4. Probe paths must pass IN FRONT OF and BEHIND standing objects and
     UNDER suspended ones at feet-depths beyond the +/-10px dead zone
     around each part's base, otherwise those observations are discarded
     as ambiguous.

INPUT FILES:
  --parts     .npz with key 'inst': int32 part-id map in plate space
  --ground    grayscale png, >127 = walkable floor (the ground prior)
  --collision grayscale png, >127 = walkable (footprints blocked), any
              resolution (nearest-resized to the parts map)
  --plate     the clean scene image the videos are registered against
  --truth     OPTIONAL json {pid: ground|ysort|overhead} — when the source
              knows the answer (synthetic benches, or the game engine
              itself), the run is scored and a confusion table is written
"""
import argparse
import glob
import json
import os

import cv2
import numpy as np
from PIL import Image

import veo_layers_v4 as v4


def score_vs_truth(pred, truth):
    """Confusion + hard errors for predicted layers vs a truth mapping.

    ysort -> collision/collision-prior is acceptable (an unvisited standing
    object correctly keeps its prior); everything else must match."""
    conf, errors = {}, []
    for pid, t in truth.items():
        p = pred.get(int(pid), pred.get(str(pid), 'missing'))
        conf[(t, p)] = conf.get((t, p), 0) + 1
        if p != t and not (t == v4.YSORT and p in (v4.COLLISION, v4.COLLISION_PRIOR)):
            errors.append({'part': pid, 'truth': t, 'pred': p})
    return conf, errors


def load_inputs(parts_npz, ground_png, coll_png, plate_png):
    """Load the four scene inputs from disk into estimate()'s formats."""
    parts = np.load(parts_npz)['inst']
    ground = np.asarray(Image.open(ground_png).convert('L')) > 127
    coll = np.asarray(Image.open(coll_png).convert('L').resize(
        (parts.shape[1], parts.shape[0]), Image.Resampling.NEAREST)) > 127
    plate = cv2.imread(plate_png)
    if plate is None:
        raise FileNotFoundError(plate_png)
    return parts, ground, coll, plate


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--parts', required=True)
    ap.add_argument('--ground', required=True)
    ap.add_argument('--collision', required=True)
    ap.add_argument('--plate', required=True)
    ap.add_argument('--videos', required=True, help='glob of probe mp4s')
    ap.add_argument('--out', required=True, help='output path prefix')
    ap.add_argument('--truth', default=None, help='optional truth json to score against')
    ap.add_argument('--view', default='1200x675', help='processing resolution WxH')
    args = ap.parse_args()

    parts, ground, coll, plate = load_inputs(
        args.parts, args.ground, args.collision, args.plate)
    videos = sorted(glob.glob(args.videos))
    if not videos:
        raise FileNotFoundError(f'no videos match {args.videos}')
    vw, vh = (int(x) for x in args.view.split('x'))
    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    res = v4.estimate(parts, ground, coll, plate, videos, args.out, view_wh=(vw, vh))

    if args.truth:
        truth = json.load(open(args.truth))
        last = [r for r in res['iterations'] if 'skipped' not in r][-1]
        pred = {int(k): p for k, p in last['layers'].items()}
        conf, errors = score_vs_truth(pred, truth)
        print('\nconfusion (truth -> pred):')
        for (t, p), n in sorted(conf.items()):
            print(f'  {t:9s} -> {p:15s} {n}')
        print(f'hard errors: {len(errors)}')
        json.dump({'confusion': {f'{t}->{p}': n for (t, p), n in conf.items()},
                   'errors': errors},
                  open(f'{args.out}-score.json', 'w'), indent=1)


if __name__ == '__main__':
    main()
