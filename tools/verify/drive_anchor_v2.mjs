#!/usr/bin/env node
// Coordinate-free anchor-room acceptance drive.
// All test coordinates are computed from the live collision PNG each run —
// no hardcoded rows, no coord staleness.  10 checks, 3 consecutive green = ship.
//
// Usage:  node tools/verify/drive_anchor_v2.mjs [--base URL]
//
// Requires playwright (resolved from termchart/node_modules if missing locally).
import { execSync } from 'child_process';
import { existsSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, '..', '..');

// Resolve playwright — try local, fall back to termchart
let pw;
const localPw = resolve(ROOT, 'node_modules', 'playwright', 'index.mjs');
const tcPw = resolve(ROOT, '..', 'termchart', 'node_modules', 'playwright', 'index.mjs');
if (existsSync(localPw)) {
  pw = await import('file://' + localPw);
} else if (existsSync(tcPw)) {
  pw = await import('file://' + tcPw);
} else {
  console.error('playwright not found'); process.exit(1);
}
const { chromium } = pw;

const baseArg = process.argv.indexOf('--base');
const BASE = baseArg >= 0 ? process.argv[baseArg + 1] : 'http://localhost:8787/?room=anchor';
const OUT = process.env.OUT || resolve(ROOT, 'tools', 'verify', '_drive-out');
execSync(`mkdir -p "${OUT}"`);

// ── Compute coordinates from collision mask ─────────────────────────────
const coordsJson = execSync(`cd "${ROOT}" && python3 -c "
import numpy as np, json
from PIL import Image
col = np.asarray(Image.open('assets/rooms/anchorroom.collision.png').convert('L')) > 127
DH, DW = col.shape
HBH = 4
def hb(lx, ly):
    for hy in range(ly - HBH, ly + HBH + 1):
        for hx in range(lx - HBH, lx + HBH + 1):
            dx, dy = hx * 2, hy * 2
            if not (0 <= dx < DW and 0 <= dy < DH and col[dy, dx]):
                return False
    return True
def wk(ly, s, e):
    step = 1 if e > s else -1
    last = s
    lx = s + step
    while lx != e + step:
        if hb(lx, ly):
            last = lx
        else:
            return last
        lx += step
    return last
# bridge: walk LEFT from x=150 and reach x<70
br = next((ly for ly in range(215, 260) if hb(150, ly) and wk(ly, 150, 30) < 70), None)
# pylon lane: walk RIGHT from x=350 through to x>=440
py = next((ly for ly in range(190, 260) if hb(350, ly) and hb(440, ly) and wk(ly, 350, 440) >= 440), None)
# pylon base: hitbox at x=350 OK but can't reach x=440
pb = next((ly for ly in range(270, 320) if hb(350, ly) and wk(ly, 350, 440) < 410), None)
# tank glass: walk LEFT from x=250 to x<195 (start search at 270 for margin)
tg = next((ly for ly in range(270, 310) if hb(250, ly) and wk(ly, 250, 160) < 195), None)
# tank base: walk LEFT from x=250 and STOP (x>200)
tb = next((ly for ly in range(310, 400) if hb(250, ly) and wk(ly, 250, 160) > 200), None)
print(json.dumps({'br': br, 'py': py, 'pb': pb, 'tg': tg, 'tb': tb}))
"`, { encoding: 'utf-8' }).trim();

const C = JSON.parse(coordsJson);
console.log('COORDS:', JSON.stringify(C));

// Require all coords found — fail fast if the collision is degenerate
const missing = Object.entries(C).filter(([, v]) => v === null).map(([k]) => k);
if (missing.length > 0) {
  console.error(`ABORT: could not find valid coords for: ${missing.join(', ')}`);
  process.exit(1);
}

// ── Playwright setup ────────────────────────────────────────────────────
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 960 } });
const errors = [];
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
page.on('console', (m) => {
  const t = m.text();
  if (m.type() === 'error' && !t.includes('favicon') && !t.includes('404'))
    errors.push('console: ' + t);
});

async function boot() {
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.waitForTimeout(900);
  for (let i = 0; i < 6; i++) {
    const m = await page.evaluate(() => window.__ew?.mode);
    if (m === 'play') break;
    await page.keyboard.press('Space');
    await page.waitForTimeout(250);
  }
  await page.waitForTimeout(600);
}

const pos = () => page.evaluate(() => ({
  x: Math.round(window.__ew.player.x),
  y: Math.round(window.__ew.player.y),
}));
const setPos = (x, y) => page.evaluate(
  ([px, py]) => { window.__ew.player.x = px; window.__ew.player.y = py; },
  [x, y],
);
async function walk(key, ms) {
  await page.keyboard.down(key);
  await page.waitForTimeout(ms);
  await page.keyboard.up(key);
  await page.waitForTimeout(120);
}

const checks = [];
function check(name, ok, detail) {
  checks.push({ name, ok });
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name} — ${detail}`);
}

// ── Checks ──────────────────────────────────────────────────────────────
await boot();

// 1 + 2. Bridge crossing and return
await setPos(150, C.br);
await walk('ArrowLeft', 3200);
let p = await pos();
check('bridge-cross', p.x < 70, `crossed at y=${C.br} to x=${p.x}`);
await page.locator('#game').screenshot({ path: `${OUT}/drive-bridge.png` });
await setPos(50, C.br);
await walk('ArrowRight', 3200);
p = await pos();
check('bridge-cross-back', p.x > 140, `returned to x=${p.x}`);

await boot();

// 3. Pylon walk-behind
await setPos(350, C.py);
await walk('ArrowRight', 2800);
p = await pos();
check('pylon-walk-behind', p.x > 430, `x 350 -> ${p.x} at y=${C.py}`);
await page.locator('#game').screenshot({ path: `${OUT}/drive-pylon.png` });

// 4. Pylon base blocks
await setPos(350, C.pb);
await walk('ArrowRight', 2200);
p = await pos();
check('pylon-base-blocks', p.x < 410, `x 350 -> ${p.x} at y=${C.pb}`);

// 5. Tank glass walk-behind
await setPos(250, C.tg);
await walk('ArrowLeft', 2600);
p = await pos();
check('tank-glass-walk-behind', p.x < 195, `x 250 -> ${p.x} at y=${C.tg}`);
await page.locator('#game').screenshot({ path: `${OUT}/drive-tank.png` });

// 6. Tank base blocks
await setPos(250, C.tb);
await walk('ArrowLeft', 2200);
p = await pos();
check('tank-base-blocks', p.x > 200, `x 250 -> ${p.x} at y=${C.tb}`);

// 7. Deck rail blocks (walk down from bridge deck)
await setPos(100, C.br);
await walk('ArrowDown', 1800);
p = await pos();
check('deck-rail-blocks', p.y < 268, `y ${C.br} -> ${p.y}`);

await boot();

// 8. Exit reachable
await setPos(423, 395);
await walk('ArrowDown', 2500);
p = await pos();
const mapId = await page.evaluate(() => window.__ew.mapId);
check('exit-reachable', p.y > 420 || mapId !== 'anchorroom', `y 395 -> ${p.y}, map=${mapId}`);

// 9. NPCs present
const ents = await page.evaluate(() =>
  window.__ew.entities.filter((e) => e.kind === 'npc' || e.name).length,
);
check('npcs-present', ents >= 3, `${ents} npc-ish entities`);

// 10. Zero console errors
check('zero-console-errors', errors.length === 0, JSON.stringify(errors.slice(0, 3)));

await browser.close();
const fails = checks.filter((c) => !c.ok);
console.log(`\n${checks.length - fails.length}/${checks.length} drive checks passed`);
if (fails.length > 0) {
  console.log('FAILED:', fails.map((c) => c.name).join(', '));
  process.exit(1);
}
