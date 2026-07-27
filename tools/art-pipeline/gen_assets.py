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

# Verified against official Eastward screenshots (eastwardgame.com/media):
# the perspective is straight-on 3/4 top-down, NEVER rotated or isometric.
PERSPECTIVE = (
    'CRITICAL PERSPECTIVE RULES (classic JRPG 3/4 top-down, exactly like the '
    'reference): the object is drawn FRONT-ON with its facade parallel to the '
    'bottom edge of the frame. NO rotation, NO isometric angle, NO vanishing '
    'points, NO visible side walls. Vertical surfaces face the camera '
    'directly; horizontal top surfaces tilt slightly toward the viewer. '
)

BASE_PROMPT = (
    'Using EXACTLY the pixel-art style, palette, lighting and level of detail '
    'of the reference image (dense modern pixel art, dusk teal shadows, warm '
    'neon highlights): generate ONE single isolated game asset — {desc} — '
    'centered on a {bg}, filling most of the frame. ' + PERSPECTIVE +
    'No ground, no shadow cast on the background, no other objects, no text, '
    'no border.'
)

# theme -> anchor image + assets: name -> (description, target_height_px)
THEMES = {
    'fantasy': {
        'anchor': 'nbp-eastward-village.png',
        'assets': {
            'tree': ('a leafy deciduous tree with a visible trunk, canopy lit from the upper left', 96),
            'rock': ('a single mossy grey boulder', 32),
            'chest': ('a closed wooden treasure chest with gold trim, front face visible', 32),
            'beacon': ('a round stone beacon brazier with a bright orange flame burning in its bowl', 48),
            'lamp': ('STRICTLY ONE OBJECT: a single tall thin wrought-iron street lamp post with one glowing lantern at its top. Nothing else in the image; every pixel that is not the lamp post itself must be flat magenta', 64),
            'house': ('a two-story timber-frame cottage with a steep shingled roof, warm glowing windows and a wooden door, front facade and roof visible', 160),
        },
    },
    'scifi': {
        'anchor': 'nbp-scifi-anchor.png',
        'assets': {
            'tree': ('STRICTLY ONE OBJECT: a bio-engineered tree growing from a hydroponic ring collar, canopy with a faint teal glow, small maintenance lights on the collar', 96),
            'rock': ('STRICTLY ONE OBJECT: a single free-standing boulder-shaped chunk of collapsed concrete with bent rebar sticking out and faded hazard-stripe paint. Crisp chunky pixel clusters with hard-banded shading and a dark outline, NOT soft gradients. One rounded lump with a clear silhouette against the magenta — NOT a tile, NOT a flat ground patch', 32),
            'chest': ('STRICTLY ONE OBJECT: a closed armored supply crate with a glowing orange latch and worn hazard stripes, front face visible', 32),
            'beacon': ('STRICTLY ONE OBJECT: a signal-beacon pylon — a squat armored base cradling a bright orange energy core. No cables. The glow must stay INSIDE the object silhouette: no halo, no light spill, no gradient on the background — the magenta background stays perfectly flat and pure everywhere', 48),
            'lamp': ('STRICTLY ONE OBJECT: a single tall thin dark-metal street-light pole with one warm amber-white lantern head at its top, matching the warm lamp glow of the reference scene. Crisp chunky pixel clusters, sharp edges, no blur. Nothing else; every pixel that is not the pole must be flat magenta', 64),
            'bush': ('STRICTLY ONE OBJECT: a small low shrub of teal-glowing alien leaves in a shallow scrap-metal ring, crisp chunky pixels, dark outline', 40),
            'mast': ('STRICTLY ONE OBJECT standing alone: a single tall thin antenna pole with one small dish near the top and one tiny red light on the tip. Just the one vertical pole, nothing else anywhere; every pixel that is not the pole must be flat magenta. Crisp chunky pixels', 88),
            'crates': ('STRICTLY ONE OBJECT: a small stack of two worn supply crates with faded stencil markings, front-on, crisp chunky pixels, dark outline', 40),
            'pipe': ('STRICTLY ONE OBJECT: a short broken industrial pipe segment jutting from the ground with a faint teal drip stain, crisp chunky pixels', 32),
            'wallchunk': ('STRICTLY ONE OBJECT: a ruined concrete wall fragment with exposed rebar and faded hazard paint, front-on flat elevation, crisp chunky pixels', 48),
            'stall': ('STRICTLY ONE OBJECT: a small market stall — metal frame with a patched fabric awning and a counter of salvaged goods, front-on flat elevation like a stage-set flat, no side walls, crisp chunky pixels', 72),
            'tree2': ('STRICTLY ONE OBJECT: a tall slender bio-engineered tree with a narrow drooping teal canopy and exposed pale roots over a small hydroponic collar — clearly DIFFERENT silhouette from a round-canopy tree, crisp chunky pixels', 96),
            'tanktree': ('STRICTLY ONE OBJECT: a slender bio-tree growing inside a tall rectangular glass hydroponic tank with a metal base and teal nutrient liquid glow, exactly like a greenhouse specimen tank. Front-on flat elevation, crisp chunky pixels, dark outline', 80),
            'garage': ('STRICTLY ONE OBJECT drawn as a FLAT FRONT ELEVATION like a stage-set flat: a wide single-story industrial depot storefront — corrugated walls, one large closed roller garage door with worn orange-and-blue paint, a glowing neon sign above the door, small pipes and an AC unit along the roofline, junction boxes by the door. Bottom edge perfectly horizontal, ONLY the front face plus a narrow roof strip, NO side walls, NO isometric rotation', 140),
            'junction': ('STRICTLY ONE OBJECT: a small wall-mount electrical junction box with conduit stubs and one tiny green status light, crisp chunky pixels, dark outline', 26),
            'terminal': ('STRICTLY ONE OBJECT: a free-standing data terminal — a dark metal pedestal with a tilted glowing teal screen showing faint scan lines, a few small blinking status lights. Crisp chunky pixels, dark outline', 48),
            'rack': ('STRICTLY ONE OBJECT: an industrial storage rack shelf holding a few crates and canisters, front-on flat elevation, crisp chunky pixels', 48),
            'vat': ('STRICTLY ONE OBJECT: a broken cylindrical glass bio-vat on a metal base, cracked glass, dead vines inside, faint teal residue glowing at the bottom. Front-on, crisp chunky pixels', 64),
            'house': ('STRICTLY ONE OBJECT: a compact two-story modular habitat block drawn as a FLAT FRONT ELEVATION, like a stage-set flat facing the audience straight on — the bottom edge of the wall perfectly horizontal, ONLY the front face visible plus a narrow strip of solar-panel roof tilted toward the viewer above the facade. ABSOLUTELY NO corner view, NO second visible face, NO diagonal wall edges, NO isometric rotation. Corrugated metal walls, warm glowing windows, a sliding metal door with a small neon sign above it, antennas on the roof strip', 160),
        },
    },
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
        img = None
        for attempt in range(3):
            resp = client.models.generate_content(
                model='gemini-3-pro-image',
                contents=[anchor, prompt],
                config=types.GenerateContentConfig(
                    image_config=types.ImageConfig(aspect_ratio='1:1', image_size='1K'),
                ),
            )
            for part in (resp.parts or []):
                if part.inline_data is not None:
                    img = Image.open(io.BytesIO(part.inline_data.data))
            if img is not None:
                break
        if img is None:
            print(f'{name}: NO IMAGE after retries')
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
    args = sys.argv[1:]
    theme = 'fantasy'
    if args and args[0] == '--theme':
        theme = args[1]
        args = args[2:]
    cfg = THEMES[theme]
    global RAW_DIR, OUT_DIR
    if theme != 'fantasy':
        RAW_DIR = os.path.join(ROOT, 'docs', 'art-options', f'assets-{theme}', 'raw')
        OUT_DIR = os.path.join(ROOT, 'docs', 'art-options', f'assets-{theme}')
    os.makedirs(RAW_DIR, exist_ok=True)
    client = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
    anchor = Image.open(os.path.join(ROOT, 'docs', 'art-options', cfg['anchor']))
    anchor.thumbnail((1024, 1024))
    names = args or list(cfg['assets'])
    for name in names:
        desc, target_h = cfg['assets'][name]
        process(name, desc, target_h, client, anchor)


if __name__ == '__main__':
    main()
