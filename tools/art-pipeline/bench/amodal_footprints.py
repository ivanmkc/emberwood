#!/usr/bin/env python3
"""A4: Amodal-completion footprints via NBP.

For each impeding object (from v3/v4 census), asks NBP to paint the FULL
UNOCCLUDED object on its crop (pix2gestalt-style amodal completion).
The footprint is then extracted deterministically: bottom band of the amodal
mask, scaled by VLM-estimated plan depth.

This decouples the "what does the hidden part look like" (NBP strengths) from
the "where does it sit on the ground" (code-drawn from depth estimate).

Usage: amodal_footprints.py <room>
"""
import io
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw
from google import genai
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
client = genai.Client(vertexai=True, project='adk-coding-agents', location='global')


def gen_image(contents, size='2K'):
    for _ in range(3):
        try:
            resp = client.models.generate_content(
                model='gemini-3-pro-image', contents=contents,
                config=types.GenerateContentConfig(
                    image_config=types.ImageConfig(aspect_ratio='4:3', image_size=size)))
            for part in (resp.parts or []):
                if part.inline_data is not None:
                    return Image.open(io.BytesIO(part.inline_data.data)).convert('RGB')
        except Exception:
            pass
    return None


def ask_json(contents, maxtok=8192):
    for _ in range(3):
        try:
            r = client.models.generate_content(
                model='gemini-3.1-pro-preview', contents=contents,
                config=types.GenerateContentConfig(max_output_tokens=maxtok))
            t = r.text or ''
            st = min([i for i in (t.find('['), t.find('{')) if i >= 0], default=-1)
            if st >= 0:
                v, _ = json.JSONDecoder().raw_decode(t[st:])
                return v
        except Exception:
            pass
    return None


def resolve_paths(room):
    if room == 'anchorroom':
        plate = os.path.join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor-clean.png')
        walk = os.path.join(ROOT, 'docs', 'art-options', 'nbp-walk.png')
        cls = os.path.join(ROOT, 'docs', 'art-options', 'nbp-mask.png')
    else:
        base = os.path.join(ROOT, 'docs', 'art-options', 'rooms', room)
        plate = os.path.join(base, 'plate.png')
        walk = os.path.join(base, 'nbp-walk.png')
        cls = os.path.join(base, 'nbp-mask.png')
    return plate, walk, cls


def census_and_select(src, seg_in, W, H, out):
    """Reuse v3/v4 census + select pipeline. Returns list of impeding instances."""
    census_prompt = (
        'Repaint this EXACT image, keeping every silhouette PIXEL-IDENTICAL, as an instance '
        'segmentation OVERLAY: fill each distinct raised object/structure (buildings, machines, '
        'tanks, stalls, crates, barrels, furniture, pylons, cranes, railings, lamp posts, large '
        'pipes) with ONE flat saturated color, a DIFFERENT color per object; neighboring objects '
        'must not share a color. Leave open ground/floor/water EXACTLY as in the source (do not '
        'recolor them). NO dithering, NO gradients, hard boundaries.'
    )
    missed_note = ''
    census_img = None
    colored_mask = None
    for rd in range(4):
        prompt = census_prompt + (f'\nYou previously MISSED these — they MUST be colored '
                                  f'this time: {missed_note}' if missed_note else '')
        img = gen_image([seg_in, prompt])
        if img is None:
            continue
        img = img.resize((W, H), Image.NEAREST)
        a = np.asarray(img).astype(np.int16)
        b = np.asarray(src).astype(np.int16)
        diff = np.linalg.norm(a - b, axis=2)
        hsv = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2HSV)
        colored_mask = (diff > 90) & (hsv[..., 1] > 120)
        census_img = img

        blend = b.astype(np.float32) * 0.45 + a.astype(np.float32) * 0.55
        ov = Image.fromarray(blend.clip(0, 255).astype(np.uint8))
        ov.thumbnail((1400, 1400), Image.LANCZOS)
        ov.save(os.path.join(out, f'amodal-census-r{rd}.jpg'), quality=86)

        v = ask_json([ov, 'Image: a game scene with instance-segmentation color overlay. '
                          'List raised objects NOT covered by any flat color overlay. Ignore '
                          'floor, water, flat markings, shadows. Return JSON only: '
                          '{"missed": [{"name": "..."}]}'])
        missed = (v or {}).get('missed', [])
        print(f'[census r{rd}] colored {colored_mask.mean():.1%}; missed: '
              f'{[m["name"] for m in missed][:8]}')
        if not missed:
            break
        missed_note = '; '.join(m['name'] for m in missed[:12])

    if colored_mask is None:
        return []

    ncc, lab = cv2.connectedComponents(cv2.morphologyEx(
        colored_mask.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)))
    insts = []
    for i in range(1, ncc):
        comp = lab == i
        if comp.sum() < 900:
            continue
        ys, xs = np.where(comp)
        insts.append({'id': len(insts), 'mask': comp,
                      'box': [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]})

    thumb = src.copy()
    thumb.thumbnail((1100, 1100))
    listing = '\n'.join(f'{i["id"]}. box_frac=({i["box"][0]/W:.2f},{i["box"][1]/H:.2f},'
                        f'{i["box"][2]/W:.2f},{i["box"][3]/H:.2f})' for i in insts)
    v = ask_json([thumb, f'For each numbered region, decide if the object IMPEDES WALKING '
                         '(raised off ground: walls, machines, tanks, furniture, crates, '
                         'stalls, railings, pylons). NOT impeding: stairs, ramps, flat '
                         'markings, cables lying flat, doors, shadows.\n'
                         f'{listing}\nReturn JSON: {{"impeding": [ids], '
                         '"names": {{"<id>": "short name"}}}}'])
    keep_ids = set((v or {}).get('impeding', [i['id'] for i in insts]))
    names = (v or {}).get('names', {})
    kept = [dict(i, name=names.get(str(i['id']), 'object')) for i in insts if i['id'] in keep_ids]
    print(f'selected impeding: {len(kept)}/{len(insts)}')
    return kept


def amodal_complete(crop_pil, inst_mask_crop, name):
    """Paint the fully unoccluded object on a magenta background crop."""
    bg = np.asarray(crop_pil).copy()
    bg[~inst_mask_crop] = [255, 0, 255]
    input_img = Image.fromarray(bg)

    prompt = (
        f'This is a crop showing "{name}" against a magenta background. Paint the COMPLETE, '
        f'FULLY UNOCCLUDED version of this object — show everything including any parts that '
        f'would be hidden behind it or under it in the original view. Paint the full object as '
        f'it would look from the same camera angle but with nothing blocking it. Keep the '
        f'magenta background everywhere the object does not cover. Paint with the same art '
        f'style and colors as the original.'
    )

    img = gen_image([input_img, prompt], size='1K')
    return img


def extract_amodal_footprint(amodal_img, crop_h, crop_w, depth_ratio=0.35):
    """Extract footprint from the amodal completion: bottom band of the
    non-magenta region, scaled by estimated plan depth."""
    arr = np.asarray(amodal_img.resize((crop_w, crop_h), Image.NEAREST)).astype(np.int16)
    dm = np.linalg.norm(arr - np.array([255, 0, 255], np.int16), axis=2)
    obj_mask = dm > 90

    if not obj_mask.any():
        return np.zeros((crop_h, crop_w), bool)

    ys, xs = np.where(obj_mask)
    y_max = int(ys.max())
    y_min = int(ys.min())
    obj_height = y_max - y_min

    band_height = max(10, int(obj_height * depth_ratio))
    band_top = max(0, y_max - band_height)

    footprint = obj_mask.copy()
    footprint[:band_top, :] = False

    return footprint


def main():
    room = sys.argv[1] if len(sys.argv) > 1 else 'anchorroom'
    plate_p, walk_p, cls_p = resolve_paths(room)

    if not os.path.exists(plate_p):
        sys.exit(f'plate not found: {plate_p}')

    out = os.path.join(ROOT, 'docs', 'art-options', 'bench', 'prompt', room)
    os.makedirs(out, exist_ok=True)

    src = Image.open(plate_p).convert('RGB')
    W, H = src.size
    seg_in = src.copy()
    seg_in.thumbnail((1200, 1200))

    print(f'=== A4: Amodal footprints for {room} ===')

    kept = census_and_select(src, seg_in, W, H, out)
    if not kept:
        sys.exit('no impeding instances found')

    fp_union = np.zeros((H, W), bool)
    results = []

    for inst in kept:
        x0, y0, x1, y1 = inst['box']
        pad = max(60, (y1 - y0) // 2)
        cx0, cy0 = max(0, x0 - pad), max(0, y0 - pad)
        cx1, cy1 = min(W, x1 + pad), min(H, y1 + pad + 30)
        crop = src.crop((cx0, cy0, cx1, cy1))
        crop_w, crop_h = crop.size
        nm = inst['name']
        sub = inst['mask'][cy0:cy1, cx0:cx1]

        amodal = amodal_complete(crop, sub, nm)
        if amodal is None:
            print(f'  [{inst["id"]}:{nm}] amodal completion failed')
            fb = inst['mask'].copy()
            fb[:max(0, y1 - max(20, (y1 - y0) // 4)), :] = False
            fp_union |= fb
            results.append({'id': inst['id'], 'name': nm, 'status': 'fallback'})
            continue

        amodal.save(os.path.join(out, f'amodal-{inst["id"]}-{nm.replace(" ", "_")}.jpg'), quality=86)

        depth_est = ask_json([crop,
                              f'This is a crop of "{nm}" in a 3/4 top-down game scene. '
                              f'The object\'s visible height in the crop is about {crop_h}px. '
                              f'What fraction of its TOTAL height (from ground contact to top) '
                              f'represents its plan depth (how far it extends into the ground '
                              f'plane away from camera)? Return JSON: '
                              f'{{"depth_ratio": 0.0 to 1.0}}'], maxtok=512)
        dr = 0.35
        if depth_est and 'depth_ratio' in depth_est:
            dr = max(0.15, min(0.8, float(depth_est['depth_ratio'])))

        fp = extract_amodal_footprint(amodal, crop_h, crop_w, depth_ratio=dr)
        fp_union[cy0:cy1, cx0:cx1] |= fp

        print(f'  [{inst["id"]}:{nm}] amodal footprint extracted, depth_ratio={dr:.2f}, '
              f'fp_px={fp.sum()}')
        results.append({'id': inst['id'], 'name': nm, 'status': 'ok',
                        'depth_ratio': round(dr, 2), 'fp_px': int(fp.sum())})

    Image.fromarray((fp_union * 255).astype(np.uint8)).save(
        os.path.join(out, 'amodal-footprints.png'))

    walk = np.asarray(Image.open(walk_p).convert('L').resize((W, H), Image.NEAREST)) > 127
    water = np.zeros((H, W), bool)
    if os.path.exists(cls_p):
        cls = np.asarray(Image.open(cls_p).convert('RGB').resize((W, H), Image.NEAREST)).astype(np.int16)
        water = np.linalg.norm(cls - np.array([0, 0, 255], np.int16), axis=2) < 90

    bodies = np.zeros((H, W), bool)
    for inst in kept:
        bodies |= inst['mask']

    collision = (walk | cv2.dilate((bodies & ~fp_union).astype(np.uint8),
                                   np.ones((13, 13), np.uint8)).astype(bool)) & ~(fp_union | water)

    Image.fromarray((collision * 255).astype(np.uint8)).save(
        os.path.join(out, 'amodal-collision.png'))

    b = np.asarray(src).astype(np.float32)
    ov = b.copy()
    ov[collision] = ov[collision] * 0.6 + np.array([40, 255, 90], np.float32) * 0.4
    ov[~collision] = ov[~collision] * 0.6 + np.array([255, 40, 40], np.float32) * 0.4
    Image.fromarray(ov.clip(0, 255).astype(np.uint8)).save(
        os.path.join(out, 'amodal-collision-on-source.jpg'), quality=88)

    ov2 = b.copy()
    ov2[fp_union] = ov2[fp_union] * 0.4 + np.array([255, 60, 60], np.float32) * 0.6
    Image.fromarray(ov2.clip(0, 255).astype(np.uint8)).save(
        os.path.join(out, 'amodal-footprints-on-source.jpg'), quality=88)

    ok_count = sum(1 for r in results if r['status'] == 'ok')
    metrics = {
        'room': room,
        'method': 'A4-amodal',
        'instances': len(kept),
        'ok': ok_count,
        'fallback': len(results) - ok_count,
        'walk_frac': round(float(collision.mean()), 3),
        'per_instance': results,
    }
    with open(os.path.join(out, 'amodal-metrics.json'), 'w') as f:
        json.dump(metrics, f, indent=2)

    print(f'\namodal done: {ok_count}/{len(kept)} ok, walk_frac={collision.mean():.3f}')


if __name__ == '__main__':
    main()
