import { test } from 'node:test';
import assert from 'node:assert/strict';
import { MAPS, START, buildGrid } from '../src/maps.js';
import { TILES } from '../src/tiles.js';

function walkableChar(ch) {
  const t = TILES[ch];
  return t && !t.solid;
}

const SOLID_KINDS = ['npc', 'chest', 'sign', 'beacon', 'lockedDoor', 'terminal', 'charter'];
const SOLID_DECO = ['stall', 'crates', 'vat', 'rack', 'mast', 'rock', 'bush', 'pipe', 'lamp', 'tanktree', 'junction'];

// BFS over a map's grid. Solid entities block, except the target entity.
// opts.doorPasses: treat lockedDoor entities as passable.
function reachable(map, from, to, opts = {}) {
  const grid = buildGrid(map);
  const H = grid.length;
  const W = grid[0].length;
  const blocked = new Set();
  for (const e of map.entities) {
    const isSolidKind = SOLID_KINDS.includes(e.kind);
    if (!isSolidKind) continue;
    if (e.kind === 'lockedDoor' && opts.doorPasses) continue;
    if (e.x === to.x && e.y === to.y) continue; // target itself
    blocked.add(`${e.x},${e.y}`);
  }
  for (const d of map.deco || []) {
    if (SOLID_DECO.includes(d.type) && !(d.x === to.x && d.y === to.y)) {
      blocked.add(`${d.x},${d.y}`);
    }
  }
  const pass = (x, y) =>
    x >= 0 && y >= 0 && x < W && y < H
    && walkableChar(grid[y][x]) && !blocked.has(`${x},${y}`);

  const seen = new Set([`${from.x},${from.y}`]);
  const queue = [[from.x, from.y]];
  while (queue.length) {
    const [x, y] = queue.shift();
    if (x === to.x && y === to.y) return true;
    // adjacency counts for solid targets (you interact from a neighbor tile)
    if (Math.abs(x - to.x) + Math.abs(y - to.y) === 1) return true;
    for (const [dx, dy] of [[0, 1], [0, -1], [1, 0], [-1, 0]]) {
      const nx = x + dx, ny = y + dy;
      if (!pass(nx, ny) || seen.has(`${nx},${ny}`)) continue;
      seen.add(`${nx},${ny}`);
      queue.push([nx, ny]);
    }
  }
  return false;
}

test('every map grid is rectangular and uses only known tiles', () => {
  for (const map of Object.values(MAPS)) {
    const w = map.rows[0].length;
    map.rows.forEach((row, y) => {
      assert.equal(row.length, w, `${map.id} row ${y} has width ${row.length}, expected ${w}`);
      for (const ch of row) assert.ok(TILES[ch], `${map.id} row ${y}: unknown tile '${ch}'`);
    });
    for (const [x, y, ch] of map.decor) {
      assert.ok(TILES[ch], `${map.id} decor unknown tile '${ch}'`);
      assert.ok(y >= 0 && y < map.rows.length && x >= 0 && x < w, `${map.id} decor out of bounds ${x},${y}`);
    }
  }
});

test('map borders are fully solid (no walking off the edge)', () => {
  for (const map of Object.values(MAPS)) {
    const grid = buildGrid(map);
    const H = grid.length, W = grid[0].length;
    for (let x = 0; x < W; x++) {
      for (const y of [0, H - 1]) {
        if (map.portals.some((p) => p.x === x && p.y === y)) continue;
        assert.ok(!walkableChar(grid[y][x]), `${map.id} border open at ${x},${y}`);
      }
    }
    for (let y = 0; y < H; y++) {
      for (const x of [0, W - 1]) {
        if (map.portals.some((p) => p.x === x && p.y === y)) continue;
        assert.ok(!walkableChar(grid[y][x]), `${map.id} border open at ${x},${y}`);
      }
    }
  }
});

test('entities and spawn stand on walkable tiles', () => {
  for (const map of Object.values(MAPS)) {
    const grid = buildGrid(map);
    for (const e of map.entities) {
      assert.ok(walkableChar(grid[e.y][e.x]), `${map.id}/${e.id ?? e.kind} at ${e.x},${e.y} sits on solid tile '${grid[e.y][e.x]}'`);
    }
  }
  const grid = buildGrid(MAPS[START.map]);
  assert.ok(walkableChar(grid[START.y][START.x]), 'spawn tile solid');
});

test('portals: valid targets, walkable both ends, no instant bounce', () => {
  for (const map of Object.values(MAPS)) {
    const grid = buildGrid(map);
    for (const p of map.portals) {
      assert.ok(MAPS[p.to], `${map.id}: portal to unknown map ${p.to}`);
      assert.ok(walkableChar(grid[p.y][p.x]), `${map.id}: portal source ${p.x},${p.y} not walkable`);
      const tgrid = buildGrid(MAPS[p.to]);
      assert.ok(walkableChar(tgrid[p.ty][p.tx]), `${map.id}->${p.to}: arrival ${p.tx},${p.ty} not walkable`);
      assert.ok(
        !MAPS[p.to].portals.some((q) => q.x === p.tx && q.y === p.ty),
        `${map.id}->${p.to}: arrival lands on a portal (infinite bounce)`,
      );
    }
  }
});

test('overworld: all quest points reachable from spawn', () => {
  const map = MAPS.overworld;
  const from = { x: START.x, y: START.y };
  const targets = map.entities
    .filter((e) => ['chest', 'npc', 'sign', 'beacon', 'sparkle', 'terminal', 'item', 'charter'].includes(e.kind))
    .concat(map.portals.map((p) => ({ id: `portal->${p.to}`, ...p })));
  for (const t of targets) {
    assert.ok(reachable(map, from, { x: t.x, y: t.y }), `overworld: ${t.id ?? t.kind} at ${t.x},${t.y} unreachable from spawn`);
  }
});

test('biodome: keeper, terminal, Bolt, chest and exit reachable from hatch', () => {
  const arrival = MAPS.overworld.portals.find((p) => p.to === 'biodome');
  const from = { x: arrival.tx, y: arrival.ty };
  for (const e of MAPS.biodome.entities) {
    assert.ok(reachable(MAPS.biodome, from, { x: e.x, y: e.y }), `biodome: ${e.id} at ${e.x},${e.y} unreachable`);
  }
  const exit = MAPS.biodome.portals[0];
  assert.ok(reachable(MAPS.biodome, from, { x: exit.x, y: exit.y }), 'biodome exit unreachable');
});

test('mine2: filter chest, terminal and loot reachable from gallery entrance', () => {
  const arrival = MAPS.cave.portals.find((p) => p.to === 'mine2');
  const from = { x: arrival.tx, y: arrival.ty };
  for (const e of MAPS.mine2.entities) {
    assert.ok(reachable(MAPS.mine2, from, { x: e.x, y: e.y }), `mine2: ${e.id} at ${e.x},${e.y} unreachable`);
  }
  const exit = MAPS.mine2.portals[0];
  assert.ok(reachable(MAPS.mine2, from, { x: exit.x, y: exit.y }), 'mine2 exit unreachable');
});

test('mine2 entrance is gated behind the locked blast door', () => {
  const caveArrival = MAPS.overworld.portals.find((p) => p.to === 'cave');
  const from = { x: caveArrival.tx, y: caveArrival.ty };
  const toMine2 = MAPS.cave.portals.find((p) => p.to === 'mine2');
  assert.ok(!reachable(MAPS.cave, from, { x: toMine2.x, y: toMine2.y }, { doorPasses: false }),
    'mine2 portal reachable without opening the blast door — gate broken');
  assert.ok(reachable(MAPS.cave, from, { x: toMine2.x, y: toMine2.y }, { doorPasses: true }),
    'mine2 portal unreachable even with the door open');
});

test('home: Mara, archive terminal and chest reachable from doorway', () => {
  const arrival = MAPS.overworld.portals.find((p) => p.to === 'home');
  const from = { x: arrival.tx, y: arrival.ty };
  for (const e of MAPS.home.entities) {
    assert.ok(reachable(MAPS.home, from, { x: e.x, y: e.y }), `home: ${e.id} unreachable`);
  }
  const exit = MAPS.home.portals[0];
  assert.ok(reachable(MAPS.home, from, { x: exit.x, y: exit.y }), 'home exit unreachable');
});

test('deco props sit on walkable tiles (no buried scenery)', () => {
  for (const map of Object.values(MAPS)) {
    const grid = buildGrid(map);
    for (const d of map.deco || []) {
      assert.ok(walkableChar(grid[d.y][d.x]),
        `${map.id}: deco ${d.type} at ${d.x},${d.y} sits on solid tile '${grid[d.y][d.x]}'`);
    }
  }
});

test('solid deco never sits on portals, relay pads or entity tiles', () => {
  const RESERVED = [[40, 28], [31, 7], [31, 8], [40, 27], [30, 5], [30, 6], [30, 7]];
  for (const map of Object.values(MAPS)) {
    for (const d of map.deco || []) {
      if (!SOLID_DECO.includes(d.type)) continue;
      assert.ok(!map.portals.some((p) => p.x === d.x && p.y === d.y),
        `${map.id}: deco ${d.type} blocks portal at ${d.x},${d.y}`);
      assert.ok(!map.entities.some((e) => e.x === d.x && e.y === d.y),
        `${map.id}: deco ${d.type} overlaps entity at ${d.x},${d.y}`);
      if (map.id === 'overworld') {
        assert.ok(!RESERVED.some(([rx, ry]) => rx === d.x && ry === d.y),
          `${map.id}: deco ${d.type} blocks reserved route tile ${d.x},${d.y}`);
      }
    }
  }
});

test('house: elder and chest reachable from arrival point', () => {
  const arrival = MAPS.overworld.portals.find((p) => p.to === 'house');
  const from = { x: arrival.tx, y: arrival.ty };
  for (const e of MAPS.house.entities) {
    assert.ok(reachable(MAPS.house, from, { x: e.x, y: e.y }), `house: ${e.id} unreachable`);
  }
  const exit = MAPS.house.portals[0];
  assert.ok(reachable(MAPS.house, from, { x: exit.x, y: exit.y }), 'house exit unreachable');
});

test('cave: shard chest gated by the locked door, reachable once open', () => {
  const arrival = MAPS.overworld.portals.find((p) => p.to === 'cave');
  const from = { x: arrival.tx, y: arrival.ty };
  const shard = MAPS.cave.entities.find((e) => e.id === 'shard3');
  assert.ok(!reachable(MAPS.cave, from, { x: shard.x, y: shard.y }, { doorPasses: false }),
    'cave: shard3 reachable WITHOUT opening the locked door — gate broken');
  assert.ok(reachable(MAPS.cave, from, { x: shard.x, y: shard.y }, { doorPasses: true }),
    'cave: shard3 unreachable even with the door open');
  const door = MAPS.cave.entities.find((e) => e.kind === 'lockedDoor');
  assert.ok(reachable(MAPS.cave, from, { x: door.x, y: door.y }), 'cave: locked door itself unreachable');
  const exit = MAPS.cave.portals[0];
  assert.ok(reachable(MAPS.cave, from, { x: exit.x, y: exit.y }), 'cave exit unreachable');
});

test('cave: boss and remaining loot reachable with door open', () => {
  const arrival = MAPS.overworld.portals.find((p) => p.to === 'cave');
  const from = { x: arrival.tx, y: arrival.ty };
  for (const e of MAPS.cave.entities) {
    if (e.kind === 'lockedDoor') continue;
    assert.ok(reachable(MAPS.cave, from, { x: e.x, y: e.y }, { doorPasses: true }),
      `cave: ${e.id} unreachable with door open`);
  }
});
