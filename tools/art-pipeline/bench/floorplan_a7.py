#!/usr/bin/env python3
"""A7: screen-space floorplan generation.

Asks the image model to redraw each scene as an architect-style floorplan
kept in the SAME camera/screen space (same perspective, pixel-aligned for
overlay). Two arms:
  - NBP (gemini-3-pro-image): always available
  - GPT-Image-2: runs only when OPENAI_API_KEY is set

Floorplan convention:
  white (#FFFFFF) = walkable floor
  black lines     = wall bases / structural outlines
  solid gray      = each object's full plan-view ground footprint
  blue (#0000FF)  = water
  faint 16px grid preserved

Extraction: white -> walk mask, gray shapes -> footprint mask.
Gate: Canny agreement between floorplan edges and source plate edges.

Usage:
  python3 floorplan_a7.py <room> [--rolls 3]
  python3 floorplan_a7.py anchorroom night-bazaar plaza-market-inside
"""
import io
import json
import os
import sys
import threading

import cv2
import numpy as np
from PIL import Image
from google import genai
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

FLOORPLAN_PROMPT = (
    'Redraw this EXACT scene as an architect-style FLOORPLAN in the SAME screen space. '
    'Every object and wall must stay at its EXACT screen position — the floorplan must '
    'overlay the original image pixel-for-pixel.\n\n'
    'Use these flat colors with NO shading, NO gradients, NO anti-aliasing:\n'
    '- pure WHITE #FFFFFF: all walkable floor surfaces (plaza ground, decks, bridges, '
    'grates, platforms, staircases, doorway thresholds, interior floors, flat ground '
    'markings like stains/cables/cracks)\n'
    '- BLACK lines: wall bases, structural outlines, building footprint edges\n'
    '- solid GRAY #808080: each object\'s full PLAN-VIEW ground footprint — the area '
    'the object occupies on the floor as seen from directly above, INCLUDING hidden '
    'base area behind the object\'s body. Draw the footprint as a solid gray shape at '
    'the object\'s base position. Tanks, pylons, crates, benches, machines — all get '
    'gray footprints.\n'
    '- pure BLUE #0000FF: water, coolant, liquid surfaces\n'
    '- Keep a faint 16-pixel tile grid visible\n\n'
    'The result must look like a FLAT architectural plan drawing that overlays the '
    'original scene perfectly — same camera angle, same positions, no rotation or '
    'rectification to bird\'s-eye. Every pixel must be exactly one of: white, black, '
    'gray, or blue.'
)

MIN_CANNY_AGREEMENT = 0.10
N_BEST_OF = 3

_tl = threading.local()


def cli():
    if not hasattr(_tl, 'c'):
        _tl.c = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
    return _tl.c


def resolve_plate(room):
    if room == 'anchorroom':
        return os.path.join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor-clean.png')
    return os.path.join(ROOT, 'docs', 'art-options', 'rooms', room, 'plate.png')


def canny_agreement(floorplan_rgb, source_rgb, threshold=5):
    """Fraction of source Canny edges within threshold px of floorplan edges."""
    src_gray = cv2.cvtColor(np.asarray(source_rgb), cv2.COLOR_RGB2GRAY)
    fp_gray = cv2.cvtColor(np.asarray(floorplan_rgb), cv2.COLOR_RGB2GRAY)
    src_edges = cv2.Canny(src_gray, 80, 200) > 0
    fp_edges = cv2.Canny(fp_gray, 80, 200) > 0
    k = threshold * 2 + 1
    dilated_fp = cv2.dilate(fp_edges.astype(np.uint8), np.ones((k, k), np.uint8)) > 0
    if src_edges.sum() == 0:
        return 1.0
    return float((src_edges & dilated_fp).sum() / src_edges.sum())


def extract_masks(floorplan_rgb, W, H):
    """Extract walk and footprint masks from the floorplan.

    White (#FFFFFF vicinity) -> walkable
    Gray (#808080 vicinity) -> object footprints (blocked)
    Blue (#0000FF vicinity) -> water (blocked)
    Black -> walls (blocked)
    """
    arr = np.asarray(floorplan_rgb.resize((W, H), Image.NEAREST)).astype(np.float32)

    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]

    white = (r > 200) & (g > 200) & (b > 200)

    gray = (np.abs(r - 128) < 60) & (np.abs(g - 128) < 60) & (np.abs(b - 128) < 60) & ~white
    gray &= (np.abs(r - g) < 30) & (np.abs(r - b) < 30)

    blue = (b > 150) & (r < 100) & (g < 100)

    walk = white
    footprint = gray
    water = blue

    collision = walk & ~footprint & ~water

    return {
        'walk': walk,
        'footprint': footprint,
        'water': water,
        'collision': collision,
        'walk_frac': float(walk.mean()),
        'footprint_frac': float(footprint.mean()),
        'water_frac': float(water.mean()),
    }


def generate_nbp_floorplan(plate_img, W, H):
    """Generate a single floorplan roll via gemini-3-pro-image."""
    seg_in = plate_img.copy()
    seg_in.thumbnail((1200, 1200))

    for attempt in range(3):
        try:
            resp = cli().models.generate_content(
                model='gemini-3-pro-image',
                contents=[seg_in, FLOORPLAN_PROMPT],
                config=types.GenerateContentConfig(
                    image_config=types.ImageConfig(aspect_ratio='4:3', image_size='2K')),
            )
            for part in (resp.parts or []):
                if part.inline_data is not None:
                    img = Image.open(io.BytesIO(part.inline_data.data)).convert('RGB')
                    return img.resize((W, H), Image.NEAREST)
        except Exception as e:
            print(f'    NBP attempt {attempt} error: {e}')
    return None


def generate_gpt_floorplan(plate_img, W, H):
    """Generate a floorplan via GPT-Image-2 (requires OPENAI_API_KEY)."""
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return None

    try:
        import openai
    except ImportError:
        print('  openai package not installed, skipping GPT arm')
        return None

    buf = io.BytesIO()
    plate_thumb = plate_img.copy()
    plate_thumb.thumbnail((1024, 1024))
    plate_thumb.save(buf, format='PNG')
    buf.seek(0)

    client = openai.OpenAI(api_key=api_key)
    for attempt in range(3):
        try:
            response = client.images.edit(
                model='gpt-image-2',
                image=buf,
                prompt=FLOORPLAN_PROMPT,
                size='1024x1024',
            )
            if response.data and response.data[0].b64_json:
                import base64
                img_bytes = base64.b64decode(response.data[0].b64_json)
                img = Image.open(io.BytesIO(img_bytes)).convert('RGB')
                return img.resize((W, H), Image.NEAREST)
            elif response.data and response.data[0].url:
                import urllib.request
                img_bytes = urllib.request.urlopen(response.data[0].url).read()
                img = Image.open(io.BytesIO(img_bytes)).convert('RGB')
                return img.resize((W, H), Image.NEAREST)
        except Exception as e:
            print(f'    GPT attempt {attempt} error: {e}')
    return None


def make_overlay(source_rgb, floorplan_rgb, alpha=0.5):
    """Blend floorplan over source for visual comparison."""
    s = np.asarray(source_rgb).astype(np.float32)
    f = np.asarray(floorplan_rgb).astype(np.float32)
    if f.shape[:2] != s.shape[:2]:
        f = np.asarray(Image.fromarray(f.astype(np.uint8)).resize(
            (s.shape[1], s.shape[0]), Image.NEAREST)).astype(np.float32)
    blend = s * (1 - alpha) + f * alpha
    return Image.fromarray(blend.clip(0, 255).astype(np.uint8))


def run_room(room, n_rolls=3):
    """Run A7 floorplan generation + evaluation for one room."""
    plate_p = resolve_plate(room)
    if not os.path.exists(plate_p):
        print(f'[{room}] plate not found: {plate_p}')
        return None

    out = os.path.join(ROOT, 'docs', 'art-options', 'bench', 'prompt', room)
    os.makedirs(out, exist_ok=True)

    src = Image.open(plate_p).convert('RGB')
    W, H = src.size

    print(f'=== A7 floorplan: {room} ({W}x{H}) ===')

    best_nbp = None
    best_nbp_score = -1
    nbp_rolls = []

    for r in range(n_rolls):
        print(f'  [NBP roll {r}]')
        fp_img = generate_nbp_floorplan(src, W, H)
        if fp_img is None:
            print(f'    failed')
            nbp_rolls.append({'roll': r, 'status': 'failed'})
            continue

        ca = canny_agreement(fp_img, src)
        masks = extract_masks(fp_img, W, H)
        roll_info = {
            'roll': r,
            'status': 'ok',
            'canny_agreement': round(ca, 3),
            'walk_frac': round(masks['walk_frac'], 3),
            'footprint_frac': round(masks['footprint_frac'], 3),
            'water_frac': round(masks['water_frac'], 3),
        }
        nbp_rolls.append(roll_info)
        print(f'    canny={ca:.3f}, walk={masks["walk_frac"]:.3f}, '
              f'fp={masks["footprint_frac"]:.3f}')

        fp_img.save(os.path.join(out, f'A7-nbp-floorplan-roll-{r}.png'))

        if ca > best_nbp_score:
            best_nbp_score = ca
            best_nbp = (fp_img, masks, ca)

    nbp_result = None
    if best_nbp is not None:
        fp_img, masks, ca = best_nbp
        fp_img.save(os.path.join(out, 'A7-nbp-floorplan.png'))

        collision_mask = masks['collision']
        Image.fromarray((collision_mask * 255).astype(np.uint8)).save(
            os.path.join(out, 'A7-nbp-collision.png'))

        overlay = make_overlay(src, fp_img, alpha=0.5)
        overlay.save(os.path.join(out, 'A7-nbp-floorplan-overlay.jpg'), quality=88)

        coll_overlay_arr = np.asarray(src).astype(np.float32).copy()
        coll_overlay_arr[collision_mask] = (
            coll_overlay_arr[collision_mask] * 0.6 +
            np.array([40, 255, 90], np.float32) * 0.4)
        coll_overlay_arr[~collision_mask] = (
            coll_overlay_arr[~collision_mask] * 0.6 +
            np.array([255, 40, 40], np.float32) * 0.4)
        Image.fromarray(coll_overlay_arr.clip(0, 255).astype(np.uint8)).save(
            os.path.join(out, 'A7-nbp-overlay.jpg'), quality=88)

        sys.path.insert(0, os.path.join(ROOT, 'tools', 'art-pipeline', 'bench'))
        import evaluate as ev
        met = ev.evaluate_method(room, 'A7-nbp-floorplan',
                                 os.path.join(out, 'A7-nbp-collision.png'),
                                 out_dir=out)
        nbp_result = {
            'method': 'A7-nbp-floorplan',
            'canny_agreement_floorplan': round(ca, 3),
            'gate': 'pass' if ca >= MIN_CANNY_AGREEMENT else 'fail',
            'metrics': met,
            'rolls': nbp_rolls,
        }
        print(f'  [NBP best] canny={ca:.3f} IoU={met.get("iou_vs_consensus", "N/A")} '
              f'config_reach={met.get("config_space_reach_frac", "N/A")}')
    else:
        print(f'  [NBP] all rolls failed')

    gpt_result = None
    api_key = os.environ.get('OPENAI_API_KEY')
    if api_key:
        print(f'  [GPT-Image-2]')
        best_gpt = None
        best_gpt_score = -1
        gpt_rolls = []

        for r in range(n_rolls):
            print(f'  [GPT roll {r}]')
            fp_img = generate_gpt_floorplan(src, W, H)
            if fp_img is None:
                gpt_rolls.append({'roll': r, 'status': 'failed'})
                continue

            ca = canny_agreement(fp_img, src)
            masks = extract_masks(fp_img, W, H)
            roll_info = {
                'roll': r, 'status': 'ok',
                'canny_agreement': round(ca, 3),
                'walk_frac': round(masks['walk_frac'], 3),
                'footprint_frac': round(masks['footprint_frac'], 3),
            }
            gpt_rolls.append(roll_info)
            print(f'    canny={ca:.3f}')

            fp_img.save(os.path.join(out, f'A7-gpt-floorplan-roll-{r}.png'))
            if ca > best_gpt_score:
                best_gpt_score = ca
                best_gpt = (fp_img, masks, ca)

        if best_gpt is not None:
            fp_img, masks, ca = best_gpt
            fp_img.save(os.path.join(out, 'A7-gpt-floorplan.png'))
            collision_mask = masks['collision']
            Image.fromarray((collision_mask * 255).astype(np.uint8)).save(
                os.path.join(out, 'A7-gpt-collision.png'))
            overlay = make_overlay(src, fp_img, alpha=0.5)
            overlay.save(os.path.join(out, 'A7-gpt-floorplan-overlay.jpg'), quality=88)

            met = ev.evaluate_method(room, 'A7-gpt-floorplan',
                                     os.path.join(out, 'A7-gpt-collision.png'),
                                     out_dir=out)
            gpt_result = {
                'method': 'A7-gpt-floorplan',
                'canny_agreement_floorplan': round(ca, 3),
                'metrics': met,
                'rolls': gpt_rolls,
            }
    else:
        gpt_result = {
            'method': 'A7-gpt-floorplan',
            'blocked': True,
            'reason': 'no OPENAI_API_KEY in environment',
        }
        print(f'  [GPT-Image-2] BLOCKED: no OPENAI_API_KEY')

    combined = {
        'room': room,
        'nbp': nbp_result,
        'gpt': gpt_result,
    }
    with open(os.path.join(out, 'A7-floorplan-metrics.json'), 'w') as f:
        json.dump(combined, f, indent=2)

    return combined


def main():
    rooms = sys.argv[1:] or ['anchorroom', 'night-bazaar', 'plaza-market-inside']
    n_rolls = N_BEST_OF
    filtered_rooms = []
    i = 0
    while i < len(rooms):
        if rooms[i] == '--rolls' and i + 1 < len(rooms):
            n_rolls = int(rooms[i + 1])
            i += 2
        else:
            filtered_rooms.append(rooms[i])
            i += 1

    all_results = {}
    for room in filtered_rooms:
        result = run_room(room, n_rolls=n_rolls)
        if result:
            all_results[room] = result

    print('\n=== A7 SUMMARY ===')
    for room, res in all_results.items():
        nbp = res.get('nbp')
        gpt = res.get('gpt')
        nbp_iou = nbp['metrics'].get('iou_vs_consensus', 'N/A') if nbp else 'failed'
        nbp_ca = nbp.get('canny_agreement_floorplan', 'N/A') if nbp else 'N/A'
        gpt_status = 'blocked' if (gpt and gpt.get('blocked')) else (
            gpt['metrics'].get('iou_vs_consensus', 'N/A') if gpt and gpt.get('metrics') else 'failed')
        print(f'  {room}: NBP IoU={nbp_iou} canny={nbp_ca} | GPT={gpt_status}')


if __name__ == '__main__':
    main()
