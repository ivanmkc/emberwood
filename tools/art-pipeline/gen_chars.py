#!/usr/bin/env python3
"""Character/creature sprite generator (sci-fi Eastward direction).

Humanoids: one NBP call per character produces a 2x2 sprite sheet on magenta
(quadrants: TL=facing down/front, TR=facing up/back, BL=facing left,
BR=facing right). We slice quadrants deterministically, key, trim, and scale
to a uniform height. Creatures: single idle pose.

Usage: python3 tools/art-pipeline/gen_chars.py [name ...]   (default: all)
"""
import io
import os
import sys
import statistics

from PIL import Image, ImageFilter
from google import genai
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ANCHOR = os.path.join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor.png')
OUT_DIR = os.path.join(ROOT, 'docs', 'art-options', 'chars-scifi')
RAW_DIR = os.path.join(OUT_DIR, 'raw')

SHEET_PROMPT = (
    'Using EXACTLY the pixel-art style, palette and lighting of the reference '
    'image — clean chunky pixel clusters, crisp dark outlines, warm-vs-teal '
    'dusk palette, the same rendering as the characters standing in the '
    'reference scene: a 2x2 sprite sheet of THE SAME SINGLE CHARACTER — {desc} — on a '
    'flat solid pure magenta (#FF00FF) background. Four cells: top-left the '
    'character FACING THE VIEWER (front), top-right FACING AWAY (back), '
    'bottom-left FACING LEFT in profile, bottom-right FACING RIGHT in profile. '
    'Identical outfit, colors and proportions in all four cells. Taller JRPG '
    'proportions like Eastward (about 3 heads tall), NOT chibi. Standing idle '
    'pose. Each cell shows the full body with margin. No ground, no shadows, '
    'no text, no grid lines, no border — only the four character poses on '
    'flat magenta.'
)

SINGLE_PROMPT = (
    'Using EXACTLY the pixel-art style, palette and lighting of the reference '
    'image: ONE single game creature sprite — {desc} — centered on a flat '
    'solid pure magenta (#FF00FF) background, filling most of the frame. '
    'Front-on JRPG 3/4 view. No ground, no shadow on the background, no other '
    'objects, no text, no border.'
)

HUMANOIDS = {
    'player': 'a young sci-fi wasteland engineer hero: short brown hair with goggles pushed up, worn teal utility jacket with glowing orange trim lines, armored shoulder pad, glowing wrist console, dark work pants, small tech backpack with an antenna',
    'chief': 'an elderly settlement overseer with white hair and a long pale lab coat over grey overalls, a small glowing badge',
    'angler': 'a grizzled old scavenger angler with an orange beanie, heavy blue weatherproof coat, waders',
    'settler': 'a friendly young settler with dark hair, a rust-red work vest over a tan shirt, tool belt',
}

CREATURES = {
    'trader': 'a boxy friendly merchant droid on small tracked wheels, teal-and-brass plating, one big glowing eye screen, a small awning antenna',
    'sludge': 'a rounded blob of glowing toxic orange-green sludge with two small dark eyes, menacing but cute',
    'drone': 'a small hostile surveillance drone with two stubby rotors, a single red camera eye, dark grey hull with hazard stripes',
    'boss': 'a huge intimidating boss blob of molten orange sludge with a glowing core and several small dark eyes, dripping. Crisp chunky pixel clusters with hard-banded shading and a dark outline, NOT smooth gradients',
}

TARGET_H = {'player': 44, 'chief': 44, 'angler': 44, 'settler': 44,
            'trader': 36, 'sludge': 28, 'drone': 26, 'boss': 72}


def border_median_key(img, thresh=95):
    img = img.convert('RGBA')
    px = img.load()
    w, h = img.size
    border = []
    for x in range(0, w, 5):
        border += [px[x, 0][:3], px[x, h - 1][:3]]
    for y in range(0, h, 5):
        border += [px[0, y][:3], px[w - 1, y][:3]]
    key = tuple(int(statistics.median(c[i] for c in border)) for i in range(3))
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if (r - key[0]) ** 2 + (g - key[1]) ** 2 + (b - key[2]) ** 2 < thresh ** 2:
                px[x, y] = (0, 0, 0, 0)
    mask = img.getchannel('A').point(lambda v: 255 if v > 0 else 0)
    img.putalpha(mask.filter(ImageFilter.MinFilter(3)))
    return img, key


def gen(client, anchor, prompt, raw_path):
    if os.path.exists(raw_path):
        return Image.open(raw_path)
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
        raise RuntimeError('no image: ' + (resp.text or '?')[:150])
    img.save(raw_path)
    return img


def scale_to(img, target_h):
    s = target_h / img.height
    return img.resize((max(1, round(img.width * s)), target_h), Image.LANCZOS)


def process_humanoid(name, client, anchor):
    raw_path = os.path.join(RAW_DIR, f'{name}.png')
    img = gen(client, anchor, SHEET_PROMPT.format(desc=HUMANOIDS[name]), raw_path)
    w, h = img.size
    cells = {
        'down': img.crop((0, 0, w // 2, h // 2)),
        'up': img.crop((w // 2, 0, w, h // 2)),
        'left': img.crop((0, h // 2, w // 2, h)),
        'right': img.crop((w // 2, h // 2, w, h)),
    }
    outs = {}
    for dirn, cell in cells.items():
        keyed, key = border_median_key(cell)
        bbox = keyed.getbbox()
        if not bbox:
            print(f'{name}/{dirn}: EMPTY after key {key}')
            return False
        outs[dirn] = scale_to(keyed.crop(bbox), TARGET_H[name])
    for dirn, im in outs.items():
        im.save(os.path.join(OUT_DIR, f'{name}-{dirn}.png'))
    # identity strip for the judge
    pad = 6
    W = sum(i.width for i in outs.values()) + pad * 5
    H = TARGET_H[name] + pad * 2
    strip = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    x = pad
    for dirn in ['down', 'up', 'left', 'right']:
        strip.paste(outs[dirn], (x, pad), outs[dirn])
        x += outs[dirn].width + pad
    strip.save(os.path.join(OUT_DIR, f'{name}.png'))
    print(f'{name}: 4 dirs ok, widths={[outs[d].width for d in ["down","up","left","right"]]}')
    return True


def process_creature(name, client, anchor):
    raw_path = os.path.join(RAW_DIR, f'{name}.png')
    img = gen(client, anchor, SINGLE_PROMPT.format(desc=CREATURES[name]), raw_path)
    keyed, key = border_median_key(img)
    bbox = keyed.getbbox()
    if not bbox:
        print(f'{name}: EMPTY after key {key}')
        return False
    out = scale_to(keyed.crop(bbox), TARGET_H[name])
    out.save(os.path.join(OUT_DIR, f'{name}.png'))
    print(f'{name}: {out.size} key={key}')
    return True


def main():
    os.makedirs(RAW_DIR, exist_ok=True)
    client = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
    anchor = Image.open(ANCHOR)
    anchor.thumbnail((1024, 1024))
    names = sys.argv[1:] or (list(HUMANOIDS) + list(CREATURES))
    for name in names:
        if name in HUMANOIDS:
            process_humanoid(name, client, anchor)
        else:
            process_creature(name, client, anchor)


if __name__ == '__main__':
    main()
