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

Run from tools/art-pipeline (cwd-based sibling imports)::

    cd tools/art-pipeline && python3 synth3d_bench.py
"""
import base64
import http.server
import json
import os
import subprocess
import sys
import threading

import cv2
import numpy as np
from PIL import Image

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))

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
     (-1, 1.8), (5, -3.5), (5, -0.5), (-6, 0.0), (-6, 2.8),
     (-7, -3.5), (-7, -0.5)],
    # Path 3: under cable 1 — walker at z=-2 (in front of cable at z=-3)
    # so walker feet project below the cable's base_y, escaping the
    # +/-10px dead zone in the estimator's front/behind classification.
    [(-10, -2), (-5, -2), (-2, -2), (0, -2), (1, -2), (4, -2), (10, -2)],
    # Path 4: under cable 2 — walker at z=4 (in front of cable at z=3)
    [(-10, 4), (-5, 4), (-3, 4), (0, 4), (5, 4), (10, 4)],
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
    # Path 7: across decals at their z-positions
    # decal1(-2,3), decal2(9,-6), decal3(-5,-3)
    [(-2, 3), (-2, 4.5), (9, -6), (9, -4.5), (-5, -3), (-5, -1.5)],
    # Path 8: focused house.glb coverage at (-7,-2) — walker behind the
    # house at z=-2.5 to z=-2.8 (close enough for screen overlap, far enough
    # to escape the +/-10px dead zone around the house's base_y)
    [(-7, -2.8), (-7, -2.3), (-7, -2.8), (-7, -2.3),
     (-7, -2.8), (-7, -2.3), (-7, -0.5)],
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

const SCENE_URL = `http://127.0.0.1:${PORT}/synth3d/index.html`;
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

// 5b. overhead reachability sweep (screen-space overlap computation)
const reach = await page.evaluate(() => window.synth3d.getOverheadReachability());
writeFileSync(resolve(OUT, 'overhead-reachability.json'), JSON.stringify(reach, null, 2));
console.log('Wrote overhead-reachability.json');

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


def report_overhead_reachability(out_dir):
    """Load and report overhead reachability from the JS scene computation.

    For each overhead part, the scene's getOverheadReachability() swept all
    ground positions and checked if the walker's projected body overlaps
    the part's projected pixels. Parts with zero overlap positions are
    provably irreducible under this camera geometry.
    """
    reach_path = os.path.join(out_dir, 'overhead-reachability.json')
    if not os.path.exists(reach_path):
        print('No overhead-reachability.json — skipping reachability report')
        return
    with open(reach_path) as f:
        reach = json.load(f)
    print('\n--- Overhead reachability (screen-space sweep) ---')
    for pid_str, info in sorted(reach.items(), key=lambda x: int(x[0])):
        status = 'REACHABLE' if info['reachable'] else 'IRREDUCIBLE'
        n = info['overlapCount']
        box = info['partScreenBox']
        print(f'  pid {pid_str}: {status} ({n} overlap positions) '
              f'screen box [{box["x0"]},{box["y0"]}]-[{box["x1"]},{box["y1"]}]')
        if info['reachable'] and info.get('overlapExamples'):
            ex = info['overlapExamples'][0]
            print(f'    example: world ({ex["worldX"]:.1f}, {ex["worldZ"]:.1f}), '
                  f'feet screen y={ex["feetScreenY"]}')


def main():
    """Render the 3D scene, capture walks, and run the estimator via layers_harness."""
    os.makedirs(OUT, exist_ok=True)
    print('=== Synth3D Layer Bench ===')

    print('\n--- Rendering 3D scene ---')
    plate_bgr, parts_map, ground, coll, _, truth = render_scene(OUT)

    print('\n--- Assembling videos ---')
    video_paths = assemble_videos(OUT)

    print('\n--- Making GIFs ---')
    make_gifs(video_paths, OUT)

    npz_path = save_parts_npz(parts_map, OUT)

    print('\n--- Truth map ---')
    make_truth_map(plate_bgr, parts_map, truth, OUT)

    flat_truth = {pid: info['truth'] for pid, info in truth.items()}
    flat_truth_path = os.path.join(OUT, 'truth-harness.json')
    with open(flat_truth_path, 'w') as f:
        json.dump(flat_truth, f, indent=1)

    print('\n--- Running estimator via layers_harness ---')
    harness_result = subprocess.run(
        [sys.executable, os.path.join(SCRIPT_DIR, 'layers_harness.py'),
         '--parts', npz_path,
         '--ground', os.path.join(OUT, 'ground.png'),
         '--collision', os.path.join(OUT, 'collision.png'),
         '--plate', os.path.join(OUT, 'plate.png'),
         '--videos', os.path.join(OUT, 'walk*.mp4'),
         '--out', os.path.join(OUT, 'synth3d-layers'),
         '--truth', flat_truth_path,
         '--view', f'{RENDER_W}x{RENDER_H}'],
        cwd=SCRIPT_DIR, timeout=300,
    )
    if harness_result.returncode != 0:
        raise RuntimeError(f'layers_harness exited {harness_result.returncode}')

    report_overhead_reachability(OUT)

    score_path = os.path.join(OUT, 'synth3d-layers-score.json')
    if os.path.exists(score_path):
        with open(score_path) as f:
            score_data = json.load(f)
        n_errors = len(score_data.get('errors', []))
        print(f'\nHarness score: {n_errors} hard errors')
        return score_data

    print('WARNING: no score file produced by layers_harness')
    return {}


if __name__ == '__main__':
    main()
