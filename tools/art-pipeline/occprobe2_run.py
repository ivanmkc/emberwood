#!/usr/bin/env python3
"""P1+P2 of the multi-char occlusion experiment (reviewed plan v3), async.

Concurrency (expert-reviewed): single genai client on the aio surface,
asyncio.Semaphore(6) in-flight cap, jittered exponential backoff on transient
API errors (429/500/503), numpy/PIL post-processing in asyncio.to_thread so
the event loop stays free, semaphore held across a crop's retry attempts to
avoid thundering-herd. Arm B's ramp is inherently sequential (each K level
depends on the prior) and only uses the async client internally.

Evidence fix from the P1 pilot: diffs are computed in lightly blurred space —
on limited-palette pixel art, character pixels chance-match the plate behind
them and punch phantom "occluder" holes in the silhouette; a sigma~1.5 blur
kills single-pixel coincidences while preserving real occluder regions.
"""
import asyncio
import io
import json
import os
import random
import sys
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image, ImageDraw

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLIENT = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
SEM = asyncio.Semaphore(6)
RETRIABLE = {429, 500, 503}

SCENES = {
 'anchorroom': 'docs/art-options/nbp-scifi-anchor-clean.png',
 'night-bazaar': 'docs/art-options/rooms/night-bazaar/plate.png',
 'plaza-market-inside': 'docs/art-options/rooms/plaza-market-inside/plate.png',
}
CROP = 800
CHAR_W, CHAR_H = 80, 176
DIFF_T = 42
BLUR_K = 5                 # gaussian kernel for chance-match suppression
NOISE_BUDGET = 0.08        # calibrated: worst clean roll 0.049
MIN_MARKER_PX = 600
CENTROID_TOL = 100
MIN_CONSTRAINT_PX = 50
CONCORDANCE = 20
SPACING = int(1.5 * CHAR_W)
APRON_DOWN, APRON_SIDE = 20, 30
YSORT, OVERHEAD, CONTRA, NOEV = 'ysort', 'overhead', 'contradiction', 'no-evidence'

PROMPT_A = (
 'Add the pixel-art character from the second image INTO this scene — place one copy standing '
 f'with feet exactly on EACH magenta cross marker. Each copy about {CHAR_H} pixels tall, facing '
 'the viewer, matching the scene\'s pixel-art style. CRITICAL RULES: (1) every pixel of the '
 'scene not under a character must stay EXACTLY identical — same colors, same lighting, same '
 'objects; (2) draw each character correctly layered: if any scene object is physically in '
 'front of him at that spot, that object covers the overlapping parts of him; (3) characters '
 'do NOT interact — each stands independently, facing the viewer, same pose.'
)


@dataclass
class MarkerEvidence:
    pos: tuple
    visible: np.ndarray
    occluded: np.ndarray
    origin: tuple


@dataclass
class CropJob:
    positions: list
    cx0: int = 0
    cy0: int = 0
    gen: Image.Image = None
    evidence: list = field(default_factory=list)


async def backoff_call(coro_factory, max_retries=4, base=2.0):
    """Jittered exponential backoff on transient API errors; permanent errors
    raise immediately (expert params: 2s base, x2, jitter 0.5-1.5, cap 32s)."""
    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except genai_errors.APIError as e:
            if getattr(e, 'code', None) not in RETRIABLE or attempt == max_retries:
                raise
            delay = min(base * (2 ** attempt) * random.uniform(0.5, 1.5), 32)
            print(f'  transient {getattr(e, "code", "?")}, retry in {delay:.1f}s')
            await asyncio.sleep(delay)


def group_into_crops(positions):
    todo = sorted(positions)
    jobs = []
    while todo:
        seed = todo.pop(0)
        group = [seed]
        for p in list(todo):
            if len(group) >= 3:
                break
            if max(abs(p[0] - seed[0]), abs(p[1] - seed[1])) > CROP - 200:
                continue
            if all(np.hypot(p[0] - q[0], p[1] - q[1]) >= SPACING for q in group):
                group.append(p)
                todo.remove(p)
        jobs.append(CropJob(group))
    return jobs


def bbox_of(mx, my):
    return (max(0, mx - CHAR_W // 2 - 8), max(0, my - CHAR_H - 12),
            min(CROP, mx + CHAR_W // 2 + 8), min(CROP, my + 14))


def column_fill_holes(vis, bx0, by0, bx1, by1):
    vb = vis[by0:by1, bx0:bx1]
    fill = np.zeros_like(vb)
    for c in range(vb.shape[1]):
        rs = np.nonzero(vb[:, c])[0]
        if len(rs) >= 2 and rs[-1] - rs[0] >= 8:
            fill[rs[0]:rs[-1] + 1, c] = True
    out = np.zeros_like(vis)
    out[by0:by1, bx0:bx1] = fill & ~vb
    return out


def blur_diff(a_img, b_img):
    """Max-channel diff in blurred space: suppresses pixel-art chance matches."""
    ab = cv2.GaussianBlur(a_img.astype(np.float32), (BLUR_K, BLUR_K), 0)
    bb = cv2.GaussianBlur(b_img.astype(np.float32), (BLUR_K, BLUR_K), 0)
    return np.abs(ab - bb).max(axis=2) > DIFF_T


def process_gen(response, ma, job, local):
    """Pure numpy/PIL: diff, gates, evidence. Runs in a worker thread.
    Returns job on success, None to signal retry."""
    for p in (response.parts or []):
        if p.inline_data is None:
            continue
        gen = Image.open(io.BytesIO(p.inline_data.data)).convert('RGB') \
                   .resize((CROP, CROP), Image.LANCZOS)
        g = np.asarray(gen).astype(np.int16)
        diff = blur_diff(ma, g)
        boxes = [bbox_of(mx, my) for mx, my in local]
        allbox = np.zeros((CROP, CROP), bool)
        for bx0, by0, bx1, by1 in boxes:
            allbox[by0:by1, bx0:bx1] = True
        noise = float((diff & ~allbox).sum() / max(1, (~allbox).sum()))
        if noise > NOISE_BUDGET:
            print(f'  crop@{job.positions[0]} noisy {noise:.2%}, retry')
            return None
        apron = np.zeros((CROP, CROP), bool)
        for bx0, by0, bx1, by1 in boxes:
            apron[by1:min(CROP, by1 + APRON_DOWN),
                  max(0, bx0 - APRON_SIDE):min(CROP, bx1 + APRON_SIDE)] = True
        ev = []
        for (mx, my), (bx0, by0, bx1, by1) in zip(local, boxes):
            box = np.zeros((CROP, CROP), bool)
            box[by0:by1, bx0:bx1] = True
            vis = diff & box & ~apron
            if vis.sum() < MIN_MARKER_PX:
                print(f'  marker ({mx},{my}) missing char ({int(vis.sum())}px)')
                return None
            yy, xx = np.nonzero(vis)
            if np.hypot(xx.mean() - mx, yy.mean() - (my - CHAR_H / 2)) > CENTROID_TOL:
                print(f'  marker ({mx},{my}) centroid off — possible swap')
                return None
            occ = column_fill_holes(vis, bx0, by0, bx1, by1) & ~apron
            ev.append(MarkerEvidence((mx + job.cx0, my + job.cy0), vis, occ,
                                     (job.cx0, job.cy0)))
        if len(boxes) > 1:
            claim = np.zeros((CROP, CROP), np.int8)
            for bx0, by0, bx1, by1 in boxes:
                claim[by0:by1, bx0:bx1] += 1
            if bool((diff & (claim > 1)).sum() > 200):
                print('  merge-gate: overlapping char blobs')
                return None
        job.gen = gen
        job.evidence = ev
        return job
    return None


async def run_crop(plate, sprite, job):
    W, H = plate.size
    xs = [p[0] for p in job.positions]
    ys = [p[1] for p in job.positions]
    job.cx0 = int(np.clip((min(xs) + max(xs)) // 2 - CROP // 2, 0, W - CROP))
    job.cy0 = int(np.clip((min(ys) + max(ys)) // 2 - int(CROP * 0.55), 0, H - CROP))
    crop = plate.crop((job.cx0, job.cy0, job.cx0 + CROP, job.cy0 + CROP))
    marked = crop.copy()
    dr = ImageDraw.Draw(marked)
    local = [(x - job.cx0, y - job.cy0) for x, y in job.positions]
    for mx, my in local:
        dr.line([(mx - 12, my), (mx + 12, my)], fill=(255, 0, 255), width=4)
        dr.line([(mx, my - 12), (mx, my + 12)], fill=(255, 0, 255), width=4)
    ma = np.asarray(marked).astype(np.int16)

    # semaphore held across both attempts: a failing crop must not re-queue
    # behind fresh crops and thundering-herd the retry path
    async with SEM:
        for _attempt in range(2):
            try:
                r = await backoff_call(lambda: CLIENT.aio.models.generate_content(
                    model='gemini-3-pro-image', contents=[marked, sprite, PROMPT_A],
                    config=types.GenerateContentConfig(
                        image_config=types.ImageConfig(aspect_ratio='1:1', image_size='1K'))))
                result = await asyncio.to_thread(process_gen, r, ma, job, local)
                if result is not None:
                    return result
            except (genai_errors.APIError, OSError, ValueError) as e:
                print(f'  crop error: {e}')
    return job


async def arm_b_ramp(plate, sprite, stand_positions):
    """Sequential by design: each K level depends on the prior pass/fail."""
    W, _H = plate.size
    results = {}
    for K, need in ((3, 3), (6, 5), (10, 8)):
        passes = 0
        fails = 0
        while passes < 2 and fails < 4:
            pts = [stand_positions[i] for i in
                   np.linspace(0, len(stand_positions) - 1, K).astype(int)]
            img = plate.copy()
            img.thumbnail((1200, 1200))
            sc = img.width / W
            dr = ImageDraw.Draw(img)
            for x, y in pts:
                mx, my = int(x * sc), int(y * sc)
                dr.line([(mx - 8, my), (mx + 8, my)], fill=(255, 0, 255), width=3)
                dr.line([(mx, my - 8), (mx, my + 8)], fill=(255, 0, 255), width=3)
            prompt = PROMPT_A.replace('EACH magenta cross marker',
                                      f'EACH magenta cross marker ({K} markers total)') + \
                ' (4) you MUST place a character at EVERY marker, not a subset.'
            placed = 0
            try:
                r = await backoff_call(lambda: CLIENT.aio.models.generate_content(
                    model='gemini-3-pro-image', contents=[img, sprite, prompt],
                    config=types.GenerateContentConfig(
                        image_config=types.ImageConfig(aspect_ratio='4:3', image_size='2K'))))
                placed = await asyncio.to_thread(_count_placed, r, img, pts, sc)
            except (genai_errors.APIError, OSError, ValueError) as e:
                print(f'  armB K={K} error: {e}')
            if placed >= need:
                passes += 1
            else:
                fails += 1
            print(f'  armB K={K}: placed {placed}/{K} (pass {passes}, fail {fails})')
        results[K] = {'passes': passes, 'fails': fails, 'advanced': passes >= 2}
        if passes < 2:
            break
    return results


def _count_placed(response, img, pts, sc):
    for p in (response.parts or []):
        if p.inline_data is None:
            continue
        gen = Image.open(io.BytesIO(p.inline_data.data)).convert('RGB') \
                   .resize((img.width, img.height), Image.LANCZOS)
        d = blur_diff(np.asarray(img).astype(np.int16)[:, :, :3],
                      np.asarray(gen).astype(np.int16))
        placed = 0
        for x, y in pts:
            mx, my = int(x * sc), int(y * sc)
            hw, hh = int(CHAR_W * sc * 0.7), int(CHAR_H * sc * 1.1)
            box = d[max(0, my - hh):my + 10, max(0, mx - hw):mx + hw]
            if box.sum() >= MIN_MARKER_PX * sc * sc:
                placed += 1
        return placed
    return 0


def bound(vals, concordance, upper):
    if len(vals) >= 4:
        return float(np.percentile(vals, 10 if upper else 90))
    s = sorted(vals, reverse=not upper)
    for i in range(len(s) - 1):
        if abs(s[i] - s[i + 1]) <= concordance:
            return float(s[i + 1])
    return None


def aggregate(evidence, inst, blocking, min_px, concordance):
    cons = {}
    for ev in evidence:
        gy = ev.pos[1]
        ox0, oy0 = ev.origin
        for key, m in (('behind', ev.occluded), ('front', ev.visible)):
            yy, xx = np.nonzero(m)
            if not len(yy):
                continue
            ids, cts = np.unique(inst[np.clip(yy + oy0, 0, inst.shape[0] - 1),
                                      np.clip(xx + ox0, 0, inst.shape[1] - 1)],
                                 return_counts=True)
            for oid, ct in zip(ids, cts):
                if int(oid) in blocking and ct >= min_px:
                    cons.setdefault(int(oid), {'behind': [], 'front': []})[key].append(gy)
    out = {}
    for oid, c in cons.items():
        lo = bound(c['behind'], concordance, upper=False)
        hi = bound(c['front'], concordance, upper=True)
        if lo is None and hi is None:
            v = NOEV
        elif hi is None:
            v = OVERHEAD
        elif lo is None or lo < hi:
            v = YSORT
        else:
            v = CONTRA
        out[oid] = {'lo': lo, 'hi': hi, 'verdict': v,
                    'n_behind': len(c['behind']), 'n_front': len(c['front'])}
    return out


async def run_async(room):
    plan = json.load(open(os.path.join(
        ROOT, 'docs', 'art-options', f'occprobe2-plan-{room}.json')))
    plate = Image.open(os.path.join(ROOT, SCENES[room])).convert('RGB')
    plate.load()  # defuse lazy-load races for any Pillow version
    inst = np.load(os.path.join(ROOT, 'tools/art-pipeline', f'_srcmasks_{room}.npz'))['inst']
    meta = json.load(open(os.path.join(ROOT, 'assets/rooms', f'{room}.instances.json')))
    blocking = {o['id']: o.get('label', '?') for o in meta['instances'] if o.get('blocking')}
    base_row = {}
    for o in meta['instances']:
        if o['id'] in blocking:
            m = inst == o['id']
            if m.any():
                base_row[o['id']] = int(np.where(m.any(axis=1))[0][-1])
    sprite = Image.open(os.path.join(ROOT, 'assets/chars/player-down.png')).convert('RGBA')
    sprite = sprite.resize((sprite.width * 4, sprite.height * 4), Image.NEAREST)
    sprite.load()

    positions = [tuple(p['pos']) for p in plan['probes']]
    jobs = group_into_crops(positions)
    print(f'[{room}] {len(positions)} probes in {len(jobs)} crops (async, sem=6)')
    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(run_crop(plate, sprite, j)) for j in jobs]
    jobs = [t.result() for t in tasks]
    evidence = [e for j in jobs for e in j.evidence]
    ok_crops = sum(1 for j in jobs if j.evidence)
    print(f'[{room}] Arm A: {ok_crops}/{len(jobs)} crops valid, '
          f'{len(evidence)}/{len(positions)} marker evidences')

    print(f'[{room}] Arm B ramp:')
    armb = await arm_b_ramp(plate, sprite, positions)

    base = aggregate(evidence, inst, blocking, MIN_CONSTRAINT_PX, CONCORDANCE)
    sweeps = [aggregate(evidence, inst, blocking, mp, cw)
              for mp, cw in ((25, 10), (100, 40))]
    for oid, rec in base.items():
        rec['fragile'] = any(s.get(oid, {}).get('verdict') != rec['verdict'] for s in sweeps)
        rec['label'] = blocking.get(oid, '?')
        b = base_row.get(oid)
        rec['engine_base_row'] = b
        if rec['verdict'] == YSORT and b is not None:
            lo = rec['lo'] if rec['lo'] is not None else -1e9
            hi = rec['hi'] if rec['hi'] is not None else 1e9
            rec['engine_key_contained'] = bool(lo <= b <= hi)
    ys = [r for r in base.values() if r['verdict'] == YSORT and 'engine_key_contained' in r]
    contained = sum(1 for r in ys if r['engine_key_contained'])
    summary = {
        'probes': len(positions), 'crops': len(jobs), 'crops_valid': ok_crops,
        'marker_evidences': len(evidence), 'arm_b': armb,
        'objects_with_verdicts': len(base),
        'verdict_counts': {v: sum(1 for r in base.values() if r['verdict'] == v)
                           for v in (YSORT, OVERHEAD, CONTRA, NOEV)},
        'fragile': sum(1 for r in base.values() if r['fragile']),
        'engine_containment': f'{contained}/{len(ys)}'}
    out = os.path.join(ROOT, 'docs', 'art-options')
    json.dump({'room': room, 'summary': summary,
               'objects': {str(k): v for k, v in sorted(base.items())}},
              open(os.path.join(out, f'occprobe2-constraints-{room}.json'), 'w'), indent=1)

    tint = {YSORT: (80, 230, 120), OVERHEAD: (80, 170, 255),
            CONTRA: (255, 90, 90), NOEV: (150, 150, 150)}
    b_img = np.asarray(plate).astype(np.float32) * 0.32
    for oid, rec in base.items():
        m = inst == oid
        col = np.array((255, 200, 60), np.float32) if rec['fragile'] else \
            np.array(tint[rec['verdict']], np.float32)
        b_img[m] = b_img[m] * 0.45 + col * 0.55
    o = Image.fromarray(b_img.clip(0, 255).astype(np.uint8))
    o.thumbnail((1400, 1400), Image.LANCZOS)
    o.save(os.path.join(out, f'occprobe2-zmap-{room}.jpg'), quality=86)

    good = [j for j in jobs if j.evidence and j.gen is not None]
    if good:
        tile = 380
        cols = min(4, len(good))
        rows = (len(good) + cols - 1) // cols
        sheet = Image.new('RGB', (cols * tile, rows * tile), (12, 12, 16))
        for n, j in enumerate(good):
            g = np.asarray(j.gen).astype(np.float32)
            for ev in j.evidence:
                g[ev.visible] = g[ev.visible] * 0.55 + np.array([80, 255, 120], np.float32) * 0.45
                g[ev.occluded] = g[ev.occluded] * 0.45 + np.array([255, 70, 70], np.float32) * 0.55
            t = Image.fromarray(g.clip(0, 255).astype(np.uint8)).resize((tile, tile), Image.LANCZOS)
            sheet.paste(t, ((n % cols) * tile, (n // cols) * tile))
        sheet.save(os.path.join(out, f'occprobe2-sheet-{room}.jpg'), quality=86)
    print(f'[{room}] {json.dumps(summary)}')


if __name__ == '__main__':
    asyncio.run(run_async(sys.argv[1] if len(sys.argv) > 1 else 'night-bazaar'))
