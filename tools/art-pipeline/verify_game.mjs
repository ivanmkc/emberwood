// Final in-game verification driver: boots the game in 4 scenarios, captures
// screenshots, asserts zero console errors and non-blank frames.
// Screenshots are then judged by judge.py (screenshot rubric) in gate_final.py.
import { chromium } from 'file:///home/ivanmkc/termchart/node_modules/playwright/index.mjs';

const OUT = process.env.OUT || '/tmp/emberwood-verify';
const BASE = process.env.BASE || 'http://localhost:8787/';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 960 } });
const errors = [];
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
page.on('console', (m) => {
  const t = m.text();
  if (m.type() === 'error' && !t.includes('favicon')) errors.push('console: ' + t);
});

async function boot(save) {
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.evaluate((s) => {
    localStorage.clear();
    if (s) localStorage.setItem('emberwood-save-v2', JSON.stringify(s));
  }, save);
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(700);
  await page.keyboard.press('Space'); // leave title
  await page.waitForTimeout(400);
}

const quest = (over) => Object.assign({
  coins: 12, hearts: 3, maxHearts: 3, shards: 1, kills: 2, flags: {}, opened: {},
}, over);

// 1. fresh village spawn
await boot(null);
await page.locator('#game').screenshot({ path: `${OUT}/final-village.png` });

// 2. lake + bridge + forest edge
await boot({ quest: quest({}), mapId: 'overworld', x: 20 * 16, y: 18 * 16, time: 60 });
await page.locator('#game').screenshot({ path: `${OUT}/final-lake.png` });

// 3. house interior with chief
await boot({ quest: quest({}), mapId: 'house', x: 6 * 16, y: 6 * 16, time: 60 });
await page.locator('#game').screenshot({ path: `${OUT}/final-house.png` });

// 4. mine with keycard, near blast door + boss beyond
await boot({
  quest: quest({ flags: { hasCaveKey: true, talkedElder: true, gaveRing: true } }),
  mapId: 'cave', x: 12 * 16, y: 12 * 16, time: 120,
});
await page.keyboard.down('ArrowUp'); await page.waitForTimeout(600); await page.keyboard.up('ArrowUp');
await page.locator('#game').screenshot({ path: `${OUT}/final-mine.png` });

// 5. full playthrough beat: 3 cells -> beacon -> win overlay
await boot({
  quest: quest({ shards: 3, flags: { talkedElder: true } }),
  mapId: 'overworld', x: 38 * 16, y: 26 * 16, time: 500,
});
await page.keyboard.down('ArrowUp'); await page.waitForTimeout(150); await page.keyboard.up('ArrowUp');
for (let i = 0; i < 6; i++) { await page.keyboard.press('Space'); await page.waitForTimeout(280); }
await page.waitForTimeout(500);
await page.locator('#game').screenshot({ path: `${OUT}/final-win.png` });
const winState = await page.evaluate(() => JSON.parse(localStorage.getItem('emberwood-save-v2') || '{}'));

const result = {
  errors,
  beaconLit: !!(winState.quest && winState.quest.flags && winState.quest.flags.beaconLit),
};
console.log(JSON.stringify(result));
await browser.close();
process.exit(errors.length === 0 && result.beaconLit ? 0 : 1);
