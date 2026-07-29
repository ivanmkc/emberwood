
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

const PATHS = [[[-10, -6], [-5, -6], [0, -6], [5, -6], [10, -6]], [[-10, 8], [-5, 8], [0, 8], [5, 8], [10, 8]], [[-4, -4.8], [-4, -2.5], [2, -3.8], [2, -1.5], [-1, -0.8], [-1, 1.8], [5, -3.5], [5, -0.5], [-6, 0.0], [-6, 2.8], [-7, -3.5], [-7, -0.5]], [[-10, -2], [-5, -2], [-2, -2], [0, -2], [1, -2], [4, -2], [10, -2]], [[-10, 4], [-5, 4], [-3, 4], [0, 4], [5, 4], [10, 4]], [[3, 3.0], [3, 5.5], [6, 1.0], [6, 3.5], [-3, 4.0], [-3, 6.5], [0, 5.0], [0, 7.5]], [[0, 8], [0, 4], [0, 0], [0, -4], [0, -7], [0, -4], [0, 0], [0, 4], [0, 8]], [[-2, 3], [-2, 4.5], [9, -6], [9, -4.5], [-5, -3], [-5, -1.5]], [[-7, -2.8], [-7, -2.3], [-7, -2.8], [-7, -2.3], [-7, -2.8], [-7, -2.3], [-7, -0.5]]];
const FPS = 24;
const NFRAMES = 192;

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
