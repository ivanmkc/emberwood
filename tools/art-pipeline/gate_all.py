#!/usr/bin/env python3
"""Run ALL pipeline gates (deterministic + Gemini rubric) and write a report.

Usage: python3 tools/art-pipeline/gate_all.py [assets|tiles|characters] ...
Writes tools/art-pipeline/verdicts.json (merged) and prints a pass/fail table.
Exit code 1 if anything failed.
"""
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from judge import judge_image, judge_vote  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ART = os.path.join(ROOT, 'docs', 'art-options')
ANCHOR = os.path.join(ART, 'nbp-scifi-anchor.png')
VERDICTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'verdicts.json')
TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_gate_tmp')


def checker_composite(path):
    img = Image.open(path).convert('RGBA')
    bg = Image.new('RGBA', img.size, (30, 30, 42, 255))
    px = bg.load()
    for y in range(0, img.height, 8):
        for x in range(0, img.width, 8):
            if (x // 8 + y // 8) % 2 == 0:
                for yy in range(y, min(y + 8, img.height)):
                    for xx in range(x, min(x + 8, img.width)):
                        px[xx, yy] = (40, 40, 56, 255)
    out = Image.alpha_composite(bg, img).convert('RGB')
    big = out.resize((out.width * 3, out.height * 3), Image.NEAREST)
    p = os.path.join(TMP, 'judge_' + os.path.basename(path))
    big.save(p)
    return p


def det_asset(path):
    img = Image.open(path).convert('RGBA')
    a = np.asarray(img)
    alpha = a[..., 3] > 0
    coverage = alpha.mean()
    rgb = a[..., :3][alpha]
    fringe = 0.0
    if len(rgb):
        fr = (rgb[:, 0] > 190) & (rgb[:, 2] > 190) & (rgb[:, 1] < 120)
        fringe = fr.mean()
    ok = 0.10 <= coverage <= 0.99 and fringe < 0.02
    return ok, {'coverage': round(float(coverage), 3), 'magenta_fringe': round(float(fringe), 4)}


def det_tile(path):
    img = Image.open(path).convert('RGB')
    a = np.asarray(img).astype(int)
    lr = np.abs(a[:, 0] - a[:, -1]).mean()
    tb = np.abs(a[0, :] - a[-1, :]).mean()
    var = a.std()
    ok = max(lr, tb) < 26 and var > 4
    return ok, {'seam_lr': round(float(lr), 1), 'seam_tb': round(float(tb), 1), 'std': round(float(var), 1)}


def tiled_preview(path, n=5, scale=2):
    """Tile n x n, mixing variants (name-0/1/2.png) by position hash the same
    way the engine will — the repetition-grid judgment must see what the
    player will see."""
    base = path[:-4]
    variants = []
    for i in range(8):
        vp = f'{base}-{i}.png'
        if os.path.exists(vp):
            variants.append(Image.open(vp).convert('RGB'))
    if not variants:
        variants = [Image.open(path).convert('RGB')]
    variants = [v.resize((v.width * scale, v.height * scale), Image.NEAREST) for v in variants]
    tw, th = variants[0].size
    out = Image.new('RGB', (tw * n, th * n))
    for y in range(n):
        for x in range(n):
            out.paste(variants[(x * 73 + y * 151) % len(variants)], (x * tw, y * th))
    p = os.path.join(TMP, 'tiled_' + os.path.basename(path))
    out.save(p)
    return p


def gate_assets(verdicts):
    d = os.path.join(ART, 'assets-scifi')
    fails = []
    for f in sorted(os.listdir(d)):
        if not f.endswith('.png'):
            continue
        path = os.path.join(d, f)
        det_ok, det = det_asset(path)
        jv = judge_vote([ANCHOR, checker_composite(path)], 'asset',
                        context=f'asset name: {f[:-4]} (sci-fi settlement prop)')
        passed = bool(det_ok and jv.get('style_match', 0) >= 7 and jv.get('perspective_ok')
                      and jv.get('single_object') and jv.get('silhouette_clean')
                      and jv.get('theme_fit', 0) >= 7)
        verdicts[f'asset:{f[:-4]}'] = {'pass': passed, 'det': det, 'judge': jv}
        print(f'{"PASS" if passed else "FAIL"} asset:{f[:-4]} det={det} judge={jv}')
        if not passed:
            fails.append(f'asset:{f[:-4]}')
    return fails


WALL_TILES = {'wallpanel', 'minewall'}  # face-on / blocking tiles: plan view not required


def gate_tiles(verdicts, only=None):
    d = os.path.join(ART, 'tiles-scifi')
    fails = []
    for f in sorted(os.listdir(d)):
        if not f.endswith('.png') or f[-6] == '-':  # skip variant files
            continue
        name = f[:-4]
        if only and name not in only:
            continue
        path = os.path.join(d, f)
        det_ok, det = det_tile(path)
        is_wall = name in WALL_TILES
        ctx = f'terrain: {name}'
        if is_wall:
            ctx += (' — NOTE: this is a face-on WALL / solid blocking tile (interior wall or '
                    'cave rock), so a front-facing or dense blocking texture is CORRECT here; '
                    'judge flat_plan_view as true if it works as a wall/blocking tile.')
        jv = judge_vote([ANCHOR, tiled_preview(path)], 'tile', context=ctx)
        passed = bool(det_ok and jv.get('style_match', 0) >= 7
                      and (jv.get('flat_plan_view') or is_wall)
                      and jv.get('tileable', 0) >= 6 and jv.get('readability', 0) >= 6)
        verdicts[f'tile:{name}'] = {'pass': passed, 'det': det, 'judge': jv}
        print(f'{"PASS" if passed else "FAIL"} tile:{name} det={det} judge={jv}')
        if not passed:
            fails.append(f'tile:{name}')
    return fails


HUMANOIDS = ['player', 'chief', 'angler', 'settler']
CREATURES = {
    'trader': 'a small boxy merchant droid on tracked wheels with one glowing eye screen — box shape is the intended design',
    'sludge': 'a small blob of glowing toxic sludge with tiny eyes — blob shape is the intended design',
    'drone': 'a small hostile surveillance drone with rotors and one red camera eye',
    'boss': 'a HUGE molten sludge boss blob with a glowing core and several small eyes — a big blob monster is the intended design',
}


def gate_characters(verdicts):
    """Judge each character once: humanoids on their 4-direction strip
    (individual 44px direction files are too small to judge fairly),
    creatures on their single sprite with design-intent context."""
    d = os.path.join(ART, 'chars-scifi')
    if not os.path.isdir(d):
        return []
    fails = []
    for name in HUMANOIDS:
        path = os.path.join(d, f'{name}.png')
        if not os.path.exists(path):
            continue
        det_ok = True
        dets = {}
        for dirn in ['down', 'up', 'left', 'right']:
            dp = os.path.join(d, f'{name}-{dirn}.png')
            ok, det = det_asset(dp)
            det_ok = det_ok and ok
            dets[dirn] = det
        jv = judge_vote([ANCHOR, checker_composite(path)], 'character',
                        context=f'4-direction strip (down, up, left, right) of: {name}')
        passed = bool(det_ok and jv.get('style_match', 0) >= 6 and jv.get('single_character')
                      and jv.get('silhouette_clean') and jv.get('theme_fit', 0) >= 6
                      and jv.get('directions_consistent', True))
        verdicts[f'char:{name}'] = {'pass': passed, 'det': dets, 'judge': jv}
        print(f'{"PASS" if passed else "FAIL"} char:{name} judge={jv}')
        if not passed:
            fails.append(f'char:{name}')
    for name, design in CREATURES.items():
        path = os.path.join(d, f'{name}.png')
        if not os.path.exists(path):
            continue
        det_ok, det = det_asset(path)
        jv = judge_vote([ANCHOR, checker_composite(path)], 'creature',
                        context=f'intended design: {design}')
        passed = bool(det_ok and jv.get('style_match', 0) >= 6 and jv.get('single_creature')
                      and jv.get('silhouette_clean') and jv.get('theme_fit', 0) >= 6
                      and jv.get('reads_as_design'))
        verdicts[f'char:{name}'] = {'pass': passed, 'det': det, 'judge': jv}
        print(f'{"PASS" if passed else "FAIL"} char:{name} judge={jv}')
        if not passed:
            fails.append(f'char:{name}')
    return fails


def main():
    os.makedirs(TMP, exist_ok=True)
    which = sys.argv[1:] or ['assets', 'tiles']
    verdicts = {}
    if os.path.exists(VERDICTS):
        verdicts = json.load(open(VERDICTS))
    fails = []
    if 'assets' in which:
        fails += gate_assets(verdicts)
    if 'tiles' in which:
        fails += gate_tiles(verdicts)
    if 'characters' in which:
        fails += gate_characters(verdicts)
    json.dump(verdicts, open(VERDICTS, 'w'), indent=1)
    print(f'\n{len(fails)} failures: {fails}' if fails else '\nALL GATES PASS')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
