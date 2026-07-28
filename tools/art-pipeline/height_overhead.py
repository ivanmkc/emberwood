#!/usr/bin/env python3
"""Pretrained height-map arm for the overhead mask (Ivan: "take this flat image
and generate a height map?").

Monocular depth (Depth Anything V2, pretrained) is not height, but height-above-
ground is derivable under our fixed oblique camera: ground depth is a smooth
function of screen row, so fit it from the known walk-consensus pixels and flag
pixels whose depth is anomalously CLOSER than the ground at their row — overhead
wires/signs occlude what's behind them and pop out as toward-camera anomalies.

Outputs per room in docs/art-options/:
  height-depth-<room>.jpg     colorized DAv2 depth
  height-overhead-<room>.jpg  toward-camera anomaly overlay (cyan)
  height-<room>-metrics.json
"""
import json
import os

import cv2
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCENES = {
 'anchorroom': 'docs/art-options/nbp-scifi-anchor-clean.png',
 'night-bazaar': 'docs/art-options/rooms/night-bazaar/plate.png',
 'plaza-market-inside': 'docs/art-options/rooms/plaza-market-inside/plate.png',
}


def load_pipe():
    # transformers is a genuinely expensive import (~6s); only this entry
    # point needs it and callers import this module for its helpers too
    from transformers import pipeline
    return pipeline('depth-estimation',
                    model='depth-anything/Depth-Anything-V2-Small-hf', device='cpu')


def colorize(d):
    n = (d - d.min()) / max(1e-6, d.max() - d.min())
    return cv2.applyColorMap((n * 255).astype(np.uint8), cv2.COLORMAP_TURBO)[:, :, ::-1]


def run(pipe, room):
    src = Image.open(os.path.join(ROOT, SCENES[room])).convert('RGB')
    W, H = src.size
    thumb = src.copy()
    thumb.thumbnail((1024, 1024))
    res = pipe(thumb)
    d = np.asarray(res['depth'].resize((W, H), Image.BILINEAR), dtype=np.float32) \
        if 'depth' in res else res['predicted_depth'].squeeze().numpy()
    if d.shape != (H, W):
        d = np.asarray(Image.fromarray(d).resize((W, H), Image.BILINEAR))

    walk = np.asarray(Image.open(os.path.join(
        ROOT, 'docs', 'art-options', 'bench', 'prompt', room, 'consensus-walk.png'))
        .convert('L').resize((W, H), Image.NEAREST)) > 127

    # DAv2 is disparity-like (larger = closer); verify with the walk pixels:
    # near-camera (bottom) rows must read larger than far rows, else flip.
    rows = np.where(walk.any(axis=1))[0]
    row_med = np.array([np.median(d[r][walk[r]]) for r in rows])
    slope = np.polyfit(rows, row_med, 1)[0]
    if slope < 0:  # bottom rows should be larger
        d = -d
        row_med = -row_med

    # ground model: disparity is linear in row on a flat ground plane under
    # pinhole projection, so a count-weighted linear fit IS the correct model
    # (panel review: interp through noisy medians overfits; sigma must come
    # from fit residuals, not within-row noise)
    counts = walk[rows].sum(axis=1).astype(np.float32)
    lin = np.polyfit(rows, row_med, 1, w=np.sqrt(counts))
    ground = np.polyval(lin, np.arange(H)).astype(np.float32)
    fit_res = row_med - np.polyval(lin, rows)
    sigma = float(np.median(np.abs(fit_res))) * 1.4826 + 1e-6

    resid = d - ground[:, None]  # positive = closer than ground = elevated
    z = resid / sigma
    raised = z > 6.0

    # "not ground" != "overhead": a standing wall is also closer than the
    # ground at its row. Suspended objects are the components with NO
    # contiguous closer-than-ground support path down to walkable ground.
    walk_d = cv2.dilate(walk.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    n, lab = cv2.connectedComponents(raised.astype(np.uint8))
    over = np.zeros((H, W), dtype=bool)
    for i in range(1, n):
        comp = lab == i
        if comp.sum() < 50:
            continue
        crows = np.where(comp.any(axis=1))[0]
        band = comp & (np.arange(H)[:, None] >= crows[-1] - 3)
        grounded = bool((cv2.dilate(band.astype(np.uint8),
                                    np.ones((5, 5), np.uint8)) > 0)[walk_d].any())
        if not grounded:
            over |= comp
    frac = float(over.mean())

    out = os.path.join(ROOT, 'docs', 'art-options')
    Image.fromarray(colorize(d).astype(np.uint8)).save(
        os.path.join(out, f'height-depth-{room}.jpg'), quality=86)
    b = np.asarray(src).astype(np.float32)
    v = b * 0.30
    v[over] = b[over] * 0.25 + np.array([0, 220, 255], np.float32) * 0.75
    o = Image.fromarray(v.clip(0, 255).astype(np.uint8))
    o.thumbnail((1400, 1400), Image.LANCZOS)
    o.save(os.path.join(out, f'height-overhead-{room}.jpg'), quality=86)
    json.dump({'arm': 'dav2-height', 'zthresh': 6.0, 'sigma': round(sigma, 4),
               'overhead_frac': round(frac, 4)},
              open(os.path.join(out, f'height-{room}-metrics.json'), 'w'), indent=1)
    print(f'[{room}] dav2-height: anomaly frac {frac:.2%} (sigma {sigma:.3f})')


if __name__ == '__main__':
    p = load_pipe()
    for r in SCENES:
        run(p, r)
