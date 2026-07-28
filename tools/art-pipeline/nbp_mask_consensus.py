#!/usr/bin/env python3
"""Consensus class-mask pass: N gated rolls of the nbp_mask repaint -> per-
pixel per-class majority. Single rolls carry NBP's spatial drift (the bazaar
misalignment Ivan caught: up to 34px per object); pixel consensus averages it
out, exactly as it does for the walk mask. Drop-in: overwrites nbp-mask.png +
nbp-mask-metrics.json so segment_room consumes it unchanged.
"""
import io
import json
import os
import random
import sys
import time

import cv2
import numpy as np
from PIL import Image
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

import nbp_mask  # reuse CLASSES, PROMPT, gate values

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
N_ROLLS = 5
MAX_TRIES = 12


def one_roll(client, seg_in, src, cols, names):
    try:
        resp = client.models.generate_content(
            model='gemini-3-pro-image', contents=[seg_in, nbp_mask.PROMPT],
            config=types.GenerateContentConfig(
                image_config=types.ImageConfig(aspect_ratio='4:3', image_size='2K')))
        mask_img = None
        for part in (resp.parts or []):
            if part.inline_data is not None:
                mask_img = Image.open(io.BytesIO(part.inline_data.data)).convert('RGB')
        if mask_img is None:
            return None
        mask_img = mask_img.resize(src.size, Image.NEAREST)
        m = np.asarray(mask_img).astype(np.int16)
        d = np.linalg.norm(m[:, :, None, :] - cols[None, None, :, :], axis=3)
        idx = d.argmin(axis=2).astype(np.int8)
        mind = d.min(axis=2)
        pure = float((mind < 90).mean())
        floor_frac = float((idx == names.index('floor'))[mind < 90].mean())
        sg = cv2.Canny(cv2.cvtColor(np.asarray(src), cv2.COLOR_RGB2GRAY), 60, 140)
        mg = cv2.Canny(cv2.cvtColor(np.asarray(mask_img), cv2.COLOR_RGB2GRAY), 60, 140)
        sgd = cv2.dilate(sg, np.ones((9, 9), np.uint8))
        al = mg > 0
        edge_agree = float((sgd[al] > 0).mean()) if al.any() else 0.0
        ok = pure >= 0.85 and 0.12 <= floor_frac <= 0.80 and edge_agree >= 0.55
        print(f'  roll purity {pure:.2f} floor {floor_frac:.2f} edge {edge_agree:.2f}'
              f' -> {"ACCEPT" if ok else "reject"}')
        if not ok:
            return None
        idx[mind >= 90] = -1  # impure pixels abstain from the vote
        return idx
    except (genai_errors.APIError, OSError, ValueError) as e:
        print('  roll error', e)
        time.sleep(4 * random.uniform(0.5, 1.5))
        return None


def main(room):
    out = os.path.join(ROOT, 'docs', 'art-options', 'rooms', room)
    src = Image.open(os.path.join(out, 'plate.png')).convert('RGB')
    seg_in = src.copy()
    seg_in.thumbnail((1200, 1200))
    names = list(nbp_mask.CLASSES)
    cols = np.array([nbp_mask.CLASSES[n] for n in names], dtype=np.int16)
    W, H = src.size

    client = genai.Client(vertexai=True, project='adk-coding-agents', location='global')
    votes = np.zeros((len(names), H, W), np.int8)
    accepted = 0
    tries = 0
    while accepted < N_ROLLS and tries < MAX_TRIES:
        tries += 1
        idx = one_roll(client, seg_in, src, cols, names)
        if idx is None:
            continue
        for c in range(len(names)):
            votes[c] += (idx == c)
        accepted += 1
    if accepted < 3:
        sys.exit(f'FATAL: only {accepted} rolls accepted')

    top = votes.argmax(axis=0)
    topv = votes.max(axis=0)
    known = topv >= 2  # at least 2 rolls agree; else nearest-label fill
    lab = top.astype(np.int16)
    lab[~known] = -1
    while (lab < 0).any():
        grown = cv2.dilate((lab + 1).astype(np.uint8), np.ones((3, 3), np.uint8))
        fill = (lab < 0) & (grown > 0)
        lab[fill] = grown[fill].astype(np.int16) - 1

    snapped = cols[lab].astype(np.uint8)
    Image.fromarray(snapped).save(os.path.join(out, 'nbp-mask.png'))

    # consensus-level gate metrics (agreement = fraction of pixels with >=3 votes)
    agree3 = float((votes.max(axis=0) >= 3).mean())
    floor_frac = float((lab == names.index('floor')).mean())
    sg = cv2.Canny(cv2.cvtColor(np.asarray(src), cv2.COLOR_RGB2GRAY), 60, 140)
    mg = cv2.Canny(cv2.cvtColor(snapped, cv2.COLOR_RGB2GRAY), 60, 140)
    sgd = cv2.dilate(sg, np.ones((9, 9), np.uint8))
    al = mg > 0
    edge_agree = float((sgd[al] > 0).mean()) if al.any() else 0.0
    metrics = {'method': 'consensus', 'rolls_accepted': accepted,
               'agreement3': round(agree3, 3), 'snap_purity': 1.0,
               'floor_fraction': round(floor_frac, 3),
               'edge_alignment': round(edge_agree, 3),
               'pass': bool(0.12 <= floor_frac <= 0.80 and edge_agree >= 0.55)}
    json.dump(metrics, open(os.path.join(out, 'nbp-mask-metrics.json'), 'w'))
    b = np.asarray(src).astype(np.float32) * 0.45 + snapped.astype(np.float32) * 0.45
    bi = Image.fromarray(b.clip(0, 255).astype(np.uint8))
    bi.thumbnail((1400, 1400))
    bi.save(os.path.join(out, 'nbp-mask-on-source.jpg'), quality=86)
    print(json.dumps(metrics))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'night-bazaar')
