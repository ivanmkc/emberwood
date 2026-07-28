#!/usr/bin/env python3
"""Iterative chroma-keyed occlusion probing over the PARTS map (Ivan: probes
"should be fairly color-differentiated from the scene to be easy to extract",
and "show a couple iterations ... and the resultant object sort order as it
changes so i can debug the algorithm").

Changes vs occprobe2:
- The probe character is recolored to two pure greens absent from the bazaar
  palette; extraction is a chroma KEY (distance to green), not an image diff —
  shadows, relighting and pixel-art chance-matches can no longer fake
  character pixels. The marked-plate diff remains only as the re-render gate.
- Evidence attributes to the 238-part map (parts inherit blocking from their
  parent instance), so canopy vs counter get independent z verdicts.
- Probes run in batches; after every batch the cumulative per-part verdicts
  and the resulting sort order are re-rendered, with a change list per
  iteration for debugging.
"""
import asyncio
import glob
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw

import occprobe2_run as o2  # backoff, gates, geometry, client, constants

ROOT = o2.ROOT
GREEN_BODY = np.array([0, 255, 64], np.int16)
GREEN_DARK = np.array([0, 130, 40], np.int16)
KEY_R = 100
BATCHES = 4
MIN_PART_PX = 30

PROMPT = (
 'Add the BRIGHT GREEN mannequin character from the second image INTO this scene, standing '
 f'with feet exactly on the magenta cross marker, about {o2.CHAR_H} pixels tall, facing the '
 'viewer. Keep his colors EXACTLY the same pure greens as the reference — flat green, no '
 'shading, no re-coloring: he is a green test mannequin. CRITICAL: (1) every other pixel of '
 'the scene stays EXACTLY identical; (2) layer him correctly — any scene object physically in '
 'front of him at that spot must cover the overlapping parts of him.'
)


def green_sprite():
    s = Image.open(os.path.join(ROOT, 'assets/chars/player-down.png')).convert('RGBA')
    a = np.asarray(s).copy()
    vis = a[:, :, 3] > 0
    lum = a[:, :, :3].astype(np.int32).sum(axis=2)
    a[vis & (lum < 300)] = [0, 130, 40, 255]
    a[vis & (lum >= 300)] = [0, 255, 64, 255]
    img = Image.fromarray(a)
    return img.resize((img.width * 4, img.height * 4), Image.NEAREST)


def key_mask(g):
    d1 = np.linalg.norm(g - GREEN_BODY, axis=2)
    d2 = np.linalg.norm(g - GREEN_DARK, axis=2)
    return (d1 < KEY_R) | (d2 < KEY_R)


async def probe(plate, sprite, pos):
    x, y = pos
    W, H = plate.size
    cx0 = int(np.clip(x - o2.CROP // 2, 0, W - o2.CROP))
    cy0 = int(np.clip(y - o2.CROP * 0.55, 0, H - o2.CROP))
    crop = plate.crop((cx0, cy0, cx0 + o2.CROP, cy0 + o2.CROP))
    marked = crop.copy()
    dr = ImageDraw.Draw(marked)
    mx, my = x - cx0, y - cy0
    dr.line([(mx - 12, my), (mx + 12, my)], fill=(255, 0, 255), width=4)
    dr.line([(mx, my - 12), (mx, my + 12)], fill=(255, 0, 255), width=4)
    ma = np.asarray(marked).astype(np.int16)
    bx0, by0, bx1, by1 = o2.bbox_of(mx, my)

    async with o2.SEM:
        for _ in range(2):
            try:
                r = await o2.backoff_call(lambda: o2.CLIENT.aio.models.generate_content(
                    model='gemini-3-pro-image', contents=[marked, sprite, PROMPT],
                    config=o2.types.GenerateContentConfig(
                        image_config=o2.types.ImageConfig(aspect_ratio='1:1', image_size='1K'))))
                out = await asyncio.to_thread(_extract, r, ma, crop, mx, my,
                                              (bx0, by0, bx1, by1), (cx0, cy0), pos)
                if out is not None:
                    return out
            except (o2.genai_errors.APIError, OSError, ValueError) as e:
                print(f'  probe {pos} error: {e}')
    return None


def _extract(resp, ma, crop, mx, my, box, origin, pos):
    bx0, by0, bx1, by1 = box
    for p in (resp.parts or []):
        if p.inline_data is None:
            continue
        import io
        gen = Image.open(io.BytesIO(p.inline_data.data)).convert('RGB') \
                   .resize((o2.CROP, o2.CROP), Image.LANCZOS)
        g = np.asarray(gen).astype(np.int16)
        # correct-by-construction: anything already green in the PLATE
        # (produce, plants) can never be character evidence
        plate_green = key_mask(np.asarray(crop).astype(np.int16))
        keyed = key_mask(g) & ~plate_green
        diff = o2.blur_diff(ma, g)
        bbox = np.zeros((o2.CROP, o2.CROP), bool)
        bbox[by0:by1, bx0:bx1] = True
        noise = float(((diff & ~bbox) | (keyed & ~bbox)).sum() / max(1, (~bbox).sum()))
        if noise > o2.NOISE_BUDGET:
            print(f'  probe {pos} noisy {noise:.2%}, retry')
            return None
        apron = np.zeros((o2.CROP, o2.CROP), bool)
        apron[by1:min(o2.CROP, by1 + o2.APRON_DOWN),
              max(0, bx0 - o2.APRON_SIDE):min(o2.CROP, bx1 + o2.APRON_SIDE)] = True
        vis = keyed & bbox & ~apron
        if vis.sum() < o2.MIN_MARKER_PX:
            print(f'  probe {pos} missing green char ({int(vis.sum())}px)')
            return None
        occ = o2.column_fill_holes(vis, bx0, by0, bx1, by1) & ~apron
        return {'ev': o2.MarkerEvidence(pos, vis, occ, origin), 'gen': gen,
                'box': box}
    return None


def sort_table(base, base_row):
    """Rank parts: ysort by interval midpoint (fallback base row), overhead
    last (always on top = highest z)."""
    rows = []
    for pid, r in base.items():
        if r['verdict'] == o2.YSORT:
            lo = r['lo'] if r['lo'] is not None else base_row.get(pid, 0)
            hi = r['hi'] if r['hi'] is not None else base_row.get(pid, 0)
            rows.append((pid, (lo + hi) / 2, r['verdict']))
        elif r['verdict'] == o2.OVERHEAD:
            rows.append((pid, 10 ** 6, r['verdict']))
        elif r['verdict'] == o2.CONTRA:
            rows.append((pid, base_row.get(pid, 0), r['verdict']))
    return sorted(rows, key=lambda t: t[1])


async def main(room):
    plate = Image.open(os.path.join(ROOT, o2.SCENES[room])).convert('RGB')
    plate.load()
    sprite = green_sprite()
    parts = np.load(os.path.join(ROOT, 'tools/art-pipeline',
                                 f'_srcmasks_{room}-parts.npz'))['inst']
    pmeta = json.load(open(os.path.join(ROOT, 'docs/art-options',
                                        f'parts-{room}-metrics.json')))
    imeta = json.load(open(os.path.join(ROOT, 'docs/art-options',
                                        f'occprobe2-instances-{room}-aligned.json')))
    iblock = {o['id'] for o in imeta['instances'] if o.get('blocking')}
    parent = {int(k): v for k, v in pmeta['parent'].items()}
    blocking = {pid: f'part{pid}<{parent[pid]}>' for pid in parent
                if parent[pid] in iblock}
    base_row = {}
    for pid in blocking:
        m = parts == pid
        if m.any():
            base_row[pid] = int(np.where(m.any(axis=1))[0][-1])
    plan = json.load(open(os.path.join(ROOT, 'docs/art-options',
                                       f'occprobe2-plan-{room}.json')))
    positions = [tuple(p['pos']) for p in plan['probes']]
    interior = o2.interior_mask(parts)

    batches = [positions[i::BATCHES] for i in range(BATCHES)]
    cum = []
    prev_verdicts = {}
    prev_rank = {}
    out = os.path.join(ROOT, 'docs/art-options')
    report = []
    for it, batch in enumerate(batches, 1):
        results = [r for r in await asyncio.gather(
            *(probe(plate, sprite, p) for p in batch)) if r is not None]
        cum.extend(results)
        evidence = [r['ev'] for r in cum]
        # front-probed parts from evidence geometry
        fp = set()
        for e in evidence:
            x, y = e.pos
            H, W = parts.shape
            sub = parts[max(0, y - o2.CHAR_H):min(H, y + 6),
                        max(0, x - o2.CHAR_W // 2):min(W, x + o2.CHAR_W // 2)]
            for pid in np.unique(sub):
                pid = int(pid)
                if pid in blocking and (sub == pid).sum() >= 200 \
                        and base_row.get(pid, 10 ** 9) + 16 < y:
                    fp.add(pid)
        base = o2.aggregate(evidence, parts, interior, blocking,
                            MIN_PART_PX, o2.CONCORDANCE, frozenset(fp))
        table = sort_table(base, base_row)
        rank = {pid: i for i, (pid, _, _) in enumerate(table)}
        changes = []
        for pid, r in base.items():
            pv = prev_verdicts.get(pid)
            if pv != r['verdict']:
                changes.append(f"{blocking[pid]}: {pv or 'new'} -> {r['verdict']}")
            elif pid in prev_rank and pid in rank and prev_rank[pid] != rank[pid]:
                changes.append(f"{blocking[pid]}: rank {prev_rank[pid]} -> {rank[pid]}")
        prev_verdicts = {pid: r['verdict'] for pid, r in base.items()}
        prev_rank = rank

        # iteration zmap: rank gradient for sorted parts, verdict tints
        b_img = np.asarray(plate).astype(np.float32) * 0.32
        nrank = max(1, len(table) - 1)
        for pid, key, verdict in table:
            m = parts == pid
            if verdict == o2.OVERHEAD:
                col = np.array([80, 170, 255], np.float32)
            elif verdict == o2.CONTRA:
                col = np.array([255, 90, 90], np.float32)
            else:
                t = rank[pid] / nrank
                col = np.array([60 + 195 * t, 230 - 160 * t, 90], np.float32)
            b_img[m] = b_img[m] * 0.40 + col * 0.60
        zi = Image.fromarray(b_img.clip(0, 255).astype(np.uint8))
        zi.thumbnail((1400, 1400), Image.LANCZOS)
        zi.save(os.path.join(out, f'occprobe3-iter{it}-zmap-{room}.jpg'), quality=86)

        # iteration probe strip (this batch's keyed extractions)
        if results:
            tile = 300
            strip = Image.new('RGB', (tile * len(results), tile), (12, 12, 16))
            for n, r in enumerate(results):
                g = np.asarray(r['gen']).astype(np.float32)
                g[r['ev'].visible] = g[r['ev'].visible] * 0.4 + np.array([0, 255, 64], np.float32) * 0.6
                g[r['ev'].occluded] = g[r['ev'].occluded] * 0.4 + np.array([255, 70, 70], np.float32) * 0.6
                t = Image.fromarray(g.clip(0, 255).astype(np.uint8)).resize((tile, tile), Image.LANCZOS)
                strip.paste(t, (n * tile, 0))
            strip.save(os.path.join(out, f'occprobe3-iter{it}-probes-{room}.jpg'), quality=85)

        rec = {'iteration': it, 'batch_probes': len(batch), 'batch_valid': len(results),
               'cum_evidence': len(evidence), 'parts_with_verdicts': len(base),
               'verdicts': {v: sum(1 for r in base.values() if r['verdict'] == v)
                            for v in (o2.YSORT, o2.OVERHEAD, o2.CONTRA, o2.NOEV)},
               'sort_order_top': [[blocking[pid], round(key, 1), v]
                                  for pid, key, v in table[:15]],
               'changes': changes}
        report.append(rec)
        print(f"iter {it}: +{len(results)}/{len(batch)} probes, "
              f"{rec['verdicts']}, {len(changes)} changes")

    json.dump({'room': room, 'iterations': report},
              open(os.path.join(out, f'occprobe3-iterations-{room}.json'), 'w'), indent=1)


if __name__ == '__main__':
    # occprobe2_run resolves because python puts the script's dir on sys.path
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else 'night-bazaar'))
