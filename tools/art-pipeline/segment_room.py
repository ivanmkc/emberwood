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
OUT_W, OUT_H = 1280, 896      # device px (logical 640x448 at DS=2)
SPAWN_PX = (320, 330)          # logical px, plaza floor
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
    plate_full = Image.open(PLATE).convert('RGB')
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
    for sweep, what, blocking in SWEEPS:
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
    # water: deterministic teal-color mask (detection is run-variant; color is not)
    rgbw = plate_np_seg.astype(np.float32) / 255.0
    mxw = rgbw.max(axis=2)
    mnw = rgbw.min(axis=2)
    satw = np.where(mxw > 0, (mxw - mnw) / np.maximum(mxw, 1e-6), 0)
    b_dom = (rgbw[..., 2] > rgbw[..., 0] * 1.15) & (rgbw[..., 1] > rgbw[..., 0] * 1.05)
    water = b_dom & (satw > 0.28) & (mxw > 0.35) & (mxw < 0.95)
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

    # collision: blocked = any blocking instance; walkable eroded for safety
    blocked = np.zeros((OUT_H, OUT_W), dtype=bool)
    for inst in instances:
        if inst['blocking']:
            blocked |= (inst_arr == inst['id'])
    walk = Image.fromarray((~blocked * 255).astype(np.uint8))
    walk = walk.filter(ImageFilter.MinFilter(7))  # erode walkable ~3px
    walk_arr = np.asarray(walk) > 127
    # border walls
    walk_arr[:8, :] = False
    walk_arr[-8:, :] = False
    walk_arr[:, :8] = False
    walk_arr[:, -8:] = False

    # pixel BFS gate on a 4px lattice (device px; logical = /2)
    step = max(8, round(8 * OUT_W / 1280))
    src_per_logical = OUT_W / 640
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
    frac = walk_arr.mean()
    print(f'walkable fraction: {frac:.2f}; lattice reachable: {len(seen)}; exit reachable: {exit_ok}')
    assert 0.15 < frac < 0.8, 'walkable fraction out of bounds'
    if not exit_ok:
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
        for cx2, cy2 in pts:
            walk_arr[cy2 * step - 12:cy2 * step + 20, cx2 * step - 12:cx2 * step + 20] = True

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
    dscale = DEV_W / OUT_W
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
        ci = ci.resize((max(1, round(ci.width * dscale)), max(1, round(ci.height * dscale))), Image.LANCZOS)
        fn = f'{NAME}.fg{inst["id"]}.png'
        ci.save(os.path.join(rooms_dir, fn))
        fg_meta.append({'img': f'rooms/{fn}', 'x': round(x0 * dscale), 'y': round(y0 * dscale),
                        'baseY': round(inst['baseY'] * dscale),
                        'label': inst['label'], 'kind': inst['kind']})
    json.dump({'spawn': list(SPAWN_PX), 'exit': list(EXIT_RECT), 'fg': fg_meta,
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
