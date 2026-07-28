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

const coordsJson = execSync(`cd "${ROOT}" && python3 -c "
import numpy as np, json
from collections import deque
from PIL import Image
import cv2
col = np.asarray(Image.open('assets/rooms/night-bazaar.collision.png').convert('L')) > 127
free = cv2.erode(col.astype(np.uint8), np.ones((17,17),np.uint8)) > 0  # 8x8 LOCAL hitbox = +-8 device px clearance
DH, DW = free.shape
H, W = DH//2, DW//2
grid = free[::2, ::2]
inst = json.load(open('assets/rooms/night-bazaar.instances.json'))
sx, sy = inst['spawn']
def bfs(tx0, ty0, tx1, ty1):
    prev = {}
    q = deque([(sx, sy)])
    seen = {(sx, sy)}
    goal = None
    while q:
        x, y = q.popleft()
        if tx0 <= x <= tx1 and ty0 <= y <= ty1:
            goal = (x, y); break
        for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
            nx, ny = x+dx, y+dy
            if 0 <= nx < W and 0 <= ny < H and (nx,ny) not in seen and grid[ny, nx]:
                seen.add((nx,ny)); prev[(nx,ny)] = (x,y); q.append((nx,ny))
    if goal is None: return None
    path = [goal]
    while path[-1] != (sx, sy):
        path.append(prev[path[-1]])
    path.reverse()
    return path[::20] + [path[-1]]
targets = {}
for e in inst['exits']:
    x0, y0, x1, y1 = e['rect']
    if e['edge']=='n': y1=min(y1,16)
    if e['edge']=='w': x1=min(x1,16)
    if e['edge']=='e': x0=max(x0,624)
    p = bfs(x0,y0,x1,y1)
    targets[e['edge']] = p
print(json.dumps({'spawn':[sx,sy],'paths':{k:(v if v else None) for k,v in targets.items()}}))
"`, { encoding: 'utf-8' }).trim();
const C = JSON.parse(coordsJson);
const routes = Object.entries(C.paths).filter(([, p]) => p);
console.log('routes:', routes.map(([k, p]) => `${k}(${p.length} wp)`).join(', '));
if (routes.length < 3) { console.error('ABORT: BFS route missing'); process.exit(1); }

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
// world-mode offset: player boots at the room spawn in WORLD coords;
// offset = boot position - local spawn maps all local waypoints to world
const bootP = await pos();
const OX = Math.round(bootP.x) - C.spawn[0];
const OY = Math.round(bootP.y) - C.spawn[1];
console.log(`world offset: (${OX},${OY})`);
for (const [edge, path] of routes) {
  await setPos(C.spawn[0] + OX, C.spawn[1] + OY);
  await page.waitForTimeout(150);
  let stuck = 0, budget = path.length * 20;
  for (let wi = 1; wi < path.length && budget > 0 && stuck < 40; ) {
    const [tx0, ty0] = path[wi];
    const tx = tx0 + OX, ty = ty0 + OY;
    const p = await pos();
    const dx = tx - p.x, dy = ty - p.y;
    if (Math.abs(dx) <= 6 && Math.abs(dy) <= 6) { wi++; stuck = 0; continue; }
    const key = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? 'ArrowRight' : 'ArrowLeft')
                                            : (dy > 0 ? 'ArrowDown' : 'ArrowUp');
    await step(key, 110);
    budget--;
    const q = await pos();
    if (Math.abs(q.x - p.x) < 1 && Math.abs(q.y - p.y) < 1) stuck++; else stuck = 0;
  }
  const p = await pos();
  const [gx0, gy0] = path[path.length - 1];
  const gx = gx0 + OX, gy = gy0 + OY;
  const ok = Math.hypot(p.x - gx, p.y - gy) <= 14;
  check(`walk-to-${edge}-exit`, ok, `reached (${Math.round(p.x)},${Math.round(p.y)}) goal (${gx},${gy}), ${path.length} wp`);
  await page.locator('#game').screenshot({ path: `${OUT}/bazaar-${edge}.png` });
}
// blocked check: walking into the noodle stand from below must stop
await setPos(C.spawn[0] + OX, C.spawn[1] + OY);
const before = await pos();
await step('ArrowUp', 2600);
const after = await pos();
check('walls-block', after.y - OY > 120, `y ${Math.round(before.y)} -> ${Math.round(after.y)} (didn't phase through)`);
check('no-page-errors', errors.length === 0, errors.join(' | ') || 'clean');
await browser.close();
const passed = checks.filter(Boolean).length;
console.log(`RESULT ${passed}/${checks.length}`);
process.exit(passed === checks.length ? 0 : 1);
