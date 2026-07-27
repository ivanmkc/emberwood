#!/usr/bin/env python3
"""Content-aware humanoid sheet slicing.

NBP lays out sprite sheets however it likes, so fixed quadrant slicing cuts
through figures. Instead: key the whole raw sheet, extract connected figure
blobs deterministically, then ask the Gemini judge to classify each blob's
facing. One sprite per direction is selected (largest of its class); a missing
left/right is mirrored from its opposite.

Usage: python3 tools/art-pipeline/resegment_chars.py [name ...]
"""
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from judge import judge_image  # noqa: E402
from gen_chars import border_median_key, scale_to, TARGET_H, HUMANOIDS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(ROOT, 'docs', 'art-options', 'chars-scifi')
RAW_DIR = os.path.join(OUT_DIR, 'raw')
TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_gate_tmp')


def blobs_of(img):
    alpha = np.asarray(img)[..., 3] > 0
    h, w = alpha.shape
    seen = np.zeros_like(alpha, dtype=bool)
    total = int(alpha.sum())
    out = []
    for sy in range(0, h, 2):
        for sx in range(0, w, 2):
            if not alpha[sy, sx] or seen[sy, sx]:
                continue
            stack = [(sy, sx)]
            seen[sy, sx] = True
            pts = []
            while stack:
                y, x = stack.pop()
                pts.append((y, x))
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and alpha[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            if len(pts) > total * 0.02:
                ys = [p[0] for p in pts]
                xs = [p[1] for p in pts]
                out.append((min(xs), min(ys), max(xs) + 1, max(ys) + 1, len(pts)))
    # merge overlapping boxes (a figure can fragment via thin joints)
    merged = True
    while merged:
        merged = False
        for i in range(len(out)):
            for j in range(i + 1, len(out)):
                a, b = out[i], out[j]
                if a[0] < b[2] + 4 and b[0] < a[2] + 4 and a[1] < b[3] + 4 and b[1] < a[3] + 4:
                    out[i] = (min(a[0], b[0]), min(a[1], b[1]),
                              max(a[2], b[2]), max(a[3], b[3]), a[4] + b[4])
                    out.pop(j)
                    merged = True
                    break
            if merged:
                break
    out.sort(key=lambda b: b[0])  # left to right
    return out


def process(name):
    raw = Image.open(os.path.join(RAW_DIR, f'{name}.png'))
    keyed, key = border_median_key(raw)
    bl = blobs_of(keyed)
    if len(bl) < 3:
        print(f'{name}: only {len(bl)} figures found — regenerate raw')
        return False
    crops = [keyed.crop(b[:4]) for b in bl]
    # classification strip
    pad = 8
    hmax = max(c.height for c in crops)
    strip = Image.new('RGBA', (sum(c.width for c in crops) + pad * (len(crops) + 1), hmax + pad * 2), (0, 0, 0, 0))
    bg = Image.new('RGB', strip.size, (30, 30, 42))
    x = pad
    for c in crops:
        strip.paste(c, (x, pad + (hmax - c.height)), c)
        x += c.width + pad
    bg.paste(strip, (0, 0), strip)
    spath = os.path.join(TMP, f'facing_{name}.png')
    os.makedirs(TMP, exist_ok=True)
    bg.resize((bg.width * 2, bg.height * 2), Image.NEAREST).save(spath)

    jv = judge_image([spath], 'facing', context=f'{len(crops)} sprites of: {name}')
    facings = jv.get('facings') or []
    if len(facings) != len(crops):
        print(f'{name}: facing count mismatch {len(facings)} vs {len(crops)}: {jv}')
        return False
    picked = {}
    for c, f, b in zip(crops, facings, bl):
        if f in ('down', 'up', 'left', 'right'):
            if f not in picked or b[4] > picked[f][1]:
                picked[f] = (c, b[4])
    if 'left' in picked and 'right' not in picked:
        picked['right'] = (picked['left'][0].transpose(Image.FLIP_LEFT_RIGHT), 0)
    if 'right' in picked and 'left' not in picked:
        picked['left'] = (picked['right'][0].transpose(Image.FLIP_LEFT_RIGHT), 0)
    missing = [d for d in ['down', 'up', 'left', 'right'] if d not in picked]
    if missing:
        print(f'{name}: missing directions {missing} (facings={facings})')
        return False
    outs = {}
    for d in ['down', 'up', 'left', 'right']:
        outs[d] = scale_to(picked[d][0], TARGET_H[name])
        outs[d].save(os.path.join(OUT_DIR, f'{name}-{d}.png'))
    pad2 = 6
    W = sum(i.width for i in outs.values()) + pad2 * 5
    H = TARGET_H[name] + pad2 * 2
    strip2 = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    x = pad2
    for d in ['down', 'up', 'left', 'right']:
        strip2.paste(outs[d], (x, pad2), outs[d])
        x += outs[d].width + pad2
    strip2.save(os.path.join(OUT_DIR, f'{name}.png'))
    print(f'{name}: {len(bl)} figures -> 4 dirs via facing judge (facings={facings})')
    return True


if __name__ == '__main__':
    names = sys.argv[1:] or list(HUMANOIDS)
    ok = all(process(n) for n in names)
    sys.exit(0 if ok else 1)
