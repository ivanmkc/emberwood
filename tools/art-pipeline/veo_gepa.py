#!/usr/bin/env python3
"""GEPA-lite over the Veo walk prompt (Ivan): objective = LOCKED camera +
magenta-keyed walkers. Score = drift term (ORB homography center-drift vs
frame 0) + key term (median per-frame magenta pixel count in walker range).
Gen1: 3 camera-lock phrasings; reflect on measured failures; Gen2: 2 mutants
of the winner. Winner regenerates the production walk set."""
import io
import json
import os
import time

import cv2
import numpy as np
from PIL import Image
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = '/home/ivanmkc/.claude/jobs/92f6b395/tmp/veogepa'
MODEL = 'veo-3.1-generate-001'
MAG = np.array([255, 0, 255], np.int16)

SUIT = ('One villager wearing a FLAT PURE MAGENTA (#FF00FF) full-body suit — hood, torso, legs, '
        'all the same solid flat magenta, no shading — walks slowly through the market: enters '
        'left, passes behind the noodle stand counter, exits right. Crisp pixel-art animation, '
        'character scaled to the scene. ')
SCENE = ('The pixel-art night-market scene stays EXACTLY as shown in the reference image — same '
         'layout, same lighting, nothing redecorated. ')
CANDS_G1 = {
 'lock-a': 'Completely static locked-off camera: no camera movement, no zoom, no pan, no cuts. ' + SCENE + SUIT,
 'lock-b': ('Footage from a security camera bolted rigidly to a wall: the framing is absolutely fixed, '
            'tripod-locked, zero camera motion of any kind, no push-in, no drift, no cuts. ') + SCENE + SUIT,
 'lock-c': ('A screen recording of a 2D video game: the viewport NEVER scrolls or zooms — the background '
            'is a static bitmap and only sprites move. ') + SCENE + SUIT,
}

def gen_video(client, prompt, name, plate_bytes):
    try:
        op = client.models.generate_videos(model=MODEL, prompt=prompt,
            image=types.Image(image_bytes=plate_bytes, mime_type='image/png'),
            config=types.GenerateVideosConfig(aspect_ratio='16:9', number_of_videos=1))
    except (genai_errors.APIError, ValueError) as e:
        print(name, 'launch error', e); return None
    t0 = time.time()
    while time.time() - t0 < 600:
        time.sleep(15)
        try:
            op = client.operations.get(op)
        except genai_errors.APIError:
            continue
        if op.done:
            vids = getattr(op.response, 'generated_videos', None) or []
            if not vids: print(name, 'empty'); return None
            p = os.path.join(OUT, f'{name}.mp4')
            open(p, 'wb').write(vids[0].video.video_bytes)
            return p
    print(name, 'timeout'); return None

def score(path):
    cap = cv2.VideoCapture(path)
    frames = []
    while len(frames) < 190:
        ok, fr = cap.read()
        if not ok: break
        frames.append(cv2.resize(fr, (600, 338)))
    cap.release()
    grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    orb = cv2.ORB_create(1500)
    kr, dr = orb.detectAndCompute(grays[0], None)
    drifts = []
    for g in grays[10::20]:
        kf, df = orb.detectAndCompute(g, None)
        if df is None: continue
        m = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(dr, df)
        if len(m) < 30: continue
        src = np.float32([kr[x.queryIdx].pt for x in m]).reshape(-1,1,2)
        dst = np.float32([kf[x.trainIdx].pt for x in m]).reshape(-1,1,2)
        H, _ = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
        if H is None: continue
        c2 = cv2.perspectiveTransform(np.float32([[[300,169]]]), H)[0,0]
        drifts.append(float(np.hypot(c2[0]-300, c2[1]-169)))
    drift = float(np.median(drifts)) if drifts else 999
    keys = []
    for f in frames[::8]:
        rgb = f[:, :, ::-1].astype(np.int16)
        k = int((np.linalg.norm(rgb - MAG, axis=2) < 90).sum())
        keys.append(k)
    kmed = float(np.median(keys))
    key_ok = 1.0 if 300 <= kmed <= 25000 else 0.0
    s = 1.0 / (1.0 + drift) + key_ok
    return {'drift_median': round(drift, 2), 'key_px_median': kmed, 'key_ok': key_ok, 'score': round(s, 3)}

def main():
    os.makedirs(OUT, exist_ok=True)
    plate = Image.open(os.path.join(ROOT, 'docs/art-options/rooms/night-bazaar/plate.png')).convert('RGB')
    plate.thumbnail((1280, 1280))
    buf = io.BytesIO(); plate.save(buf, format='PNG')
    pb = buf.getvalue()
    client = genai.Client(vertexai=True, project='adk-coding-agents', location='us-central1')
    results = {}
    for name, prompt in CANDS_G1.items():
        p = gen_video(client, prompt, name, pb)
        results[name] = {'prompt': prompt, 'video': p, **(score(p) if p else {'score': 0})}
        print(name, results[name].get('drift_median'), results[name].get('key_px_median'), results[name]['score'])
    best = max(results, key=lambda k: results[k]['score'])
    bp = results[best]['prompt']
    # reflect: strengthen what measurement says is weak
    muts = {}
    if results[best].get('drift_median', 999) > 2:
        muts['g2-drift'] = bp + ('The first and last frames must be PIXEL-IDENTICAL outside the character. '
                                 'Absolutely no slow push-in or creeping zoom.')
    if not results[best].get('key_ok'):
        muts['g2-key'] = bp.replace('FLAT PURE MAGENTA (#FF00FF)', 'GLOWING NEON MAGENTA (#FF00FF), maximally saturated,')
    if not muts:
        muts['g2-tight'] = bp + 'Frame 1 and frame 192 are identical except the character.'
    for name, prompt in muts.items():
        p = gen_video(client, prompt, name, pb)
        results[name] = {'prompt': prompt, 'video': p, **(score(p) if p else {'score': 0})}
        print(name, results[name].get('drift_median'), results[name].get('key_px_median'), results[name]['score'])
    winner = max(results, key=lambda k: results[k]['score'])
    json.dump({'results': {k: {kk: vv for kk, vv in v.items() if kk != 'video'} for k, v in results.items()},
               'winner': winner, 'winning_prompt': results[winner]['prompt']},
              open(os.path.join(ROOT, 'docs/art-options/veo-gepa-night-bazaar.json'), 'w'), indent=1)
    print('WINNER:', winner, results[winner]['score'])

if __name__ == '__main__':
    main()
