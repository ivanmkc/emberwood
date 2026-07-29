#!/usr/bin/env python3
"""Synthetic vetting bench for the feet-conditioned layer estimator (Ivan:
"vet this algorithm with procedurally generated video before applying it
again to our scene").

Generates a procedural 2.5D scene where every object's layer is TRUE BY
CONSTRUCTION, renders walker videos with an engine-faithful compositor
(y-sort by feet vs baseY; overhead always on top), adds the adversarial
nuisances the real pipeline must survive (smoke drawn IN FRONT of the
walker, flickering light, camera jitter, non-magenta head/boots on the
walker), then runs the IDENTICAL estimator code (veo_layers_v4.estimate)
and scores predictions against truth.

Truth classes: ground (flat rugs), ysort (standing crates/stalls),
overhead (lanterns, awning, wire). Distractors (smoke, flicker) have no
part id — any vote they produce is a leak and fails the gate.
"""
import json
import os

import cv2
import numpy as np

import layers_harness
import veo_layers_v4 as v4

ROOT = v4.ROOT
OUT = os.path.join(ROOT, 'docs/art-options/synthbench')
W, H = 1200, 900
RNG = np.random.default_rng(7)

# ---- scene definition: id, class, geometry -------------------------------
RUGS = [  # (x0, y0, x1, y1)
    (150, 560, 400, 700), (700, 620, 1000, 760),
]
CRATES = [  # (x0, baseY, w, h_front, h_top) — front face + top face
    (250, 520, 150, 90, 40), (560, 480, 130, 110, 45),
    (860, 540, 170, 80, 35), (450, 780, 140, 100, 40),
    (950, 380, 120, 90, 40),
]
LANTERNS = [(380, 240, 26), (760, 210, 30)]      # (cx, cy, r) hanging
AWNING = (520, 60, 980, 150)                     # wide suspended canopy
WIRE_Y = 180                                     # sinusoid wire across
SMOKE_EMITTERS = [(680, 470), (200, 500)]        # drawn in front of walker
FLICKER = (1040, 620, 1140, 720)                 # brightness-oscillating patch


def build_scene():
    """Build the procedural plate, part-id map, truth labels and masks."""
    plate = np.zeros((H, W, 3), np.uint8)
    plate[:] = (78, 92, 108)                     # BGR floor
    tex = RNG.integers(-12, 12, (H // 4, W // 4, 3)).astype(np.float32)
    plate = np.clip(plate.astype(np.int16) +
                    cv2.resize(tex, (W, H), interpolation=cv2.INTER_LINEAR).astype(np.int16),
                    0, 255).astype(np.uint8)
    parts = np.zeros((H, W), np.int32)
    truth, base_of = {}, {}
    nid = 1
    for x0, y0, x1, y1 in RUGS:
        plate[y0:y1, x0:x1] = (60, 60, 140)
        plate[y0:y1:16, x0:x1] = (50, 50, 110)
        parts[y0:y1, x0:x1] = nid
        truth[nid], base_of[nid] = v4.GROUND, y1
        nid += 1
    crate_sprites = []
    for x0, by, w, hf, ht in CRATES:
        spr = np.zeros((H, W), bool)
        spr[by - hf:by, x0:x0 + w] = True         # front face
        spr[by - hf - ht:by - hf, x0 + 8:x0 + w - 8] = True  # top face
        crate_sprites.append((spr, by, (30 + nid * 17 % 60, 90, 140 + nid * 23 % 80)))
        parts[spr] = nid
        truth[nid], base_of[nid] = v4.YSORT, by
        nid += 1
    over_sprites = []
    for cx, cy, r in LANTERNS:
        spr = np.zeros((H, W), bool)
        cv2.circle(spr.view(np.uint8), (cx, cy), r, 1, -1)
        spr[cy - r - 60:cy - r, cx - 1:cx + 2] = True   # hanging string
        over_sprites.append((spr, (40, 190, 230)))
        parts[spr] = nid
        truth[nid], base_of[nid] = v4.OVERHEAD, cy + r
        nid += 1
    x0, y0, x1, y1 = AWNING
    spr = np.zeros((H, W), bool)
    spr[y0:y1, x0:x1] = True
    over_sprites.append((spr, (60, 60, 150)))
    parts[spr] = nid
    truth[nid], base_of[nid] = v4.OVERHEAD, y1
    nid += 1
    spr = np.zeros((H, W), bool)
    xs = np.arange(0, W)
    ys = (WIRE_Y + 24 * np.sin(xs / 140)).astype(int)
    for t in range(-2, 3):
        spr[np.clip(ys + t, 0, H - 1), xs] = True
    over_sprites.append((spr, (30, 30, 30)))
    parts[spr] = nid
    truth[nid], base_of[nid] = v4.OVERHEAD, int(ys.max())
    nid += 1

    ground = np.ones((H, W), bool)               # walkable floor incl. rugs
    coll = np.ones((H, W), bool)                 # True = walkable
    for x0, by, w, hf, ht in CRATES:
        ground[by - hf - ht:by, x0:x0 + w] = False
        coll[by - 26:by, x0:x0 + w] = False      # footprint band blocks
    static = plate.copy()
    for sspr, by, col in crate_sprites:          # paint statics onto plate
        static[sspr] = col
    for sspr, col in over_sprites:
        static[sspr] = col
    return (plate, static, parts, truth, base_of, ground, coll,
            crate_sprites, over_sprites)


def draw_walker(img, x, feet_y):
    """Walker in plate space: magenta suit + skin head + dark boots (the
    real Veo walkers are ~90% suited, never 100%)."""
    sw, sh = 34, 64
    x0, y0 = int(x - sw / 2), int(feet_y - 8 - sh)
    suit = np.clip(np.array([255, 0, 255]) +
                   RNG.integers(-6, 6, 3), 0, 255).tolist()
    cv2.rectangle(img, (x0, y0), (x0 + sw, int(feet_y - 8)), suit[::-1], -1)
    cv2.circle(img, (int(x), y0 - 8), 11, (150, 190, 235), -1)   # skin head
    cv2.rectangle(img, (x0 + 2, int(feet_y - 8)), (x0 + sw - 2, int(feet_y)),
                  (35, 30, 30), -1)                              # boots


def render_video(path, waypoints, scene, n_frames=180, smoke=True):
    """Render one walker probe video along `waypoints` with engine-faithful
    y-sort compositing, overhead always on top, and the smoke/flicker/jitter
    nuisances."""
    plate, crate_sprites, over_sprites = scene[0], scene[7], scene[8]
    vw, vh = 1200, 675
    wr = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'mp4v'), 24, (vw, vh))
    pts = np.array(waypoints, float)
    seg = np.linspace(0, len(pts) - 1, n_frames)
    for f in range(n_frames):
        i = int(seg[f]); t = seg[f] - i
        p = pts[min(i, len(pts) - 1)] * (1 - t) + pts[min(i + 1, len(pts) - 1)] * t
        wx, wy = p
        frame = plate.copy()
        # engine-faithful y-sort: crates + walker ordered by base anchor
        ents = [(by, 'crate', k) for k, (_, by, _) in enumerate(crate_sprites)]
        ents.append((wy, 'walker', -1))
        for by, kind, k in sorted(ents):
            if kind == 'crate':
                spr, _, col = crate_sprites[k]
                frame[spr] = col
            else:
                draw_walker(frame, wx, wy)
        for spr, col in over_sprites:            # overhead ALWAYS on top
            frame[spr] = col
        if smoke:                                # smoke in FRONT of walker
            for ex, ey in SMOKE_EMITTERS:
                for puff in range(4):
                    ph = (f * 3 + puff * 37) % 130
                    r = 10 + ph // 8
                    a = max(0.0, 0.5 - ph / 260)
                    ov = frame.copy()
                    cv2.circle(ov, (int(ex + 8 * np.sin((f + puff * 9) / 7)),
                                    int(ey - ph)), r, (190, 190, 195), -1)
                    frame = cv2.addWeighted(ov, a, frame, 1 - a, 0)
        fx0, fy0, fx1, fy1 = FLICKER             # flickering light patch
        gain = 1.0 + 0.25 * np.sin(f / 2.3)
        frame[fy0:fy1, fx0:fx1] = np.clip(
            frame[fy0:fy1, fx0:fx1].astype(np.float32) * gain, 0, 255).astype(np.uint8)
        jx, jy = RNG.integers(-1, 2), RNG.integers(-1, 2)   # residual jitter
        M = np.float32([[1, 0, jx], [0, 1, jy]])
        frame = cv2.warpAffine(frame, M, (W, H), borderMode=cv2.BORDER_REPLICATE)
        frame = cv2.resize(frame, (vw, vh))
        noise = RNG.integers(-4, 4, frame.shape)
        frame = np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        wr.write(frame)
    wr.release()


PATHS = [
    # in front of + behind every crate row, under the lanterns/awning/wire
    [(120, 640), (330, 640), (330, 470), (380, 430), (760, 430), (900, 470),
     (1050, 640)],                                   # behind crates 1-3, under lanterns
    [(120, 720), (330, 700), (620, 700), (900, 700), (1100, 720)],  # in front row
    [(380, 760), (380, 315), (300, 320), (850, 320), (760, 315), (760, 760)],  # dwell under lanterns
    [(520, 860), (520, 620), (200, 620), (200, 760), (950, 760), (950, 620)],
    [(100, 245), (1100, 245)],                       # body crosses the wire band
    [(1100, 290), (100, 290)],                       # deeper sweep: lanterns clearly in-front
    [(540, 215), (960, 215), (540, 215)],            # body overlaps the awning bottom
]


def main():
    """Generate the scene + probe videos, run the estimator, score vs truth."""
    os.makedirs(OUT, exist_ok=True)
    scene = build_scene()
    plate, static, parts, truth, base_of, ground, coll = scene[:7]
    cv2.imwrite(os.path.join(OUT, 'plate.png'), static)
    vids = []
    for i, wp in enumerate(PATHS):
        p = os.path.join(OUT, f'swalk{i}.mp4')
        render_video(p, wp, scene)
        vids.append(p)
        print(f'rendered {p}')
    res = v4.estimate(parts, ground, coll, static, vids,
                      os.path.join(OUT, 'synth-layers'))
    last = [r for r in res['iterations'] if 'skipped' not in r][-1]
    pred = {int(k): v for k, v in last['layers'].items()}
    conf, errors = layers_harness.score_vs_truth(pred, truth)
    for e in errors:
        e['votes'] = res['votes'][str(e['part'])]
    # footprint-band accuracy (tower case): crates block only a 26px base
    # band; footprint_top estimates must sit at/above the true band top
    fp = res['footprint_top']
    print('\nfootprint bands (crates: true band top = baseY-26):')
    for x0, by, w, hf, ht in CRATES:
        pid = [p for p, t in truth.items() if t == v4.YSORT and base_of[p] == by
               and abs(np.nonzero(parts == p)[1].min() - x0) < 12]
        if not pid:
            continue
        p = pid[0]
        est = fp.get(str(p))
        true_top = by - 26
        if est is None:
            print(f'  part {p}: no behind-evidence (unvisited) — no estimate')
        else:
            err = est - true_top
            ok = 'OK' if -4 <= err <= 26 else 'BAD (would block walkable rows)' if err < -4 else 'loose'
            print(f'  part {p}: est top {est} vs true {true_top} (err {err:+d}px) {ok}')
    print('\nconfusion (truth -> pred):')
    for (t, p), n in sorted(conf.items()):
        flag = '' if t == p or (t == v4.YSORT and p.startswith(v4.COLLISION)) else '  <-- WRONG'
        print(f'  {t:9s} -> {p:15s} {n}{flag}')
    print(f'\nhard errors: {len(errors)}')
    for e in errors:
        print(' ', e)
    json.dump({'truth': {str(k): v for k, v in truth.items()},
               'pred': {str(k): pred.get(k, 'missing') for k in truth},
               'errors': errors},
              open(os.path.join(OUT, 'synth-score.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
