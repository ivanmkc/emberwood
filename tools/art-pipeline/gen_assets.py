#!/usr/bin/env python3
"""NBP per-asset generator for Emberwood's Eastward art direction.

Policy: Nano Banana Pro generates INDIVIDUAL assets only (one prop per call,
on a flat magenta key background, style-anchored to the approved village
concept). The engine composes scenes; no whole-scene generation.

Pipeline per asset:
  1. generate  — gemini-3-pro-image, contents=[style anchor image, prompt]
  2. key       — border-median chroma key (kidsgame technique) + 1px erode
  3. trim      — crop to alpha bbox
  4. downscale — LANCZOS to target sprite height

Usage: python3 tools/art-pipeline/gen_assets.py [asset ...]   (default: all)
"""
import io
import os
import sys
import statistics

from PIL import Image
from google import genai
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ANCHOR = os.path.join(ROOT, 'docs', 'art-options', 'nbp-eastward-village.png')
RAW_DIR = os.path.join(ROOT, 'docs', 'art-options', 'assets', 'raw')
OUT_DIR = os.path.join(ROOT, 'docs', 'art-options', 'assets')

KEY_BG = 'flat solid pure magenta (#FF00FF) background'
BASE_PROMPT = (
    'Using EXACTLY the pixel-art style, palette, lighting and level of detail '
    'of the reference image (dense modern pixel art, dusk teal shadows, warm '
    'highlights): generate ONE single isolated game asset — {desc} — centered '
    'on a {bg}, filling most of the frame. Top-down oblique 3/4 RPG '
    'perspective as in the reference. No ground, no shadow cast on the '
    'background, no other objects, no text, no border.'
)

# name -> (description, target_height_px)
ASSETS = {
    'tree': ('a leafy deciduous tree with a visible trunk, canopy lit from the upper left', 96),
    'rock': ('a single mossy grey boulder', 32),
    'chest': ('a closed wooden treasure chest with gold trim, front face visible', 32),
    'beacon': ('a round stone beacon brazier with a bright orange flame burning in its bowl', 48),
    'lamp': ('STRICTLY ONE OBJECT: a single tall thin wrought-iron street lamp post with one glowing lantern at its top. Nothing else in the image — no ground, no scene, no village, no fire pit; every pixel that is not the lamp post itself must be flat magenta', 64),
    'house': ('a two-story timber-frame cottage with a steep shingled roof, warm glowing windows and a wooden door, front facade and roof visible', 160),
}


def border_median_key(img, thresh=90):
    """Remove the key background using the median border color."""
    img = img.convert('RGBA')
    px = img.load()
    w, h = img.size
    border = []
    for x in range(0, w, 7):
        border += [px[x, 0][:3], px[x, h - 1][:3]]
    for y in range(0, h, 7):
        border += [px[0, y][:3], px[w - 1, y][:3]]
    key = tuple(int(statistics.median(c[i] for c in border)) for i in range(3))
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if (r - key[0]) ** 2 + (g - key[1]) ** 2 + (b - key[2]) ** 2 < thresh ** 2:
                px[x, y] = (0, 0, 0, 0)
    # 1px erode to eat key-bleed fringes
    mask = img.getchannel('A').point(lambda v: 255 if v > 0 else 0)
    from PIL import ImageFilter
    eroded = mask.filter(ImageFilter.MinFilter(3))
    img.putalpha(eroded)
    return img, key


def process(name, desc, target_h, client, anchor):
    raw_path = os.path.join(RAW_DIR, f'{name}.png')
    if not os.path.exists(raw_path):
        prompt = BASE_PROMPT.format(desc=desc, bg=KEY_BG)
        resp = client.models.generate_content(
            model='gemini-3-pro-image',
            contents=[anchor, prompt],
            config=types.GenerateContentConfig(
                image_config=types.ImageConfig(aspect_ratio='1:1', image_size='1K'),
            ),
        )
        img = None
        for part in resp.parts:
            if part.inline_data is not None:
                img = Image.open(io.BytesIO(part.inline_data.data))
        if img is None:
            print(f'{name}: NO IMAGE ({resp.text[:120] if resp.text else "?"})')
            return None
        img.save(raw_path)
    img = Image.open(raw_path)
    keyed, key = border_median_key(img)
    bbox = keyed.getbbox()
    if not bbox:
        print(f'{name}: keyed to nothing (key={key})')
        return None
    keyed = keyed.crop(bbox)
    scale = target_h / keyed.height
    out = keyed.resize((max(1, round(keyed.width * scale)), target_h), Image.LANCZOS)
    out_path = os.path.join(OUT_DIR, f'{name}.png')
    out.save(out_path)
    print(f'{name}: raw {img.size} -> keyed {keyed.size} -> {out.size} (key={key})')
    return out_path


def main():
    os.makedirs(RAW_DIR, exist_ok=True)
    client = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
    anchor = Image.open(ANCHOR)
    anchor.thumbnail((1024, 1024))
    names = sys.argv[1:] or list(ASSETS)
    for name in names:
        desc, target_h = ASSETS[name]
        process(name, desc, target_h, client, anchor)


if __name__ == '__main__':
    main()
