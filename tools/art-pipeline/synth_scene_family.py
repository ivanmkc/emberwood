#!/usr/bin/env python3
"""Randomized scene FAMILY for anti-overfitting vetting (Ivan: "vary all
parameters and datasets"). Every scene is drawn from distributions over
layout, sizes, colors, walker build and nuisance intensity; probe paths are
DERIVED from the sampled layout (behind/front/close-skim per crate, deep
sweeps under each suspended object, rug crossings), so path coverage does
not silently depend on one hand-tuned layout.

Seed discipline: seeds < 100 are DEVELOPMENT seeds (debugging against them
is allowed); seeds >= 100 are HELD OUT — run them only to report, never to
fix. Run from tools/art-pipeline.
"""
import cv2
import numpy as np

import veo_layers_v4 as v4

W, H = 1200, 900
VIEW = (1200, 675)
MARGIN = 60


def make_spec(seed):
    """Sample one scene specification from the family distributions."""
    rng = np.random.default_rng(seed)
    spec = {'seed': int(seed), 'rng': rng}
    spec['floor'] = tuple(int(c) for c in rng.integers(60, 130, 3))
    spec['n_rugs'] = int(rng.integers(1, 4))
    spec['n_crates'] = int(rng.integers(3, 8))
    spec['n_lanterns'] = int(rng.integers(1, 4))
    spec['awning'] = bool(rng.random() < 0.7)
    spec['wire'] = bool(rng.random() < 0.8)
    spec['walker'] = {'sw': int(rng.integers(26, 43)), 'sh': int(rng.integers(50, 81)),
                      'suit_noise': int(rng.integers(4, 11)),
                      'head_r': int(rng.integers(8, 14))}
    spec['smoke_alpha'] = float(rng.uniform(0.3, 0.7))
    spec['flicker_amp'] = float(rng.uniform(0.15, 0.35))
    spec['jitter_max'] = int(rng.integers(0, 3))
    spec['noise_amp'] = int(rng.integers(2, 6))
    spec['band_h'] = int(rng.integers(18, 36))       # crate collision band height
    return spec


def _place_rects(rng, n, wmin, wmax, hmin, hmax, y0, y1, existing, tries=200):
    """Rejection-sample n non-overlapping rects (x0, y0, x1, y1)."""
    rects = []
    for _ in range(n):
        for _t in range(tries):
            w = int(rng.integers(wmin, wmax))
            h = int(rng.integers(hmin, hmax))
            x = int(rng.integers(MARGIN, W - MARGIN - w))
            y = int(rng.integers(y0, max(y0 + 1, y1 - h)))
            cand = (x, y, x + w, y + h)
            pad = 50
            if all(cand[2] + pad < r[0] or r[2] + pad < cand[0] or
                   cand[3] + pad < r[1] or r[3] + pad < cand[1]
                   for r in existing + rects):
                rects.append(cand)
                break
    return rects


def build_scene(spec):
    """Build plate/static/parts/truth/masks + sprite lists from a spec."""
    rng = spec['rng']
    plate = np.zeros((H, W, 3), np.uint8)
    plate[:] = spec['floor']
    tex = rng.integers(-12, 12, (H // 4, W // 4, 3)).astype(np.float32)
    plate = np.clip(plate.astype(np.int16) +
                    cv2.resize(tex, (W, H), interpolation=cv2.INTER_LINEAR).astype(np.int16),
                    0, 255).astype(np.uint8)
    parts = np.zeros((H, W), np.int32)
    truth, base_of, nid = {}, {}, 1

    crate_boxes = _place_rects(rng, spec['n_crates'], 90, 200, 90, 175, 330, 830, [])
    crates = []
    for x0, ytop, x1, by in crate_boxes:
        ht = int(rng.integers(25, 56))
        hf = (by - ytop) - ht
        crates.append((x0, by, x1 - x0, hf, ht))
    rug_boxes = _place_rects(rng, spec['n_rugs'], 150, 350, 100, 170, 480, 860,
                             crate_boxes)
    rugs = [(x0, y0, x1, y1) for x0, y0, x1, y1 in rug_boxes]

    for x0, y0, x1, y1 in rugs:
        col = tuple(int(c) for c in rng.integers(40, 170, 3))
        plate[y0:y1, x0:x1] = col
        plate[y0:y1:16, x0:x1] = tuple(max(0, c - 25) for c in col)
        parts[y0:y1, x0:x1] = nid
        truth[nid], base_of[nid] = v4.GROUND, y1
        nid += 1
    crate_sprites = []
    for x0, by, w, hf, ht in crates:
        spr = np.zeros((H, W), bool)
        spr[by - hf:by, x0:x0 + w] = True
        spr[by - hf - ht:by - hf, x0 + 8:x0 + w - 8] = True
        col = tuple(int(c) for c in rng.integers(30, 200, 3))
        crate_sprites.append((spr, by, col))
        parts[spr] = nid
        truth[nid], base_of[nid] = v4.YSORT, by
        nid += 1
    over_sprites = []
    lanterns = []
    for _ in range(spec['n_lanterns']):
        cx = int(rng.integers(150, W - 150))
        cy = int(rng.integers(160, 290))
        r = int(rng.integers(18, 37))
        lanterns.append((cx, cy, r))
        spr = np.zeros((H, W), bool)
        cv2.circle(spr.view(np.uint8), (cx, cy), r, 1, -1)
        spr[max(0, cy - r - 60):cy - r, cx - 1:cx + 2] = True
        over_sprites.append((spr, tuple(int(c) for c in rng.integers(30, 230, 3))))
        parts[spr] = nid
        truth[nid], base_of[nid] = v4.OVERHEAD, cy + r
        nid += 1
    awning = None
    if spec['awning']:
        ax0 = int(rng.integers(MARGIN, W // 2))
        ax1 = int(rng.integers(ax0 + 260, min(W - MARGIN, ax0 + 640)))
        ay0 = int(rng.integers(40, 90))
        ay1 = ay0 + int(rng.integers(70, 120))
        awning = (ax0, ay0, ax1, ay1)
        spr = np.zeros((H, W), bool)
        spr[ay0:ay1, ax0:ax1] = True
        over_sprites.append((spr, tuple(int(c) for c in rng.integers(40, 180, 3))))
        parts[spr] = nid
        truth[nid], base_of[nid] = v4.OVERHEAD, ay1
        nid += 1
    wire_base = None
    if spec['wire']:
        wy = int(rng.integers(150, 230))
        amp = int(rng.integers(12, 34))
        xs = np.arange(0, W)
        ys = (wy + amp * np.sin(xs / rng.uniform(100, 190))).astype(int)
        spr = np.zeros((H, W), bool)
        for t in range(-2, 3):
            spr[np.clip(ys + t, 0, H - 1), xs] = True
        over_sprites.append((spr, (30, 30, 30)))
        parts[spr] = nid
        truth[nid], base_of[nid] = v4.OVERHEAD, int(ys.max())
        wire_base = int(ys.max())
        nid += 1

    ground = np.ones((H, W), bool)
    coll = np.ones((H, W), bool)
    band = spec['band_h']
    for x0, by, w, hf, ht in crates:
        ground[by - hf - ht:by, x0:x0 + w] = False
        coll[by - band:by, x0:x0 + w] = False
    static = plate.copy()
    for spr, by, col in crate_sprites:
        static[spr] = col
    for spr, col in over_sprites:
        static[spr] = col
    spec['smoke_emitters'] = [(int(rng.integers(150, W - 150)), int(rng.integers(400, 700)))
                              for _ in range(2)]
    fx = int(rng.integers(MARGIN, W - 160))
    fy = int(rng.integers(450, 780))
    spec['flicker'] = (fx, fy, fx + 100, fy + 100)
    layout = {'crates': crates, 'rugs': rugs, 'lanterns': lanterns,
              'awning': awning, 'wire_base': wire_base, 'band_h': band}
    return (plate, static, parts, truth, base_of, ground, coll,
            crate_sprites, over_sprites, layout)


PLAN_MIN_OVERLAP = 90        # px of walker-box/part overlap for a qualifying pass
PLAN_DEAD_ZONE = 16          # feet must be this far from the base to count
PLAN_MIN_RUN = 90            # qualifying positions must span this many x px


def plan_coverage_paths(parts, base_y_map, walker_w, walker_h, bands):
    """Coverage-guaranteeing planner (purely geometric — no truth input):
    for EVERY part, find feet positions whose walker box overlaps the part by
    >= PLAN_MIN_OVERLAP while the feet are clearly IN FRONT of the base, and
    likewise clearly BEHIND, avoiding collision band rects. Returns sweep
    segments + a per-part coverage report; parts with no qualifying position
    on a side get a provable-unreachability certificate, not a silent gap."""
    hgt, wid = parts.shape
    boot = 8
    kx, ky = walker_w, walker_h + boot
    paths, report = [], {}
    for pid in [int(p) for p in np.unique(parts) if p > 0]:
        m = (parts == pid).astype(np.float32)
        # overlap(x, y) = part px inside the walker box with FEET at (x, y):
        # box spans rows y-ky..y, cols x-kx/2..x+kx/2 — a box filter with the
        # anchor at the bottom-center of the kernel
        ov = cv2.boxFilter(m, -1, (kx, ky), anchor=(kx // 2, ky - 1),
                           normalize=False)
        base = base_y_map[pid]
        report[pid] = {}
        for side, lo, hi in (('front', base + PLAN_DEAD_ZONE, hgt - 20),
                             ('behind', 60 + ky, base - PLAN_DEAD_ZONE)):
            best = None
            for y in range(lo, hi, 4):
                if not (0 <= y < hgt):
                    continue
                ok = ov[y] >= PLAN_MIN_OVERLAP
                for x0b, y0b, x1b, y1b in bands:      # collision-band avoidance
                    if y0b <= y <= y1b:
                        ok[max(0, x0b - kx):x1b + kx] = False
                xs = np.nonzero(ok)[0]
                if not len(xs):
                    continue
                runs = np.split(xs, np.nonzero(np.diff(xs) > 8)[0] + 1)
                run = max(runs, key=len)
                if run[-1] - run[0] >= PLAN_MIN_RUN and (
                        best is None or run[-1] - run[0] > best[2] - best[1]):
                    best = (y, int(run[0]), int(run[-1]))
            if best:
                y, xa, xb = best
                paths.append([(max(40, xa - 50), y), (min(wid - 40, xb + 50), y)])
                report[pid][side] = {'y': y, 'x0': xa, 'x1': xb}
            else:
                report[pid][side] = 'UNREACHABLE'
    # merge sweeps at similar depths into single wide passes — one video can
    # cover several parts; without this a 15-part scene renders ~30 videos
    merged = []
    for seg in sorted(paths, key=lambda p: p[0][1]):
        y = seg[0][1]
        if merged and abs(merged[-1][0][1] - y) <= 14:
            m = merged[-1]
            x0 = min(m[0][0], seg[0][0]); x1 = max(m[1][0], seg[1][0])
            merged[-1] = [(x0, m[0][1]), (x1, m[1][1])]
        else:
            merged.append(seg)
    return merged, report


def gen_paths(spec, layout, parts=None, base_of=None):
    """Derive probe paths from the layout. When `parts`/`base_of` are given,
    the coverage PLANNER guarantees every part a qualifying front and behind
    pass where geometrically possible; heuristic crate skims and rug
    crossings are kept as supplements."""
    paths = []
    behind, front, skim = [], [], []
    for x0, by, w, hf, ht in layout['crates']:
        cx = x0 + w // 2
        behind.append((cx, max(300, by - hf - 12)))
        front.append((cx, min(H - 30, by + 40)))
        skim.append((cx, by - layout['band_h'] - 6))    # close behind the base
    if behind:
        paths.append([(80, behind[0][1])] + behind + [(W - 80, behind[-1][1])])
        paths.append([(80, front[0][1])] + front + [(W - 80, front[-1][1])])
        paths.append([(80, skim[0][1])] + skim + [(W - 80, skim[-1][1])])
    for x0, y0, x1, y1 in layout['rugs']:
        my = (y0 + y1) // 2
        paths.append([(max(60, x0 - 80), my), (min(W - 60, x1 + 80), my)])
    spec['coverage_report'] = None
    if parts is not None:
        bands = [(x0, by - layout['band_h'], x0 + w, by)
                 for x0, by, w, hf, ht in layout['crates']]
        wk = spec['walker']
        planned, report = plan_coverage_paths(parts, base_of,
                                              wk['sw'], wk['sh'], bands)
        paths.extend(planned)
        spec['coverage_report'] = {str(k): v for k, v in report.items()}
    return paths


def draw_walker(img, x, feet_y, spec):
    """Walker sprite parameterized by the spec's build."""
    wk = spec['walker']
    sw, sh, hr = wk['sw'], wk['sh'], wk['head_r']
    x0, y0 = int(x - sw / 2), int(feet_y - 8 - sh)
    n = wk['suit_noise']
    suit = np.clip(np.array([255, 0, 255]) +
                   spec['rng'].integers(-n, n, 3), 0, 255).tolist()
    cv2.rectangle(img, (x0, y0), (x0 + sw, int(feet_y - 8)), suit[::-1], -1)
    cv2.circle(img, (int(x), y0 - hr + 3), hr, (150, 190, 235), -1)
    cv2.rectangle(img, (x0 + 2, int(feet_y - 8)), (x0 + sw - 2, int(feet_y)),
                  (35, 30, 30), -1)


def render_video(path, waypoints, scene, spec, n_frames=170):
    """Engine-faithful render of one probe walk with the spec's nuisances."""
    rng = spec['rng']
    plate, crate_sprites, over_sprites = scene[0], scene[7], scene[8]
    vw, vh = VIEW
    wr = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'mp4v'), 24, (vw, vh))
    pts = np.array(waypoints, float)
    seg = np.linspace(0, len(pts) - 1, n_frames)
    for f in range(n_frames):
        i = int(seg[f]); t = seg[f] - i
        p = pts[min(i, len(pts) - 1)] * (1 - t) + pts[min(i + 1, len(pts) - 1)] * t
        wx, wy = p
        frame = plate.copy()
        ents = [(by, 'crate', k) for k, (_, by, _) in enumerate(crate_sprites)]
        ents.append((wy, 'walker', -1))
        for by, kind, k in sorted(ents):
            if kind == 'crate':
                spr, _, col = crate_sprites[k]
                frame[spr] = col
            else:
                draw_walker(frame, wx, wy, spec)
        for spr, col in over_sprites:
            frame[spr] = col
        for ex, ey in spec['smoke_emitters']:
            for puff in range(4):
                ph = (f * 3 + puff * 37) % 130
                r = 10 + ph // 8
                a = max(0.0, spec['smoke_alpha'] - ph / 260)
                ov = frame.copy()
                cv2.circle(ov, (int(ex + 8 * np.sin((f + puff * 9) / 7)),
                                int(ey - ph)), r, (190, 190, 195), -1)
                frame = cv2.addWeighted(ov, a, frame, 1 - a, 0)
        fx0, fy0, fx1, fy1 = spec['flicker']
        gain = 1.0 + spec['flicker_amp'] * np.sin(f / 2.3)
        frame[fy0:fy1, fx0:fx1] = np.clip(
            frame[fy0:fy1, fx0:fx1].astype(np.float32) * gain, 0, 255).astype(np.uint8)
        j = spec['jitter_max']
        if j:
            M = np.float32([[1, 0, rng.integers(-j, j + 1)],
                            [0, 1, rng.integers(-j, j + 1)]])
            frame = cv2.warpAffine(frame, M, (W, H), borderMode=cv2.BORDER_REPLICATE)
        frame = cv2.resize(frame, (vw, vh))
        na = spec['noise_amp']
        noise = rng.integers(-na, na, frame.shape)
        frame = np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        wr.write(frame)
    wr.release()
