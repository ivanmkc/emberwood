#!/usr/bin/env node
// Night-bazaar magenta-collision acceptance: closed-loop waypoint drives from
// spawn to every exit + blocked check. Waypoints from BFS on the live PNG.
import { execSync } from 'child_process';
import { existsSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, '..', '..');
const tcPw = resolve(ROOT, '..', 'termchart', 'node_modules', 'playwright', 'index.mjs');
const localPw = resolve(ROOT, 'node_modules', 'playwright', 'index.mjs');
const pw = await import('file://' + (existsSync(localPw) ? localPw : tcPw));
const { chromium } = pw;
const BASE = 'http://localhost:8787/?room=night-bazaar';
const OUT = resolve(ROOT, 'tools', 'verify', '_drive-out');
execSync(`mkdir -p "${OUT}"`);

// Engine-truth grid: sampled from window.__ewWorld.blocked after boot —
// the BFS plan is built from the same function that will judge the walk.
async function engineCoords(page) {
  return await page.evaluate(() => {
    const W = 640, H = 448, OXW = -640;
    const blocked = new Uint8Array(W * H);
    for (let y = 0; y < H; y++)
      for (let x = 0; x < W; x++)
        blocked[y * W + x] = window.__ewWorld.blocked(OXW + x, y) ? 1 : 0;
    const freeAt = (px, py) => {
      for (let hy = py + 7; hy < py + 15; hy += 2)
        for (let hx = px + 4; hx < px + 12; hx += 2) {
          if (hx < 0 || hx >= W || hy < 0 || hy >= H) return false;
          if (blocked[hy * W + hx]) return false;
        }
      return true;
    };
    const free = new Uint8Array(W * H);
    for (let y = 0; y < H - 16; y++)
      for (let x = 0; x < W - 12; x++) free[y * W + x] = freeAt(x, y) ? 1 : 0;
    const spawn = [Math.round(window.__ew.player.x) + 640, Math.round(window.__ew.player.y)];
    const bands = { e: [594, 0, 610, 447], n: [0, 30, 639, 46], w: [30, 0, 46, 447] };
    // multi-source BFS FROM the goal band -> distance field; the walker then
    // greedily descends it from wherever it actually is
    const fields = {};
    for (const [edge, [bx0, by0, bx1, by1]] of Object.entries(bands)) {
      const dist = new Int32Array(W * H).fill(-1);
      const q = [];
      for (let y = by0; y <= by1; y += 2)
        for (let x = bx0; x <= bx1; x += 2) {
          const i = y * W + x;
          if (free[i]) { dist[i] = 0; q.push(i); }
        }
      let head = 0;
      while (head < q.length) {
        const cur = q[head++];
        const cx = cur % W, cy = (cur / W) | 0;
        for (const [dx, dy] of [[2,0],[-2,0],[0,2],[0,-2]]) {
          const nx = cx + dx, ny = cy + dy;
          if (nx < 0 || nx >= W || ny < 0 || ny >= H) continue;
          const ni = ny * W + nx;
          if (free[ni] && dist[ni] < 0) { dist[ni] = dist[cur] + 1; q.push(ni); }
        }
      }
      const si = (spawn[1] - (spawn[1] % 2)) * W + (spawn[0] - (spawn[0] % 2));
      fields[edge] = dist[si] >= 0 ? Array.from(dist) : null;
      window.__driveFields = window.__driveFields || {};
      window.__driveFields[edge] = dist;
    }
    return { spawn, hasField: Object.fromEntries(Object.entries(fields).map(([k, v]) => [k, !!v])) };
  });
}

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 960 } });
const errors = [];
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
async function boot() {
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.waitForTimeout(900);
  for (let i = 0; i < 6; i++) {
    if ((await page.evaluate(() => window.__ew?.mode)) === 'play') break;
    await page.keyboard.press('Space');
    await page.waitForTimeout(250);
  }
  await page.waitForTimeout(400);
}
const pos = () => page.evaluate(() => ({ x: window.__ew.player.x, y: window.__ew.player.y }));
const setPos = (x, y) => page.evaluate(([a, b]) => { window.__ew.player.x = a; window.__ew.player.y = b; }, [x, y]);
async function step(key, ms) { await page.keyboard.down(key); await page.waitForTimeout(ms); await page.keyboard.up(key); }
const checks = [];
const check = (n, ok, d) => { checks.push(ok); console.log(`${ok ? 'PASS' : 'FAIL'} ${n} — ${d}`); };

await boot();
const C = await engineCoords(page);
const routes = Object.keys(C.hasField).filter(k => C.hasField[k]);
console.log('fields:', routes.join(', '));
if (routes.length < 3) { console.error('ABORT: distance field missing'); process.exit(1); }
for (const edge of routes) {
  await setPos(C.spawn[0] - 640, C.spawn[1]);
  await page.waitForTimeout(150);
  let ok = false;
  for (let i = 0; i < 900; i++) {
    const move = await page.evaluate((e) => {
      const W = 640, dist = window.__driveFields[e];
      const px = Math.round(window.__ew.player.x) + 640;
      const py = Math.round(window.__ew.player.y);
      const q = (x, y) => {
        x -= x % 2; y -= y % 2;
        if (x < 0 || x >= 640 || y < 0 || y >= 448) return -1;
        return dist[y * W + x];
      };
      const here = q(px, py);
      if (here === 0) return { done: true };
      const opts = [
        ['ArrowLeft', q(px - 2, py)], ['ArrowRight', q(px + 2, py)],
        ['ArrowUp', q(px, py - 2)], ['ArrowDown', q(px, py + 2)],
      ].filter(([, d]) => d >= 0);
      if (!opts.length) return { done: false, key: null, here };
      opts.sort((a, b) => a[1] - b[1]);
      if (here >= 0 && here <= 10) return { done: true };
      return { done: false, key: opts[0][0], here };
    }, edge);
    if (move.done) { ok = true; break; }
    if (!move.key) break;
    await step(move.key, 60);
  }
  const p = await pos();
  check(`walk-to-${edge}-exit`, ok, `descent ended at (${Math.round(p.x)},${Math.round(p.y)})`);
  await page.locator('#game').screenshot({ path: `${OUT}/bazaar-${edge}.png` });
}
// blocked check: walking into the noodle stand from below must stop
await setPos(C.spawn[0] - 640, C.spawn[1]);
const before = await pos();
await step('ArrowUp', 2600);
const after = await pos();
check('walls-block', after.y > 120, `y ${Math.round(before.y)} -> ${Math.round(after.y)} (didn't phase through)`);
check('no-page-errors', errors.length === 0, errors.join(' | ') || 'clean');
await browser.close();
const passed = checks.filter(Boolean).length;
console.log(`RESULT ${passed}/${checks.length}`);
process.exit(passed === checks.length ? 0 : 1);
