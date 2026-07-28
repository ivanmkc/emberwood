#!/usr/bin/env python3
"""v4 mask algorithm: geometric footprints (literature: Watson CVPR2020 Footprints,
MonoLayout WACV2020).

Reuses v3's proven census + impeding-selection stages.  Replaces the x-ray
painting stage with VLM-estimated NUMBERS + CODE-DRAWN footprints:

  per impeding instance:
    1. Crop + draw 16-logical-px gridlines (labeled axes every 4 cells)
    2. VLM estimates ground_contact {x0, x1, yBase}, plan_depth_px, base_shape
    3. Code draws the footprint polygon on the crop
    4. LLM gate views the drawn overlay ("plausible full plan footprint?")
       with median-of-3; retry with critique fed back (reflective)
    5. Deterministic sanity gates: yBase in lower third, plan_depth in
       [0.15, 1.2] x instance width for freestanding objects

The gridline conditioning comes from Ivan's directive and has analogues in the
literature: per-pixel coordinate conditioning (Curved Diffusion), layout-region
conditioning (LayoutDiffusion), and the proven nbp_grid_walk.py approach.

Usage: nbp_v4.py <room> [--no-grid] [--resume]
  --no-grid   disables gridlines for A/B comparison
  --resume    skip census/select, load cached instance data from v3
"""
import io
import json
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
from PIL import Image, ImageDraw
from google import genai
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

GRID_PITCH = 16

_tl = threading.local()


def cli():
    if not hasattr(_tl, 'c'):
        _tl.c = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
    return _tl.c


def gen_image(contents, size='2K'):
    for _ in range(3):
        try:
            resp = cli().models.generate_content(
                model='gemini-3-pro-image', contents=contents,
                config=types.GenerateContentConfig(
                    image_config=types.ImageConfig(aspect_ratio='4:3', image_size=size)))
            for part in (resp.parts or []):
                if part.inline_data is not None:
                    return Image.open(io.BytesIO(part.inline_data.data)).convert('RGB')
        except Exception:  # noqa: BLE001
            pass
    return None


def ask_json(contents, maxtok=8192):
    for _ in range(3):
        try:
            r = cli().models.generate_content(
                model='gemini-3.1-pro-preview', contents=contents,
                config=types.GenerateContentConfig(max_output_tokens=maxtok))
            t = r.text or ''
            st = min([i for i in (t.find('['), t.find('{')) if i >= 0], default=-1)
            if st >= 0:
                v, _ = json.JSONDecoder().raw_decode(t[st:])
                return v
        except Exception:  # noqa: BLE001
            pass
    return None


def draw_gridlines(img_pil, pitch_px):
    """Draw gridlines with labeled axes every 4 cells."""
    draw = ImageDraw.Draw(img_pil)
    W, H = img_pil.size
    cols = W // pitch_px
    rows = H // pitch_px

    for gx in range(1, cols):
        x = gx * pitch_px
        color = (200, 200, 200) if gx % 4 != 0 else (255, 255, 0)
        width = 1 if gx % 4 != 0 else 2
        draw.line([(x, 0), (x, H)], fill=color, width=width)
        if gx % 4 == 0:
            draw.text((x + 2, 2), str(gx), fill=(255, 255, 0))

    for gy in range(1, rows):
        y = gy * pitch_px
        color = (200, 200, 200) if gy % 4 != 0 else (255, 255, 0)
        width = 1 if gy % 4 != 0 else 2
        draw.line([(0, y), (W, y)], fill=color, width=width)
        if gy % 4 == 0:
            draw.text((2, y + 2), str(gy), fill=(255, 255, 0))

    return img_pil


def draw_footprint(crop_w, crop_h, contact, depth_px, shape):
    """Draw a footprint polygon given geometric parameters.

    In our fixed axis-aligned 3/4 camera, BEV projection is a pure y-shift:
    the footprint extends from the visible front base line UPWARD by plan_depth.
    """
    mask = np.zeros((crop_h, crop_w), dtype=np.uint8)
    x0 = max(0, min(crop_w - 1, int(contact['x0'])))
    x1 = max(0, min(crop_w - 1, int(contact['x1'])))
    yBase = max(0, min(crop_h - 1, int(contact['yBase'])))
    yTop = max(0, yBase - int(depth_px))

    if x0 > x1:
        x0, x1 = x1, x0
    if x1 - x0 < 4:
        return mask > 0

    if shape == 'ellipse':
        cx = (x0 + x1) // 2
        cy = (yTop + yBase) // 2
        ax = (x1 - x0) // 2
        ay = (yBase - yTop) // 2
        if ax > 1 and ay > 1:
            cv2.ellipse(mask, (cx, cy), (ax, ay), 0, 0, 360, 255, -1)
    else:
        cv2.rectangle(mask, (x0, yTop), (x1, yBase), 255, -1)

    return mask > 0


def estimate_geometry(crop_pil, inst_mask_crop, name, use_grid, critique=''):
    """Ask the VLM for ground_contact, plan_depth_px, base_shape."""
    W, H = crop_pil.size
    input_img = crop_pil.copy()

    edge = cv2.dilate(inst_mask_crop.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool) & ~inst_mask_crop
    marked = np.asarray(input_img).copy()
    marked[edge] = (0, 255, 255)
    input_img = Image.fromarray(marked)

    if use_grid:
        input_img = draw_gridlines(input_img, GRID_PITCH)

    grid_note = (
        f' The image has a grid drawn on it with {GRID_PITCH}px pitch (yellow lines with '
        f'numbers label every 4th cell). Use the grid to give pixel-accurate estimates. '
        f'The image is {W}x{H} pixels.'
    ) if use_grid else f' The image is {W}x{H} pixels.'

    critique_note = (
        f'\n\nYour previous estimate was rejected: {critique}\nAdjust accordingly.'
    ) if critique else ''

    prompt = (
        f'The object outlined in cyan is: "{name}". This is a 3/4 top-down view '
        f'(axis-aligned, camera looks down at roughly 30-40 degrees from above).{grid_note}'
        f'\n\nEstimate the GROUND FOOTPRINT geometry of this object — the area of floor it '
        f'physically occupies, INCLUDING the hidden part behind/under its body. In this '
        f'camera view the footprint extends from the visible front base line UPWARD on '
        f'screen by the object\'s plan depth (BEV depth projected into screen coords).'
        f'\n\nReturn JSON ONLY with these fields:'
        f'\n  "ground_contact": {{"x0": <left edge px>, "x1": <right edge px>, '
        f'"yBase": <bottom of ground contact in pixels from top>}}'
        f'\n  "plan_depth_px": <how many pixels the footprint extends UP from yBase>'
        f'\n  "base_shape": "rect" or "ellipse" (cylinders/barrels = ellipse, '
        f'boxes/buildings = rect)'
        f'{critique_note}'
    )

    return ask_json([input_img, prompt], maxtok=2048)


def gate_footprint(crop_pil, footprint_mask, name, use_grid):
    """LLM gate: median-of-3 vote."""
    overlay = np.asarray(crop_pil).astype(np.float32).copy()
    overlay[footprint_mask] = overlay[footprint_mask] * 0.4 + np.array([255, 60, 60], np.float32) * 0.6
    ov_img = Image.fromarray(overlay.clip(0, 255).astype(np.uint8))

    if use_grid:
        ov_img = draw_gridlines(ov_img, GRID_PITCH)

    def _vote():
        return ask_json([ov_img,
                         f'The red overlay shows a computed ground footprint for "{name}" in a '
                         f'3/4 top-down game scene. Is this a plausible full plan-view ground '
                         f'footprint? It should cover where the object meets/occupies the floor, '
                         f'including hidden base, but NOT extend far beyond the object or cover '
                         f'its whole upper body. Return JSON only: '
                         f'{{"ok": bool, "why": "short reason"}}'], maxtok=1024)

    with ThreadPoolExecutor(max_workers=3) as ex:
        results = list(ex.map(lambda _: _vote(), range(3)))

    votes = []
    reasons = []
    for v in results:
        if v is not None:
            votes.append(bool(v.get('ok', False)))
            reasons.append(v.get('why', ''))
    ok = sum(votes) >= 2 if votes else False
    critique = '; '.join(r for r, vv in zip(reasons, votes) if not vv)
    return ok, critique


def process_instance(inst, src, use_grid, W, H):
    """Process one impeding instance: estimate geometry, draw, gate. Returns (id, fp_mask_full, result_dict)."""
    x0, y0, x1, y1 = inst['box']
    nm = inst.get('name', 'object')
    pad = max(60, (y1 - y0) // 2)
    cx0, cy0 = max(0, x0 - pad), max(0, y0 - pad)
    cx1, cy1 = min(W, x1 + pad), min(H, y1 + pad + 30)
    crop = src.crop((cx0, cy0, cx1, cy1))
    crop_w, crop_h = crop.size
    sub = inst['mask'][cy0:cy1, cx0:cx1]

    ok_fp = None
    critique = ''
    best_attempt = None

    for attempt in range(4):
        geo = estimate_geometry(crop, sub, nm, use_grid, critique=critique)
        if geo is None:
            print(f'  [{inst["id"]}:{nm}] attempt {attempt}: VLM returned no JSON', flush=True)
            continue

        contact = geo.get('ground_contact', {})
        depth = geo.get('plan_depth_px', 0)
        shape = geo.get('base_shape', 'rect')

        if not all(k in contact for k in ('x0', 'x1', 'yBase')):
            critique = 'Missing required fields x0, x1, yBase in ground_contact.'
            print(f'  [{inst["id"]}:{nm}] attempt {attempt}: missing contact fields', flush=True)
            continue

        yBase = int(contact['yBase'])
        inst_ys = np.where(sub.any(axis=1))[0]
        if len(inst_ys) == 0:
            continue
        inst_height = int(inst_ys.max() - inst_ys.min())
        inst_lower_third = inst_ys.min() + inst_height * 2 / 3

        if yBase < inst_lower_third:
            critique = (f'yBase={yBase} is too high — must be in the lower third of the object '
                        f'(below y={inst_lower_third:.0f}).')
            print(f'  [{inst["id"]}:{nm}] attempt {attempt}: yBase above lower third', flush=True)
            continue

        inst_width = int(contact['x1']) - int(contact['x0'])
        if inst_width < 4:
            critique = f'Contact width {inst_width}px is too narrow. Widen x0/x1.'
            print(f'  [{inst["id"]}:{nm}] attempt {attempt}: contact too narrow', flush=True)
            continue

        depth_ratio = depth / max(1, inst_width)
        if not (0.15 <= depth_ratio <= 1.2):
            critique = (f'plan_depth_px={depth} gives depth/width ratio {depth_ratio:.2f}, '
                        f'outside [0.15, 1.2]. Adjust.')
            print(f'  [{inst["id"]}:{nm}] attempt {attempt}: depth_ratio {depth_ratio:.2f} OOB', flush=True)
            continue

        fp_mask = draw_footprint(crop_w, crop_h, contact, depth, shape)
        if fp_mask.sum() < 100:
            critique = 'Footprint too small. Increase plan_depth_px or widen contact.'
            print(f'  [{inst["id"]}:{nm}] attempt {attempt}: drawn footprint too small', flush=True)
            continue

        gate_ok, gate_critique = gate_footprint(crop, fp_mask, nm, use_grid)

        if gate_ok:
            ok_fp = fp_mask
            best_attempt = {'geo': geo, 'attempt': attempt, 'gate': 'pass'}
            break
        else:
            print(f'  [{inst["id"]}:{nm}] attempt {attempt}: LLM gate fail ({gate_critique})', flush=True)
            critique = gate_critique
            best_attempt = {'geo': geo, 'attempt': attempt, 'gate': 'fail',
                            'critique': gate_critique}

    full_mask = np.zeros((H, W), bool)
    if ok_fp is not None:
        full_mask[cy0:cy1, cx0:cx1] = ok_fp
        print(f'  [{inst["id"]}:{nm}] footprint OK (attempt {best_attempt["attempt"]})', flush=True)
        result = {'id': inst['id'], 'name': nm, 'status': 'ok',
                  'geo': best_attempt['geo'], 'attempt': best_attempt['attempt']}
    else:
        fb = inst['mask'].copy()
        fb[:max(0, y1 - max(20, (y1 - y0) // 4)), :] = False
        full_mask = fb
        print(f'  [{inst["id"]}:{nm}] FALLBACK lower-band', flush=True)
        result = {'id': inst['id'], 'name': nm, 'status': 'fallback',
                  'last_attempt': best_attempt}

    return inst['id'], full_mask, result


def main():
    room = sys.argv[1]
    use_grid = '--no-grid' not in sys.argv
    resume = '--resume' in sys.argv

    if room == 'anchorroom':
        plate_p = os.path.join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor-clean.png')
        walk_p = os.path.join(ROOT, 'docs', 'art-options', 'nbp-walk.png')
        cls_p = os.path.join(ROOT, 'docs', 'art-options', 'nbp-mask.png')
    else:
        base = os.path.join(ROOT, 'docs', 'art-options', 'rooms', room)
        plate_p = os.path.join(base, 'plate.png')
        walk_p = os.path.join(base, 'nbp-walk.png')
        cls_p = os.path.join(base, 'nbp-mask.png')

    suffix = '-nogrid' if not use_grid else ''
    out = os.path.join(ROOT, 'docs', 'art-options', 'v4', room)
    os.makedirs(out, exist_ok=True)

    src = Image.open(plate_p).convert('RGB')
    W, H = src.size
    seg_in = src.copy()
    seg_in.thumbnail((1200, 1200))

    t0 = time.time()
    print(f'=== v4 {room} (grid={"on" if use_grid else "off"}) ===', flush=True)

    # Try to reuse v3's census overlay if available
    v3_dir = os.path.join(ROOT, 'docs', 'art-options', 'v3', room)
    cached_census = None
    if resume and os.path.exists(os.path.join(v3_dir, 'census-r0.jpg')):
        # load the best v3 census (last round)
        for rd in range(3, -1, -1):
            cp = os.path.join(v3_dir, f'census-r{rd}.jpg')
            if os.path.exists(cp):
                cached_census = rd
                break

    # ========== STAGE 1: iterative census ==========
    print('--- stage 1: census ---', flush=True)
    census_prompt_base = (
        'Repaint this EXACT image, keeping every silhouette PIXEL-IDENTICAL, as an instance '
        'segmentation OVERLAY: fill each distinct raised object/structure (buildings, machines, '
        'tanks, stalls, crates, barrels, furniture, pylons, cranes, railings, lamp posts, large '
        'pipes) with ONE flat saturated color, a DIFFERENT color per object; neighboring objects '
        'must not share a color. Leave open ground/floor/water EXACTLY as in the source (do not '
        'recolor them). NO dithering, NO gradients, hard boundaries.'
    )
    missed_note = ''
    census = None
    for rd in range(4):
        prompt = census_prompt_base + (f'\nYou previously MISSED these — they MUST be colored '
                                       f'this time: {missed_note}' if missed_note else '')
        img = gen_image([seg_in, prompt])
        if img is None:
            continue
        img = img.resize((W, H), Image.NEAREST)
        a = np.asarray(img).astype(np.int16)
        b = np.asarray(src).astype(np.int16)
        diff = np.linalg.norm(a - b, axis=2)
        hsv = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2HSV)
        colored = (diff > 90) & (hsv[..., 1] > 120)
        census = {'img': img, 'colored': colored}
        blend = b.astype(np.float32) * 0.45 + a.astype(np.float32) * 0.55
        ov = Image.fromarray(blend.clip(0, 255).astype(np.uint8))
        ov.thumbnail((1400, 1400), Image.LANCZOS)
        ov.save(os.path.join(out, f'census-r{rd}{suffix}.jpg'), quality=86)
        v = ask_json([ov, 'Image: a game scene with an instance-segmentation color overlay on '
                          'its objects. List raised objects/structures that are NOT covered by '
                          'any flat color overlay (missed by the segmentation). Ignore open '
                          'floor, water, flat markings and shadows. Return JSON only: '
                          '{"missed": [{"name": "...", "box_2d": [ymin,xmin,ymax,xmax] 0-1000}]}'])
        missed = (v or {}).get('missed', [])
        print(f'[census r{rd}] colored {colored.mean():.1%}; verifier missed: '
              f'{[m["name"] for m in missed][:8]} ({len(missed)}) [{time.time()-t0:.0f}s]', flush=True)
        if not missed:
            break
        missed_note = '; '.join(m['name'] for m in missed[:12])
    if census is None:
        sys.exit('census failed')

    colored = census['colored']
    ncc, lab = cv2.connectedComponents(cv2.morphologyEx(
        colored.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)))
    insts = []
    for i in range(1, ncc):
        comp = lab == i
        if comp.sum() < 900:
            continue
        ys, xs = np.where(comp)
        insts.append({'id': len(insts), 'mask': comp,
                      'box': [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]})
    print(f'census instances: {len(insts)} [{time.time()-t0:.0f}s]', flush=True)

    # ========== STAGE 2: select movement-impeding ==========
    print('--- stage 2: select impeding ---', flush=True)
    listing = '\n'.join(f'{i["id"]}. box_frac=({i["box"][0]/W:.2f},{i["box"][1]/H:.2f},'
                        f'{i["box"][2]/W:.2f},{i["box"][3]/H:.2f})' for i in insts)
    thumb2 = src.copy()
    thumb2.thumbnail((1100, 1100))
    v = ask_json([thumb2, 'This is a 3/4 top-down game scene. For each numbered region '
                          f'(fractional boxes below), decide if the object SITS ON THE FLOOR '
                          'and would block a walking character. IMPEDING = the object\'s BASE '
                          'physically occupies floor space (tanks, crates, market stalls, '
                          'furniture, large machines resting on the ground, barrels, freestanding '
                          'pylons/pillars). NOT IMPEDING = wall-mounted objects (pipes on walls, '
                          'vents, AC units, shelves on walls), background buildings/walls (they '
                          'are part of the background plane), flat floor markings, cables lying '
                          'flat, stairs, ramps, doors/thresholds, shadows, decorative wall panels, '
                          'overhead structures, signs. Be SELECTIVE: only include objects that a '
                          'character would physically collide with at ground level.\n'
                          f'{listing}\nReturn JSON only: {{"impeding": [ids], '
                          '"names": {"<id>": "short name"}}'])
    keep_ids = set((v or {}).get('impeding', [i['id'] for i in insts]))
    names = (v or {}).get('names', {})
    kept = [i for i in insts if i['id'] in keep_ids]
    for inst in kept:
        inst['name'] = names.get(str(inst['id']), 'object')
    print(f'selected impeding: {len(kept)}/{len(insts)} [{time.time()-t0:.0f}s]', flush=True)

    # ========== STAGE 3: geometric footprints (parallel, 2 at a time) ==========
    print('--- stage 3: geometric footprints ---', flush=True)
    fp_union = np.zeros((H, W), bool)
    per_inst_results = []

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = {ex.submit(process_instance, inst, src, use_grid, W, H): inst
                   for inst in kept}
        for future in futures:
            iid, fp_mask, result = future.result()
            fp_union |= fp_mask
            per_inst_results.append(result)

    per_inst_results.sort(key=lambda r: r['id'])

    fp_path = os.path.join(out, f'geometric-footprints{suffix}.png')
    Image.fromarray((fp_union * 255).astype(np.uint8)).save(fp_path)

    # ========== STAGE 4: compose collision ==========
    print(f'--- stage 4: compose collision [{time.time()-t0:.0f}s] ---', flush=True)
    walk = np.asarray(Image.open(walk_p).convert('L').resize((W, H), Image.NEAREST)) > 127
    water = np.zeros((H, W), bool)
    if os.path.exists(cls_p):
        cls = np.asarray(Image.open(cls_p).convert('RGB').resize((W, H), Image.NEAREST)).astype(np.int16)
        water = np.linalg.norm(cls - np.array([0, 0, 255], np.int16), axis=2) < 90

    bodies = np.zeros((H, W), bool)
    for inst in kept:
        bodies |= inst['mask']

    walk_v4 = (walk | cv2.dilate((bodies & ~fp_union).astype(np.uint8),
                                 np.ones((13, 13), np.uint8)).astype(bool)) & ~(fp_union | water)

    col_path = os.path.join(out, f'collision-v4{suffix}.png')
    Image.fromarray((walk_v4 * 255).astype(np.uint8)).save(col_path)

    # overlays
    b = np.asarray(src).astype(np.float32)
    for name2, mask, col in (('footprints-on-source', fp_union, (255, 60, 60)),
                             ('collision-v4-on-source', ~walk_v4, (255, 40, 40))):
        blend = b.copy()
        blend[mask] = blend[mask] * 0.4 + np.array(col, np.float32) * 0.6
        if 'collision' in name2:
            blend[walk_v4] = blend[walk_v4] * 0.72 + np.array([40, 255, 90], np.float32) * 0.28
        ov = Image.fromarray(blend.clip(0, 255).astype(np.uint8))
        ov.thumbnail((1400, 1400), Image.LANCZOS)
        ov.save(os.path.join(out, f'{name2}{suffix}.jpg'), quality=86)

    ok_count = sum(1 for r in per_inst_results if r['status'] == 'ok')
    fb_count = sum(1 for r in per_inst_results if r['status'] == 'fallback')
    metrics = {
        'instances': len(insts),
        'impeding': len(kept),
        'geometric_ok': ok_count,
        'fallback': fb_count,
        'walk_frac_v4': round(float(walk_v4.mean()), 3),
        'grid': use_grid,
        'elapsed_s': round(time.time() - t0, 1),
        'per_instance': [{k: v for k, v in r.items() if k != 'geo'} for r in per_inst_results],
    }
    json.dump(metrics, open(os.path.join(out, f'v4-metrics{suffix}.json'), 'w'), indent=2)
    print(f'\nv4 done: {ok_count}/{len(kept)} geometric, {fb_count} fallback, '
          f'walk_frac={walk_v4.mean():.3f}, elapsed={time.time()-t0:.0f}s', flush=True)


if __name__ == '__main__':
    main()
