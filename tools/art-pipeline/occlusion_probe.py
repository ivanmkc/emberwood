#!/usr/bin/env python3
"""Occlusion probing (Ivan): sample walkable positions, have NBP insert the
player character standing at each, then diff against the clean plate. Pixels
inside the expected silhouette that DIDN'T change were drawn over by the scene
— empirical foreground evidence at that ground-y. Aggregated, that yields a
per-pixel y-sort key (z-index) measured by analysis-by-synthesis instead of
declared by a semantic mask.

Kidsgame lessons applied: patch-local crops only (full-frame edits re-render),
diff-keying with a re-render sanity budget, judge labels per probe.
"""
import io
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image, ImageDraw

from google import genai
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tl = threading.local()


def cli():
    if not hasattr(_tl, 'c'):
        _tl.c = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
    return _tl.c


SCENES = {
 'anchorroom': 'docs/art-options/nbp-scifi-anchor-clean.png',
 'night-bazaar': 'docs/art-options/rooms/night-bazaar/plate.png',
 'plaza-market-inside': 'docs/art-options/rooms/plaza-market-inside/plate.png',
}
CROP = 800          # probe window (plate px)
CHAR_W, CHAR_H = 80, 176   # 20x44 sprite at plate scale 4x (1792/448)
DIFF_T = 42         # per-pixel max-channel change threshold
NOISE_BUDGET = 0.08  # max changed fraction OUTSIDE char bbox before roll invalid

PROMPT = (
 'Add the pixel-art character from the second image INTO this scene, standing with his feet '
 f'exactly on the magenta cross marker, facing the viewer, about {CHAR_H} pixels tall to match '
 'the scene\'s perspective and pixel-art style. CRITICAL RULES: (1) every other pixel of the '
 'scene must stay EXACTLY identical to the first image — same colors, same lighting, same '
 'objects, nothing else moves or changes; (2) draw the character correctly layered in the '
 'scene: if any scene object (awning, canopy, hanging sign, wire, pole, stall, counter) is '
 'physically in front of him at that spot, that object must cover the overlapping parts of '
 'him; (3) erase the magenta marker in the output.'
)


def sample_positions(walk, k_grid=(4, 3), margin=140):
    """Stratified walkable positions: per grid cell, the walkable pixel nearest
    the cell centroid. Cells with no walkable pixels are skipped."""
    H, W = walk.shape
    pts = []
    gx, gy = k_grid
    for j in range(gy):
        for i in range(gx):
            x0, x1 = int(i * W / gx), int((i + 1) * W / gx)
            y0, y1 = int(j * H / gy), int((j + 1) * H / gy)
            ys, xs = np.nonzero(walk[y0:y1, x0:x1])
            if len(xs) < 500:
                continue
            cx, cy = xs.mean(), ys.mean()
            d2 = (xs - cx) ** 2 + (ys - cy) ** 2
            n = int(np.argmin(d2))
            x, y = x0 + int(xs[n]), y0 + int(ys[n])
            x = int(np.clip(x, margin, W - margin))
            y = int(np.clip(y, margin, H - margin))
            if walk[y, x]:
                pts.append((x, y))
    return pts


def probe_one(plate, sprite, x, y):
    """Insert character at (x,y); return dict with crop box, visible mask,
    unchanged-in-bbox mask, gen crop, noise fraction. None if roll invalid."""
    W, H = plate.size
    cx0 = int(np.clip(x - CROP // 2, 0, W - CROP))
    cy0 = int(np.clip(y - CROP * 0.55, 0, H - CROP))
    crop = plate.crop((cx0, cy0, cx0 + CROP, cy0 + CROP))
    marked = crop.copy()
    dr = ImageDraw.Draw(marked)
    mx, my = x - cx0, y - cy0
    dr.line([(mx - 12, my), (mx + 12, my)], fill=(255, 0, 255), width=4)
    dr.line([(mx, my - 12), (mx, my + 12)], fill=(255, 0, 255), width=4)

    for attempt in range(2):
        try:
            r = cli().models.generate_content(
                model='gemini-3-pro-image', contents=[marked, sprite, PROMPT],
                config=types.GenerateContentConfig(
                    image_config=types.ImageConfig(aspect_ratio='1:1', image_size='1K')))
            for p in (r.parts or []):
                if p.inline_data is None:
                    continue
                gen = Image.open(io.BytesIO(p.inline_data.data)).convert('RGB') \
                           .resize((CROP, CROP), Image.LANCZOS)
                a = np.asarray(crop).astype(np.int16)
                g = np.asarray(gen).astype(np.int16)
                diff = np.abs(a - g).max(axis=2) > DIFF_T
                bbox = np.zeros((CROP, CROP), bool)
                bx0, bx1 = max(0, mx - CHAR_W // 2 - 8), min(CROP, mx + CHAR_W // 2 + 8)
                by0, by1 = max(0, my - CHAR_H - 12), min(CROP, my + 14)
                bbox[by0:by1, bx0:bx1] = True
                noise = float((diff & ~bbox).mean() / max(1e-6, (~bbox).mean()))
                if noise > NOISE_BUDGET:
                    print(f'  probe ({x},{y}) roll noisy ({noise:.2%} outside bbox), retry')
                    continue
                visible = diff & bbox
                unchanged = bbox & ~diff
                return {'cx0': cx0, 'cy0': cy0, 'mx': mx, 'my': my,
                        'bbox': (bx0, by0, bx1, by1), 'gen': gen,
                        'visible': visible, 'unchanged': unchanged, 'noise': noise}
        except Exception as e:
            print(f'  probe ({x},{y}) error: {e}')
    return None


def judge(gen, mx, my):
    """One VLM read: did a character land on the marker spot, and what occludes him?"""
    q = ('Look at the pixel-art scene. Is there a humanoid character standing near '
         f'pixel ({mx},{my}) (origin top-left of this image)? Answer JSON only: '
         '{"character_present": bool, "fully_visible": bool, '
         '"occluding_objects": [list of scene objects that overlap/cover parts of him, '
         'empty if none], "scene_altered": bool (true if the rest of the scene looks '
         'changed/re-rendered rather than identical)}')
    try:
        r = cli().models.generate_content(model='gemini-3.1-pro-preview', contents=[gen, q])
        t = r.text or ''
        return json.loads(t[t.index('{'): t.rindex('}') + 1])
    except Exception as e:
        return {'error': str(e)}


def run(room, k_grid=(4, 3)):
    plate = Image.open(os.path.join(ROOT, SCENES[room])).convert('RGB')
    W, H = plate.size
    walk = np.asarray(Image.open(os.path.join(
        ROOT, 'docs', 'art-options', 'bench', 'prompt', room, 'consensus-walk.png'))
        .convert('L').resize((W, H), Image.NEAREST)) > 127
    sprite = Image.open(os.path.join(ROOT, 'assets', 'chars', 'player-down.png')) \
                  .convert('RGBA')
    sprite = sprite.resize((sprite.width * 4, sprite.height * 4), Image.NEAREST)

    pts = sample_positions(walk, k_grid)
    print(f'[{room}] probing {len(pts)} walkable positions')

    def work(pt):
        x, y = pt
        res = probe_one(plate, sprite, x, y)
        if res is None:
            return None
        res['pos'] = (x, y)
        res['judge'] = judge(res['gen'], res['mx'], res['my'])
        return res

    with ThreadPoolExecutor(max_workers=4) as ex:
        results = [r for r in ex.map(work, pts) if r is not None]
    print(f'[{room}] {len(results)}/{len(pts)} probes valid')
    if not results:
        return

    # contact sheet: gen crop with bbox + visible-mask outline, one tile per probe
    tile = 400
    cols = min(4, len(results))
    rows = (len(results) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * tile, rows * tile), (12, 12, 16))
    occ_evidence = np.zeros((H, W), np.int32)   # scene px drawn over the char
    zkey = np.zeros((H, W), np.float32)          # max ground-y occluded there
    for n, res in enumerate(results):
        g = np.asarray(res['gen']).astype(np.float32)
        vis = res['visible']
        g[vis] = g[vis] * 0.55 + np.array([80, 255, 120], np.float32) * 0.45
        bx0, by0, bx1, by1 = res['bbox']
        # occluder evidence = unchanged pixels INSIDE the character's visible
        # column-span (holes in the silhouette), not the whole bbox: fill each
        # column between its first and last visible row, then take unchanged
        vb = vis[by0:by1, bx0:bx1]
        fill = np.zeros_like(vb)
        for c in range(vb.shape[1]):
            rs = np.nonzero(vb[:, c])[0]
            if len(rs) >= 2 and rs[-1] - rs[0] >= 8:
                fill[rs[0]:rs[-1] + 1, c] = True
        occ_cols = np.zeros_like(vis)
        occ_cols[by0:by1, bx0:bx1] = fill & ~vb
        g[occ_cols] = g[occ_cols] * 0.55 + np.array([255, 70, 70], np.float32) * 0.45
        t = Image.fromarray(g.clip(0, 255).astype(np.uint8))
        dr = ImageDraw.Draw(t)
        dr.rectangle([bx0, by0, bx1, by1], outline=(255, 200, 40), width=2)
        j = res['judge']
        lab = 'occluded by: ' + ', '.join(j.get('occluding_objects', [])[:2]) \
              if j.get('occluding_objects') else \
              ('visible' if j.get('character_present') else 'NO CHAR')
        dr.text((6, 6), f"({res['pos'][0]},{res['pos'][1]}) {lab[:52]}", fill=(255, 255, 160))
        t = t.resize((tile, tile), Image.LANCZOS)
        sheet.paste(t, ((n % cols) * tile, (n // cols) * tile))
        # accumulate full-image evidence
        oy, ox = np.nonzero(occ_cols)
        occ_evidence[oy + res['cy0'], ox + res['cx0']] += 1
        gy = res['pos'][1]
        sl = zkey[oy + res['cy0'], ox + res['cx0']]
        zkey[oy + res['cy0'], ox + res['cx0']] = np.maximum(sl, gy)

    out = os.path.join(ROOT, 'docs', 'art-options')
    sheet.save(os.path.join(out, f'occprobe-sheet-{room}.jpg'), quality=87)

    # z-key overlay: foreground-evidence px colored by the deepest ground-y they occluded
    b = np.asarray(plate).astype(np.float32) * 0.30
    ev = occ_evidence > 0
    if ev.any():
        t = (zkey - zkey[ev].min()) / max(1.0, zkey[ev].max() - zkey[ev].min())
        col = np.stack([60 + 195 * t, 220 - 150 * t, 255 * np.ones_like(t)], axis=2)
        b[ev] = b[ev] * 0.25 + col[ev] * 0.75
    o = Image.fromarray(b.clip(0, 255).astype(np.uint8))
    o.thumbnail((1400, 1400), Image.LANCZOS)
    o.save(os.path.join(out, f'occprobe-zkey-{room}.jpg'), quality=86)

    json.dump({'room': room, 'probes_attempted': len(pts), 'probes_valid': len(results),
               'probes': [{'pos': r['pos'], 'noise': round(r['noise'], 4),
                           'visible_px': int(r['visible'].sum()),
                           'judge': r['judge']} for r in results],
               'evidence_px': int(ev.sum())},
              open(os.path.join(out, f'occprobe-{room}-metrics.json'), 'w'), indent=1)
    print(f'[{room}] sheet + zkey written, evidence px {int(ev.sum())}')


if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else 'night-bazaar')
