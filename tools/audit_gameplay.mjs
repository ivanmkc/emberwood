// Gameplay audit: deterministic analysis computed from the REAL game data
// (maps.js / quest.js constants). Reports economy, combat math, travel
// distances and quest-gate structure. Run: node tools/audit_gameplay.mjs
import { MAPS, START, buildGrid } from '../src/maps.js';
import { TILES } from '../src/tiles.js';
import { HEART_PRICE } from '../src/quest.js';

const walk = (ch) => TILES[ch] && !TILES[ch].solid;
const SOLID = new Set(['npc', 'chest', 'sign', 'beacon', 'lockedDoor', 'terminal']);

function bfsDist(map, from, to, doorPasses = true) {
  const grid = buildGrid(map);
  const W = grid[0].length, H = grid.length;
  const blocked = new Set();
  for (const e of map.entities) {
    if (!SOLID.has(e.kind)) continue;
    if (e.kind === 'lockedDoor' && doorPasses) continue;
    if (e.x === to.x && e.y === to.y) continue;
    blocked.add(`${e.x},${e.y}`);
  }
  const dist = { [`${from.x},${from.y}`]: 0 };
  const q = [[from.x, from.y]];
  while (q.length) {
    const [x, y] = q.shift();
    const d = dist[`${x},${y}`];
    if ((Math.abs(x - to.x) + Math.abs(y - to.y)) <= 1) return d + 1;
    for (const [dx, dy] of [[0, 1], [0, -1], [1, 0], [-1, 0]]) {
      const nx = x + dx, ny = y + dy, k = `${nx},${ny}`;
      if (nx < 0 || ny < 0 || nx >= W || ny >= H) continue;
      if (!walk(grid[ny][nx]) || blocked.has(k) || k in dist) continue;
      dist[k] = d + 1;
      q.push([nx, ny]);
    }
  }
  return Infinity;
}

const PLAYER_SPEED_TILES = 72 / 16; // tiles per second

// ---- economy ----
let chestScrap = 0, questScrap = 0;
const cells = [];
for (const map of Object.values(MAPS)) {
  for (const e of map.entities) {
    if (e.kind === 'chest' && e.loot.coins) chestScrap += e.loot.coins;
    if (e.kind === 'chest' && e.loot.shard) cells.push(`${map.id}:${e.id}`);
  }
}
questScrap = 8 + 20 + 10; // Bolt + filter + logs rewards (quest.js effects)
const enemies = Object.values(MAPS).flatMap((m) => m.entities.filter((e) => e.kind === 'enemy'));
const expectedDropScrap = enemies.length * 0.5; // 50% drop 1 scrap
console.log('== ECONOMY');
console.log(` chest scrap: ${chestScrap}   quest rewards: ${questScrap}   expected enemy drops: ~${expectedDropScrap}`);
console.log(` total inflow ~${chestScrap + questScrap + expectedDropScrap} vs sinks: Vitality Module ${HEART_PRICE}`);
const inflow = chestScrap + questScrap + expectedDropScrap;
if (inflow > HEART_PRICE * 3) {
  console.log(` !! SURPLUS ${Math.round(inflow - HEART_PRICE)} scrap with a single ${HEART_PRICE}-scrap sink — economy is trivial`);
}

// ---- combat math ----
console.log('\n== COMBAT (player dmg 1, or 2 with Arc Capacitor; swing ~0.25s cycle)');
const HP = { slime: 2, bat: 1, boss: 10 };
for (const [t, hp] of Object.entries(HP)) {
  console.log(` ${t}: ${hp} hits base / ${Math.ceil(hp / 2)} upgraded; contact dmg 1 vs 3-4 hearts`);
}
console.log(` boss + 2 minions at <=4hp; player heal sources: drops 25%, respawn full`);

// ---- travel ----
console.log('\n== TRAVEL (walk seconds, BFS shortest path, doors open)');
const ow = MAPS.overworld;
const spawn = { x: START.x, y: START.y };
const spots = {
  'spawn -> cave mouth': [ow, spawn, { x: 30, y: 4 }],
  'spawn -> biodome hatch': [ow, spawn, { x: 14, y: 3 }],
  'spawn -> isle cell chest': [ow, spawn, { x: 20, y: 20 }],
  'spawn -> ring sparkle': [ow, spawn, { x: 17, y: 27 }],
  'cave entry -> mine2 door': [MAPS.cave, { x: 12, y: 15 }, { x: 23, y: 2 }],
  'mine2 entry -> filter': [MAPS.mine2, { x: 2, y: 2 }, { x: 3, y: 11 }],
};
for (const [name, [m, f, t]] of Object.entries(spots)) {
  const d = bfsDist(m, f, t);
  const secs = (d / PLAYER_SPEED_TILES).toFixed(0);
  console.log(` ${name}: ${d} tiles (~${secs}s)${d / PLAYER_SPEED_TILES > 45 ? '  !! LONG' : ''}`);
}
// full filter round trip
const trip = bfsDist(ow, spawn, { x: 30, y: 4 })
  + bfsDist(MAPS.cave, { x: 12, y: 15 }, { x: 23, y: 2 })
  + bfsDist(MAPS.mine2, { x: 2, y: 2 }, { x: 3, y: 11 }) * 2
  + bfsDist(MAPS.cave, { x: 22, y: 2 }, { x: 12, y: 16 })
  + bfsDist(ow, { x: 30, y: 5 }, { x: 24, y: 26 });
console.log(` filter quest round trip: ~${trip} tiles (~${(trip / PLAYER_SPEED_TILES / 60).toFixed(1)} min)`);

// ---- death penalty ----
console.log('\n== DEATH: respawn at village spawn, full heal, keep everything');
console.log(` from mine2 depths that is ~${(bfsDist(ow, spawn, { x: 30, y: 4 }) + 40) / PLAYER_SPEED_TILES | 0}s of re-walking — the only real penalty`);

// ---- gates ----
console.log('\n== QUEST GATES');
console.log(' ring -> keycard -> blast door -> {cell 3, mine2(filter, logB)} : single hard gate chain');
console.log(` ember cells: ${cells.join(', ')}`);
console.log(' logs: biodome(A) + mine2(B, behind gate) + home(C) -> Rowan synthesis');
