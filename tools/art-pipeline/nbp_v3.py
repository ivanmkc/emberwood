#!/usr/bin/env python3
"""v3 mask algorithm (Ivan's spec): iterative instance census -> select
movement-impeding objects -> per-object X-RAY footprints -> composed collision.

Stages (all overlays saved under docs/art-options/v3/<room>/):
  1. census: NBP paints flat instance colors OVER the source; a verification
     agent lists missed objects; regenerate WITH the missed list until the
     verifier says nothing is missing (cap 4 rounds).
  2. select: verifier keeps instances that are raised off the ground and
     impede movement (stairs, flat markings, ground cables excluded).
  3. xray: for EACH kept object independently, NBP colors the FULL plan-view
     footprint where it sits on the ground — including the hidden base behind
     its body — on a padded crop; deterministic + LLM gates, retry per object.
  4. compose: collision v3 = union(xray footprints) ∪ water ∪ non-walk
     background (from the existing walk pass); bodies above footprints stay
     walk-behind.

Usage: nbp_v3.py <room>
"""
import io
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image
from google import genai
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
client = genai.Client(vertexai=True, project='adk-coding-agents', location='global')

PALETTE = [(255, 0, 0), (0, 128, 255), (255, 0, 255), (255, 128, 0), (0, 255, 255),
           (128, 0, 255), (255, 255, 0), (0, 255, 0), (128, 255, 0), (255, 0, 128),
           (0, 0, 255), (128, 128, 255), (255, 128, 128), (0, 128, 0), (128, 64, 0)]


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
        except Exception:  # noqa: BLE001
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
        except Exception:  # noqa: BLE001
            pass
    return None


def main():
    room = sys.argv[1]
    if room == 'anchorroom':
        plate_p = os.path.join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor-clean.png')
        walk_p = os.path.join(ROOT, 'docs', 'art-options', 'nbp-walk.png')
        cls_p = os.path.join(ROOT, 'docs', 'art-options', 'nbp-mask.png')
    else:
        base = os.path.join(ROOT, 'docs', 'art-options', 'rooms', room)
        plate_p = os.path.join(base, 'plate.png')
        walk_p = os.path.join(base, 'nbp-walk.png')
        cls_p = os.path.join(base, 'nbp-mask.png')
    out = os.path.join(ROOT, 'docs', 'art-options', 'v3', room)
    os.makedirs(out, exist_ok=True)
    src = Image.open(plate_p).convert('RGB')
    W, H = src.size
    seg_in = src.copy()
    seg_in.thumbnail((1200, 1200))

    # ---------- stage 1: iterative census ----------
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
        # colored = pixels that changed strongly vs source AND are saturated
        a = np.asarray(img).astype(np.int16)
        b = np.asarray(src).astype(np.int16)
        diff = np.linalg.norm(a - b, axis=2)
        hsv = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2HSV)
        colored = (diff > 90) & (hsv[..., 1] > 120)
        census = {'img': img, 'colored': colored}
        blend = b.astype(np.float32) * 0.45 + a.astype(np.float32) * 0.55
        ov = Image.fromarray(blend.clip(0, 255).astype(np.uint8))
        ov.thumbnail((1400, 1400), Image.LANCZOS)
        ov.save(os.path.join(out, f'census-r{rd}.jpg'), quality=86)
        v = ask_json([ov, 'Image: a game scene with an instance-segmentation color overlay on '
                          'its objects. List raised objects/structures that are NOT covered by '
                          'any flat color overlay (missed by the segmentation). Ignore open '
                          'floor, water, flat markings and shadows. Return JSON only: '
                          '{"missed": [{"name": "...", "box_2d": [ymin,xmin,ymax,xmax] 0-1000}]}'])
        missed = (v or {}).get('missed', [])
        print(f'[census r{rd}] colored {colored.mean():.1%}; verifier missed: '
              f'{[m["name"] for m in missed][:8]}{"..." if len(missed) > 8 else ""} ({len(missed)})')
        if not missed:
            break
        missed_note = '; '.join(m['name'] for m in missed[:12])
    if census is None:
        sys.exit('census failed')

    # instances = connected components of the colored overlay, split by color
    lab_img = cv2.cvtColor(np.asarray(census['img']), cv2.COLOR_RGB2LAB)
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
    print(f'census instances: {len(insts)}')

    # ---------- stage 2: select movement-impeding ----------
    listing = '\n'.join(f'{i["id"]}. box_frac=({i["box"][0]/W:.2f},{i["box"][1]/H:.2f},'
                        f'{i["box"][2]/W:.2f},{i["box"][3]/H:.2f})' for i in insts)
    thumb2 = src.copy()
    thumb2.thumbnail((1100, 1100))
    v = ask_json([thumb2, 'For each numbered region of this game scene (fractional boxes '
                          f'below), decide if the object there IMPEDES WALKING: it is raised '
                          'off the ground (walls, machines, tanks, furniture, crates, stalls, '
                          'railings, pylons). NOT impeding: stairs, ramps, flat floor '
                          'markings, cables lying flat, doors/thresholds, shadows.\n'
                          f'{listing}\nReturn JSON only: {{"impeding": [ids], '
                          '"names": {"<id>": "short name"}}'])
    keep_ids = set((v or {}).get('impeding', [i['id'] for i in insts]))
    names = (v or {}).get('names', {})
    kept = [i for i in insts if i['id'] in keep_ids]
    print(f'selected impeding: {len(kept)}/{len(insts)}')

    # ---------- stage 3: per-object x-ray footprints ----------
    fp_union = np.zeros((H, W), bool)
    for inst in kept:
        x0, y0, x1, y1 = inst['box']
        pad = max(60, (y1 - y0) // 2)
        cx0, cy0 = max(0, x0 - pad), max(0, y0 - pad)
        cx1, cy1 = min(W, x1 + pad), min(H, y1 + pad + 30)
        crop = src.crop((cx0, cy0, cx1, cy1))
        nm = names.get(str(inst['id']), 'object')
        # mark the object on the crop so NBP knows which one
        marked = np.asarray(crop).copy()
        sub = inst['mask'][cy0:cy1, cx0:cx1]
        edge = cv2.dilate(sub.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool) & ~sub
        marked[edge] = (0, 255, 255)
        ok_fp = None
        for attempt in range(3):
            img = gen_image([Image.fromarray(marked),
                             f'The object outlined in cyan is: {nm}. Repaint this EXACT crop with '
                             'ONE addition: paint pure red #FF0000 the FULL plan-view FOOTPRINT of '
                             'that object on the ground — the entire area of floor it occupies, '
                             'INCLUDING the hidden part behind/under its body, as if X-raying '
                             'through it (in this 3/4 view the footprint is a band from its front '
                             'base line up by its plan depth, drawn OVER its lower body). Do not '
                             'change anything else. NO dithering, hard boundary.'], size='1K')
            if img is None:
                continue
            arr = np.asarray(img.resize((cx1 - cx0, cy1 - cy0), Image.NEAREST)).astype(np.int16)
            base = np.asarray(crop).astype(np.int16)
            red = (np.linalg.norm(arr - np.array([255, 0, 0], np.int16), axis=2) < 100) & \
                  (np.linalg.norm(base - np.array([255, 0, 0], np.int16), axis=2) > 90)
            red = cv2.morphologyEx(red.astype(np.uint8), cv2.MORPH_OPEN,
                                   np.ones((7, 7), np.uint8)).astype(bool)
            area_ratio = red.sum() / max(1, sub.sum())
            # gates: footprint exists, is not the whole crop, anchored to the
            # object's lower half
            if red.sum() < 200 or red.mean() > 0.6 or not (0.05 <= area_ratio <= 1.6):
                print(f'  [{inst["id"]}:{nm}] attempt {attempt}: det gate fail '
                      f'(area_ratio {area_ratio:.2f}, frac {red.mean():.2f})')
                continue
            ys2 = np.where(red.any(axis=1))[0]
            oy = np.where(sub.any(axis=1))[0]
            if len(oy) and len(ys2) and ys2.mean() < (oy.min() + oy.max()) / 2 - (oy.max() - oy.min()) * 0.15:
                print(f'  [{inst["id"]}:{nm}] attempt {attempt}: footprint floats above lower half')
                continue
            jv = ask_json([img, f'Is the red region a plausible full plan-view ground footprint '
                                f'of the {nm} (covers where it meets/occupies the floor, '
                                'including hidden base, not its whole upper body)? Return JSON '
                                'only: {"ok": bool, "why": "short"}'], maxtok=1024)
            if jv and jv.get('ok'):
                ok_fp = red
                break
            print(f'  [{inst["id"]}:{nm}] attempt {attempt}: LLM gate fail ({(jv or {}).get("why", "?")})')
        if ok_fp is not None:
            fp_union[cy0:cy1, cx0:cx1] |= ok_fp
            print(f'  [{inst["id"]}:{nm}] footprint OK')
        else:
            # fail-safe: block the instance's own lower band rather than nothing
            fb = inst['mask'].copy()
            fb[:max(0, y1 - max(20, (y1 - y0) // 4)), :] = False
            fp_union |= fb
            print(f'  [{inst["id"]}:{nm}] FALLBACK lower-band footprint')

    Image.fromarray((fp_union * 255).astype(np.uint8)).save(os.path.join(out, 'xray-footprints.png'))

    # ---------- stage 4: compose ----------
    walk = np.asarray(Image.open(walk_p).convert('L').resize((W, H), Image.NEAREST)) > 127
    water = np.zeros((H, W), bool)
    if os.path.exists(cls_p):
        cls = np.asarray(Image.open(cls_p).convert('RGB').resize((W, H), Image.NEAREST)).astype(np.int16)
        water = np.linalg.norm(cls - np.array([0, 0, 255], np.int16), axis=2) < 90
    bodies = np.zeros((H, W), bool)
    for inst in kept:
        bodies |= inst['mask']
    walk_v3 = (walk | cv2.dilate((bodies & ~fp_union).astype(np.uint8),
                                 np.ones((13, 13), np.uint8)).astype(bool)) & ~(fp_union | water)
    Image.fromarray((walk_v3 * 255).astype(np.uint8)).save(os.path.join(out, 'collision-v3.png'))

    # overlays for the board
    b = np.asarray(src).astype(np.float32)
    for name2, mask, col in (('xray-on-source', fp_union, (255, 60, 60)),
                             ('collision-v3-on-source', ~walk_v3, (255, 40, 40))):
        blend = b.copy()
        blend[mask] = blend[mask] * 0.4 + np.array(col, np.float32) * 0.6
        if name2.startswith('collision'):
            blend[walk_v3] = blend[walk_v3] * 0.72 + np.array([40, 255, 90], np.float32) * 0.28
        ov = Image.fromarray(blend.clip(0, 255).astype(np.uint8))
        ov.thumbnail((1400, 1400), Image.LANCZOS)
        ov.save(os.path.join(out, f'{name2}.jpg'), quality=86)
    json.dump({'instances': len(insts), 'impeding': len(kept),
               'walk_frac_v3': round(float(walk_v3.mean()), 3)},
              open(os.path.join(out, 'v3-metrics.json'), 'w'))
    print('v3 done:', json.load(open(os.path.join(out, 'v3-metrics.json'))))


if __name__ == '__main__':
    main()
