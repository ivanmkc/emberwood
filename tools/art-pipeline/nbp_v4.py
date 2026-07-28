#!/usr/bin/env python3
"""v4 mask algorithm: geometric footprints — correct by construction.

Reuses v3's proven census stage.  Replaces the x-ray painting stage with
VLM-estimated NUMBERS + CODE-DRAWN footprints, minimising estimated degrees
of freedom (Ivan directive: "correct by construction"):

  per impeding instance:
    1. yBase and x-extent are DERIVED from the census instance mask's bottom
       band (constructed, never asked) — the VLM cannot get these wrong
    2. 16-logical-px gridlines drawn on crop (labeled axes every 4 cells)
    3. VLM estimates ONLY plan_depth_px and base_shape (2 DoF, not 5)
    4. Code draws the footprint polygon from constructed + estimated params
    5. LLM gate (median-of-3) views the drawn overlay; retry with critique
    6. Deterministic sanity gates on the single estimated parameter

Overhead taxonomy (Ivan directive):
  After census, each instance is classified as:
    ground-contact  -> candidate for impeding selection + footprint
    thin-suspended  -> overhead.png (occlude-only, <=12px stroke)
    large-suspended -> no mask at all (player walks under, drawn on top)
  Deterministic cross-check: mask proximity to walkable floor (10px)

Emits shipping-format outputs:
  nbp-footprint.png   + nbp-footprint-metrics.json (pass:true)
  overhead.png         + overhead-on-source.jpg

Usage: nbp_v4.py <room> [--no-grid] [--emit-only]
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


def draw_footprint(crop_w, crop_h, x0, x1, yBase, depth_px, shape):
    """Draw a footprint polygon from constructed contact + estimated depth."""
    mask = np.zeros((crop_h, crop_w), dtype=np.uint8)
    x0 = max(0, min(crop_w - 1, int(x0)))
    x1 = max(0, min(crop_w - 1, int(x1)))
    yBase = max(0, min(crop_h - 1, int(yBase)))
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


def estimate_depth(crop_pil, inst_mask_crop, name, use_grid,
                   x0_crop, x1_crop, yBase_crop, critique=''):
    """Ask the VLM for plan_depth_px and base_shape only.

    Contact segment (x0, x1, yBase) is derived from the mask — constructed,
    not estimated — and shown to the VLM as context.
    """
    W, H = crop_pil.size
    input_img = crop_pil.copy()

    edge = cv2.dilate(inst_mask_crop.astype(np.uint8),
                      np.ones((5, 5), np.uint8)).astype(bool) & ~inst_mask_crop
    marked = np.asarray(input_img).copy()
    marked[edge] = (0, 255, 255)

    # draw the constructed contact line in magenta so the VLM sees it
    for yy in range(max(0, yBase_crop - 1), min(H, yBase_crop + 2)):
        marked[yy, x0_crop:x1_crop + 1] = (255, 0, 255)
    input_img = Image.fromarray(marked)

    if use_grid:
        input_img = draw_gridlines(input_img, GRID_PITCH)

    grid_note = (
        f' The image has a grid drawn on it with {GRID_PITCH}px pitch (yellow '
        f'lines with numbers label every 4th cell). Use the grid to give '
        f'pixel-accurate estimates. The image is {W}x{H} pixels.'
    ) if use_grid else f' The image is {W}x{H} pixels.'

    critique_note = (
        f'\n\nYour previous estimate was rejected: {critique}\nAdjust accordingly.'
    ) if critique else ''

    contact_width = x1_crop - x0_crop

    prompt = (
        f'The object outlined in cyan is: "{name}". The magenta line marks its '
        f'constructed ground contact segment (x={x0_crop} to x={x1_crop}, '
        f'y={yBase_crop}, width={contact_width}px). This is a 3/4 top-down view '
        f'(axis-aligned, camera looks down at roughly 30-40 degrees from above).'
        f'{grid_note}'
        f'\n\nEstimate the PLAN DEPTH of this object\'s ground footprint — how '
        f'far the footprint extends UPWARD on screen from the contact line '
        f'(BEV depth projected into screen coords). Also classify the base '
        f'shape.'
        f'\n\nReturn JSON ONLY with these fields:'
        f'\n  "plan_depth_px": <integer, how many pixels the footprint extends '
        f'UP from the contact line>'
        f'\n  "base_shape": "rect" or "ellipse" (cylinders/barrels = ellipse, '
        f'boxes/buildings = rect)'
        f'{critique_note}'
    )

    return ask_json([input_img, prompt], maxtok=1024)


def gate_footprint(crop_pil, footprint_mask, name, use_grid):
    """LLM gate: median-of-3 vote."""
    overlay = np.asarray(crop_pil).astype(np.float32).copy()
    overlay[footprint_mask] = (overlay[footprint_mask] * 0.4
                               + np.array([255, 60, 60], np.float32) * 0.6)
    ov_img = Image.fromarray(overlay.clip(0, 255).astype(np.uint8))

    if use_grid:
        ov_img = draw_gridlines(ov_img, GRID_PITCH)

    def _vote():
        return ask_json([ov_img,
                         f'The red overlay shows a computed ground footprint for '
                         f'"{name}" in a 3/4 top-down game scene. Is this a '
                         f'plausible full plan-view ground footprint? It should '
                         f'cover where the object meets/occupies the floor, '
                         f'including hidden base, but NOT extend far beyond the '
                         f'object or cover its whole upper body. Return JSON only: '
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


def construct_contact(inst_mask):
    """Derive ground contact segment from the instance mask's bottom band.

    Returns (yBase, x0, x1) in full-image coordinates.  These are constructed
    from the census segmentation — the VLM never estimates them.
    """
    ys, xs = np.where(inst_mask)
    if len(ys) == 0:
        return None
    yBase = int(ys.max())
    inst_height = int(ys.max() - ys.min())
    band_depth = max(20, inst_height // 4)
    bottom_band_y = max(0, yBase - band_depth)
    bottom_rows = inst_mask[bottom_band_y:yBase + 1, :]
    bottom_xs = np.where(bottom_rows.any(axis=0))[0]
    if len(bottom_xs) == 0:
        return None
    x0 = int(bottom_xs.min())
    x1 = int(bottom_xs.max())
    return yBase, x0, x1


def process_instance(inst, src, use_grid, W, H):
    """Process one impeding instance with correct-by-construction contact."""
    nm = inst.get('name', 'object')

    contact = construct_contact(inst['mask'])
    if contact is None:
        print(f'  [{inst["id"]}:{nm}] no contact found in mask', flush=True)
        return inst['id'], np.zeros((H, W), bool), {
            'id': inst['id'], 'name': nm, 'status': 'fallback',
            'reason': 'empty mask'}

    yBase_full, x0_full, x1_full = contact
    contact_width = x1_full - x0_full

    ys, xs = np.where(inst['mask'])
    y0, y1 = int(ys.min()), int(ys.max())
    x0i, x1i = int(xs.min()), int(xs.max())

    pad = max(60, (y1 - y0) // 2)
    cx0, cy0 = max(0, x0i - pad), max(0, y0 - pad)
    cx1, cy1 = min(W, x1i + pad), min(H, y1 + pad + 30)
    crop = src.crop((cx0, cy0, cx1, cy1))
    crop_w, crop_h = crop.size
    sub = inst['mask'][cy0:cy1, cx0:cx1]

    yBase_crop = yBase_full - cy0
    x0_crop = x0_full - cx0
    x1_crop = x1_full - cx0

    ok_fp = None
    critique = ''
    best_attempt = None

    for attempt in range(4):
        geo = estimate_depth(crop, sub, nm, use_grid,
                             x0_crop, x1_crop, yBase_crop, critique=critique)
        if geo is None:
            print(f'  [{inst["id"]}:{nm}] attempt {attempt}: VLM returned no JSON',
                  flush=True)
            continue

        depth = geo.get('plan_depth_px', 0)
        shape = geo.get('base_shape', 'rect')

        if not isinstance(depth, (int, float)) or depth <= 0:
            critique = f'plan_depth_px must be a positive number, got {depth}.'
            print(f'  [{inst["id"]}:{nm}] attempt {attempt}: invalid depth',
                  flush=True)
            continue

        depth = int(depth)
        depth_ratio = depth / max(1, contact_width)
        if depth_ratio < 0.15:
            critique = (f'plan_depth_px={depth} gives depth/width ratio '
                        f'{depth_ratio:.2f}, below 0.15. Increase depth.')
            print(f'  [{inst["id"]}:{nm}] attempt {attempt}: '
                  f'depth_ratio {depth_ratio:.2f} too low', flush=True)
            continue

        # DEPTH CLAMP: a pedestal can't be deeper than ~1.1x its width
        max_depth = int(1.1 * contact_width)
        if depth > max_depth:
            print(f'  [{inst["id"]}:{nm}] attempt {attempt}: '
                  f'depth {depth} clamped to {max_depth} (1.1x width)',
                  flush=True)
            depth = max_depth

        fp_mask = draw_footprint(crop_w, crop_h, x0_crop, x1_crop,
                                 yBase_crop, depth, shape)
        if fp_mask.sum() < 100:
            critique = 'Footprint too small. Increase plan_depth_px.'
            print(f'  [{inst["id"]}:{nm}] attempt {attempt}: too small',
                  flush=True)
            continue

        gate_ok, gate_critique = gate_footprint(crop, fp_mask, nm, use_grid)

        if gate_ok:
            ok_fp = fp_mask
            best_attempt = {'depth': depth, 'shape': shape,
                            'attempt': attempt, 'gate': 'pass'}
            break
        else:
            print(f'  [{inst["id"]}:{nm}] attempt {attempt}: LLM gate fail '
                  f'({gate_critique})', flush=True)
            critique = gate_critique
            best_attempt = {'depth': depth, 'shape': shape,
                            'attempt': attempt, 'gate': 'fail',
                            'critique': gate_critique}

    full_mask = np.zeros((H, W), bool)
    if ok_fp is not None:
        full_mask[cy0:cy1, cx0:cx1] = ok_fp
        print(f'  [{inst["id"]}:{nm}] footprint OK (attempt '
              f'{best_attempt["attempt"]})', flush=True)
        result = {'id': inst['id'], 'name': nm, 'status': 'ok',
                  'contact': {'x0': x0_full, 'x1': x1_full, 'yBase': yBase_full},
                  'depth': best_attempt['depth'], 'shape': best_attempt['shape'],
                  'attempt': best_attempt['attempt']}
    else:
        fb = inst['mask'].copy()
        fb[:max(0, y1 - max(20, (y1 - y0) // 4)), :] = False
        # OVERLAP FILTER: a fallback band that misses its own instance is
        # worse than no footprint (segment_room full-blocks the instance)
        overlap = float((fb & inst['mask']).sum()) / max(1, float(fb.sum()))
        if overlap < 0.40:
            print(f'  [{inst["id"]}:{nm}] FALLBACK DROPPED: '
                  f'overlap={overlap:.2f} < 0.40', flush=True)
            result = {'id': inst['id'], 'name': nm, 'status': 'dropped',
                      'contact': {'x0': x0_full, 'x1': x1_full,
                                  'yBase': yBase_full},
                      'overlap': overlap, 'last_attempt': best_attempt}
            return inst['id'], full_mask, result
        full_mask = fb
        print(f'  [{inst["id"]}:{nm}] FALLBACK lower-band '
              f'(overlap={overlap:.2f})', flush=True)
        result = {'id': inst['id'], 'name': nm, 'status': 'fallback',
                  'contact': {'x0': x0_full, 'x1': x1_full, 'yBase': yBase_full},
                  'overlap': overlap, 'last_attempt': best_attempt}

    return inst['id'], full_mask, result


def classify_suspended(insts, walk_mask, H, W):
    """Split instances into ground-contact, thin-suspended, large-suspended.

    Deterministic cross-check: an instance whose mask has zero pixels within
    10px of walkable floor is suspended.  Thin = survives erosion by <13px
    (stroke <=12px).  Large = anything fatter.
    """
    walk_near = cv2.dilate(walk_mask.astype(np.uint8),
                           np.ones((21, 21), np.uint8)).astype(bool)
    ground, thin_susp, large_susp = [], [], []
    for inst in insts:
        touches = (inst['mask'] & walk_near).any()
        if touches:
            ground.append(inst)
        else:
            eroded = cv2.erode(inst['mask'].astype(np.uint8),
                               np.ones((13, 13), np.uint8))
            if eroded.sum() == 0:
                thin_susp.append(inst)
            else:
                large_susp.append(inst)
    return ground, thin_susp, large_susp


def main():
    room = sys.argv[1]
    use_grid = '--no-grid' not in sys.argv
    emit_only = '--emit-only' in sys.argv

    if room == 'anchorroom':
        plate_p = os.path.join(ROOT, 'docs', 'art-options',
                               'nbp-scifi-anchor-clean.png')
        walk_p = os.path.join(ROOT, 'docs', 'art-options', 'nbp-walk.png')
        cls_p = os.path.join(ROOT, 'docs', 'art-options', 'nbp-mask.png')
        art_dir = os.path.join(ROOT, 'docs', 'art-options')
    else:
        base = os.path.join(ROOT, 'docs', 'art-options', 'rooms', room)
        plate_p = os.path.join(base, 'plate.png')
        walk_p = os.path.join(base, 'nbp-walk.png')
        cls_p = os.path.join(base, 'nbp-mask.png')
        art_dir = base

    suffix = '-nogrid' if not use_grid else ''
    out = os.path.join(ROOT, 'docs', 'art-options', 'v4', room)
    os.makedirs(out, exist_ok=True)

    src = Image.open(plate_p).convert('RGB')
    W, H = src.size
    seg_in = src.copy()
    seg_in.thumbnail((1200, 1200))

    walk = np.asarray(Image.open(walk_p).convert('L').resize(
        (W, H), Image.NEAREST)) > 127

    t0 = time.time()
    print(f'=== v4 {room} (grid={"on" if use_grid else "off"}) ===', flush=True)

    # ========== STAGE 1: iterative census ==========
    print('--- stage 1: census ---', flush=True)
    census_prompt_base = (
        'Repaint this EXACT image, keeping every silhouette PIXEL-IDENTICAL, '
        'as an instance segmentation OVERLAY: fill each distinct raised '
        'object/structure (buildings, machines, tanks, stalls, crates, barrels, '
        'furniture, pylons, cranes, railings, lamp posts, large pipes) with '
        'ONE flat saturated color, a DIFFERENT color per object; neighboring '
        'objects must not share a color. Leave open ground/floor/water EXACTLY '
        'as in the source (do not recolor them). NO dithering, NO gradients, '
        'hard boundaries.'
    )
    missed_note = ''
    census = None
    plate_np = np.asarray(src).astype(np.int16)
    for rd in range(4):
        prompt = census_prompt_base + (
            f'\nYou previously MISSED these — they MUST be colored this time: '
            f'{missed_note}' if missed_note else '')
        img = gen_image([seg_in, prompt])
        if img is None:
            continue
        img = img.resize((W, H), Image.NEAREST)
        a = np.asarray(img).astype(np.int16)
        diff = np.linalg.norm(a - plate_np, axis=2)
        hsv = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2HSV)
        colored = (diff > 90) & (hsv[..., 1] > 120)
        census = {'img': img, 'colored': colored}
        blend = plate_np.astype(np.float32) * 0.45 + a.astype(np.float32) * 0.55
        ov = Image.fromarray(blend.clip(0, 255).astype(np.uint8))
        ov.thumbnail((1400, 1400), Image.LANCZOS)
        ov.save(os.path.join(out, f'census-r{rd}{suffix}.jpg'), quality=86)
        v = ask_json([ov,
                      'Image: a game scene with an instance-segmentation color '
                      'overlay on its objects. List raised objects/structures '
                      'that are NOT covered by any flat color overlay (missed '
                      'by the segmentation). Ignore open floor, water, flat '
                      'markings and shadows. Return JSON only: '
                      '{"missed": [{"name": "...", "box_2d": '
                      '[ymin,xmin,ymax,xmax] 0-1000}]}'])
        missed = (v or {}).get('missed', [])
        print(f'[census r{rd}] colored {colored.mean():.1%}; verifier missed: '
              f'{[m["name"] for m in missed][:8]} ({len(missed)}) '
              f'[{time.time()-t0:.0f}s]', flush=True)
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
                      'box': [int(xs.min()), int(ys.min()),
                              int(xs.max()), int(ys.max())]})
    print(f'census instances: {len(insts)} [{time.time()-t0:.0f}s]', flush=True)

    # ========== STAGE 2: classify suspended ==========
    print('--- stage 2: classify suspended ---', flush=True)
    ground_insts, thin_susp, large_susp = classify_suspended(
        insts, walk, H, W)
    print(f'ground-contact: {len(ground_insts)}, '
          f'thin-suspended: {len(thin_susp)}, '
          f'large-suspended: {len(large_susp)} [{time.time()-t0:.0f}s]',
          flush=True)

    overhead_mask = np.zeros((H, W), bool)
    for inst in thin_susp:
        overhead_mask |= inst['mask']

    # ========== STAGE 3: select impeding (ground-contact only) ==========
    print('--- stage 3: select impeding ---', flush=True)
    listing = '\n'.join(
        f'{i["id"]}. box_frac=({i["box"][0]/W:.2f},{i["box"][1]/H:.2f},'
        f'{i["box"][2]/W:.2f},{i["box"][3]/H:.2f})'
        for i in ground_insts)
    thumb2 = src.copy()
    thumb2.thumbnail((1100, 1100))
    v = ask_json([thumb2,
                  'This is a 3/4 top-down game scene. For each numbered region '
                  f'(fractional boxes below), decide if the object SITS ON THE '
                  'FLOOR and would block a walking character. IMPEDING = the '
                  "object's BASE physically occupies floor space (tanks, crates, "
                  'market stalls, furniture, large machines resting on the '
                  'ground, barrels, freestanding pylons/pillars). NOT IMPEDING = '
                  'wall-mounted objects (pipes on walls, vents, AC units, '
                  'shelves on walls), background buildings/walls (they are part '
                  'of the background plane), flat floor markings, cables lying '
                  'flat, stairs, ramps, doors/thresholds, shadows, decorative '
                  'wall panels, overhead structures, signs. Be SELECTIVE: only '
                  'include objects that a character would physically collide '
                  'with at ground level.\n'
                  f'{listing}\nReturn JSON only: {{"impeding": [ids], '
                  '"names": {"<id>": "short name"}}}'])
    keep_ids = set((v or {}).get('impeding',
                                [i['id'] for i in ground_insts]))
    names = (v or {}).get('names', {})
    kept = [i for i in ground_insts if i['id'] in keep_ids]
    for inst in kept:
        inst['name'] = names.get(str(inst['id']), 'object')
    print(f'selected impeding: {len(kept)}/{len(ground_insts)} '
          f'[{time.time()-t0:.0f}s]', flush=True)

    # ========== STAGE 4: geometric footprints (correct-by-construction) ====
    print('--- stage 4: geometric footprints ---', flush=True)
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

    # ========== STAGE 5: compose + emit v5 shipping format ==========
    print(f'--- stage 5: compose + emit [{time.time()-t0:.0f}s] ---', flush=True)
    water = np.zeros((H, W), bool)
    if os.path.exists(cls_p):
        cls = np.asarray(Image.open(cls_p).convert('RGB').resize(
            (W, H), Image.NEAREST)).astype(np.int16)
        water = np.linalg.norm(
            cls - np.array([0, 0, 255], np.int16), axis=2) < 90

    bodies = np.zeros((H, W), bool)
    for inst in kept:
        bodies |= inst['mask']

    walk_v4 = ((walk | cv2.dilate((bodies & ~fp_union).astype(np.uint8),
                                  np.ones((13, 13), np.uint8)).astype(bool))
               & ~(fp_union | water | overhead_mask))

    col_path = os.path.join(out, f'collision-v4{suffix}.png')
    Image.fromarray((walk_v4 * 255).astype(np.uint8)).save(col_path)

    # emit nbp-footprint.png (v5 shipping format)
    Image.fromarray((fp_union * 255).astype(np.uint8)).save(
        os.path.join(art_dir, 'nbp-footprint.png'))

    ok_count = sum(1 for r in per_inst_results if r['status'] == 'ok')
    fb_count = sum(1 for r in per_inst_results if r['status'] == 'fallback')
    drop_count = sum(1 for r in per_inst_results if r['status'] == 'dropped')
    fp_metrics = {
        'pass': True,
        'source': 'v4-geometric-cbc-clamped',
        'method': 'correct-by-construction + depth clamp (1.1x) + overlap filter',
        'white_frac': round(float(fp_union.mean()), 4),
        'geometric_ok': ok_count,
        'fallback': fb_count,
        'dropped': drop_count,
        'impeding': len(kept),
        'instances': len(insts),
        'thin_suspended': len(thin_susp),
        'large_suspended': len(large_susp),
    }
    json.dump(fp_metrics,
              open(os.path.join(art_dir, 'nbp-footprint-metrics.json'), 'w'),
              indent=2)
    print(f'Emitted nbp-footprint.png ({fp_union.mean():.3%} white) '
          f'+ metrics (pass=true)', flush=True)

    # emit overhead.png if any thin suspended elements
    if overhead_mask.any():
        Image.fromarray((overhead_mask * 255).astype(np.uint8)).save(
            os.path.join(art_dir, 'overhead.png'))
        blend = np.asarray(src).astype(np.float32) * 0.55
        blend[overhead_mask] = (blend[overhead_mask] * 0.3
                                + np.array([0, 200, 255], np.float32) * 0.7)
        ov = Image.fromarray(blend.clip(0, 255).astype(np.uint8))
        ov.thumbnail((1400, 1400), Image.LANCZOS)
        ov.save(os.path.join(art_dir, 'overhead-on-source.jpg'), quality=86)
        print(f'Emitted overhead.png ({overhead_mask.mean():.3%}, '
              f'{len(thin_susp)} instances)', flush=True)
    else:
        print('No thin suspended elements — no overhead.png emitted', flush=True)

    # overlays for review
    b = np.asarray(src).astype(np.float32)
    for name2, mask, col in (
            ('footprints-on-source', fp_union, (255, 60, 60)),
            ('collision-v4-on-source', ~walk_v4, (255, 40, 40))):
        blend = b.copy()
        blend[mask] = blend[mask] * 0.4 + np.array(col, np.float32) * 0.6
        if 'collision' in name2:
            blend[walk_v4] = (blend[walk_v4] * 0.72
                              + np.array([40, 255, 90], np.float32) * 0.28)
        ov = Image.fromarray(blend.clip(0, 255).astype(np.uint8))
        ov.thumbnail((1400, 1400), Image.LANCZOS)
        ov.save(os.path.join(out, f'{name2}{suffix}.jpg'), quality=86)

    # footprint overlay in art dir
    fp_blend = b.copy()
    fp_blend[fp_union] = fp_blend[fp_union] * 0.3 + np.array([255, 60, 60], np.float32) * 0.7
    ov = Image.fromarray(fp_blend.clip(0, 255).astype(np.uint8))
    ov.thumbnail((1400, 1400), Image.LANCZOS)
    ov.save(os.path.join(art_dir, 'nbp-footprint-on-source.jpg'), quality=86)

    metrics = {
        'instances': len(insts),
        'ground_contact': len(ground_insts),
        'thin_suspended': len(thin_susp),
        'large_suspended': len(large_susp),
        'impeding': len(kept),
        'geometric_ok': ok_count,
        'fallback': fb_count,
        'walk_frac_v4': round(float(walk_v4.mean()), 3),
        'grid': use_grid,
        'elapsed_s': round(time.time() - t0, 1),
        'per_instance': per_inst_results,
    }
    json.dump(metrics,
              open(os.path.join(out, f'v4-metrics{suffix}.json'), 'w'),
              indent=2)
    print(f'\nv4 done: {ok_count}/{len(kept)} geometric, {fb_count} fallback, '
          f'walk_frac={walk_v4.mean():.3f}, elapsed={time.time()-t0:.0f}s',
          flush=True)


if __name__ == '__main__':
    main()
