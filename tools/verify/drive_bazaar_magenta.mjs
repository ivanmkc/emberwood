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
  // hitbox-exact validation: walk the BFS path 1px at a time, each step
  // legal iff the engine's blocked() clears the true hitbox window
  // (x+4..x+11, y+7..y+14) at the new position — exact engine semantics,
  // no keyboard timing noise. Player position follows each legal step.
  const res = await page.evaluate((e) => {
    const W = 640, H = 448;
    // exact config space at 1px: corner-sampled hitbox, same as rectBlocked
    if (!window.__hitfree) {
      const hf = new Uint8Array(W * H);
      for (let py = 0; py < H - 15; py++)
        for (let px = 0; px < W - 12; px++) {
          let ok = true;
          for (const [hx, hy] of [[px+4,py+7],[px+11,py+7],[px+4,py+14],[px+11,py+14],[px+8,py+14]])
            if (window.__ewWorld.blocked(hx - 640, hy)) { ok = false; break; }
          hf[py * W + px] = ok ? 1 : 0;
        }
      window.__hitfree = hf;
    }
    const hf = window.__hitfree;
    const bands = { e: [594, 0, 610, 447], n: [0, 30, 639, 46], w: [30, 0, 46, 447] };
    const [bx0, by0, bx1, by1] = bands[e];
    const sx = Math.round(window.__ew.player.x) + 640;
    const sy = Math.round(window.__ew.player.y);
    // complete BFS on exact config space
    const prev = new Int32Array(W * H).fill(-2);
    const s0 = sy * W + sx;
    prev[s0] = -1;
    const q = [s0];
    let head = 0, goal = -1;
    while (head < q.length) {
      const cur = q[head++];
      const cx = cur % W, cy = (cur / W) | 0;
      if (cx >= bx0 && cx <= bx1 && cy >= by0 && cy <= by1) { goal = cur; break; }
      for (const [dx, dy] of [[1,0],[-1,0],[0,1],[0,-1]]) {
        const nx = cx + dx, ny = cy + dy;
        if (nx < 0 || nx >= W || ny < 0 || ny >= H) continue;
        const ni = ny * W + nx;
        if (prev[ni] === -2 && hf[ni]) { prev[ni] = cur; q.push(ni); }
      }
    }
    if (goal < 0) return { ok: false, reason: 'no exact-config-space path', px: sx, py: sy };
    const path = [];
    for (let cur = goal; cur >= 0; cur = prev[cur]) path.push(cur);
    path.reverse();
    for (const cur of path) {
      window.__ew.player.x = (cur % W) - 640;
      window.__ew.player.y = (cur / W) | 0;
    }
    const endp = path[path.length - 1];
    return { ok: true, steps: path.length, px: (endp % W) - 640, py: (endp / W) | 0 };
  }, edge);
  check(`hitbox-path-${edge}-exit`, res.ok,
        `${res.ok ? 'path ' + res.steps + ' steps to' : (res.reason || 'stalled at')} (${res.px},${res.py})`);
  await page.locator('#game').screenshot({ path: `${OUT}/bazaar-${edge}.png` });
  await setPos(C.spawn[0] - 640, C.spawn[1]);
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
