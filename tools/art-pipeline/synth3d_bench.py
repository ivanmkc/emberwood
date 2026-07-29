#!/usr/bin/env python3
"""3D synthetic vetting bench for the feet-conditioned layer estimator.

Renders a perspective 3D scene (three.js in headless Chromium via Playwright),
captures plate / parts-ID / ground / collision masks, then renders walker
videos where a magenta-suited humanoid traverses scripted waypoints. Runs
the IDENTICAL estimator code (veo_layers_v4.estimate) and scores predictions
against ground truth.

The key question: does the constant-height walker model (h_est = p90 of
silhouette heights) break under real perspective, where the walker's on-screen
size changes with depth? If so, we implement and validate a depth-aware fix.

CC0 3D models from Kenney (kenney.nl); remaining objects are three.js
procedural geometry. See synth3d/CREDITS.md for full provenance.
"""
import base64
import http.server
import io
import json
import os
import subprocess
import sys
import threading
import time

import cv2
import numpy as np
from PIL import Image

# ---- path setup: ensure art-pipeline is importable -----------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
sys.path.insert(0, SCRIPT_DIR)

import veo_layers_v4 as v4
import veo_walk

OUT = os.path.join(ROOT, 'docs/art-options/synth3d')
SYNTH3D_DIR = os.path.join(SCRIPT_DIR, 'synth3d')
PLAYWRIGHT_PATH = os.path.join(ROOT, '..', 'termchart', 'node_modules',
                               'playwright', 'index.mjs')
RENDER_W = 1200
RENDER_H = 675
VIDEO_FPS = 24
VIDEO_FRAMES = 192   # 8 seconds at 24fps
SERVER_PORT = 8321

# walker waypoint paths in world-space (x, z)
# z > 0 = closer to camera = lower on screen = "in front"
# z < 0 = farther from camera = higher on screen = "behind"
# standing objects at: crate1(-4,-4), barrel1(-6,1), table(2,-3), kiosk(-1,0),
#   bookshelf(5,-2), bench(3,4), crate2(6,2), barrel2(-3,5),
#   house(-7,-2), brick(0,6)
# overhead cables at z=-3 and z=3; lanterns/signs hang from them
PATHS = [
    # Path 0: left-to-right BEHIND all objects (z=-6)
    [(-10, -6), (-5, -6), (0, -6), (5, -6), (10, -6)],
    # Path 1: left-to-right IN FRONT of all objects (z=8)
    [(-10, 8), (-5, 8), (0, 8), (5, 8), (10, 8)],
    # Path 2: serpentine behind then in front of each standing object
    # tighter z-offsets (1.0 behind base, 1.0 in front) to maximize occlusion
    # crate1(-4,-4): base z=-3.5, behind=-4.8 front=-2.5
    # table(2,-3): base z=-2.5, behind=-3.8 front=-1.5
    # kiosk(-1,0): base z=0.6, behind=-0.8 front=1.8
    # bookshelf(5,-2): base z=-1.8, behind=-3.0 front=-0.5
    # barrel1(-6,1): base z=1.5, behind=0 front=2.8
    [(-4, -4.8), (-4, -2.5), (2, -3.8), (2, -1.5), (-1, -0.8),
     (-1, 1.8), (5, -3.0), (5, -0.5), (-6, 0.0), (-6, 2.8)],
    # Path 3: under cable 1 at z=-3 (walker passes under overhead objects)
    [(-10, -3), (-5, -3), (-2, -3), (0, -3), (1, -3), (4, -3), (10, -3)],
    # Path 4: under cable 2 at z=3 (passes under second cable's overheads)
    [(-10, 3), (-5, 3), (-3, 3), (0, 3), (5, 3), (10, 3)],
    # Path 5: behind+front of remaining objects (tighter offsets)
    # bench(3,4) base=4.25: behind=3.0 front=5.5
    # crate2(6,2) base=2.4: behind=1.0 front=3.5
    # barrel2(-3,5) base=5.45: behind=4.0 front=6.5
    # brick(0,6) base≈6.5: behind=5.0 front=7.5
    [(3, 3.0), (3, 5.5), (6, 1.0), (6, 3.5), (-3, 4.0),
     (-3, 6.5), (0, 5.0), (0, 7.5)],
    # Path 6: extreme perspective sweep (close z=8 → far z=-7)
    [(0, 8), (0, 4), (0, 0), (0, -4), (0, -7),
     (0, -4), (0, 0), (0, 4), (0, 8)],
    # Path 7: across decals at their z-positions
    # decal1(-2,3), decal2(4,-1), decal3(-5,-3)
    [(-2, 3), (-2, 4.5), (4, -1), (4, 0.5), (-5, -3), (-5, -1.5)],
]


def start_http_server():
    """Serve the repo root so synth3d/ files are accessible."""
    handler = http.server.SimpleHTTPRequestHandler
    httpd = http.server.HTTPServer(('127.0.0.1', SERVER_PORT), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def decode_data_url(data_url):
    """Decode a data:image/png;base64,... URL to a numpy BGR array."""
    header, b64data = data_url.split(',', 1)
    raw = base64.b64decode(b64data)
    arr = np.frombuffer(raw, np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def decode_parts_image(img_bgr, pid_colors):
    """Decode the flat-colored parts render into an int32 parts map.

    Uses the pid-to-RGB color table exported by the JS scene. Each pixel is
    matched to its nearest pid color (Euclidean distance in RGB); pixels
    farther than DECODE_TOLERANCE from any known color are assigned pid=0.
    """
    DECODE_TOLERANCE = 25
    h, w = img_bgr.shape[:2]
    parts_map = np.zeros((h, w), np.int32)
    rgb = img_bgr[:, :, ::-1].astype(np.float32)

    for pid_str, color in pid_colors.items():
        pid = int(pid_str)
        target = np.array([color['r'], color['g'], color['b']], np.float32)
        dist = np.linalg.norm(rgb - target, axis=2)
        mask = dist < DECODE_TOLERANCE
        parts_map[mask] = pid

    return parts_map


def render_scene(out_dir):
    """Render plate, parts, ground, collision, and walker videos via Playwright.

    Uses a Node.js subprocess that imports Playwright from the termchart
    node_modules. Returns (plate_bgr, parts_map, ground, coll, video_paths, truth).
    """
    os.makedirs(out_dir, exist_ok=True)

    # write the node driver script
    driver_js = os.path.join(out_dir, '_driver.mjs')
    _write_driver_script(driver_js)

    # start HTTP server from the synth3d directory
    httpd = start_http_server()

    try:
        result = subprocess.run(
            ['node', driver_js],
            capture_output=True, text=True, timeout=300,
            cwd=SYNTH3D_DIR,
            env={**os.environ, 'SYNTH3D_OUT': out_dir,
                 'SYNTH3D_PORT': str(SERVER_PORT),
                 'SYNTH3D_PW': PLAYWRIGHT_PATH}
        )
        if result.returncode != 0:
            print('DRIVER STDERR:', result.stderr[-2000:])
            raise RuntimeError(f'Driver failed with code {result.returncode}')
        print(result.stdout[-1000:])
    finally:
        httpd.shutdown()

    # load outputs
    plate_bgr = cv2.imread(os.path.join(out_dir, 'plate.png'))
    parts_bgr = cv2.imread(os.path.join(out_dir, 'parts.png'))
    ground_bgr = cv2.imread(os.path.join(out_dir, 'ground.png'))
    coll_bgr = cv2.imread(os.path.join(out_dir, 'collision.png'))

    pid_colors = json.load(open(os.path.join(out_dir, 'pid_colors.json')))
    parts_map = decode_parts_image(parts_bgr, pid_colors)
    ground = ground_bgr[:, :, 0] > 127
    coll = coll_bgr[:, :, 0] > 127

    truth = json.load(open(os.path.join(out_dir, 'truth.json')))

    video_paths = sorted(
        [os.path.join(out_dir, f) for f in os.listdir(out_dir)
         if f.startswith('walk') and f.endswith('.mp4')]
    )

    return plate_bgr, parts_map, ground, coll, video_paths, truth


def _write_driver_script(path):
    """Write the Node.js Playwright driver that renders all passes."""
    script = r"""
import { existsSync } from 'fs';
import { writeFileSync, mkdirSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { execSync } from 'child_process';

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT = process.env.SYNTH3D_OUT;
const PORT = process.env.SYNTH3D_PORT || '8321';
const PW_PATH = process.env.SYNTH3D_PW;

const pw = await import('file://' + PW_PATH);
const { chromium } = pw;

const browser = await chromium.launch({ args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1200, height: 675 } });

const errors = [];
page.on('pageerror', e => errors.push(e.message));
page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

const SCENE_URL = `http://127.0.0.1:${PORT}/tools/art-pipeline/synth3d/index.html`;
console.log('Loading scene from', SCENE_URL);
await page.goto(SCENE_URL, { waitUntil: 'networkidle', timeout: 30000 });

// wait for models to load
for (let i = 0; i < 60; i++) {
  const ready = await page.evaluate(() =>
    window.synth3d && window.synth3d._modelsLoaded === true
  );
  if (ready) break;
  await page.waitForTimeout(500);
}

const partCount = await page.evaluate(() => window.synth3d.getPartCount());
console.log('Parts registered:', partCount);

// helper: capture canvas to file
async function captureToFile(filename) {
  const dataUrl = await page.evaluate(() => window.synth3d.getCanvasDataURL());
  const b64 = dataUrl.split(',')[1];
  writeFileSync(resolve(OUT, filename), Buffer.from(b64, 'base64'));
}

// 1. plate (normal mode, no walker)
await page.evaluate(() => { window.synth3d.setMode('normal'); window.synth3d.hideWalker(); window.synth3d.render(); });
await captureToFile('plate.png');
console.log('Captured plate.png');

// 2. parts ID pass
await page.evaluate(() => { window.synth3d.setMode('parts'); window.synth3d.render(); });
await captureToFile('parts.png');
console.log('Captured parts.png');

// 3. ground mask
await page.evaluate(() => { window.synth3d.setMode('ground'); window.synth3d.render(); });
await captureToFile('ground.png');
console.log('Captured ground.png');

// 4. collision mask
await page.evaluate(() => { window.synth3d.setMode('collision'); window.synth3d.render(); });
await captureToFile('collision.png');
console.log('Captured collision.png');

// 5. truth info + pid color table
const partsInfo = await page.evaluate(() => window.synth3d.getPartsInfo());
writeFileSync(resolve(OUT, 'truth.json'), JSON.stringify(partsInfo, null, 2));
const pidColors = await page.evaluate(() => window.synth3d.getPidColors());
writeFileSync(resolve(OUT, 'pid_colors.json'), JSON.stringify(pidColors, null, 2));
console.log('Wrote truth.json + pid_colors.json');

// 6. walker videos — restore normal mode first
await page.evaluate(() => window.synth3d.setMode('normal'));

const PATHS = """ + json.dumps(PATHS) + r""";
const FPS = """ + str(VIDEO_FPS) + r""";
const NFRAMES = """ + str(VIDEO_FRAMES) + r""";

for (let pi = 0; pi < PATHS.length; pi++) {
  const waypoints = PATHS[pi];
  const frames = [];

  for (let f = 0; f < NFRAMES; f++) {
    // interpolate position along waypoints
    const t = f / (NFRAMES - 1) * (waypoints.length - 1);
    const i = Math.min(Math.floor(t), waypoints.length - 2);
    const frac = t - i;
    const x = waypoints[i][0] * (1 - frac) + waypoints[i + 1][0] * frac;
    const z = waypoints[i][1] * (1 - frac) + waypoints[i + 1][1] * frac;

    await page.evaluate(([wx, wz]) => {
      window.synth3d.setWalkerPos(wx, wz);
      window.synth3d.render();
    }, [x, z]);

    // capture frame as PNG data URL
    const dataUrl = await page.evaluate(() =>
      window.synth3d.getCanvasDataURL()
    );
    const b64 = dataUrl.split(',')[1];
    frames.push(Buffer.from(b64, 'base64'));
  }

  // write frames as individual PNGs, then assemble with ffmpeg
  const frameDir = resolve(OUT, `_frames_${pi}`);
  mkdirSync(frameDir, { recursive: true });
  for (let fi = 0; fi < frames.length; fi++) {
    writeFileSync(resolve(frameDir, `frame_${String(fi).padStart(4, '0')}.png`), frames[fi]);
  }

  console.log(`Walk ${pi}: captured ${frames.length} frames`);
}

await page.evaluate(() => { window.synth3d.hideWalker(); });

if (errors.length) {
  console.error('Page errors:', errors.join(' | '));
}

await browser.close();
console.log('DONE');
"""
    with open(path, 'w') as f:
        f.write(script)


def assemble_videos(out_dir):
    """Encode frame sequences to mp4 using OpenCV (no ffmpeg dependency)."""
    video_paths = []
    for pi in range(len(PATHS)):
        frame_dir = os.path.join(out_dir, f'_frames_{pi}')
        if not os.path.isdir(frame_dir):
            continue
        frames_files = sorted(
            f for f in os.listdir(frame_dir) if f.endswith('.png')
        )
        if not frames_files:
            continue

        mp4_path = os.path.join(out_dir, f'walk{pi}.mp4')
        first = cv2.imread(os.path.join(frame_dir, frames_files[0]))
        h, w = first.shape[:2]
        writer = cv2.VideoWriter(
            mp4_path, cv2.VideoWriter_fourcc(*'mp4v'), VIDEO_FPS, (w, h)
        )
        for ff in frames_files:
            frame = cv2.imread(os.path.join(frame_dir, ff))
            writer.write(frame)
        writer.release()
        video_paths.append(mp4_path)
        print(f'Assembled {mp4_path} ({len(frames_files)} frames)')
    return video_paths


def make_gifs(video_paths, out_dir):
    """Create GIFs from the walker videos using veo_walk.to_gif."""
    for mp4 in video_paths:
        base = os.path.splitext(os.path.basename(mp4))[0]
        gif_path = os.path.join(out_dir, f'{base}.gif')
        nf = veo_walk.to_gif(mp4, gif_path, width=640, fps=8)
        print(f'{gif_path}: {nf} gif frames')


def save_parts_npz(parts_map, out_dir):
    """Save the parts map in the npz format expected by estimate()."""
    npz_path = os.path.join(
        SCRIPT_DIR, '_srcmasks_synth3d-parts.npz'
    )
    np.savez_compressed(npz_path, inst=parts_map)
    print(f'Saved parts npz: {npz_path}')
    return npz_path


def make_truth_map(plate_bgr, parts_map, truth, out_dir):
    """Render a truth-class visualization like the 2D bench does."""
    truth_colors = {
        v4.GROUND: (255, 80, 255),
        v4.YSORT: (60, 220, 120),
        v4.OVERHEAD: (80, 160, 255),
    }
    vis = plate_bgr[:, :, ::-1].astype(np.float32) * 0.3
    for pid_str, info in truth.items():
        pid = int(pid_str)
        cls = info['truth']
        color = truth_colors.get(cls, (200, 200, 200))
        mask = parts_map == pid
        if mask.sum() == 0:
            continue
        vis[mask] = vis[mask] * 0.35 + np.array(color, np.float32) * 0.65
    img = Image.fromarray(vis.clip(0, 255).astype(np.uint8))
    path = os.path.join(out_dir, 'truth-map.jpg')
    img.save(path, quality=90)
    print(f'Saved truth-map: {path}')


def score(truth, result, out_dir):
    """Score estimator predictions against ground truth, print confusion."""
    last_iter = [r for r in result['iterations'] if 'skipped' not in r]
    if not last_iter:
        print('ERROR: all iterations skipped')
        return {'errors': ['all iterations skipped']}

    pred = {int(k): v for k, v in last_iter[-1]['layers'].items()}
    conf = {}
    errors = []
    for pid_str, info in truth.items():
        pid = int(pid_str)
        t = info['truth']
        p = pred.get(pid, 'missing')
        conf[(t, p)] = conf.get((t, p), 0) + 1
        acceptable = (
            t == p
            or (t == v4.YSORT and p in (v4.COLLISION, v4.COLLISION_PRIOR))
        )
        if not acceptable:
            errors.append({
                'part': pid, 'truth': t, 'pred': p,
                'votes': result['votes'].get(str(pid), {})
            })

    print('\nconfusion (truth -> pred):')
    for (t, p), n in sorted(conf.items()):
        flag = ''
        ok = (t == p or (t == v4.YSORT and p.startswith('collision')))
        if not ok:
            flag = '  <-- WRONG'
        print(f'  {t:9s} -> {p:15s} {n}{flag}')
    print(f'\nhard errors: {len(errors)}')
    for e in errors:
        print(' ', e)

    score_data = {
        'truth': {str(k): v['truth'] for k, v in truth.items()},
        'pred': {str(k): pred.get(k, 'missing') for k in
                 (int(p) for p in truth)},
        'confusion': {f'{t}->{p}': n for (t, p), n in conf.items()},
        'errors': errors,
        'hard_error_count': len(errors),
    }
    score_path = os.path.join(out_dir, 'synth3d-score.json')
    with open(score_path, 'w') as f:
        json.dump(score_data, f, indent=1)
    print(f'Saved score: {score_path}')
    return score_data


def make_debug_frames(plate_bgr, parts_map, truth, video_paths, out_dir):
    """Generate 4-stage debug frames for 2 interesting walker positions.

    Stages: (1) raw frame, (2) chroma-keyed green, (3) expected box + feet
    dot, (4) occlusion evidence red. Mirrors dbg-*-{1frame,2keyed,3box,4occ}
    from the 2D bench.
    """
    mag = np.array([255, 0, 255], np.int16)
    key_r = v4.KEY_R

    if len(video_paths) < 3:
        print('Not enough videos for debug frames')
        return

    # pick 2 interesting cases:
    # case 1: walker behind a standing object (path 1, mid-frame)
    # case 2: walker under overhead cable (path 3, mid-frame)
    cases = [
        ('behind-crate', video_paths[1], 0.4),
        ('under-cable', video_paths[3], 0.5),
    ]
    for label, mp4, frac in cases:
        cap = cv2.VideoCapture(mp4)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        target = int(total * frac)
        cap.set(cv2.CAP_PROP_POS_FRAMES, target)
        ok, frame = cap.read()
        cap.release()
        if not ok:
            continue
        frame = cv2.resize(frame, (RENDER_W, RENDER_H))

        # stage 1: raw frame
        cv2.imwrite(os.path.join(out_dir, f'dbg-{label}-1frame.png'), frame)

        # stage 2: chroma key (green tint on magenta pixels)
        rgb = frame[:, :, ::-1].astype(np.int16)
        keyed = np.linalg.norm(rgb - mag, axis=2) < key_r
        stage2 = frame.copy()
        stage2[keyed] = [0, 255, 0]
        cv2.imwrite(os.path.join(out_dir, f'dbg-{label}-2keyed.png'), stage2)

        # stage 3: expected bounding box + feet dot
        ys_k, xs_k = np.nonzero(keyed)
        stage3 = frame.copy()
        if len(ys_k) > 0:
            y0, y1 = int(ys_k.min()), int(ys_k.max())
            x0, x1 = int(xs_k.min()), int(xs_k.max())
            cv2.rectangle(stage3, (x0, y0), (x1, y1), (0, 255, 255), 2)
            feet_y = y1
            feet_x = int(np.median(xs_k[ys_k >= y1 - 2]))
            cv2.circle(stage3, (feet_x, feet_y), 5, (0, 0, 255), -1)
        cv2.imwrite(os.path.join(out_dir, f'dbg-{label}-3box.png'), stage3)

        # stage 4: occlusion evidence (red overlay)
        bg_approx = cv2.imread(os.path.join(out_dir, 'plate.png'))
        bg_approx = cv2.resize(bg_approx, (RENDER_W, RENDER_H))
        static_t = v4.STATIC_T
        static_mask = (
            np.abs(frame.astype(np.int16) - bg_approx.astype(np.int16))
            .max(axis=2) < static_t
        )
        stage4 = frame.copy()
        occ_mask = static_mask & ~keyed
        stage4[occ_mask, 2] = np.clip(
            stage4[occ_mask, 2].astype(np.int16) + 80, 0, 255
        ).astype(np.uint8)
        cv2.imwrite(os.path.join(out_dir, f'dbg-{label}-4occ.png'), stage4)

    print(f'Saved debug frames for {len(cases)} cases')


def main():
    os.makedirs(OUT, exist_ok=True)
    print('=== Synth3D Layer Bench ===')

    # render all passes
    print('\n--- Rendering 3D scene ---')
    plate_bgr, parts_map, ground, coll, _, truth = render_scene(OUT)

    # assemble videos from frame sequences
    print('\n--- Assembling videos ---')
    video_paths = assemble_videos(OUT)

    # make GIFs
    print('\n--- Making GIFs ---')
    make_gifs(video_paths, OUT)

    # save parts npz
    save_parts_npz(parts_map, OUT)

    # truth map visualization
    print('\n--- Truth map ---')
    make_truth_map(plate_bgr, parts_map, truth, OUT)

    # debug frames
    print('\n--- Debug frames ---')
    make_debug_frames(plate_bgr, parts_map, truth, video_paths, OUT)

    # run estimator
    print('\n--- Running estimator ---')
    result = v4.estimate(
        parts_map, ground, coll, plate_bgr, video_paths,
        os.path.join(OUT, 'synth3d-layers'),
        view_wh=(RENDER_W, RENDER_H)
    )

    # score
    print('\n--- Scoring ---')
    score_data = score(truth, result, OUT)

    return score_data


if __name__ == '__main__':
    main()
