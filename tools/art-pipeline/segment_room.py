#!/usr/bin/env python3
"""Pixel-level room segmentation: plate image -> mask stack.

Sweeps Gemini segmentation by category (multi-modal sweep pattern), composes:
  - instance cutout PNGs + base-line y per instance (occlusion)
  - collision.png: walkable=white, blocked=black (eroded for safety)
  - instances.json: id, label, box, baseY, blocking, kind
  - debug overlay for human review

Gates: walkable fraction bounds + pixel BFS (4px lattice) spawn->exit.

Usage: python3 tools/art-pipeline/segment_room.py
"""
import hashlib
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from google import genai
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATE = os.path.join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor.png')
NAME = 'anchorroom'
ART = os.path.join(ROOT, 'docs', 'art-options')
AUTO_SPAWN = False
EXIT_EDGES = []
import argparse
_ap = argparse.ArgumentParser()
_ap.add_argument('--room', default=None)
_args, _ = _ap.parse_known_args()
if _args.room:
    NAME = _args.room
    ART = os.path.join(ROOT, 'docs', 'art-options', 'rooms', NAME)
    PLATE = os.path.join(ART, 'plate.png')
    AUTO_SPAWN = True
    LEGACY_S = False
    _rooms = json.load(open(os.path.join(ROOT, 'tools', 'art-pipeline', 'rooms.json')))
    if NAME in _rooms['rooms']:
        EXIT_EDGES = sorted(_rooms['rooms'][NAME]['exits'])
    else:
        EXIT_EDGES = ['s']  # interiors: single return exit to the parent room
else:
    LEGACY_S = True
    # anchor room: legacy spawn + S exit, plus graph edges from rooms.json
    _rooms = json.load(open(os.path.join(ROOT, 'tools', 'art-pipeline', 'rooms.json')))
    EXIT_EDGES = sorted(_rooms['anchors'].get(NAME, {}).get('exits', {}))
OUT_W, OUT_H = 1280, 896      # device px (logical 640x448 at DS=2)
SPAWN_PX = (250, 300)          # logical px, open plaza floor
EXIT_RECT = (150, 425, 205, 447)  # logical: bottom-left stair region

SWEEPS = [
    ('structure', 'every solid structure and large object: buildings/storefronts, the central glowing pylon, glass hydroponic tanks, market stalls, machines, crates, barrels, railings, staircases, large pipes on the ground', True),
    ('character', 'every person, robot and creature standing in the scene', True),
    ('emissive', 'glowing emissive elements: neon signs, the pylon energy core, tank liquid glow, lamp lights, lit windows and screens', False),
]

client = genai.Client(vertexai=True, project='adk-coding-agents', location='global')


def detect_boxes(im, what):
    """Gemini gives accurate instance boxes; masks are refined locally."""
    prompt = (
        f'Detect {what}. Output a JSON list where each entry contains the 2D bounding box in the '
        'key "box_2d" ([ymin, xmin, ymax, xmax] normalized to 0-1000) and a short text label in '
        'the key "label". Include every distinct instance.'
    )
    for attempt in range(3):
        resp = client.models.generate_content(
            model='gemini-3.1-pro-preview',
            contents=[im, prompt],
            config=types.GenerateContentConfig(max_output_tokens=16384),
        )
        text = resp.text or ''
        start = text.find('[')
        if start < 0:
            continue
        try:
            items, _ = json.JSONDecoder().raw_decode(text[start:])
            out = [{'label': it.get('label', what), 'box': it['box_2d']} for it in items if 'box_2d' in it]
            if out:
                return out
        except Exception as e:  # noqa: BLE001
            print(f'  parse fail ({what}) attempt {attempt}: {e}', file=sys.stderr)
    return []


def grabcut_mask(plate_np, box):
    """Pixel-level instance mask via GrabCut initialized from the box."""
    import cv2
    x0, y0, x1, y1 = box
    pad = 6
    x0p, y0p = max(0, x0 - pad), max(0, y0 - pad)
    x1p, y1p = min(plate_np.shape[1], x1 + pad), min(plate_np.shape[0], y1 + pad)
    crop = plate_np[y0p:y1p, x0p:x1p].copy()
    mask = np.zeros(crop.shape[:2], np.uint8)
    rect = (x0 - x0p, y0 - y0p, x1 - x0, y1 - y0)
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(crop[:, :, ::-1].copy(), mask, rect, bgd, fgd, 5, cv2.GC_INIT_WITH_RECT)
    except Exception:  # noqa: BLE001
        return None
    m = ((mask == 1) | (mask == 3)).astype(np.uint8)
    # keep the largest component; close small holes
    n, lab = cv2.connectedComponents(m)
    if n > 1:
        sizes = [(lab == i).sum() for i in range(1, n)]
        m = (lab == (1 + int(np.argmax(sizes)))).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    full = np.zeros(plate_np.shape[:2], dtype=bool)
    full[y0p:y1p, x0p:x1p] = m.astype(bool)
    return full


def paste_mask(canvas_arr, item, value):
    """Rasterize a box-normalized mask into a full-res index array."""
    ymin, xmin, ymax, xmax = item['box']
    x0, y0 = int(xmin / 1000 * OUT_W), int(ymin / 1000 * OUT_H)
    x1, y1 = int(xmax / 1000 * OUT_W), int(ymax / 1000 * OUT_H)
    if x1 <= x0 or y1 <= y0:
        return None
    m = item['mask'].resize((x1 - x0, y1 - y0), Image.BILINEAR)
    ma = np.asarray(m) > 127
    region = canvas_arr[y0:y1, x0:x1]
    region[ma] = value
    return (x0, y0, x1, y1)


def main():
    clean = os.path.join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor-clean.png')
    spawns_f = os.path.join(ROOT, 'tools', 'art-pipeline', '_char_spawns.json')
    chars_removed = NAME == 'anchorroom' and os.path.exists(clean) and os.path.exists(spawns_f)
    plate_path = clean if chars_removed else PLATE
    plate_full = Image.open(plate_path).convert('RGB')
    plate_hash = hashlib.sha256(open(plate_path, 'rb').read()).hexdigest()
    if chars_removed:
        print('using CLEAN plate (painted characters removed)')
    SW, SH = plate_full.size  # native source res: all masks computed here
    global OUT_W, OUT_H
    scale = OUT_W / SW
    plate = plate_full.resize((OUT_W, OUT_H), Image.LANCZOS)
    seg_input = plate_full.copy()
    seg_input.thumbnail((1024, 1024))

    plate_np_seg = np.asarray(plate_full)
    OUT_W, OUT_H = SW, SH  # mask space = source space from here on
    inst_arr = np.zeros((OUT_H, OUT_W), dtype=np.uint16)  # 0 = background
    instances = []
    iid = 0

    # PRIMARY: NBP-native class mask (nbp_mask.py), if present and gated.
    nbp_path = os.path.join(ART, 'nbp-mask.png')
    met_path = os.path.join(ART, 'nbp-mask-metrics.json')
    use_nbp = os.path.exists(nbp_path) and os.path.exists(met_path) \
        and json.load(open(met_path)).get('pass')
    if use_nbp:
        import cv2
        print('using NBP-native class mask (gated: '
              + json.dumps(json.load(open(met_path))) + ')')
        CLS = {'building': (255, 0, 0), 'water': (0, 0, 255), 'character': (255, 255, 0),
               'tank': (0, 255, 255), 'pylon': (255, 128, 0), 'prop': (255, 0, 255),
               'pipe': (128, 0, 255)}
        nb = np.asarray(Image.open(nbp_path).convert('RGB').resize((OUT_W, OUT_H), Image.NEAREST)).astype(np.int16)
        for cname, col in CLS.items():
            dist = np.linalg.norm(nb - np.array(col, np.int16), axis=2)
            cmask = (dist < 90).astype(np.uint8)
            ncc, lab = cv2.connectedComponents(cmask)
            for ci in range(1, ncc):
                comp = (lab == ci)
                if comp.sum() < 800:
                    continue
                iid += 1
                inst_arr[comp & (inst_arr == 0)] = iid
                ys, xs = np.where(comp)
                if chars_removed and cname == 'character':
                    inst_arr[inst_arr == iid] = 0
                    iid -= 1
                    continue  # removed from the plate: ground is walkable now
                instances.append({'id': iid, 'label': cname, 'kind':
                                  'character' if cname == 'character' else
                                  ('water' if cname == 'water' else 'structure'),
                                  'blocking': cname != 'pipe',  # ground cables walkable-over
                                  'box': [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
                                  'baseY': int(ys.max())})
    for sweep, what, blocking in ([] if use_nbp else SWEEPS):
        if sweep == 'emissive':
            continue  # emissive derived by HSV threshold below
        print(f'sweep: {sweep}...')
        items = detect_boxes(seg_input, what)
        if sweep == 'structure':  # de-flake: union of two calls, IoU-deduped
            more = detect_boxes(seg_input, what)
            def iou(a, b):
                ay0, ax0, ay1, ax1 = a
                by0, bx0, by1, bx1 = b
                ix = max(0, min(ax1, bx1) - max(ax0, bx0))
                iy = max(0, min(ay1, by1) - max(ay0, by0))
                inter = ix * iy
                ua = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
                return inter / ua if ua else 0
            for m2 in more:
                if all(iou(m2['box'], e['box']) < 0.6 for e in items):
                    items.append(m2)
        print(f'  {len(items)} boxes')
        for it in items:
            ymin, xmin, ymax, xmax = it['box']
            box = [int(xmin / 1000 * OUT_W), int(ymin / 1000 * OUT_H),
                   int(xmax / 1000 * OUT_W), int(ymax / 1000 * OUT_H)]
            if box[2] - box[0] < 8 or box[3] - box[1] < 8:
                continue
            full = grabcut_mask(plate_np_seg, box)
            box_area = (box[2] - box[0]) * (box[3] - box[1])
            if full is None or full.sum() < 0.30 * box_area:
                # GrabCut defeated (glow/low-contrast) -> conservative box fill
                full = np.zeros(plate_np_seg.shape[:2], dtype=bool)
                full[box[1]:box[3], box[0]:box[2]] = True
            if full.sum() < 200:
                continue
            iid += 1
            inst_arr[full & (inst_arr == 0)] = iid
            ys, xs = np.where(inst_arr == iid)
            if len(ys) < 200:
                inst_arr[inst_arr == iid] = 0
                iid -= 1
                continue
            instances.append({
                'id': iid, 'label': it['label'], 'kind': sweep, 'blocking': blocking,
                'box': [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
                'baseY': int(ys.max()),
            })
    # water: deterministic teal-color mask (skipped when NBP mask provides water)
    if use_nbp:
        water = np.zeros((OUT_H, OUT_W), dtype=bool)
        for inst in instances:
            if inst['kind'] == 'water':
                water |= (inst_arr == inst['id'])
    # (legacy fallback below only runs without the NBP mask)
    rgbw = plate_np_seg.astype(np.float32) / 255.0
    if use_nbp:
        rgbw = rgbw  # keep names defined; water already set above
    mxw = rgbw.max(axis=2)
    mnw = rgbw.min(axis=2)
    satw = np.where(mxw > 0, (mxw - mnw) / np.maximum(mxw, 1e-6), 0)
    if not use_nbp:
        b_dom = (rgbw[..., 2] > rgbw[..., 0] * 1.15) & (rgbw[..., 1] > rgbw[..., 0] * 1.05)
        water = b_dom & (satw > 0.28) & (mxw > 0.35) & (mxw < 0.95)
    if not use_nbp:
        import cv2 as _cv2
        wmask = _cv2.morphologyEx(water.astype(np.uint8), _cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        n_w, lab_w = _cv2.connectedComponents(wmask)
        water = np.zeros_like(water)
        for wi in range(1, n_w):
            if (lab_w == wi).sum() > 2500:  # keep large water bodies only
                water |= (lab_w == wi)
        if water.any():
            iid += 1
            inst_arr[water & (inst_arr == 0)] = iid
            ys, xs = np.where(water)
            instances.append({'id': iid, 'label': 'canal water', 'kind': 'water', 'blocking': True,
                              'box': [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
                              'baseY': int(ys.max())})
    print(f'water pixels: {int(water.sum())}')

    # emissive: bright saturated pixels (neon, core, tank glow) by HSV threshold
    import colorsys  # noqa: F401  (documentation only; vectorized below)
    rgbf = plate_np_seg.astype(np.float32) / 255.0
    mx = rgbf.max(axis=2)
    mn = rgbf.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    emissive = (mx > 0.82) & (sat > 0.35)

    # collision: FOOTPRINT mechanic. NBP paints the authoritative footprint
    # mask (nbp_footprint.py, gated): red = the ground area each object
    # physically occupies (base-only for freestanding, full for buildings).
    # Body above the footprint is overhang: occludes but never blocks.
    # Geometric band heuristic below survives only as ungated fallback.
    fppath = os.path.join(ART, 'nbp-footprint.png')
    fpmet = os.path.join(ART, 'nbp-footprint-metrics.json')
    fpmask = None
    if os.path.exists(fppath) and os.path.exists(fpmet) and json.load(open(fpmet)).get('pass'):
        print('using NBP footprint mask (gated)')
        fpmask = np.asarray(Image.open(fppath).convert('L')
                            .resize((OUT_W, OUT_H), Image.NEAREST)) > 127
    nwalk_probe = None
    wpath_p = os.path.join(ART, 'nbp-walk.png')
    if os.path.exists(wpath_p):
        nwalk_probe = np.asarray(Image.open(wpath_p).convert('L')
                                 .resize((OUT_W, OUT_H), Image.NEAREST)) > 127
    blocked = np.zeros((OUT_H, OUT_W), dtype=bool)
    overhang_all = np.zeros((OUT_H, OUT_W), dtype=bool)
    for inst in instances:
        if not inst['blocking']:
            continue
        m = (inst_arr == inst['id'])
        if inst['kind'] == 'water':
            blocked |= m
            continue
        x0b, y0b, x1b, y1b = inst['box']
        # mixed structure FIRST (bridge, railings over deck): when the walk
        # pass says much of the instance interior is standable, it is the
        # authority — the footprint pass thins to nothing on such structures
        # and the nbp-missed fallback would otherwise full-block the deck
        if nwalk_probe is not None:
            iw = float((m & nwalk_probe).sum()) / max(1, int(m.sum()))
            if iw > 0.15:
                blocked |= (m & ~nwalk_probe)
                inst['footprint'] = 'mixed'
                continue
        if fpmask is not None:
            fp = m & fpmask
            cover = float(fp.sum()) / max(1, int(m.sum()))
            if cover < 0.02:
                # NBP painted no base for this object: block it whole rather
                # than let the player walk through it — but the walk pass
                # keeps authority over standable pixels inside (stairs,
                # balconies, flat floor stains)
                blocked |= (m & ~nwalk_probe) if nwalk_probe is not None else m
                inst['footprint'] = 'nbp-missed'
            elif cover > 0.85:
                blocked |= (m & ~nwalk_probe) if nwalk_probe is not None else m
                inst['footprint'] = 'nbp-full'
            else:
                blocked |= fp
                # dilate the liberated body: the painted silhouette OUTLINE is
                # classed as neither object nor floor, so the hidden floor
                # behind glass/columns would be ring-sealed and island-culled
                import cv2 as _cvf
                body = _cvf.dilate((m & ~fp).astype(np.uint8),
                                   np.ones((13, 13), np.uint8)).astype(bool)
                overhang_all |= body
                inst['footprint'] = 'nbp'
            continue
        # mixed structure (bridge): the walk mask already distinguishes its
        # walkable deck from railings — trust it within the instance
        inner_walk = 0.0
        if nwalk_probe is not None:
            inner_walk = float((m & nwalk_probe).sum()) / max(1, int(m.sum()))
        if inner_walk > 0.15:
            blocked |= (m & ~nwalk_probe)
            inst['footprint'] = 'mixed'
            continue
        freestanding = False
        if nwalk_probe is not None and y0b > 20:
            band = nwalk_probe[max(0, y0b - 26):y0b - 4, x0b:x1b + 1]
            freestanding = band.size > 0 and band.mean() > 0.35
        if freestanding:
            fdepth = max(14, int(0.28 * (y1b - y0b)))
            fp = m.copy()
            fp[:max(0, inst['baseY'] - fdepth), :] = False
            blocked |= fp
            # the body above the footprint is overhang: hidden floor the
            # player may walk on while the cutout occludes them
            overhang_all |= (m & ~fp)
            inst['footprint'] = True
        else:
            blocked |= (m & ~nwalk_probe) if nwalk_probe is not None else m
            inst['footprint'] = False
    ohpath = os.path.join(ART, 'overhead.png')
    if os.path.exists(ohpath):
        overhead = np.asarray(Image.open(ohpath).convert('L')
                              .resize((OUT_W, OUT_H), Image.NEAREST)) > 127
        blocked = blocked & ~overhead
        print(f'overhead mask: subtracted {int(overhead.sum())} suspended px from blocked')
    walk_src = ~blocked
    wpath = os.path.join(ART, 'nbp-walk.png')
    wmet = os.path.join(ART, 'nbp-walk-metrics.json')
    if os.path.exists(wpath) and os.path.exists(wmet) and json.load(open(wmet)).get('pass'):
        print('using NBP walkability mask (gated)')
        nwalk = np.asarray(Image.open(wpath).convert('L').resize((OUT_W, OUT_H), Image.NEAREST)) > 127
        # ground cables/pipes are step-over-able: they must not partition the
        # floor into islands — union the pipe class back into walkability
        npb = os.path.join(ART, 'nbp-mask.png')
        if os.path.exists(npb):
            clsb = np.asarray(Image.open(npb).convert('RGB').resize((OUT_W, OUT_H), Image.NEAREST)).astype(np.int16)
            pipes = np.linalg.norm(clsb - np.array([128, 0, 255], np.int16), axis=2) < 90
            # step-over applies to GROUND cables only: a pipe component is
            # step-over-able iff its neighborhood is substantially walkable
            # floor (roof/wall pipes live in all-red context and stay blocked)
            import cv2 as _cvp
            npc_, plab = _cvp.connectedComponents(pipes.astype(np.uint8))
            for pi in range(1, npc_):
                pcomp = (plab == pi)
                ring = _cvp.dilate(pcomp.astype(np.uint8), np.ones((31, 31), np.uint8)).astype(bool) & ~pcomp
                if ring.any() and float((ring & nwalk).sum()) / float(ring.sum()) >= 0.25:
                    nwalk = nwalk | pcomp
        if chars_removed:
            # ground under removed characters is walkable: take the yellow
            # class pixels near each recorded spawn and open them up
            spawns_d = json.load(open(spawns_f))
            import cv2 as _cvc
            nbp2 = np.asarray(Image.open(nbp_path).convert('RGB').resize((OUT_W, OUT_H), Image.NEAREST)).astype(np.int16)
            ym = (np.linalg.norm(nbp2 - np.array([255, 255, 0], np.int16), axis=2) < 90).astype(np.uint8)
            for sp in spawns_d:
                sxs = int(sp['x'] * OUT_W / 640)
                sys2 = int(sp['y'] * OUT_H / 448)
                r = 130
                y0r, y1r = max(0, sys2 - 2 * r), min(OUT_H, sys2 + r // 2)
                x0r, x1r = max(0, sxs - r), min(OUT_W, sxs + r)
                cm = np.zeros_like(ym)
                cm[y0r:y1r, x0r:x1r] = ym[y0r:y1r, x0r:x1r]
                cm = _cvc.dilate(cm, np.ones((35, 35), np.uint8)).astype(bool)
                nwalk = nwalk | cm
        walk_src = (nwalk | overhang_all) & ~blocked
    import cv2 as _cv
    # grates/slatted decks: thin dark lines fragment the mask — close them
    walk_src = _cv.morphologyEx(walk_src.astype(np.uint8), _cv.MORPH_CLOSE,
                                np.ones((9, 9), np.uint8)).astype(bool) & ~blocked

    red_solid = _cv.morphologyEx((~walk_src).astype(np.uint8), _cv.MORPH_OPEN,
                                 np.ones((11, 11), np.uint8)).astype(bool)
    thin_red = ~walk_src & ~red_solid
    near_walk = _cv.dilate(walk_src.astype(np.uint8), np.ones((13, 13), np.uint8)).astype(bool)
    walk_src = walk_src | (thin_red & near_walk)
    # island connector: large walkable islands (bridge deck!) get a corridor
    # to the main region, routed ONLY through class-mask floor pixels — can
    # cross a red-marked shore strip, can never tunnel through buildings/water
    ncc2, lab2 = _cv.connectedComponents(walk_src.astype(np.uint8))
    if ncc2 > 2:
        sizes = [(lab2 == i).sum() for i in range(1, ncc2)]
        main_id = 1 + int(np.argmax(sizes))
        floor_ok = np.zeros_like(walk_src)
        npb2 = os.path.join(ART, 'nbp-mask.png')
        if os.path.exists(npb2):
            clsb2 = np.asarray(Image.open(npb2).convert('RGB').resize((OUT_W, OUT_H), Image.NEAREST)).astype(np.int16)
            floor_ok = (np.linalg.norm(clsb2 - np.array([0, 255, 0], np.int16), axis=2) < 90) & ~blocked
        allowed = walk_src | floor_ok
        globals()['CARVE_LEGAL'] = allowed.copy()
        stp = 8
        lath, latw = OUT_H // stp, OUT_W // stp
        lat_ok = np.zeros((lath, latw), dtype=bool)
        lat_lab = np.zeros((lath, latw), dtype=np.int32)
        for ly2 in range(lath):
            for lx2 in range(latw):
                blk = allowed[ly2 * stp:(ly2 + 1) * stp, lx2 * stp:(lx2 + 1) * stp]
                lat_ok[ly2, lx2] = blk.mean() > 0.5
                lat_lab[ly2, lx2] = lab2[min(OUT_H - 1, ly2 * stp + stp // 2), min(OUT_W - 1, lx2 * stp + stp // 2)]
        from collections import deque
        for isl in range(1, ncc2):
            if isl == main_id or sizes[isl - 1] < 5000:
                continue
            starts = [(x, y) for y in range(lath) for x in range(latw) if lat_lab[y, x] == main_id and lat_ok[y, x]]
            if not starts:
                break
            prev = {}
            qq = deque(starts[::37] or starts[:1])
            vis = set(qq)
            goal = None
            while qq and goal is None:
                cx3, cy3 = qq.popleft()
                for dx3, dy3 in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx3, ny3 = cx3 + dx3, cy3 + dy3
                    if 0 <= nx3 < latw and 0 <= ny3 < lath and lat_ok[ny3, nx3] and (nx3, ny3) not in vis:
                        vis.add((nx3, ny3))
                        prev[(nx3, ny3)] = (cx3, cy3)
                        if lat_lab[ny3, nx3] == isl:
                            goal = (nx3, ny3)
                            break
                        qq.append((nx3, ny3))
            if goal:
                node = goal
                while node in prev:
                    gx, gy = node
                    y0c, x0c = max(0, gy * stp - 8), max(0, gx * stp - 8)
                    patch = allowed[y0c:gy * stp + stp + 8, x0c:gx * stp + stp + 8]
                    walk_src[y0c:gy * stp + stp + 8, x0c:gx * stp + stp + 8] |= patch
                    node = prev[node]
                print(f'connected island {isl} ({sizes[isl - 1]}px) to main region')
    walk = Image.fromarray((walk_src * 255).astype(np.uint8))
    if not use_nbp:
        walk = walk.filter(ImageFilter.MinFilter(3))  # nbp path erodes pre-connector
    walk_arr = np.asarray(walk) > 127
    # border walls
    walk_arr[:8, :] = False
    walk_arr[-8:, :] = False
    walk_arr[:, :8] = False
    walk_arr[:, -8:] = False

    # pixel BFS gate on a 4px lattice (device px; logical = /2)
    step = max(8, round(8 * OUT_W / 1280))
    src_per_logical = OUT_W / 640
    if AUTO_SPAWN:
        # spawn = deepest point of the largest walkable region (max clearance)
        import cv2 as _cvs
        nsp, lsp = _cvs.connectedComponents(walk_arr.astype(np.uint8))
        if nsp > 1:
            big = 1 + int(np.argmax([(lsp == i).sum() for i in range(1, nsp)]))
            dt = _cvs.distanceTransform((lsp == big).astype(np.uint8), _cvs.DIST_L2, 5)
            syp, sxp = np.unravel_index(int(dt.argmax()), dt.shape)
            globals()['SPAWN_PX'] = (int(sxp / src_per_logical), int(syp / src_per_logical))
            print(f'auto-spawn at logical {SPAWN_PX} (clearance {dt.max():.0f}px)')
    sx, sy = int(SPAWN_PX[0] * src_per_logical) // step, int(SPAWN_PX[1] * src_per_logical) // step
    lat_w, lat_h = OUT_W // step, OUT_H // step
    lat = np.zeros((lat_h, lat_w), dtype=bool)
    for ly in range(lat_h):
        for lx in range(lat_w):
            lat[ly, lx] = walk_arr[ly * step:(ly + 1) * step, lx * step:(lx + 1) * step].mean() > 0.6
    if not lat[sy, sx]:
        sys.exit(f'spawn not walkable at lattice {sx},{sy} — adjust SPAWN_PX')
    seen = {(sx, sy)}
    q = [(sx, sy)]
    while q:
        x, y = q.pop()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < lat_w and 0 <= ny < lat_h and lat[ny, nx] and (nx, ny) not in seen:
                seen.add((nx, ny))
                q.append((nx, ny))
    ex0, ey0, ex1, ey1 = [int(v * src_per_logical) // step for v in EXIT_RECT]
    exit_ok = any((x, y) in seen for y in range(ey0, ey1 + 1) for x in range(ex0, ex1 + 1))
    # zero-island guarantee: keep only the spawn's connected component
    import cv2 as _cvz
    nz, lz = _cvz.connectedComponents(walk_arr.astype(np.uint8))
    sx_px, sy_px = int(SPAWN_PX[0] * src_per_logical), int(SPAWN_PX[1] * src_per_logical)
    keep = lz[min(OUT_H - 1, sy_px), min(OUT_W - 1, sx_px)]
    if keep > 0:
        walk_arr = (lz == keep)
    # multi-edge exits (per rooms.json): a walkable strip near each exit edge,
    # detected if present, carved to the edge center if not
    EXITS_OUT = []
    if EXIT_EDGES:
        margin = int(40 * src_per_logical / 3.75)
        probe_f = os.path.join(ART, 'exit-probe.json')
        probes = json.load(open(probe_f)) if os.path.exists(probe_f) else {}
        for edge in EXIT_EDGES:
            if edge in ('n', 's'):
                band = walk_arr[8:8 + margin, :] if edge == 'n' else walk_arr[OUT_H - margin - 8:OUT_H - 8, :]
                ok_idx = np.where(band.any(axis=0))[0]
            else:
                band = walk_arr[:, 8:8 + margin] if edge == 'w' else walk_arr[:, OUT_W - margin - 8:OUT_W - 8]
                ok_idx = np.where(band.any(axis=1))[0]
            if len(ok_idx) < int(24 * src_per_logical):
                # carve toward the LLM-located passage on this edge (never
                # the blind edge center — that painted stripes through walls)
                pr = probes.get(edge)
                if pr:
                    pc = int((pr['lo'] + pr['hi']) / 2 * src_per_logical)
                else:
                    pc = OUT_W // 2 if edge in ('n', 's') else OUT_H // 2
                if edge == 'n':
                    tgt = (pc // step, 2)
                elif edge == 's':
                    tgt = (pc // step, (OUT_H - 12) // step)
                elif edge == 'w':
                    tgt = (2, pc // step)
                else:
                    tgt = ((OUT_W - 12) // step, pc // step)
                nx0, ny0 = min(seen, key=lambda t: abs(t[0] - tgt[0]) + abs(t[1] - tgt[1]))
                xC, yC = nx0, ny0
                ptsC = []
                while xC != tgt[0]:
                    xC += 1 if tgt[0] > xC else -1
                    ptsC.append((xC, yC))
                while yC != tgt[1]:
                    yC += 1 if tgt[1] > yC else -1
                    ptsC.append((xC, yC))
                legalC = globals().get('CARVE_LEGAL')
                for cxe, cye in ptsC:
                    sl = (slice(max(0, cye * step - 16), cye * step + 24),
                          slice(max(0, cxe * step - 16), cxe * step + 24))
                    if legalC is not None:
                        walk_arr[sl] |= legalC[sl]
                    else:
                        walk_arr[sl] = True
                walk_arr[:8, :] = False
                walk_arr[-8:, :] = False
                walk_arr[:, :8] = False
                walk_arr[:, -8:] = False
                if edge in ('n', 's'):
                    band = walk_arr[8:8 + margin, :] if edge == 'n' else walk_arr[OUT_H - margin - 8:OUT_H - 8, :]
                    ok_idx = np.where(band.any(axis=0))[0]
                else:
                    band = walk_arr[:, 8:8 + margin] if edge == 'w' else walk_arr[:, OUT_W - margin - 8:OUT_W - 8]
                    ok_idx = np.where(band.any(axis=1))[0]
                print(f'exit edge {edge}: carved corridor to border')
            if len(ok_idx) == 0:
                print(f'exit edge {edge}: NO reachable strip even after legal carve — '
                      'passage must be painted into the plate (edit_exit.py); skipping')
                continue
            lo, hi = int(ok_idx.min() / src_per_logical), int(ok_idx.max() / src_per_logical)
            # confine the warp strip to the located passage (a whole-edge
            # detected strip would otherwise warp from anywhere on that edge)
            prc = probes.get(edge)
            if prc:
                lo2, hi2 = max(lo, prc['lo'] - 24), min(hi, prc['hi'] + 24)
                if hi2 > lo2:
                    lo, hi = lo2, hi2
            if edge == 'n':
                rect = (lo, 0, hi, 18)
            elif edge == 's':
                rect = (lo, 430, hi, 447)
            elif edge == 'w':
                rect = (0, lo, 18, hi)
            else:
                rect = (622, lo, 640, hi)
            EXITS_OUT.append({'edge': edge, 'rect': list(rect)})
            print(f'exit edge {edge}: strip {lo}..{hi} (logical)')
        # spawn must reach an exit: if not, move spawn into the exit's component
        if AUTO_SPAWN and EXITS_OUT:
            import cv2 as _cvx
            nse, lse = _cvx.connectedComponents(walk_arr.astype(np.uint8))
            spid = lse[min(OUT_H - 1, int(SPAWN_PX[1] * src_per_logical)),
                       min(OUT_W - 1, int(SPAWN_PX[0] * src_per_logical))]
            e0 = EXITS_OUT[0]['rect']
            exp_ = lse[min(OUT_H - 1, int((e0[1] + e0[3]) / 2 * src_per_logical)),
                       min(OUT_W - 1, int((e0[0] + e0[2]) / 2 * src_per_logical))]
            if exp_ == 0:
                ys0, xs0 = np.where(walk_arr)
                if len(ys0):
                    ex_cx = int((e0[0] + e0[2]) / 2 * src_per_logical)
                    ex_cy = int((e0[1] + e0[3]) / 2 * src_per_logical)
                    k0 = ((ys0 - ex_cy) ** 2 + (xs0 - ex_cx) ** 2).argmin()
                    exp_ = lse[ys0[k0], xs0[k0]]
            if spid != exp_ and exp_ > 0:
                dtx = _cvx.distanceTransform((lse == exp_).astype(np.uint8), _cvx.DIST_L2, 5)
                syq, sxq = np.unravel_index(int(dtx.argmax()), dtx.shape)
                globals()['SPAWN_PX'] = (int(sxq / src_per_logical), int(syq / src_per_logical))
                sy_px, sx_px = syq, sxq
                print(f'spawn moved into exit component: logical {SPAWN_PX}')
    # legacy single auto-exit (anchor room): reachable strip on bottom border
    band = walk_arr[OUT_H - 40:OUT_H - 8, :]
    cols_ok = np.where(band.any(axis=0))[0]
    if LEGACY_S and len(cols_ok) > 20:
        exl = int(cols_ok.min() / src_per_logical)
        exr = int(cols_ok.max() / src_per_logical)
        globals()['EXIT_RECT'] = (exl, 430, exr, 447)
        print(f'auto-exit selected on bottom border: x {exl}..{exr}')
    frac = walk_arr.mean()
    print(f'walkable fraction: {frac:.2f}; lattice reachable: {len(seen)}; exit reachable: {exit_ok}')
    assert 0.15 < frac < 0.8, 'walkable fraction out of bounds'
    if LEGACY_S and not exit_ok:
        # carve: straight ramp from nearest reachable lattice cell to exit center
        tx, ty = (ex0 + ex1) // 2, (ey0 + ey1) // 2
        nx, ny = min(seen, key=lambda t: abs(t[0] - tx) + abs(t[1] - ty))
        print(f'carving exit corridor from lattice {nx},{ny}')
        x, y = nx, ny
        pts = []
        while x != tx:
            x += 1 if tx > x else -1
            pts.append((x, y))
        while y != ty:
            y += 1 if ty > y else -1
            pts.append((x, y))
        legalL = globals().get('CARVE_LEGAL')
        for cx2, cy2 in pts:
            sl = (slice(max(0, cy2 * step - 12), cy2 * step + 20),
                  slice(max(0, cx2 * step - 12), cx2 * step + 20))
            if legalL is not None:
                walk_arr[sl] |= legalL[sl]
            else:
                walk_arr[sl] = True

    # CONFIG-SPACE guarantee: the player hitbox is 8x8 logical px, so pixel
    # connectivity is not traversability (bridge posts leave gaps a box can't
    # thread). Erode by the hitbox; every sizable region must be box-reachable
    # from spawn, else carve a box-wide corridor along a floor-routed path.
    hb = int(np.ceil(10 * src_per_logical)) + 2  # comfort clearance beyond the 8px hitbox
    half = hb  # corridors a full hitbox wider than minimum — forgiving lanes
    # pinprick blocked speckles (< ~10x10 logical) enclosed by walkable are
    # mask noise, not object bases — the smallest real prop is ~5x larger
    invw = (~walk_arr).astype(np.uint8)
    ninv, linv, statsv, _ = _cvz.connectedComponentsWithStats(invw)
    for ii in range(1, ninv):
        if statsv[ii, _cvz.CC_STAT_AREA] < 1500:
            walk_arr[linv == ii] = True
    # walk-pass reference: rescue-eligibility + corridor routing surface
    nwalk_ref = np.zeros_like(walk_arr)
    wref = os.path.join(ART, 'nbp-walk.png')
    if os.path.exists(wref):
        nwalk_ref = np.asarray(Image.open(wref).convert('L')
                               .resize((OUT_W, OUT_H), Image.NEAREST)) > 127
    cls_floor = np.zeros_like(walk_arr)
    npbc = os.path.join(ART, 'nbp-mask.png')
    if os.path.exists(npbc):
        clsc = np.asarray(Image.open(npbc).convert('RGB').resize((OUT_W, OUT_H), Image.NEAREST)).astype(np.int16)
        cls_floor = np.linalg.norm(clsc - np.array([0, 255, 0], np.int16), axis=2) < 90
    for cs_round in range(4):
        free = _cvz.erode(walk_arr.astype(np.uint8), np.ones((hb, hb), np.uint8)).astype(bool)
        nf, lf = _cvz.connectedComponents(free.astype(np.uint8))
        sfid = lf[min(OUT_H - 1, sy_px), min(OUT_W - 1, sx_px)]
        if sfid == 0:
            ysf, xsf = np.where(free)
            if not len(ysf):
                break
            kf = ((ysf - sy_px) ** 2 + (xsf - sx_px) ** 2).argmin()
            sfid = lf[ysf[kf], xsf[kf]]
        pending = [ci for ci in range(1, nf)
                   if ci != sfid and (lf == ci).sum() >= 4000
                   and ((lf == ci) & nwalk_ref).sum() >= 1500]
        if not pending:
            print(f'config-space: all regions box-reachable (round {cs_round})')
            break
        allowedc = walk_arr | ((cls_floor | nwalk_ref) & ~water)
        stpc = 8
        lathc, latwc = OUT_H // stpc, OUT_W // stpc
        lat_okc = np.zeros((lathc, latwc), dtype=bool)
        lat_regc = np.zeros((lathc, latwc), dtype=np.int32)
        for lyc in range(lathc):
            for lxc in range(latwc):
                lat_okc[lyc, lxc] = allowedc[lyc * stpc:(lyc + 1) * stpc,
                                             lxc * stpc:(lxc + 1) * stpc].mean() > 0.5
                lat_regc[lyc, lxc] = lf[min(OUT_H - 1, lyc * stpc + stpc // 2),
                                        min(OUT_W - 1, lxc * stpc + stpc // 2)]
        from collections import deque as _dq
        carved_any = False
        for ci in pending:
            starts = [(x, y) for y in range(lathc) for x in range(latwc)
                      if lat_regc[y, x] == sfid and lat_okc[y, x]]
            if not starts:
                break
            prevc, visc = {}, set(starts[::31] or starts[:1])
            qc = _dq(visc)
            goalc = None
            while qc and goalc is None:
                cxq, cyq = qc.popleft()
                for dxq, dyq in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nxq, nyq = cxq + dxq, cyq + dyq
                    if 0 <= nxq < latwc and 0 <= nyq < lathc and lat_okc[nyq, nxq] \
                            and (nxq, nyq) not in visc:
                        visc.add((nxq, nyq))
                        prevc[(nxq, nyq)] = (cxq, cyq)
                        if lat_regc[nyq, nxq] == ci:
                            goalc = (nxq, nyq)
                            break
                        qc.append((nxq, nyq))
            if goalc:
                node = goalc
                while node in prevc:
                    gx, gy = node
                    cyp, cxp = gy * stpc + stpc // 2, gx * stpc + stpc // 2
                    sl = (slice(max(0, cyp - half), cyp + half),
                          slice(max(0, cxp - half), cxp + half))
                    walk_arr[sl] |= allowedc[sl]
                    node = prevc[node]
                carved_any = True
                print(f'config-space: carved box-wide corridor to region {ci} '
                      f'({int((lf == ci).sum())}px)')
        if not carved_any:
            print('config-space: no corridor could be routed; leaving as-is')
            break

    # EXIT MOUTH STUBS: walk masks rarely touch the frame border, so the
    # trigger strip can sit isolated behind a few blocked rows. Carve a short
    # forced ramp (the exit threshold at the LLM-located passage) from the
    # nearest reachable pixel to the border, inside the strip range.
    if EXITS_OUT:
        nst, lst = _cvz.connectedComponents(walk_arr.astype(np.uint8))
        sst = lst[min(OUT_H - 1, sy_px), min(OUT_W - 1, sx_px)]
        if sst == 0:
            yss, xss = np.where(walk_arr)
            if len(yss):
                ks = ((yss - sy_px) ** 2 + (xss - sx_px) ** 2).argmin()
                sst = lst[yss[ks], xss[ks]]
        stub_w = hb + int(8 * src_per_logical)
        depth_lim = int(60 * src_per_logical)
        for e in EXITS_OUT:
            x0e, y0e, x1e, y1e = [int(v * src_per_logical) for v in e['rect']]
            if e['edge'] in ('n', 's'):
                xr = slice(max(0, x0e), min(OUT_W, x1e + 1))
                band = slice(0, depth_lim) if e['edge'] == 'n' else slice(OUT_H - depth_lim, OUT_H)
                sub = (lst[band, xr] == sst) & (sst > 0)
                if not sub.any():
                    continue
                ys3, xs3 = np.where(sub)
                pick = ys3.argmin() if e['edge'] == 'n' else ys3.argmax()
                px3 = xs3[pick] + xr.start
                py3 = ys3[pick] + band.start
                yb = 0 if e['edge'] == 'n' else OUT_H
                y_lo, y_hi = (0, py3 + stub_w) if e['edge'] == 'n' else (py3 - stub_w, OUT_H)
                walk_arr[max(0, y_lo):min(OUT_H, y_hi),
                         max(0, px3 - stub_w // 2):min(OUT_W, px3 + stub_w // 2)] = True
            else:
                yr = slice(max(0, y0e), min(OUT_H, y1e + 1))
                band = slice(0, depth_lim) if e['edge'] == 'w' else slice(OUT_W - depth_lim, OUT_W)
                sub = (lst[yr, band] == sst) & (sst > 0)
                if not sub.any():
                    continue
                ys3, xs3 = np.where(sub)
                pick = xs3.argmin() if e['edge'] == 'w' else xs3.argmax()
                py3 = ys3[pick] + yr.start
                px3 = xs3[pick] + band.start
                x_lo, x_hi = (0, px3 + stub_w) if e['edge'] == 'w' else (px3 - stub_w, OUT_W)
                walk_arr[max(0, py3 - stub_w // 2):min(OUT_H, py3 + stub_w // 2),
                         max(0, x_lo):min(OUT_W, x_hi)] = True
            print(f'exit edge {e["edge"]}: mouth stub carved to border')
        # narrow each exit rect to the columns/rows that actually reach the
        # border zone — a whole-edge rect makes center approaches stall
        deep = int(8 + 14 * src_per_logical)
        for e in EXITS_OUT:
            if e['edge'] == 'n':
                bandd = walk_arr[8:deep, :]
                okd = np.where(bandd.any(axis=0))[0]
            elif e['edge'] == 's':
                bandd = walk_arr[OUT_H - deep:OUT_H - 8, :]
                okd = np.where(bandd.any(axis=0))[0]
            elif e['edge'] == 'w':
                bandd = walk_arr[:, 8:deep]
                okd = np.where(bandd.any(axis=1))[0]
            else:
                bandd = walk_arr[:, OUT_W - deep:OUT_W - 8]
                okd = np.where(bandd.any(axis=1))[0]
            if len(okd) == 0:
                continue
            lo2, hi2 = int(okd.min() / src_per_logical), int(okd.max() / src_per_logical)
            r0 = e['rect']
            if e['edge'] in ('n', 's'):
                e['rect'] = [lo2, r0[1], hi2, r0[3]]
            else:
                e['rect'] = [r0[0], lo2, r0[2], hi2]
            print(f'exit edge {e["edge"]}: rect narrowed to {lo2}..{hi2}')

    # EXIT VALIDITY: an exit is real only if the player box can reach its
    # trigger strip from spawn; phantom exits are dropped and reported
    if EXITS_OUT:
        freeV = _cvz.erode(walk_arr.astype(np.uint8), np.ones((hb, hb), np.uint8)).astype(bool)
        nfv, lfv = _cvz.connectedComponents(freeV.astype(np.uint8))
        sidv = lfv[min(OUT_H - 1, sy_px), min(OUT_W - 1, sx_px)]
        if sidv == 0:
            ysv, xsv = np.where(freeV)
            if len(ysv):
                kv = ((ysv - sy_px) ** 2 + (xsv - sx_px) ** 2).argmin()
                sidv = lfv[ysv[kv], xsv[kv]]
        kept = []
        for e in EXITS_OUT:
            x0e, y0e, x1e, y1e = [int(v * src_per_logical) for v in e['rect']]
            # widen the probe band inward: the player stands NEAR the strip
            pad_in = int(26 * src_per_logical)
            if e['edge'] == 'n':
                y1e += pad_in
            elif e['edge'] == 's':
                y0e -= pad_in
            elif e['edge'] == 'w':
                x1e += pad_in
            else:
                x0e -= pad_in
            zone = lfv[max(0, y0e):min(OUT_H, y1e + 1), max(0, x0e):min(OUT_W, x1e + 1)]
            if sidv > 0 and (zone == sidv).any():
                kept.append(e)
            else:
                print(f'exit edge {e["edge"]}: PHANTOM (strip not box-reachable) — dropped')
        EXITS_OUT[:] = kept

    # outputs — masks computed at source res, saved at device res (1280x896)
    DEV_W, DEV_H = 1280, 896
    rooms_dir = os.path.join(ROOT, 'assets', 'rooms')
    os.makedirs(rooms_dir, exist_ok=True)
    Image.fromarray((walk_arr * 255).astype(np.uint8)).resize((DEV_W, DEV_H), Image.LANCZOS)\
        .point(lambda v: 255 if v > 127 else 0).save(os.path.join(rooms_dir, f'{NAME}.collision.png'))
    Image.fromarray((emissive * 255).astype(np.uint8)).resize((DEV_W, DEV_H), Image.LANCZOS)\
        .save(os.path.join(rooms_dir, f'{NAME}.emissive.png'))
    # save source-space masks for board visualization
    np.savez_compressed(os.path.join(ROOT, 'tools', 'art-pipeline', f'_srcmasks_{NAME}.npz'),
                        inst=inst_arr, walk=walk_arr, emissive=emissive, water=water)
    json.dump(instances, open(os.path.join(ROOT, 'tools', 'art-pipeline', f'_srcinst_{NAME}.json'), 'w'))
    dsx, dsy = DEV_W / OUT_W, DEV_H / OUT_H
    plate_np = np.asarray(plate)
    fg_meta = []
    for inst in instances:
        if not inst['blocking'] or inst['kind'] == 'water':
            continue
        x0, y0, x1, y1 = inst['box']
        m = (inst_arr[y0:y1 + 1, x0:x1 + 1] == inst['id'])
        cut = np.zeros((y1 - y0 + 1, x1 - x0 + 1, 4), dtype=np.uint8)
        cut[..., :3] = plate_np_seg[y0:y1 + 1, x0:x1 + 1]
        cut[..., 3] = m * 255
        ci = Image.fromarray(cut)
        ci = ci.resize((max(1, round(ci.width * dsx)), max(1, round(ci.height * dsy))), Image.LANCZOS)
        fn = f'{NAME}.fg{inst["id"]}.png'
        ci.save(os.path.join(rooms_dir, fn))
        fg_meta.append({'img': f'rooms/{fn}', 'x': round(x0 * dsx), 'y': round(y0 * dsy),
                        'baseY': round(inst['baseY'] * dsy),
                        'label': inst['label'], 'kind': inst['kind']})
    json.dump({'spawn': list(SPAWN_PX), 'exit': list(EXIT_RECT), 'exits': EXITS_OUT,
               'plateHash': plate_hash,
               'fg': fg_meta,
               'instances': [{k: v for k, v in i.items()} for i in instances]},
              open(os.path.join(rooms_dir, f'{NAME}.instances.json'), 'w'))

    return  # debug overlay removed per direction
    dbg = plate.copy()
    dd = ImageDraw.Draw(dbg, 'RGBA')
    red = np.zeros((OUT_H, OUT_W, 4), dtype=np.uint8)
    red[~walk_arr] = (255, 40, 40, 80)
    dbg = Image.alpha_composite(dbg.convert('RGBA'), Image.fromarray(red))
    dd = ImageDraw.Draw(dbg)
    for inst in instances:
        x0, y0, x1, y1 = inst['box']
        dd.rectangle([x0, y0, x1, y1], outline=(0, 255, 255), width=1)
        dd.line([(x0, inst['baseY']), (x1, inst['baseY'])], fill=(255, 255, 0), width=2)
    dbg.convert('RGB').save(os.path.join(ROOT, 'docs', 'art-options', f'{NAME}-pixseg-debug.png'))
    print(f'{len(instances)} instances, {len(fg_meta)} fg cutouts emitted')


if __name__ == '__main__':
    main()
