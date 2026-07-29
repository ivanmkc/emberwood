#!/usr/bin/env python3
"""Veo walk-probing (Ivan): image-to-video from the plate with a LOCKED static
camera and characters walking through the scene — the video generalization of
occlusion probing (continuous evidence as characters pass behind/in front of
objects). Model chosen from models.list: veo-3.1-generate-001 (newest GA).
Outputs mp4 + board-ready GIF per video under docs/art-options/veo/.
"""
import io
import os
import sys
import time

import cv2
import numpy as np
from PIL import Image
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL = 'veo-3.1-generate-001'
PLATE = os.path.join(ROOT, 'docs/art-options/rooms/night-bazaar/plate.png')
OUT = os.path.join(ROOT, 'docs/art-options/veo')

BASE = ('Completely static locked-off camera: no camera movement, no zoom, no pan, no cuts. '
        'The pixel-art night-market scene stays EXACTLY as shown in the reference image — '
        'same layout, same lighting, nothing redecorated. ')
PROMPTS_EXTRA = [
 BASE + 'Two villagers cross the market diagonally: one from bottom-left toward the noodle stand, '
        'stopping behind its counter; one from the right edge walking left along the back stalls. '
        'Crisp pixel-art animation, characters scaled to the scene.',
 BASE + 'One villager walks slowly from the bottom-center straight up the middle aisle, passing '
        'under the hanging lanterns and behind the produce stall, ending at the far back. '
        'Crisp pixel-art animation, character scaled to the scene.',
]
PROMPTS = [
 BASE + 'One villager in a brown coat walks slowly through the market: enters from the left '
        'edge, walks along the open ground, passes BEHIND the noodle stand counter so the '
        'counter hides his legs, then in front of the produce stalls, and exits to the right. '
        'Crisp pixel-art animation, character scaled to the scene.',
 BASE + 'Three villagers walk around the market at the same time on different paths: one '
        'crosses the foreground left to right, one walks far in the back passing behind the '
        'stalls, one walks from the front toward the noodle stand and stops behind its '
        'counter. They never block the camera. Crisp pixel-art animation.',
 BASE + 'One villager walks a loop: down the left aisle toward the camera, across the front, '
        'up the right side passing behind the hanging lanterns and under the awnings, ending '
        'behind the far stalls. Crisp pixel-art animation, character scaled to the scene.',
]


def to_gif(mp4_path, gif_path, width=640, fps=8):
    cap = cv2.VideoCapture(mp4_path)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 24
    step = max(1, round(src_fps / fps))
    frames = []
    i = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        if i % step == 0:
            h = int(fr.shape[0] * width / fr.shape[1])
            fr = cv2.resize(fr, (width, h))
            frames.append(Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)))
        i += 1
    cap.release()
    if frames:
        frames[0].save(gif_path, save_all=True, append_images=frames[1:],
                       duration=int(1000 / fps), loop=0)
    return len(frames)


def main():
    os.makedirs(OUT, exist_ok=True)
    plate = Image.open(PLATE).convert('RGB')
    plate.thumbnail((1280, 1280))
    buf = io.BytesIO()
    plate.save(buf, format='PNG')
    client = genai.Client(vertexai=True, project='adk-coding-agents',
                          location='us-central1')
    ops = []
    import sys
    plist = PROMPTS_EXTRA if '--extra' in sys.argv else PROMPTS
    base_n = 3 if '--extra' in sys.argv else 0
    for n, prompt in enumerate(plist, start=base_n):
        try:
            op = client.models.generate_videos(
                model=MODEL, prompt=prompt,
                image=types.Image(image_bytes=buf.getvalue(), mime_type='image/png'),
                config=types.GenerateVideosConfig(aspect_ratio='16:9',
                                                  number_of_videos=1))
            ops.append((n, op))
            print(f'video {n}: operation started')
        except (genai_errors.APIError, ValueError) as e:
            print(f'video {n}: launch error {e}')

    deadline = time.time() + 900
    pending = dict(ops)
    while pending and time.time() < deadline:
        time.sleep(20)
        for n, op in list(pending.items()):
            try:
                op = client.operations.get(op)
            except genai_errors.APIError as e:
                print(f'video {n}: poll error {e}')
                continue
            if not op.done:
                pending[n] = op
                continue
            del pending[n]
            vids = getattr(op.response, 'generated_videos', None) or []
            if not vids:
                print(f'video {n}: DONE but empty (filtered?) — {op.error or op.response}')
                continue
            vb = vids[0].video.video_bytes
            mp4 = os.path.join(OUT, f'walk{n}.mp4')
            open(mp4, 'wb').write(vb)
            nf = to_gif(mp4, os.path.join(OUT, f'walk{n}.gif'))
            print(f'video {n}: saved {len(vb)//1024}KB mp4, gif {nf} frames')
    for n in pending:
        print(f'video {n}: TIMEOUT still pending')


if __name__ == '__main__':
    main()
