#!/usr/bin/env python3
"""Remove painted characters from the plate and record spawn points for real
NPC entities. Patch-local inpainting (kidsgame recipe): NBP reconstructs only
a padded crop; we paste back ONLY within the character's dilated pixel mask,
so every pixel outside the mask stays identical by construction.
"""
import io
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image
from google import genai
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATE = os.path.join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor.png')
CLEAN = os.path.join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor-clean.png')
OUT = os.path.join(ROOT, 'docs', 'art-options')

client = genai.Client(vertexai=True, project='adk-coding-agents', location='global')


def main():
    src = Image.open(PLATE).convert('RGB')
    W, H = src.size
    instances = json.load(open(os.path.join(ROOT, 'tools', 'art-pipeline', '_srcinst_anchorroom.json')))
    chars = [i for i in instances if i['kind'] == 'character']
    if not chars:
        sys.exit('no character instances found')
    # verify each candidate: curtain highlights etc. can snap to the yellow
    # class — only true characters may be inpainted away
    verified = []
    for inst in chars:
        bx0, by0, bx1, by1 = inst['box']
        pad2 = 20
        crop2 = Image.open(PLATE).convert('RGB').crop(
            (max(0, bx0 - pad2), max(0, by0 - pad2), bx1 + pad2, by1 + pad2))
        vr = client.models.generate_content(
            model='gemini-3.1-pro-preview',
            contents=[crop2, 'Is the main subject of this crop a person or a robot character '
                             '(not curtains, not machinery, not signage)? '
                             'Return JSON only: {"is_character": bool, "what": "short"}'],
            config=types.GenerateContentConfig(max_output_tokens=1024),
        )
        txt2 = vr.text or ''
        st2 = txt2.find('{')
        v2 = {}
        if st2 >= 0:
            try:
                v2, _ = json.JSONDecoder().raw_decode(txt2[st2:])
            except Exception:  # noqa: BLE001
                pass
        print(f'  candidate at {inst["box"]}: is_character={v2.get("is_character")} ({v2.get("what", "?")})')
        if v2.get('is_character'):
            verified.append(inst)
    chars = verified
    if not chars:
        sys.exit('no VERIFIED characters — nothing to remove')
    # rebuild character pixel masks from the class mask (yellow)
    cls = np.asarray(Image.open(os.path.join(OUT, 'nbp-mask.png')).convert('RGB')
                     .resize(src.size, Image.NEAREST)).astype(np.int16)
    charpix = np.linalg.norm(cls - np.array([255, 255, 0], np.int16), axis=2) < 90

    plate_np = np.asarray(src).copy()
    spawns = []
    # the characters stand adjacent: treat them as ONE removal region, or the
    # judge always sees the neighbors and can never pass
    def nearest_aspect(w, h):
        opts = {'1:1': 1.0, '4:3': 4 / 3, '3:4': 3 / 4, '16:9': 16 / 9, '9:16': 9 / 16}
        r = w / h
        return min(opts, key=lambda k: abs(opts[k] - r))

    groups = [(i['box'][0], i['box'][1], i['box'][2], i['box'][3], [i]) for i in chars]
    for ci, (x0, y0, x1, y1, members) in enumerate(groups):
        pad = 70
        cx0, cy0 = max(0, x0 - pad), max(0, y0 - pad)
        cx1, cy1 = min(W, x1 + pad), min(H, y1 + pad)
        prompt = ('The flat magenta regions in this image mark removed objects. Fill ONLY the magenta '
                  'regions with the continuing ground, floor and background surfaces, seamlessly '
                  'matching the surrounding pixel-art style, lighting and palette. Keep every '
                  'non-magenta pixel EXACTLY identical to the input.')
        # iterative clean-up: generate patch -> paste -> JUDGE -> re-roll
        m = charpix[cy0:cy1, cx0:cx1].astype(np.uint8)
        m = cv2.dilate(m, np.ones((35, 35), np.uint8))  # swallow AA edges + cast shadows
        mf = cv2.GaussianBlur(m.astype(np.float32), (9, 9), 0)[..., None]
        original = plate_np[cy0:cy1, cx0:cx1].copy()
        # masked-fill input: characters painted flat magenta (explicit region)
        fill_input = original.copy()
        fill_input[m.astype(bool)] = (255, 0, 255)
        done = False
        for round_i in range(3):
            patch = None
            resp = client.models.generate_content(
                model='gemini-3-pro-image',
                contents=[Image.fromarray(fill_input), prompt],
                config=types.GenerateContentConfig(
                    image_config=types.ImageConfig(
                        aspect_ratio=nearest_aspect(cx1 - cx0, cy1 - cy0), image_size='1K'),
                ),
            )
            for part in (resp.parts or []):
                if part.inline_data is not None:
                    patch = Image.open(io.BytesIO(part.inline_data.data)).convert('RGB')
            if patch is None:
                continue
            patch = np.asarray(patch.resize((cx1 - cx0, cy1 - cy0), Image.LANCZOS))
            # hard-edged paste (feathering ghosts the removed characters back in)
            hard = (mf[..., 0] > 0.35)
            candidate = original.copy()
            candidate[hard] = patch[hard]
            # judge the pasted result
            jr = client.models.generate_content(
                model='gemini-3.1-pro-preview',
                contents=[Image.fromarray(candidate),
                          'This crop had one character digitally removed and the hole filled. Judge ONLY '
                          'the filled area: is the character fully gone (no silhouette/limbs), and does '
                          'the reconstructed ground/floor continue the surrounding textures plausibly '
                          '(grate lines continue, tile seams continue)? Other characters may legitimately '
                          'be present elsewhere in the crop — ignore them. '
                          'Return JSON only: {"character_free": bool, "ground_ok": bool, "issues": "short"}'],
                config=types.GenerateContentConfig(max_output_tokens=2048),
            )
            txt = jr.text or ''
            st = txt.find('{')
            verdict = {}
            if st >= 0:
                try:
                    verdict, _ = json.JSONDecoder().raw_decode(txt[st:])
                except Exception:  # noqa: BLE001
                    pass
            ok = bool(verdict.get('character_free'))
            g_ok = bool(verdict.get('ground_ok'))
            print(f'  group {ci} round {round_i}: character_free={ok} ground_ok={g_ok} issues={verdict.get("issues", "?")}')
            Image.fromarray(candidate).save(os.path.join(OUT, f'_inpaint_candidate_r{round_i}.png'))
            if ok and g_ok:
                plate_np[cy0:cy1, cx0:cx1] = candidate
                done = True
                break
        if not done:
            print(f'group {ci}: not cleanly removed after 3 rounds, keeping painted characters')
            continue
        for inst in members:
            bx0, by0, bx1, by1 = inst['box']
            lx = round((bx0 + bx1) / 2 / W * 640)
            ly = round(inst['baseY'] / H * 448)
            spawns.append({'label': inst['label'], 'x': lx, 'y': ly})
            print(f'  npc spawn at logical ({lx},{ly}) [{inst["label"]}]')

    Image.fromarray(plate_np).save(CLEAN)
    json.dump(spawns, open(os.path.join(ROOT, 'tools', 'art-pipeline', '_char_spawns.json'), 'w'), indent=1)
    print('clean plate saved:', CLEAN)


if __name__ == '__main__':
    main()
