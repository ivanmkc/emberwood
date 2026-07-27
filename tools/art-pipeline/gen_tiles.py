#!/usr/bin/env python3
"""Seamless terrain-tile generator for the sci-fi Eastward direction.

Per tile: NBP generates a tileable plan-view texture (style-anchored),
we measure the wrap seam, cross-fade-blend it away if needed, and export a
32px game tile. The preview sheet tiles each texture 4x4 so seams show.

Usage: python3 tools/art-pipeline/gen_tiles.py [tile ...]   (default: all)
"""
import io
import os
import sys

import numpy as np
from PIL import Image
from google import genai
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ANCHOR = os.path.join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor.png')
RAW_DIR = os.path.join(ROOT, 'docs', 'art-options', 'tiles-scifi', 'raw')
OUT_DIR = os.path.join(ROOT, 'docs', 'art-options', 'tiles-scifi')
TILE_PX = 32
CROP_PX = 256
N_VARIANTS = 3

PROMPT = (
    'Using EXACTLY the pixel-art style and palette of the reference image: '
    'a SEAMLESS TILEABLE top-down 2D game terrain texture of {desc}. '
    'Flat plan view straight down at the ground, perfectly even lighting, '
    'no perspective, no objects, no shadows from off-screen, no border, '
    'no vignette. The texture must tile perfectly: the left edge continues '
    'the right edge, the top edge continues the bottom edge. Fill the '
    'entire frame edge to edge.'
)

TILES = {
    'ground': 'packed dry earth warmed by orange dusk light, sparse small patches of glowing teal moss, clean chunky pixel clusters like the reference, gentle contrast',
    'plate': 'worn metal plaza floor plating with rivets, panel lines and faint scuff marks',
    'dust': 'fine grey-tan regolith dust with subtle drifts and scattered grit',
    'coolant': 'deep dark teal industrial coolant liquid, mostly dark with sparse faint lighter ripple lines, muted and calm, low contrast',
    'walkway': 'industrial metal walkway planks with tread grip texture, laid horizontally',
    'rubble': 'uniform field of small broken concrete fragments and grey grit, consistent small feature size, muted low contrast, no large slabs, no recognizable objects',
    'minefloor': 'dark rocky mine floor with grit, small stones and faint tool marks',
    'minewall': 'solid mass of dark rough rock lumps, uniform dense stone field, no plants, no structures, no branches, nearly black crevices between grey-brown stone lumps',
    'floorpanel': 'clean habitat interior floor made of light grey composite panels with thin seam lines and subtle wear',
    'wallpanel': 'habitat interior wall panelling with vertical corrugated metal ribs and occasional small vents, muted warm grey',
    'carpet': 'CHUNKY PIXEL ART (big visible square pixels, like a 32x32 game tile scaled up): dark red utility floor matting with a subtle repeating geometric weave pattern and thin gold accent lines',
}


def seam_error(arr):
    lr = np.abs(arr[:, 0].astype(int) - arr[:, -1].astype(int)).mean()
    tb = np.abs(arr[0, :].astype(int) - arr[-1, :].astype(int)).mean()
    return lr, tb


def wrap_blend(img, band_frac=0.06):
    """Cross-fade opposite edges over a narrow band to kill wrap seams."""
    arr = np.asarray(img.convert('RGB')).astype(float)
    h, w, _ = arr.shape
    bw = max(2, int(w * band_frac))
    bh = max(2, int(h * band_frac))
    rolled = np.roll(arr, w // 2, axis=1)
    for i in range(bw):
        a = (i + 1) / (bw + 1)
        c = w // 2 - bw // 2 + i
        rolled[:, c] = rolled[:, c] * a + rolled[:, w // 2 - bw // 2 - 1] * (1 - a)
    arr = np.roll(rolled, -(w // 2), axis=1)
    rolled = np.roll(arr, h // 2, axis=0)
    for i in range(bh):
        a = (i + 1) / (bh + 1)
        r = h // 2 - bh // 2 + i
        rolled[r, :] = rolled[r, :] * a + rolled[h // 2 - bh // 2 - 1, :] * (1 - a)
    arr = np.roll(rolled, -(h // 2), axis=0)
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8))


def main():
    os.makedirs(RAW_DIR, exist_ok=True)
    client = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
    anchor = Image.open(ANCHOR)
    anchor.thumbnail((1024, 1024))
    names = sys.argv[1:] or list(TILES)
    for name in names:
        raw_path = os.path.join(RAW_DIR, f'{name}.png')
        if not os.path.exists(raw_path):
            resp = client.models.generate_content(
                model='gemini-3-pro-image',
                contents=[anchor, PROMPT.format(desc=TILES[name])],
                config=types.GenerateContentConfig(
                    image_config=types.ImageConfig(aspect_ratio='1:1', image_size='1K'),
                ),
            )
            img = None
            for part in resp.parts:
                if part.inline_data is not None:
                    img = Image.open(io.BytesIO(part.inline_data.data))
            if img is None:
                print(f'{name}: NO IMAGE')
                continue
            img.save(raw_path)
        img = Image.open(raw_path).convert('RGB')
        # Crop representative patches instead of squashing the whole texture:
        # full-image downscale changes feature scale and mushes detail.
        # Rank candidate windows by post-blend seam error + mean-color drift,
        # then keep the best N_VARIANTS as tile variants — the engine picks a
        # variant per cell by position hash, which kills the repetition grid.
        w, h = img.size
        full_mean = np.asarray(img).reshape(-1, 3).mean(axis=0)
        scored = []
        for ox, oy in [(0, 0), (-180, 0), (180, 0), (0, -180), (0, 180),
                       (-180, -180), (180, 180), (-180, 180), (180, -180),
                       (-300, 0), (300, 0), (0, -300), (0, 300)]:
            cx = (w - CROP_PX) // 2 + ox
            cy = (h - CROP_PX) // 2 + oy
            if cx < 0 or cy < 0 or cx + CROP_PX > w or cy + CROP_PX > h:
                continue
            crop = img.crop((cx, cy, cx + CROP_PX, cy + CROP_PX))
            fixed = wrap_blend(crop)
            arr = np.asarray(fixed)
            lr, tb = seam_error(arr)
            drift = np.abs(arr.reshape(-1, 3).mean(axis=0) - full_mean).mean()
            scored.append((max(lr, tb) + drift * 0.5, fixed, lr, tb))
        scored.sort(key=lambda s: s[0])
        picks = scored[:N_VARIANTS]
        for i, (_, fixed, lr, tb) in enumerate(picks):
            # normalize each variant's per-channel mean to the texture's global
            # mean — otherwise the variant mix reads as a brightness patchwork
            arr = np.asarray(fixed).astype(float)
            arr += full_mean - arr.reshape(-1, 3).mean(axis=0)
            fixed = Image.fromarray(arr.clip(0, 255).astype(np.uint8))
            tile = fixed.resize((TILE_PX, TILE_PX), Image.LANCZOS)
            tile.save(os.path.join(OUT_DIR, f'{name}-{i}.png'))
        # variant 0 doubles as the canonical single tile
        Image.open(os.path.join(OUT_DIR, f'{name}-0.png')).save(
            os.path.join(OUT_DIR, f'{name}.png'))
        print(f'{name}: {len(picks)} variants, best seam lr={picks[0][2]:.1f} tb={picks[0][3]:.1f}')


if __name__ == '__main__':
    main()
