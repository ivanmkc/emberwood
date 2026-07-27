// Emberwood engine: loop, collision, combat, AI, dialogue, HUD, save.
// Renders at 2x device scale (640x480) with logical 16px tiles; sci-fi PNG
// art from assets/ with procedural pixel-string fallback.

import { TILES, TILE_SIZE as T } from './tiles.js';
import { SPRITES, drawDef } from './sprites.js';
import { MAPS, START, buildGrid } from './maps.js';
import {
  newQuestState, applyEffects, npcDialogue, beaconInteract,
  lockedDoorInteract, sparkleInteract, chestLootLines,
  terminalText, itemPickup, INTRO_LINES, questJournal,
  BASE_PROJECTS, projectStatus, buyProject, rankFor, RANKS, grantXp,
} from './quest.js';
import { createMusic } from './music.js';

const VIEW_W = 320;
const VIEW_H = 240;
const DS = 2; // device scale: canvas is VIEW*DS, art PNGs are authored at 2x
const SAVE_KEY = 'emberwood-save-v2';

const ENEMY_DEFS = {
  slime: { hp: 2, speed: 22, chaseSpeed: 36, aggroR: 90, sprite: 'slime', art: 'sludge', size: 16 },
  bat: { hp: 1, speed: 30, chaseSpeed: 56, aggroR: 110, sprite: 'bat', art: 'drone', size: 16 },
  boss: { hp: 10, speed: 20, chaseSpeed: 30, aggroR: 220, sprite: 'boss', art: 'boss', size: 32 },
};

// map tile char -> art tile name (null = keep procedural)
const TILE_ART = {
  '.': 'ground', ',': 'ground', '#': 'ground', '~': 'coolant', '=': 'walkway',
  's': 'dust', 'M': 'rubble', 'p': 'plate', 'w': 'wallpanel', 'f': 'floorpanel',
  'h': 'ground', 'H': 'ground', 'D': 'ground', 'o': 'plate', 'C': 'rubble',
  'c': 'carpet', 'd': 'minefloor', 'W': 'minewall', 'F': 'ground',
  'V': 'overgrowth', 'G': 'domefloor',
};

const DISPLAY_FONT = '8px PixelDisplay, monospace';

// deco props with physical presence: you cannot walk through the furniture
const PROP_SOLID = new Set(['stall', 'crates', 'vat', 'rack', 'mast', 'rock', 'bush', 'pipe', 'lamp', 'tanktree', 'junction']);

const NPC_ART = {
  elder: 'chief', merchant: 'trader', fisherman: 'angler', villager: 'settler',
  keeper: 'keeper', mara: 'settler',
};

// ---------- sprite/tile canvas cache (procedural fallback art) ----------

function makeCanvas(def, scale = 1) {
  const size = def.art.length;
  const c = document.createElement('canvas');
  c.width = size * scale;
  c.height = size * scale;
  drawDef(c.getContext('2d'), def, 0, 0, scale);
  return c;
}

function buildCaches() {
  const tiles = {};
  for (const [ch, t] of Object.entries(TILES)) tiles[ch] = makeCanvas(t.def);
  const sprites = {};
  const put = (name, def, scale = 1) => { sprites[name] = makeCanvas(def, scale); };
  for (const who of ['player', 'elder', 'merchant', 'fisherman', 'villager']) {
    for (const dir of ['down', 'up', 'left', 'right']) put(`${who}:${dir}`, SPRITES[who][dir]);
  }
  put('slime', SPRITES.slime.idle);
  put('bat', SPRITES.bat.idle);
  put('boss', SPRITES.boss.idle, 2);
  for (const name of ['chestClosed', 'chestOpen', 'sparkle', 'beacon', 'beaconLit',
    'lockedDoor', 'heart', 'coin', 'key', 'shard', 'sign', 'ring']) {
    put(name, SPRITES[name]);
  }
  return { tiles, sprites };
}

// ---------- tiny synth SFX ----------

function createSfx() {
  let ctx = null;
  function beep(freq, dur = 0.08, type = 'square', vol = 0.04, slide = 0) {
    try {
      ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.type = type;
      o.frequency.setValueAtTime(freq, ctx.currentTime);
      if (slide) o.frequency.exponentialRampToValueAtTime(Math.max(30, freq + slide), ctx.currentTime + dur);
      g.gain.setValueAtTime(vol, ctx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + dur);
      o.connect(g).connect(ctx.destination);
      o.start();
      o.stop(ctx.currentTime + dur);
    } catch { /* audio is a garnish, never fatal */ }
  }
  return {
    sword: () => beep(320, 0.07, 'sawtooth', 0.03, -180),
    hit: () => beep(140, 0.1, 'square', 0.05, -60),
    hurt: () => beep(90, 0.18, 'sawtooth', 0.06, -40),
    pickup: () => beep(660, 0.07, 'square', 0.04, 220),
    chest: () => { beep(392, 0.09, 'square', 0.04); setTimeout(() => beep(523, 0.12, 'square', 0.04), 90); },
    talk: () => beep(500, 0.03, 'triangle', 0.03),
    win: () => { [523, 659, 784, 1047].forEach((f, i) => setTimeout(() => beep(f, 0.16, 'triangle', 0.05), i * 130)); },
    die: () => { [300, 240, 180, 120].forEach((f, i) => setTimeout(() => beep(f, 0.14, 'sawtooth', 0.05), i * 110)); },
    open: () => beep(200, 0.2, 'square', 0.05, 90),
  };
}

// ---------- helpers ----------

function aabb(ax, ay, aw, ah, bx, by, bw, bh) {
  return ax < bx + bw && ax + aw > bx && ay < by + bh && ay + ah > by;
}

export function createGame(canvas, input, art) {
  const ctx = canvas.getContext('2d');
  ctx.imageSmoothingEnabled = false;
  const cache = buildCaches();
  const sfx = createSfx();
  const music = createMusic();
  art = art || { tiles: {}, props: {}, chars: {} };

  const HIT = { ox: 4, oy: 7, w: 8, h: 8 }; // hitbox within a 16px logical body

  const g = {
    mode: 'title',
    quest: newQuestState(),
    mapId: START.map,
    grid: null,
    map: null,
    entities: [],
    props: [], // static scenery: trees, houses, rocks, lamps
    drops: [],
    particles: [],
    player: {
      x: START.x * T, y: START.y * T, dir: 'down',
      moving: false, anim: 0, invuln: 0, attack: 0, swing: 0, kx: 0, ky: 0,
    },
    cam: { x: 0, y: 0 },
    dialogue: null,
    afterDialogue: null,
    time: 0,
    deadTimer: 0,
    winShown: false,
    hitStop: 0,
    shake: 0,
    baseSel: 0,
    baseNavT: 0,
    regenT: 0,
  };
  const walkFrames = {}; // dir -> [frameA, frameB] synthesized leg-step canvases

  function stepFrames(im, dir) {
    if (walkFrames[dir]) return walkFrames[dir];
    const w = im.width, h = im.height;
    const legs = Math.round(h * 0.3);
    const mk = (leftUp) => {
      const c = document.createElement('canvas');
      c.width = w;
      c.height = h;
      const cc = c.getContext('2d');
      cc.drawImage(im, 0, 0);
      cc.clearRect(0, h - legs, w, legs);
      const half = Math.floor(w / 2);
      cc.drawImage(im, 0, h - legs, half, legs, 0, h - legs - (leftUp ? 2 : 0), half, legs);
      cc.drawImage(im, half, h - legs, w - half, legs, half, h - legs - (leftUp ? 0 : 2), w - half, legs);
      return c;
    };
    walkFrames[dir] = [mk(true), mk(false)];
    return walkFrames[dir];
  }

  // ---------- persistence ----------

  function save() {
    try {
      localStorage.setItem(SAVE_KEY, JSON.stringify({
        quest: g.quest, mapId: g.mapId, x: g.player.x, y: g.player.y, time: g.time,
      }));
    } catch { /* private mode etc. */ }
  }

  function load() {
    try {
      const raw = localStorage.getItem(SAVE_KEY);
      if (!raw) return false;
      const s = JSON.parse(raw);
      g.quest = Object.assign(newQuestState(), s.quest);
      g.mapId = s.mapId;
      g.time = s.time || 0;
      loadMap(s.mapId, null, null);
      g.player.x = s.x;
      g.player.y = s.y;
      return true;
    } catch { return false; }
  }

  function newGame() {
    g.quest = newQuestState();
    g.time = 0;
    g.winShown = false;
    g.pendingIntro = true;
    loadMap(START.map, START.x, START.y);
    try { localStorage.removeItem(SAVE_KEY); } catch { /* ok */ }
  }

  // ---------- map / entities / props ----------

  function buildProps() {
    g.props = [];
    if (g.map.plate) { // plate rooms: scenery is painted, not synthesized
      g.solidProps = [];
      return;
    }
    const grid = g.grid;
    const H = grid.length, W = grid[0].length;
    // house blocks: connected components of h/H/D -> one facade prop each
    const isHouse = (ch) => ch === 'h' || ch === 'H' || ch === 'D';
    const seen = Array.from({ length: H }, () => new Array(W).fill(false));
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        if (!isHouse(grid[y][x]) || seen[y][x]) continue;
        let x0 = x, x1 = x, y0 = y, y1 = y;
        const stack = [[x, y]];
        seen[y][x] = true;
        while (stack.length) {
          const [cx, cy] = stack.pop();
          x0 = Math.min(x0, cx); x1 = Math.max(x1, cx);
          y0 = Math.min(y0, cy); y1 = Math.max(y1, cy);
          for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
            const nx = cx + dx, ny = cy + dy;
            if (nx >= 0 && ny >= 0 && nx < W && ny < H && isHouse(grid[ny][nx]) && !seen[ny][nx]) {
              seen[ny][nx] = true;
              stack.push([nx, ny]);
            }
          }
        }
        g.props.push({ type: 'house', x: x0 * T, baseY: (y1 + 1) * T, wTiles: x1 - x0 + 1, depot: g.mapId === 'overworld' && x0 >= 40 });
      }
    }
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const ch = grid[y][x];
        if (ch === '#') {
          g.props.push({ type: 'tree', x: x * T + T / 2, baseY: (y + 1) * T, jitter: (x * 31 + y * 17) % 3 });
        } else if (ch === 'M' && (x * 31 + y * 17) % 5 === 0) {
          g.props.push({ type: 'rock', x: x * T + T / 2, baseY: (y + 1) * T });
        }
      }
    }
    for (const d of g.map.deco || []) {
      g.props.push({ type: d.type, x: d.x * T + T / 2, baseY: (d.y + 1) * T });
    }
    for (const [px2, py2, ty2] of g.lateProps || []) {
      g.props.push({ type: ty2, x: px2 * T + T / 2, baseY: (py2 + 1) * T });
    }
    g.lateProps = null;
    g.solidProps = g.props.filter((pr) => PROP_SOLID.has(pr.type));
  }

  function loadMap(id, tx, ty) {
    g.mapId = id;
    g.map = MAPS[id];
    g.grid = buildGrid(g.map);
    g.drops = [];
    g.particles = [];
    g.entities = [];
    for (const e of g.map.entities) {
      if (e.kind === 'sparkle' && (g.quest.flags.hasRing || g.quest.flags.gaveRing)) continue;
      if (e.kind === 'enemy' && e.type === 'boss' && g.quest.flags.bossDefeated) continue;
      if (e.kind === 'lockedDoor' && g.quest.flags.doorOpen) continue;
      if (e.kind === 'item' && e.id === 'petdrone'
          && (g.quest.flags.petFound || g.quest.flags.petReturned)) continue;
      const ent = { ...e, x: e.x * T, y: e.y * T, tx: e.x, ty: e.y };
      if (e.kind === 'enemy') {
        const def = ENEMY_DEFS[e.type];
        Object.assign(ent, {
          hp: def.hp, def, wanderT: 0, wx: 0, wy: 0, kx: 0, ky: 0,
          invuln: 0, lastSwing: -1, anim: Math.random() * 6, minionsSpawned: false,
        });
      }
      g.entities.push(ent);
    }
    // Bolt hovers beside Pip once returned
    if (id === 'overworld' && g.quest.flags.petReturned) {
      g.entities.push({ kind: 'pet', id: 'bolt', x: 36 * T, y: 27 * T, anim: 0 });
    }
    // settlement restoration: built projects reshape the world
    g.dynPortals = [];
    if (id === 'overworld') {
      const f = g.quest.flags;
      if (f.baseLamps) {
        g.lateProps = [[16, 26, 'lamp'], [7, 13, 'lamp'], [43, 28, 'lamp']];
      }
      if (f.baseGreenhouse) {
        (g.lateProps = g.lateProps || []).push([42, 28, 'vat']);
        if (g.quest.hearts < g.quest.maxHearts) {
          g.drops.push({ type: 'heart', x: 42 * T, y: 29 * T });
        }
      }
      if (f.baseRelay) {
        g.dynPortals = [
          { x: 40, y: 28, tx: 31, ty: 8 },
          { x: 31, y: 7, tx: 40, ty: 27 },
        ];
      }
    }
    buildProps();
    if (tx !== null && tx !== undefined) {
      g.player.x = tx * T;
      g.player.y = ty * T;
    }
    updateCamera();
  }

  function tileSolid(tx, ty) {
    if (ty < 0 || ty >= g.grid.length || tx < 0 || tx >= g.grid[0].length) return true;
    const t = TILES[g.grid[ty][tx]];
    return !t || t.solid;
  }

  function entitySolid(e) {
    return e.kind === 'npc' || e.kind === 'chest' || e.kind === 'sign'
      || e.kind === 'beacon' || e.kind === 'lockedDoor' || e.kind === 'terminal'
      || e.kind === 'charter';
  }

  function rectBlocked(x, y, w, h, self) {
    const x0 = Math.floor(x / T), x1 = Math.floor((x + w - 1) / T);
    const y0 = Math.floor(y / T), y1 = Math.floor((y + h - 1) / T);
    for (let ty = y0; ty <= y1; ty++) {
      for (let tx = x0; tx <= x1; tx++) if (tileSolid(tx, ty)) return true;
    }
    for (const e of g.entities) {
      if (e === self || !entitySolid(e)) continue;
      if (aabb(x, y, w, h, e.x + 2, e.y + 2, 12, 12)) return true;
    }
    for (const pr of g.solidProps || []) {
      if (aabb(x, y, w, h, pr.x - 6, pr.baseY - 9, 12, 9)) return true;
    }
    return false;
  }

  function moveBody(b, dx, dy, self) {
    if (dx !== 0) {
      const nx = b.x + dx;
      if (!rectBlocked(nx + HIT.ox, b.y + HIT.oy, HIT.w, HIT.h, self)) b.x = nx;
    }
    if (dy !== 0) {
      const ny = b.y + dy;
      if (!rectBlocked(b.x + HIT.ox, ny + HIT.oy, HIT.w, HIT.h, self)) b.y = ny;
    }
  }

  function moveBoss(b, dx, dy, self) {
    const bx = { x: b.x, y: b.y };
    if (dx !== 0 && !rectBlocked(b.x + dx + 6, b.y + 12, 20, 18, self)) bx.x += dx;
    if (dy !== 0 && !rectBlocked(bx.x + 6, b.y + dy + 12, 20, 18, self)) bx.y += dy;
    b.x = bx.x; b.y = bx.y;
  }

  // ---------- dialogue ----------

  function wrap(text, maxChars = 50) {
    const words = text.split(' ');
    const lines = [];
    let cur = '';
    for (const w of words) {
      if ((cur + ' ' + w).trim().length > maxChars) { lines.push(cur.trim()); cur = w; }
      else cur = cur + ' ' + w;
    }
    if (cur.trim()) lines.push(cur.trim());
    return lines;
  }

  function openDialogue(result, after) {
    // speaker tag: strip a short "Name: " prefix into a name plate
    let speaker = null;
    let lines = result.lines;
    const m = /^([^:]{2,24}): (.+)/.exec(lines[0] || '');
    if (m) {
      speaker = m[1];
      lines = lines.map((l) => (l.startsWith(speaker + ': ') ? l.slice(speaker.length + 2) : l));
    }
    const pages = lines.map((l) => wrap(l));
    if (result.effects) {
      const r0 = rankFor(g.quest.xp || 0);
      applyEffects(g.quest, result.effects);
      const r1 = rankFor(g.quest.xp || 0);
      if (r1 > r0) {
        if (r1 === 4 && !g.quest.flags.bkHeart) {
          g.quest.flags.bkHeart = true;
          g.quest.maxHearts += 1;
          g.quest.hearts = g.quest.maxHearts;
        }
        pages.push(wrap(`RANK UP — ${RANKS[r1].name.toUpperCase()}! ${RANKS[r1].perk}`));
      }
      save();
    }
    g.dialogue = { pages, page: 0, chars: 0, speaker };
    g.mode = 'dialogue';
    g.afterDialogue = after || null;
    sfx.talk();
  }

  function advanceDialogue() {
    const d = g.dialogue;
    const full = d.pages[d.page].join(' ').length;
    if (d.chars < full) { d.chars = full; return; }
    if (d.page < d.pages.length - 1) { d.page += 1; d.chars = 0; sfx.talk(); return; }
    g.dialogue = null;
    g.mode = 'play';
    const after = g.afterDialogue;
    g.afterDialogue = null;
    if (after) after();
  }

  // ---------- interaction / combat ----------

  const DIRV = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] };

  function facingPoint() {
    const [dx, dy] = DIRV[g.player.dir];
    return { x: g.player.x + 8 + dx * 14, y: g.player.y + 11 + dy * 13 };
  }

  function interactTarget() {
    const p = facingPoint();
    for (const e of g.entities) {
      if (!['npc', 'sign', 'chest', 'beacon', 'lockedDoor', 'terminal', 'charter'].includes(e.kind)) continue;
      if (p.x >= e.x && p.x < e.x + 16 && p.y >= e.y && p.y < e.y + 16) return e;
    }
    return null;
  }

  function doInteract(e) {
    if (e.kind === 'npc') {
      // turn to face the player
      const ddx = g.player.x - e.x, ddy = g.player.y - e.y;
      e.face = Math.abs(ddx) > Math.abs(ddy) ? (ddx < 0 ? 'left' : 'right') : (ddy < 0 ? 'up' : 'down');
      openDialogue(npcDialogue(e.id, g.quest));
    } else if (e.kind === 'sign') {
      openDialogue({ lines: e.text });
    } else if (e.kind === 'beacon') {
      const litBefore = g.quest.flags.beaconLit;
      const res = beaconInteract(g.quest);
      openDialogue(res, () => {
        if (!litBefore && g.quest.flags.beaconLit) {
          g.mode = 'win';
          sfx.win();
          save();
        }
      });
    } else if (e.kind === 'lockedDoor') {
      const res = lockedDoorInteract(g.quest);
      openDialogue(res, () => {
        if (g.quest.flags.doorOpen) {
          g.entities = g.entities.filter((x) => x !== e);
          sfx.open();
          save();
        }
      });
    } else if (e.kind === 'charter') {
      g.mode = 'base';
      g.baseSel = 0;
    } else if (e.kind === 'terminal') {
      openDialogue(terminalText(e.id, g.quest));
    } else if (e.kind === 'chest') {
      if (g.quest.opened[e.id]) {
        openDialogue({ lines: ['Empty. You already cleaned it out.'] });
        return;
      }
      g.quest.opened[e.id] = true;
      if (e.loot.coins) g.quest.coins += e.loot.coins;
      if (e.loot.shard) g.quest.shards += 1;
      if (e.loot.item === 'filter') g.quest.flags.filterPart = true;
      sfx.chest();
      save();
      openDialogue({ lines: chestLootLines(e.loot) });
    }
  }

  function swing() {
    g.player.attack = 0.22;
    g.player.swing += 1;
    sfx.sword();
  }

  function attackHitbox() {
    const p = facingPoint();
    const half = rankFor(g.quest.xp) >= 2 ? 13 : 10; // Engineer: long reach
    return { x: p.x - half, y: p.y - half, w: half * 2, h: half * 2 };
  }

  function hurtPlayer(from) {
    if (g.player.invuln > 0 || g.mode !== 'play') return;
    g.quest.hearts -= 1;
    g.player.invuln = 1.0;
    g.hurtFlash = 0.6;
    g.shake = 0.3;
    const ang = Math.atan2(g.player.y - from.y, g.player.x - from.x);
    const kb = rankFor(g.quest.xp) >= 3 ? 55 : 130; // Warden: bulwark
    g.player.kx = Math.cos(ang) * kb;
    g.player.ky = Math.sin(ang) * kb;
    sfx.hurt();
    burst(g.player.x + 8, g.player.y + 8, '#e64539', 6);
    if (g.quest.hearts <= 0) {
      g.mode = 'dead';
      g.deadTimer = 2.0;
      sfx.die();
    }
  }

  function killEnemy(e) {
    g.quest.kills += 1;
    const up = grantXp(g.quest, e.type === 'boss' ? 15 : 2);
    if (up) openDialogue({ lines: [`RANK UP — ${up.name.toUpperCase()}! ${up.perk}`] });
    burst(e.x + e.def.size / 2, e.y + e.def.size / 2, '#f4f4f4', 10);
    const roll = Math.random();
    const dropChance = rankFor(g.quest.xp) >= 1 ? 0.62 : 0.5;
    if (roll < dropChance) g.drops.push({ type: 'coin', x: e.x + e.def.size / 2 - 8, y: e.y + e.def.size / 2 - 8 });
    else if (roll < 0.75) g.drops.push({ type: 'heart', x: e.x + e.def.size / 2 - 8, y: e.y + e.def.size / 2 - 8 });
    if (e.type === 'boss') {
      g.quest.flags.bossDefeated = true;
      save();
    }
    g.entities = g.entities.filter((x) => x !== e);
  }

  function burst(x, y, color, n) {
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2;
      const s = 30 + Math.random() * 50;
      g.particles.push({ x, y, vx: Math.cos(a) * s, vy: Math.sin(a) * s, life: 0.4 + Math.random() * 0.3, color });
    }
  }

  // ---------- update ----------

  function update(dt) {
    g.time += dt;
    if (input.consumeNewGame() && (g.mode === 'win' || g.mode === 'title' || g.mode === 'dead')) {
      newGame();
      g.mode = 'play';
      return;
    }

    if (input.consumeMute()) music.toggle();
    if (g.mode === 'title') {
      if (input.consumeAction()) {
        g.mode = 'play';
        music.start();
        music.setScene(g.mapId);
      }
      return;
    }
    if (g.mode === 'journal') {
      if (input.consumeJournal() || input.consumeAction()) g.mode = 'play';
      return;
    }
    if (g.mode === 'base') {
      g.baseNavT -= dt;
      if (g.baseNavT <= 0) {
        if (input.held.up) { g.baseSel = (g.baseSel + BASE_PROJECTS.length - 1) % BASE_PROJECTS.length; g.baseNavT = 0.18; sfx.talk(); }
        else if (input.held.down) { g.baseSel = (g.baseSel + 1) % BASE_PROJECTS.length; g.baseNavT = 0.18; sfx.talk(); }
      }
      if (input.consumeJournal()) { g.mode = 'play'; return; }
      if (input.consumeAction()) {
        const proj = BASE_PROJECTS[g.baseSel];
        const r0 = rankFor(g.quest.xp || 0);
        const built = buyProject(g.quest, proj.id);
        if (built) {
          sfx.chest();
          save();
          if (built.id === 'baseLamps' || built.id === 'baseGreenhouse' || built.id === 'baseRelay') {
            loadMap(g.mapId, null, null); // rebuild world with the new project
          }
          g.mode = 'play';
          const pages = [built.built];
          if (rankFor(g.quest.xp) > r0) pages.push(`RANK UP — ${RANKS[rankFor(g.quest.xp)].name.toUpperCase()}!`);
          openDialogue({ lines: pages });
        } else {
          sfx.hurt();
        }
      }
      return;
    }
    if (g.mode === 'play' && input.consumeJournal()) {
      g.mode = 'journal';
      return;
    }
    if (g.mode === 'play' && g.pendingIntro) {
      g.pendingIntro = false;
      openDialogue({ lines: INTRO_LINES });
      return;
    }
    if (g.mode === 'dead') {
      g.deadTimer -= dt;
      if (g.deadTimer <= 0) {
        g.quest.hearts = g.quest.maxHearts;
        loadMap(START.map, START.x, START.y);
        save();
        g.mode = 'play';
      }
      return;
    }
    if (g.mode === 'dialogue') {
      g.dialogue.chars += dt * 60;
      if (input.consumeAction()) advanceDialogue();
      return;
    }
    if (g.mode === 'win') {
      if (input.consumeAction()) g.mode = 'play';
      updateParticles(dt);
      return;
    }

    if (g.hitStop > 0) {
      g.hitStop -= dt;
      updateParticles(dt);
      return;
    }
    g.shake = Math.max(0, g.shake - dt * 1.4);

    const p = g.player;

    let dx = 0, dy = 0;
    if (input.held.up) dy -= 1;
    if (input.held.down) dy += 1;
    if (input.held.left) dx -= 1;
    if (input.held.right) dx += 1;
    p.moving = dx !== 0 || dy !== 0;
    if (p.moving && rankFor(g.quest.xp) >= 4 && Math.random() < 0.15) {
      g.particles.push({ x: p.x + 8, y: p.y + 15, vx: (Math.random() - 0.5) * 8, vy: -6,
        life: 0.35, color: Math.random() < 0.5 ? '#ffb347' : '#e05a3a' });
    }
    if (p.moving) {
      if (dy < 0) p.dir = 'up';
      if (dy > 0) p.dir = 'down';
      if (dx < 0) p.dir = 'left';
      if (dx > 0) p.dir = 'right';
      const len = Math.hypot(dx, dy);
      const sp = 72;
      moveBody(p, (dx / len) * sp * dt, (dy / len) * sp * dt, null);
      p.anim += dt * 10;
    }
    if (Math.abs(p.kx) > 1 || Math.abs(p.ky) > 1) {
      moveBody(p, p.kx * dt, p.ky * dt, null);
      p.kx *= Math.pow(0.001, dt);
      p.ky *= Math.pow(0.001, dt);
    }
    p.invuln = Math.max(0, p.invuln - dt);
    p.attack = Math.max(0, p.attack - dt);

    if (input.consumeAction()) {
      const target = interactTarget();
      if (target) doInteract(target);
      else swing();
    }

    if (p.attack > 0.06) {
      const hb = attackHitbox();
      for (const e of [...g.entities]) {
        if (e.kind !== 'enemy' || e.invuln > 0 || e.lastSwing === p.swing) continue;
        const size = e.def.size;
        if (aabb(hb.x, hb.y, hb.w, hb.h, e.x, e.y, size, size)) {
          e.lastSwing = p.swing;
          e.hp -= g.quest.flags.boughtDamage ? 2 : 1;
          e.invuln = 0.25;
          const ang = Math.atan2(e.y - p.y, e.x - p.x);
          e.kx = Math.cos(ang) * 160;
          e.ky = Math.sin(ang) * 160;
          sfx.hit();
          burst(e.x + size / 2, e.y + size / 2, '#fff7d6', 5);
          g.hitStop = 0.04;
          if (e.type === 'boss') g.shake = Math.max(g.shake, 0.18);
          if (e.hp <= 0) {
            g.hitStop = 0.08;
            killEnemy(e);
          }
        }
      }
    }

    for (const e of g.entities) {
      if (e.kind !== 'enemy') continue;
      e.anim += dt * 6;
      e.invuln = Math.max(0, e.invuln - dt);
      const def = e.def;
      const size = def.size;
      const pcx = p.x + 8, pcy = p.y + 11;
      const ecx = e.x + size / 2, ecy = e.y + size / 2;
      const dist = Math.hypot(pcx - ecx, pcy - ecy);

      let vx = 0, vy = 0;
      if (dist < def.aggroR) {
        const inv = dist || 1;
        vx = ((pcx - ecx) / inv) * def.chaseSpeed;
        vy = ((pcy - ecy) / inv) * def.chaseSpeed;
      } else {
        e.wanderT -= dt;
        if (e.wanderT <= 0) {
          e.wanderT = 1 + Math.random() * 1.5;
          const a = Math.random() * Math.PI * 2;
          const go = Math.random() < 0.7;
          e.wx = go ? Math.cos(a) * def.speed : 0;
          e.wy = go ? Math.sin(a) * def.speed : 0;
        }
        vx = e.wx; vy = e.wy;
      }
      vx += e.kx; vy += e.ky;
      e.kx *= Math.pow(0.001, dt);
      e.ky *= Math.pow(0.001, dt);
      if (e.type === 'boss') moveBoss(e, vx * dt, vy * dt, e);
      else moveBody(e, vx * dt, vy * dt, e);

      if (e.type === 'boss' && !e.minionsSpawned && e.hp <= 4) {
        e.minionsSpawned = true;
        for (const off of [[-20, 8], [36, 8]]) {
          g.entities.push({
            kind: 'enemy', id: `minion${Math.random()}`, type: 'slime',
            x: e.x + off[0], y: e.y + off[1],
            hp: ENEMY_DEFS.slime.hp, def: ENEMY_DEFS.slime,
            wanderT: 0, wx: 0, wy: 0, kx: 0, ky: 0, invuln: 0, lastSwing: -1,
            anim: 0, minionsSpawned: true,
          });
        }
        burst(ecx, ecy, '#f2a65a', 14);
      }

      if (aabb(p.x + HIT.ox, p.y + HIT.oy, HIT.w, HIT.h, e.x + 2, e.y + 2, size - 4, size - 4)) {
        hurtPlayer({ x: ecx, y: ecy });
      }
    }

    for (const d of [...g.drops]) {
      if (aabb(p.x + 2, p.y + 4, 12, 12, d.x + 4, d.y + 4, 8, 8)) {
        if (d.type === 'coin') g.quest.coins += 1;
        if (d.type === 'heart') g.quest.hearts = Math.min(g.quest.maxHearts, g.quest.hearts + 1);
        sfx.pickup();
        g.drops = g.drops.filter((x) => x !== d);
      }
    }

    for (const e of [...g.entities]) {
      if (e.kind !== 'sparkle' && e.kind !== 'item') continue;
      if (aabb(p.x + 2, p.y + 4, 12, 12, e.x + 2, e.y + 2, 12, 12)) {
        g.entities = g.entities.filter((x) => x !== e);
        sfx.pickup();
        openDialogue(e.kind === 'sparkle' ? sparkleInteract(g.quest) : itemPickup(e.id));
      }
    }
    // Bolt idles with a happy bob
    for (const e of g.entities) {
      if (e.kind === 'pet') e.anim += dt * 5;
    }

    const ptx = Math.floor((p.x + 8) / T);
    const pty = Math.floor((p.y + 11) / T);
    let warped = false;
    for (const portal of g.dynPortals || []) {
      if (portal.x === ptx && portal.y === pty) {
        burst(p.x + 8, p.y + 8, '#7de8e8', 12);
        p.x = portal.tx * T;
        p.y = portal.ty * T;
        burst(p.x + 8, p.y + 8, '#7de8e8', 12);
        sfx.open();
        save();
        warped = true;
        break;
      }
    }
    if (!warped) {
      for (const portal of g.map.portals) {
        if (portal.x === ptx && portal.y === pty) {
          loadMap(portal.to, portal.tx, portal.ty);
          music.setScene(portal.to);
          save();
          break;
        }
      }
    }

    // Infirmary Wing: slow regen inside the settlement
    if (g.quest.flags.baseInfirmary && g.quest.hearts < g.quest.maxHearts) {
      const tileCh = g.grid[pty] && g.grid[pty][ptx];
      const inSettlement = g.mapId === 'house' || g.mapId === 'home'
        || (g.mapId === 'overworld' && (tileCh === 'p' || tileCh === 'o'));
      if (inSettlement) {
        g.regenT += dt;
        if (g.regenT >= 5) {
          g.regenT = 0;
          g.quest.hearts += 1;
          sfx.pickup();
          burst(p.x + 8, p.y + 4, '#7dd6a8', 5);
        }
      } else g.regenT = 0;
    }

    if (g.quest.flags.beaconLit && g.mapId === 'overworld' && Math.random() < 0.3) {
      const b = g.entities.find((e) => e.kind === 'beacon');
      if (b) {
        g.particles.push({
          x: b.x + 6 + Math.random() * 4, y: b.y + 2,
          vx: (Math.random() - 0.5) * 10, vy: -20 - Math.random() * 15,
          life: 0.5 + Math.random() * 0.4,
          color: ['#ff9e2c', '#e64539', '#f7c948'][Math.floor(Math.random() * 3)],
        });
      }
    }
    updateParticles(dt);
    updateCamera();
  }

  function updateCamera() {
    const mw = g.grid[0].length * T;
    const mh = g.grid.length * T;
    g.cam.x = Math.round(g.player.x + 8 - VIEW_W / 2);
    g.cam.y = Math.round(g.player.y + 8 - VIEW_H / 2);
    if (mw <= VIEW_W) g.cam.x = Math.round((mw - VIEW_W) / 2);
    else g.cam.x = Math.max(0, Math.min(mw - VIEW_W, g.cam.x));
    if (mh <= VIEW_H) g.cam.y = Math.round((mh - VIEW_H) / 2);
    else g.cam.y = Math.max(0, Math.min(mh - VIEW_H, g.cam.y));
  }

  function updateParticles(dt) {
    for (const pt of g.particles) {
      pt.x += pt.vx * dt;
      pt.y += pt.vy * dt;
      pt.life -= dt;
    }
    g.particles = g.particles.filter((pt) => pt.life > 0);
  }

  // ---------- render ----------

  // draw a 2x-authored PNG at logical coords (1 art px = 1 device px)
  function drawArt(img, lx, ly, lw, lh) {
    ctx.drawImage(img, lx, ly, lw ?? img.width / DS, lh ?? img.height / DS);
  }

  // smooth 2D value noise (bilinear over hashed lattice) for macro ground tint
  function vnoise(tx, ty) {
    const h2 = (a, b) => {
      let n = (a * 374761393 + b * 668265263) | 0;
      n = (n ^ (n >> 13)) * 1274126177;
      return ((n ^ (n >> 16)) >>> 0) / 4294967295;
    };
    const cs = 5; // lattice cell size in tiles
    const gx = Math.floor(tx / cs), gy = Math.floor(ty / cs);
    const fx = (tx % cs) / cs, fy = (ty % cs) / cs;
    const a = h2(gx, gy), b = h2(gx + 1, gy), c = h2(gx, gy + 1), d2 = h2(gx + 1, gy + 1);
    const u = fx * fx * (3 - 2 * fx), v = fy * fy * (3 - 2 * fy);
    return a * (1 - u) * (1 - v) + b * u * (1 - v) + c * (1 - u) * v + d2 * u * v;
  }

  const GROUNDY = new Set(['.', ',', 's', 'd', 'G']);

  function tileVariant(name, tx, ty) {
    const v = art.tiles[name];
    if (!v || !v.length) return null;
    return v[(tx * 73 + ty * 151) % v.length];
  }

  function render() {
    ctx.setTransform(DS, 0, 0, DS, 0, 0);
    ctx.imageSmoothingEnabled = false;
    ctx.fillStyle = '#0c0c12';
    ctx.fillRect(0, 0, VIEW_W, VIEW_H);
    if (!g.grid) return;
    // small maps (interiors): fill out-of-bounds with dark rock instead of void
    if (g.grid[0].length * T < VIEW_W || g.grid.length * T < VIEW_H) {
      const wallArt = art.tiles.minewall && art.tiles.minewall[0];
      if (wallArt) {
        ctx.globalAlpha = 0.5;
        for (let vy = 0; vy < VIEW_H; vy += T) {
          for (let vx = 0; vx < VIEW_W; vx += T) drawArt(wallArt, vx, vy, T, T);
        }
        ctx.globalAlpha = 1;
        ctx.fillStyle = 'rgba(6, 8, 14, 0.55)';
        ctx.fillRect(0, 0, VIEW_W, VIEW_H);
      }
    }

    // screen shake: offset the camera itself so every layer moves together
    const shx = Math.round(Math.sin(g.time * 91) * 3 * g.shake);
    const shy = Math.round(Math.cos(g.time * 83) * 3 * g.shake);
    g.cam.x += shx;
    g.cam.y += shy;
    const cx = g.cam.x, cy = g.cam.y;
    const x0 = Math.max(0, Math.floor(cx / T));
    const y0 = Math.max(0, Math.floor(cy / T));
    const x1 = Math.min(g.grid[0].length - 1, Math.ceil((cx + VIEW_W) / T));
    const y1 = Math.min(g.grid.length - 1, Math.ceil((cy + VIEW_H) / T));
    const plateImg = g.map.plate && art.rooms && art.rooms[g.mapId];
    if (plateImg) {
      ctx.drawImage(plateImg, -cx, -cy, g.grid[0].length * T, g.grid.length * T);
    } else
    for (let ty = y0; ty <= y1; ty++) {
      for (let tx = x0; tx <= x1; tx++) {
        const ch = g.grid[ty][tx];
        const lx = tx * T - cx, ly = ty * T - cy;
        const artName = TILE_ART[ch];
        const img = artName ? tileVariant(artName, tx, ty) : null;
        if (img) drawArt(img, lx, ly, T, T);
        else {
          const c = cache.tiles[ch];
          if (c) ctx.drawImage(c, lx, ly);
        }
        // decals over art tiles
        if (g.dynPortals) {
          for (const dp of g.dynPortals) {
            if (dp.x === tx && dp.y === ty) {
              const pu = 0.5 + 0.3 * Math.sin(g.time * 3);
              ctx.strokeStyle = `rgba(125, 232, 232, ${pu})`;
              ctx.lineWidth = 1;
              ctx.strokeRect(lx + 2.5, ly + 2.5, 11, 11);
              ctx.fillStyle = `rgba(125, 232, 232, ${pu * 0.5})`;
              ctx.fillRect(lx + 6, ly + 6, 4, 4);
            }
          }
        }
        if (ch === ',') drawLichen(lx, ly, tx, ty);
        else if (ch === 'o') drawPad(lx, ly);
        else if (ch === 'C') drawCaveMouth(lx, ly);
        else drawClutter(ch, lx, ly, tx, ty);
        // macro tint: large soft patches so fields never read as one texture
        if (GROUNDY.has(ch)) {
          const n = vnoise(tx, ty);
          if (n < 0.35) {
            ctx.fillStyle = `rgba(10, 20, 16, ${(0.35 - n) * 0.4})`;
            ctx.fillRect(lx, ly, T, T);
          } else if (n > 0.68) {
            ctx.fillStyle = `rgba(255, 226, 180, ${(n - 0.68) * 0.22})`;
            ctx.fillRect(lx, ly, T, T);
          }
        }
        // material transitions: dithered blend band where grounds meet —
        // kills the grid-rectangle look at every material boundary
        if (GROUNDY.has(ch) || ch === 'p' || ch === 'f') {
          const nb = (ax, ay) => (g.grid[ay] && g.grid[ay][ax]);
          const diff = (och) => och && och !== ch && och !== '~' && TILES[och] && !TILES[och].solid;
          const dither = (edge) => {
            ctx.fillStyle = 'rgba(8, 14, 16, 0.22)';
            for (let k = 0; k < 8; k++) {
              const off = ((tx * 31 + ty * 17 + k * 7) % 5);
              if (edge === 'l') { ctx.fillRect(lx, ly + k * 2, 1.5 + (off % 2), 1.5); }
              else if (edge === 'r') { ctx.fillRect(lx + T - 1.5 - (off % 2), ly + k * 2, 1.5 + (off % 2), 1.5); }
              else if (edge === 't') { ctx.fillRect(lx + k * 2, ly, 1.5, 1.5 + (off % 2)); }
              else { ctx.fillRect(lx + k * 2, ly + T - 1.5 - (off % 2), 1.5, 1.5 + (off % 2)); }
            }
          };
          if (diff(nb(tx - 1, ty))) dither('l');
          if (diff(nb(tx + 1, ty))) dither('r');
          if (diff(nb(tx, ty - 1))) dither('t');
          if (diff(nb(tx, ty + 1))) dither('b');
        }
        // height illusion: solid masses cast a face-shadow onto the tile
        // below them, and get a lit rim where they meet open ground
        {
          const above = g.grid[ty - 1] && g.grid[ty - 1][tx];
          const MASSY = above === 'M' || above === 'W' || above === 'V' || above === '#';
          if (MASSY && TILES[ch] && !TILES[ch].solid) {
            const grd = ctx.createLinearGradient(0, ly, 0, ly + 7);
            grd.addColorStop(0, 'rgba(5, 8, 12, 0.5)');
            grd.addColorStop(1, 'rgba(5, 8, 12, 0)');
            ctx.fillStyle = grd;
            ctx.fillRect(lx, ly, T, 7);
          }
          const below = g.grid[ty + 1] && g.grid[ty + 1][tx];
          if ((ch === 'M' || ch === 'W' || ch === 'V') && below && TILES[below] && !TILES[below].solid) {
            ctx.fillStyle = 'rgba(0, 0, 0, 0.30)';
            ctx.fillRect(lx, ly + T - 5, T, 5);
            ctx.fillStyle = 'rgba(255, 240, 210, 0.10)';
            ctx.fillRect(lx, ly + T - 6, T, 1);
          }
        }
        if (ch === '~') {
          drawShoreline(lx, ly, tx, ty);
          // drifting ripple highlight
          const ry = (g.time * 4 + ((tx * 7 + ty * 13) % 16)) % 16;
          ctx.fillStyle = 'rgba(120, 220, 220, 0.10)';
          ctx.fillRect(lx + 2 + ((tx * 3) % 5), ly + ry, 9, 1);
        }
      }
    }

    for (const d of g.drops) {
      ctx.drawImage(cache.sprites[d.type === 'coin' ? 'coin' : 'heart'], Math.round(d.x - cx), Math.round(d.y - cy));
    }

    // world drawables, y-sorted by feet/base
    const drawables = [];
    for (const e of g.entities) drawables.push({ sortY: e.y + 16, e });
    for (const pr of g.props) {
      if (pr.x - cx < -80 || pr.x - cx > VIEW_W + 80 || pr.baseY - cy < -20 || pr.baseY - cy > VIEW_H + 120) continue;
      drawables.push({ sortY: pr.baseY, prop: pr });
    }
    drawables.push({ sortY: g.player.y + 16, player: true });
    drawables.sort((a, b) => a.sortY - b.sortY);

    // ground shadows first so no sprite draws under another's shadow
    for (const d of drawables) {
      if (d.player) shadowEllipse(g.player.x + 8 - cx, g.player.y + 15.5 - cy, 6);
      else if (d.prop) {
        if (d.prop.type === 'tree') shadowEllipse(d.prop.x - cx, d.prop.baseY - 1.5 - cy, 10);
        else if (['rock', 'lamp', 'bush', 'crates', 'pipe', 'mast', 'wallchunk', 'stall', 'vat', 'rack'].includes(d.prop.type)) shadowEllipse(d.prop.x - cx, d.prop.baseY - 1 - cy, 7);
      } else if (d.e.kind === 'enemy' || d.e.kind === 'npc' || d.e.kind === 'chest' || d.e.kind === 'beacon') {
        const sz = d.e.kind === 'enemy' ? d.e.def.size : 16;
        shadowEllipse(d.e.x + sz / 2 - cx, d.e.y + sz - 0.5 - cy, sz * 0.42);
      }
    }
    for (const d of drawables) {
      if (d.player) drawPlayer();
      else if (d.prop) drawProp(d.prop);
      else drawEntity(d.e);
    }

    // plate rooms: redraw occluder cells whose base line is south of the
    // player's feet — pixel-exact overdraw cut from the plate itself
    if (plateImg && g.map.baseRows) {
      const pRow = Math.floor((g.player.y + 15) / T);
      const sw = plateImg.width / g.grid[0].length;
      const sh = plateImg.height / g.grid.length;
      for (let ty = y0; ty <= y1; ty++) {
        for (let tx = x0; tx <= x1; tx++) {
          const br = g.map.baseRows[ty][tx];
          if (br >= 0 && br > pRow) {
            ctx.drawImage(plateImg, tx * sw, ty * sh, sw, sh, tx * T - cx, ty * T - cy, T, T);
          }
        }
      }
    }

    if (g.player.attack > 0) {
      const base = { up: -Math.PI / 2, down: Math.PI / 2, left: Math.PI, right: 0 }[g.player.dir];
      const prog = 1 - g.player.attack / 0.22;
      const ax = g.player.x + 8 - cx, ay = g.player.y + 11 - cy;
      ctx.globalCompositeOperation = 'lighter';
      // afterimage trail
      ctx.strokeStyle = 'rgba(90, 190, 220, 0.25)';
      ctx.lineWidth = 4;
      ctx.beginPath();
      ctx.arc(ax, ay, 13, base - 1.1 + Math.max(0, prog - 0.22) * 0.9, base + 0.2 + Math.max(0, prog - 0.22) * 0.9);
      ctx.stroke();
      // glow arc
      ctx.strokeStyle = 'rgba(120, 230, 255, 0.4)';
      ctx.lineWidth = 4;
      ctx.beginPath();
      ctx.arc(ax, ay, 13, base - 1.1 + prog * 0.9, base + 0.2 + prog * 0.9);
      ctx.stroke();
      ctx.globalCompositeOperation = 'source-over';
      // bright core (amber when the Arc Capacitor is fitted)
      ctx.strokeStyle = g.quest.flags.boughtDamage ? 'rgba(255, 214, 140, 0.95)' : 'rgba(235, 255, 255, 0.95)';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(ax, ay, 13, base - 1.1 + prog * 0.9, base + 0.2 + prog * 0.9);
      ctx.stroke();
    }

    for (const pt of g.particles) {
      ctx.fillStyle = pt.color;
      ctx.fillRect(Math.round(pt.x - cx), Math.round(pt.y - cy), 2, 2);
    }

    if (g.map.plate) {
      // plate is pre-graded; only a light vignette
      const vin2 = ctx.createRadialGradient(VIEW_W / 2, VIEW_H / 2, 110, VIEW_W / 2, VIEW_H / 2, 235);
      vin2.addColorStop(0, 'rgba(8, 12, 24, 0)');
      vin2.addColorStop(1, 'rgba(8, 12, 24, 0.3)');
      ctx.fillStyle = vin2;
      ctx.fillRect(0, 0, VIEW_W, VIEW_H);
    } else if (g.map.dark) {
      const px = g.player.x + 8 - cx, py = g.player.y + 11 - cy;
      const grad = ctx.createRadialGradient(px, py, 30, px, py, 110);
      grad.addColorStop(0, 'rgba(6,6,12,0)');
      grad.addColorStop(1, 'rgba(6,6,12,0.93)');
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, VIEW_W, VIEW_H);
      // handheld lamp warmth + hot spots at the blast door and boss core
      ctx.globalCompositeOperation = 'lighter';
      const warm = (lx2, ly2, r, a, col = '255, 170, 90') => {
        const gr2 = ctx.createRadialGradient(lx2, ly2, 1, lx2, ly2, r);
        gr2.addColorStop(0, `rgba(${col}, ${a})`);
        gr2.addColorStop(1, `rgba(${col}, 0)`);
        ctx.fillStyle = gr2;
        ctx.fillRect(lx2 - r, ly2 - r, r * 2, r * 2);
      };
      warm(px, py, 46, 0.14);
      for (const e of g.entities) {
        if (e.kind === 'lockedDoor') warm(e.x + 8 - cx, e.y + 8 - cy, 20, 0.22, '120, 240, 220');
        if (e.kind === 'enemy' && e.type === 'boss') warm(e.x + 16 - cx, e.y + 16 - cy, 34, 0.20);
        if (e.kind === 'chest') warm(e.x + 8 - cx, e.y + 6 - cy, 14, 0.15);
      }
      ctx.globalCompositeOperation = 'source-over';
    } else {
      duskPass(cx, cy, x0, y0, x1, y1);
    }

    g.cam.x -= shx;
    g.cam.y -= shy;
    drawHud();
    if (g.mode === 'dialogue') drawDialogue();
    if (g.mode === 'title') drawTitle();
    if (g.mode === 'dead') drawDead();
    if (g.mode === 'win') drawWin();
    if (g.mode === 'journal') drawJournal();
    if (g.mode === 'base') drawBase();
  }

  function drawBase() {
    overlay(0.8);
    plate(10, 10, VIEW_W - 20, VIEW_H - 26);
    centerText('SETTLEMENT CHARTER', 17, '#ffb347', '10px PixelDisplay, monospace');
    centerText(`scrap available: ${g.quest.coins}`, 30, '#f4e4b8', '6px PixelDisplay, monospace');
    let y = 44;
    BASE_PROJECTS.forEach((proj, i) => {
      const st = projectStatus(g.quest, proj);
      const sel = i === g.baseSel;
      if (sel) {
        ctx.fillStyle = 'rgba(74, 192, 192, 0.10)';
        ctx.fillRect(16, y - 4, VIEW_W - 32, 40);
        text('>', 20, y, '#ffb347', '8px PixelDisplay, monospace');
      }
      const cc = st === 'BUILT' ? '#7dd6a8' : st === 'AVAILABLE' ? '#ffb347' : '#6b7286';
      text(proj.name, 32, y, sel ? '#ffffff' : '#4ac0c0', '7px PixelDisplay, monospace');
      ctx.font = '6px PixelDisplay, monospace';
      const label = st === 'BUILT' ? 'BUILT' : `${proj.cost} SCRAP`;
      const lw2 = ctx.measureText(label).width;
      text(label, VIEW_W - 30 - lw2, y, cc, '6px PixelDisplay, monospace');
      const desc = st === 'BUILT' ? proj.built : proj.desc;
      (desc.match(/.{1,54}( |$)/g) || [desc]).slice(0, 2).forEach((line, li) => {
        text(line.trim(), 32, y + 11 + li * 9, st === 'BUILT' ? '#9a9aa2' : '#c5c9d4');
      });
      y += 44;
    });
    centerText('Up/Down: select    Space: fund    J: close', VIEW_H - 12, '#9a9aa2');
  }

  function drawJournal() {
    overlay(0.78);
    plate(10, 14, VIEW_W - 20, VIEW_H - 34);
    centerText('FIELD JOURNAL', 22, '#ffb347', '10px PixelDisplay, monospace');
    let y = 42;
    for (const [title, status] of questJournal(g.quest)) {
      const done = status.startsWith('done');
      const locked = status.startsWith('locked');
      text(title, 22, y, done ? '#7dd6a8' : '#4ac0c0', '7px PixelDisplay, monospace');
      // status chip, right-aligned
      const chip = done ? 'DONE' : locked ? 'LOCKED' : 'ACTIVE';
      const cc = done ? '#7dd6a8' : locked ? '#6b7286' : '#ffb347';
      ctx.font = '6px PixelDisplay, monospace';
      const cw2 = ctx.measureText(chip).width + 12;
      ctx.fillStyle = 'rgba(0,0,0,0.5)';
      ctx.fillRect(VIEW_W - 24 - cw2, y - 2, cw2, 10);
      ctx.strokeStyle = cc;
      ctx.lineWidth = 0.5;
      ctx.strokeRect(VIEW_W - 24 - cw2 + 0.25, y - 1.75, cw2 - 0.5, 9.5);
      text(chip, VIEW_W - 20 - cw2 + 4, y, cc, '6px PixelDisplay, monospace');
      const wrapped = status.match(/.{1,52}( |$)/g) || [status];
      for (const line of wrapped) {
        y += 10;
        text(line.trim(), 30, y, done ? '#9a9aa2' : '#f4f4f4');
      }
      y += 15;
    }
    centerText('J / Space: close    M: music', VIEW_H - 14, '#9a9aa2');
  }

  // dusk grade + light glows: ambient cool wash, warm pools at lights, vignette
  function duskPass(cx, cy, x0, y0, x1, y1) {
    ctx.fillStyle = g.mapId === 'house' || g.mapId === 'home' ? 'rgba(30, 24, 20, 0.22)'
      : g.mapId === 'biodome' ? 'rgba(18, 48, 40, 0.30)' : 'rgba(18, 34, 54, 0.28)';
    ctx.fillRect(0, 0, VIEW_W, VIEW_H);
    if (g.mapId === 'overworld') {
      // anchor grade: warm dusk light washing in from the upper-left
      const wg = ctx.createLinearGradient(0, 0, VIEW_W, VIEW_H * 0.9);
      wg.addColorStop(0, 'rgba(255, 140, 60, 0.14)');
      wg.addColorStop(0.5, 'rgba(255, 140, 60, 0.04)');
      wg.addColorStop(1, 'rgba(30, 60, 90, 0.10)');
      ctx.fillStyle = wg;
      ctx.fillRect(0, 0, VIEW_W, VIEW_H);
    }

    ctx.globalCompositeOperation = 'lighter';
    // two stacked gradients: wide faint halo + tighter core = soft falloff
    const glow = (lx, ly, r, color, a) => {
      for (const [rr, aa] of [[r * 1.9, a * 0.45], [r, a]]) {
        const gr = ctx.createRadialGradient(lx, ly, 1, lx, ly, rr);
        gr.addColorStop(0, color.replace('A', String(aa)));
        gr.addColorStop(0.55, color.replace('A', String(aa * 0.45)));
        gr.addColorStop(1, color.replace('A', '0'));
        ctx.fillStyle = gr;
        ctx.fillRect(lx - rr, ly - rr, rr * 2, rr * 2);
      }
    };
    for (const pr of g.props) {
      const lx = pr.x - cx, ly = pr.baseY - cy;
      if (lx < -80 || lx > VIEW_W + 80 || ly < -80 || ly > VIEW_H + 80) continue;
      if (pr.type === 'lamp') glow(lx, ly - 26, 34, 'rgba(255, 190, 110, A)', 0.22);
      if (pr.type === 'house') {
        const w = pr.wTiles * T;
        glow(pr.x - cx + w * 0.2, ly - 14, 18, 'rgba(255, 180, 90, A)', 0.16);
        glow(pr.x - cx + w * 0.8, ly - 14, 18, 'rgba(255, 180, 90, A)', 0.16);
      }
    }
    for (const e of g.entities) {
      if (e.kind === 'beacon') {
        const lx = e.x + 8 - cx, ly = e.y + 8 - cy;
        if (g.quest.flags.beaconLit) glow(lx, ly, 60, 'rgba(255, 150, 60, A)', 0.30);
        else glow(lx, ly, 22, 'rgba(255, 170, 80, A)', 0.14); // core embers
      }
    }
    if (g.mapId === 'house' || g.mapId === 'home') {
      // warm interior: hearth glow at room center + doorway light
      const mw = g.grid[0].length * T, mh = g.grid.length * T;
      glow(mw / 2 - cx, mh / 2 - 14 - cy, 64, 'rgba(255, 190, 110, A)', 0.16);
      glow(mw / 2 - cx, mh - 10 - cy, 26, 'rgba(255, 200, 130, A)', 0.12);
    }
    for (const e of g.entities) {
      if (e.kind === 'terminal') glow(e.x + 8 - cx, e.y + 4 - cy, 16, 'rgba(90, 220, 220, A)', 0.16);
      if (e.kind === 'item' || e.kind === 'pet') glow(e.x + 8 - cx, e.y + 6 - cy, 12, 'rgba(90, 230, 240, A)', 0.14);
    }
    // faint coolant shimmer
    for (let ty = y0; ty <= y1; ty++) {
      for (let tx = x0; tx <= x1; tx++) {
        if (g.grid[ty][tx] === '~' && (tx + ty) % 3 === 0) {
          glow(tx * T + 8 - cx, ty * T + 8 - cy, 18, 'rgba(40, 200, 200, A)', 0.09);
        }
      }
    }
    ctx.globalCompositeOperation = 'source-over';

    // ambient drifting motes: spores over the world, embers near the plaza
    for (let i = 0; i < 12; i++) {
      const seed = i * 211.7;
      const mx = ((seed * 13 + g.time * (4 + (i % 3) * 2)) % (VIEW_W + 40)) - 20;
      const my = ((seed * 7 + Math.sin(g.time * 0.4 + i) * 18 + i * 37) % (VIEW_H + 30)) - 15;
      ctx.fillStyle = i % 4 === 0 ? 'rgba(255, 200, 120, 0.20)' : 'rgba(140, 230, 220, 0.16)';
      ctx.fillRect(mx, my, 1.5, 1.5);
    }
    const vin = ctx.createRadialGradient(VIEW_W / 2, VIEW_H / 2, 100, VIEW_W / 2, VIEW_H / 2, 230);
    vin.addColorStop(0, 'rgba(8, 12, 24, 0)');
    vin.addColorStop(1, 'rgba(8, 12, 24, 0.34)');
    ctx.fillStyle = vin;
    ctx.fillRect(0, 0, VIEW_W, VIEW_H);
  }

  // deterministic environmental clutter: cables, stains, vents, cracks —
  // Eastward-density detail without touching map data or collision
  function drawClutter(ch, lx, ly, tx, ty) {
    const h = ((tx * 2654435761) ^ (ty * 40503)) >>> 0;
    if (ch === '.' || ch === 's' || ch === 'd') {
      if (h % 6 === 1) { // grass/grit tufts
        ctx.fillStyle = ch === '.' ? 'rgba(30, 60, 40, 0.55)' : 'rgba(60, 52, 40, 0.5)';
        const bx3 = lx + (h % 10) + 2, by3 = ly + ((h >> 4) % 10) + 3;
        ctx.fillRect(bx3, by3, 1, 3);
        ctx.fillRect(bx3 + 2, by3 + 1, 1, 2);
        ctx.fillRect(bx3 - 2, by3 + 1, 1, 2);
      }
      if (h % 7 === 0) {
        ctx.fillStyle = 'rgba(0,0,0,0.18)';
        ctx.fillRect(lx + (h % 9), ly + ((h >> 3) % 10), 3, 2);
        ctx.fillRect(lx + ((h >> 5) % 11), ly + ((h >> 7) % 12), 2, 2);
      }
      if (h % 9 === 3) { // half-buried cable
        ctx.strokeStyle = 'rgba(20, 26, 34, 0.55)';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(lx, ly + 6 + (h % 6));
        ctx.quadraticCurveTo(lx + 8, ly + 2 + (h % 9), lx + 16, ly + 7 + ((h >> 4) % 6));
        ctx.stroke();
        ctx.fillStyle = 'rgba(80, 240, 220, 0.5)';
        ctx.fillRect(lx + 7, ly + 4 + (h % 7), 1.5, 1.5);
      }
      if (h % 13 === 5) { // scattered scrap glint
        ctx.fillStyle = 'rgba(200, 170, 90, 0.4)';
        ctx.fillRect(lx + (h % 12), ly + ((h >> 2) % 12), 2, 1.5);
      }
    } else if (ch === 'p' || ch === 'f') {
      if (h % 6 === 0) { // stain
        ctx.fillStyle = 'rgba(0,0,0,0.13)';
        ctx.beginPath();
        ctx.ellipse(lx + 4 + (h % 8), ly + 4 + ((h >> 3) % 8), 4, 2.5, 0, 0, 7);
        ctx.fill();
      }
      if (h % 17 === 2) { // vent grate
        ctx.fillStyle = 'rgba(0,0,0,0.3)';
        for (let i = 0; i < 3; i++) ctx.fillRect(lx + 4, ly + 5 + i * 3, 8, 1);
      }
      if (h % 23 === 7) { // hazard chevron corner
        ctx.fillStyle = 'rgba(240, 200, 80, 0.35)';
        ctx.fillRect(lx + 1, ly + 1, 5, 2);
        ctx.fillRect(lx + 1, ly + 1, 2, 5);
      }
    } else if (ch === '~') {
      if (h % 11 === 0) { // drifting flotsam speck
        ctx.fillStyle = 'rgba(10, 30, 36, 0.5)';
        ctx.fillRect(lx + (h % 12), ly + ((h >> 4) % 12), 3, 1.5);
      }
    } else if (ch === 'w') {
      if (h % 4 !== 0) return; // wall shelf with supplies (interiors)
      ctx.fillStyle = '#5c4a38';
      ctx.fillRect(lx + 2, ly + 9, 12, 2);
      const cols = ['#b06a4a', '#4a7d8d', '#c9a24a', '#6a8d4a'];
      ctx.fillStyle = cols[h % 4];
      ctx.fillRect(lx + 3, ly + 5, 4, 4);
      ctx.fillStyle = cols[(h >> 3) % 4];
      ctx.fillRect(lx + 9, ly + 4, 4, 5);
    }
  }

  // waterline + foam where coolant meets land — kills the hard rectangle edge
  function drawShoreline(lx, ly, tx, ty) {
    const land = (ax, ay) => {
      if (ay < 0 || ay >= g.grid.length || ax < 0 || ax >= g.grid[0].length) return false;
      const ch2 = g.grid[ay][ax];
      return ch2 !== '~' && TILES[ch2] && !TILES[ch2].solid || ch2 === '=';
    };
    ctx.fillStyle = 'rgba(8, 22, 28, 0.55)';
    const foam = 'rgba(150, 230, 230, 0.4)';
    const h = (tx * 7 + ty * 13) % 5;
    if (land(tx - 1, ty)) {
      ctx.fillRect(lx, ly, 2, 16);
      ctx.fillStyle = foam;
      ctx.fillRect(lx + 2, ly + 3 + h, 1.5, 3);
      ctx.fillStyle = 'rgba(8, 22, 28, 0.55)';
    }
    if (land(tx + 1, ty)) {
      ctx.fillRect(lx + 14, ly, 2, 16);
      ctx.fillStyle = foam;
      ctx.fillRect(lx + 12.5, ly + 6 + h, 1.5, 3);
      ctx.fillStyle = 'rgba(8, 22, 28, 0.55)';
    }
    if (land(tx, ty - 1)) {
      ctx.fillRect(lx, ly, 16, 2);
      ctx.fillStyle = foam;
      ctx.fillRect(lx + 4 + h, ly + 2, 3, 1.5);
      ctx.fillStyle = 'rgba(8, 22, 28, 0.55)';
    }
    if (land(tx, ty + 1)) {
      ctx.fillRect(lx, ly + 14, 16, 2);
      ctx.fillStyle = foam;
      ctx.fillRect(lx + 8 - h, ly + 12.5, 3, 1.5);
    }
  }

  function shadowEllipse(cx2, cy2, w) {
    ctx.fillStyle = 'rgba(8, 16, 22, 0.35)';
    ctx.beginPath();
    ctx.ellipse(cx2, cy2, w, w * 0.32, 0, 0, 7);
    ctx.fill();
  }

  function drawLichen(lx, ly, tx, ty) {
    const n = (tx * 7 + ty * 13) % 4;
    ctx.fillStyle = 'rgba(80, 240, 220, 0.75)';
    ctx.fillRect(lx + 4 + n, ly + 5, 2, 2);
    ctx.fillRect(lx + 10 - n, ly + 11, 2, 2);
    ctx.fillRect(lx + 7, ly + 8 + n, 1, 1);
  }

  function drawPad(lx, ly) {
    const pulse = 0.45 + 0.3 * Math.sin(g.time * 2.5 + lx * 0.3 + ly * 0.2);
    ctx.strokeStyle = `rgba(255, 190, 110, ${pulse})`;
    ctx.lineWidth = 1;
    ctx.strokeRect(lx + 2.5, ly + 2.5, 11, 11);
    ctx.fillStyle = `rgba(255, 190, 110, ${pulse * 0.55})`;
    ctx.fillRect(lx + 6, ly + 6, 4, 4);
  }

  function drawCaveMouth(lx, ly) {
    ctx.fillStyle = '#0a0a10';
    ctx.beginPath();
    ctx.moveTo(lx + 1, ly + 16);
    ctx.lineTo(lx + 1, ly + 6);
    ctx.quadraticCurveTo(lx + 8, ly - 2, lx + 15, ly + 6);
    ctx.lineTo(lx + 15, ly + 16);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = 'rgba(90, 220, 220, 0.5)';
    ctx.fillRect(lx + 3, ly + 7, 2, 2);
  }

  function drawProp(pr) {
    const cxx = g.cam.x, cyy = g.cam.y;
    if (pr.type === 'tree') {
      const img = (pr.jitter % 2 === 1 && art.props.tree2) || art.props.tree;
      if (img) {
        const w = img.width / DS, h = img.height / DS;
        drawArt(img, Math.round(pr.x - w / 2 - cxx + (pr.jitter - 1) * 2), Math.round(pr.baseY - h - cyy));
      } else {
        ctx.drawImage(cache.tiles['#'], Math.round(pr.x - 8 - cxx), Math.round(pr.baseY - 16 - cyy));
      }
    } else if (pr.type === 'house') {
      const img = (pr.depot && art.props.garage) || art.props.house;
      const wL = pr.wTiles * T;
      if (img) {
        const hL = (img.height / img.width) * wL;
        drawArt(img, Math.round(pr.x - cxx), Math.round(pr.baseY - hL - cyy), wL, hL);
      }
    } else if (pr.type === 'rock') {
      const img = art.props.rock;
      if (img) drawArt(img, Math.round(pr.x - img.width / DS / 2 - cxx), Math.round(pr.baseY - img.height / DS - cyy));
    } else if (pr.type === 'lamp') {
      const img = art.props.lamp;
      if (img) drawArt(img, Math.round(pr.x - img.width / DS / 2 - cxx), Math.round(pr.baseY - img.height / DS - cyy));
    } else {
      const img = art.props[pr.type];
      if (img) drawArt(img, Math.round(pr.x - img.width / DS / 2 - cxx), Math.round(pr.baseY - img.height / DS - cyy));
    }
  }

  function drawEntity(e) {
    const cx = g.cam.x, cy = g.cam.y;
    let img = null;
    let dy = 0;
    if (e.kind === 'npc') {
      const a = art.chars[NPC_ART[e.id]];
      const im = a && ((e.face && a[e.face]) || a.down || a);
      if (im && im.width) {
        drawCharArt(im, e.x, e.y);
        return;
      }
      img = cache.sprites[`${e.sprite}:${e.face || 'down'}`] || cache.sprites[`${e.sprite}:down`];
    } else if (e.kind === 'sign') img = cache.sprites.sign;
    else if (e.kind === 'beacon') {
      const im = art.props.beacon;
      if (im) {
        const w = im.width / DS, h = im.height / DS;
        const bx2 = Math.round(e.x + 8 - w / 2 - cx), by2 = Math.round(e.y + 16 - h - cy);
        drawArt(im, bx2, by2);
        ctx.globalCompositeOperation = 'lighter';
        if (g.quest.flags.beaconLit) {
          // living core pulse
          const a2 = 0.25 + 0.15 * Math.sin(g.time * 5);
          const gr2 = ctx.createRadialGradient(bx2 + w / 2, by2 + h * 0.45, 1, bx2 + w / 2, by2 + h * 0.45, 12);
          gr2.addColorStop(0, `rgba(255, 200, 90, ${a2})`);
          gr2.addColorStop(1, 'rgba(255, 200, 90, 0)');
          ctx.fillStyle = gr2;
          ctx.fillRect(bx2, by2, w, h);
        } else if (Math.floor(g.time * 1.2) % 4 === 0) {
          // cold beacon: slow red distress blink
          ctx.fillStyle = 'rgba(230, 60, 50, 0.7)';
          ctx.fillRect(bx2 + w / 2 - 1, by2 + 2, 2, 2);
        }
        ctx.globalCompositeOperation = 'source-over';
        return;
      }
      img = cache.sprites[g.quest.flags.beaconLit ? 'beaconLit' : 'beacon'];
    } else if (e.kind === 'lockedDoor') img = cache.sprites.lockedDoor;
    else if (e.kind === 'terminal') {
      const im = art.props.terminal;
      if (im) {
        const w = im.width / DS, h = im.height / DS;
        drawArt(im, Math.round(e.x + 8 - w / 2 - cx), Math.round(e.y + 16 - h - cy));
        return;
      }
      img = cache.sprites.sign;
    } else if (e.kind === 'item' || e.kind === 'pet') {
      const im = art.chars.petdrone;
      const bob = Math.round(Math.sin((e.anim ?? g.time * 4)) * 2);
      if (e.id === 'petdrone' || e.kind === 'pet') {
        if (im && im.width) {
          const w = im.width / DS, h = im.height / DS;
          drawArt(im, Math.round(e.x + 8 - w / 2 - cx), Math.round(e.y + 12 - h - cy + bob));
          return;
        }
        img = cache.sprites.sparkle;
      } else img = cache.sprites.sparkle;
    } else if (e.kind === 'sparkle') {
      img = cache.sprites.sparkle;
      dy = Math.floor(g.time * 4) % 2 === 0 ? 0 : -1;
    } else if (e.kind === 'chest') {
      const im = art.props.chest;
      if (im) {
        const opened = g.quest.opened[e.id];
        if (opened) ctx.filter = 'brightness(0.75)';
        const w = im.width / DS, h = im.height / DS;
        const chx = Math.round(e.x + 8 - w / 2 - cx), chy = Math.round(e.y + 16 - h - cy);
        drawArt(im, chx, chy);
        ctx.filter = 'none';
        if (opened) { // gaping empty slot: clearly looted
          ctx.fillStyle = 'rgba(4, 6, 10, 0.85)';
          ctx.fillRect(chx + 2, chy + 3, w - 4, 4);
        }
        return;
      }
      img = cache.sprites[g.quest.opened[e.id] ? 'chestOpen' : 'chestClosed'];
    } else if (e.kind === 'enemy') {
      if (e.invuln > 0 && Math.floor(e.invuln * 20) % 2 === 0) return;
      const im = art.chars[e.def.art];
      dy = Math.round(Math.sin(e.anim) * (e.type === 'bat' ? 3 : 1));
      if (im && im.width) {
        let w = im.width / DS, h = im.height / DS;
        let jx = 0;
        if (e.type === 'slime' || e.type === 'boss') {
          // sludge squash & stretch, volume-ish preserved
          const s = 1 + Math.sin(e.anim * (e.type === 'boss' ? 1.4 : 2.2)) * 0.06;
          w *= 2 - s;
          h *= s;
          dy = 0;
        } else if (e.type === 'bat') {
          jx = Math.round(Math.sin(e.anim * 9)); // rotor jitter
        }
        drawArt(im, Math.round(e.x + e.def.size / 2 - w / 2 - cx + jx), Math.round(e.y + e.def.size - h - cy + dy), w, h);
        return;
      }
      img = cache.sprites[e.def.sprite];
    }
    if (img) ctx.drawImage(img, Math.round(e.x - cx), Math.round(e.y - cy + dy));
  }

  function drawCharArt(im, ex, ey, bob = 0) {
    const w = im.width / DS, h = im.height / DS;
    drawArt(im, Math.round(ex + 8 - w / 2 - g.cam.x), Math.round(ey + 16 - h - g.cam.y + bob));
  }

  function drawPlayer() {
    const p = g.player;
    if (p.invuln > 0 && Math.floor(p.invuln * 14) % 2 === 0) return;
    const a = art.chars.player;
    if (a && a[p.dir]) {
      if (p.moving) {
        const frames = stepFrames(a[p.dir], p.dir);
        drawCharArt(frames[Math.floor(p.anim * 0.9) % 2], p.x, p.y, 0);
      } else {
        drawCharArt(a[p.dir], p.x, p.y, 0);
      }
      return;
    }
    const bob = p.moving ? Math.round(Math.sin(p.anim) * 1) : 0;
    ctx.drawImage(cache.sprites[`player:${p.dir}`], Math.round(p.x - g.cam.x), Math.round(p.y - g.cam.y + bob));
  }

  function text(str, x, y, color = '#f4f4f4', font = '8px monospace') {
    ctx.font = font;
    ctx.textBaseline = 'top';
    ctx.fillStyle = '#0c0c12';
    ctx.fillText(str, x + 1, y + 1);
    ctx.fillStyle = color;
    ctx.fillText(str, x, y);
  }

  function plate(x, y, w, h) {
    ctx.fillStyle = 'rgba(10, 14, 22, 0.72)';
    ctx.fillRect(x, y, w, h);
    ctx.strokeStyle = 'rgba(74, 192, 192, 0.35)';
    ctx.lineWidth = 1;
    ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
    ctx.fillStyle = 'rgba(74, 192, 192, 0.5)';
    ctx.fillRect(x, y, 3, 1);
    ctx.fillRect(x, y, 1, 3);
    ctx.fillRect(x + w - 3, y + h - 1, 3, 1);
    ctx.fillRect(x + w - 1, y + h - 3, 1, 3);
  }

  function drawHud() {
    // left plate: vitality + scrap
    const lw = 14 + g.quest.maxHearts * 11;
    plate(4, 4, Math.max(lw, 58), 30);
    for (let i = 0; i < g.quest.maxHearts; i++) {
      ctx.globalAlpha = i < g.quest.hearts ? 1 : 0.22;
      ctx.drawImage(cache.sprites.heart, 6 + i * 11, 2);
    }
    ctx.globalAlpha = 1;
    ctx.drawImage(cache.sprites.coin, 6, 15);
    text(`${g.quest.coins}`, 21, 20, '#f4e4b8', '8px PixelDisplay, monospace');
    const rk = rankFor(g.quest.xp || 0);
    text(`R${rk + 1}`, Math.max(46, 14 + g.quest.maxHearts * 11 - 16), 20, '#8fd0d0', '6px PixelDisplay, monospace');

    // right plate: cell sockets + key items
    const rw = 62;
    plate(VIEW_W - rw - 4, 4, rw, 30);
    for (let i = 0; i < 3; i++) {
      const sx = VIEW_W - rw + i * 17;
      ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
      ctx.fillRect(sx, 7, 13, 13);
      ctx.strokeStyle = i < g.quest.shards ? 'rgba(255, 170, 80, 0.7)' : 'rgba(120, 130, 150, 0.18)';
      ctx.lineWidth = 1;
      ctx.strokeRect(sx + 0.5, 7.5, 12, 12);
      if (i < g.quest.shards) ctx.drawImage(cache.sprites.shard, sx - 2, 5);
    }
    let kx = VIEW_W - rw + 1;
    if (g.quest.flags.hasRing && !g.quest.flags.gaveRing) { ctx.drawImage(cache.sprites.ring, kx, 17); kx += 13; }
    if (g.quest.flags.hasCaveKey) ctx.drawImage(cache.sprites.key, kx, 17);

    // hurt feedback: red edge pulse
    if (g.hurtFlash > 0) {
      g.hurtFlash = Math.max(0, g.hurtFlash - 0.02);
      const hv = ctx.createRadialGradient(VIEW_W / 2, VIEW_H / 2, 90, VIEW_W / 2, VIEW_H / 2, 210);
      hv.addColorStop(0, 'rgba(200, 40, 40, 0)');
      hv.addColorStop(1, `rgba(200, 40, 40, ${g.hurtFlash * 0.6})`);
      ctx.fillStyle = hv;
      ctx.fillRect(0, 0, VIEW_W, VIEW_H);
    }
  }

  function drawDialogue() {
    const d = g.dialogue;
    const lines = d.pages[d.page];
    const h = 16 + lines.length * 10;
    const y = VIEW_H - h - 8;
    // double border: outer dark, inner teal — pixel-panel look
    ctx.fillStyle = 'rgba(8, 11, 19, 0.95)';
    ctx.fillRect(6, y, VIEW_W - 12, h);
    ctx.strokeStyle = 'rgba(20, 30, 45, 1)';
    ctx.lineWidth = 2;
    ctx.strokeRect(7, y + 1, VIEW_W - 14, h - 2);
    ctx.strokeStyle = 'rgba(74, 192, 192, 0.8)';
    ctx.lineWidth = 1;
    ctx.strokeRect(8.5, y + 2.5, VIEW_W - 17, h - 5);
    if (d.speaker) {
      ctx.font = '7px PixelDisplay, monospace';
      const nw = Math.ceil(ctx.measureText(d.speaker).width) + 14;
      ctx.fillStyle = 'rgba(8, 11, 19, 1)';
      ctx.fillRect(14, y - 8, nw, 12);
      ctx.strokeStyle = 'rgba(255, 179, 71, 0.8)';
      ctx.strokeRect(14.5, y - 7.5, nw - 1, 11);
      text(d.speaker, 20, y - 6, '#ffb347', '7px PixelDisplay, monospace');
    }
    let budget = Math.floor(d.chars);
    lines.forEach((line, i) => {
      const shown = line.slice(0, Math.max(0, budget));
      budget -= line.length;
      text(shown, 14, y + 8 + i * 10);
    });
    if (budget >= 0 && Math.floor(g.time * 2.5) % 2 === 0) {
      // blinking advance chevron
      const ax = VIEW_W - 20, ay = y + h - 8;
      ctx.fillStyle = '#4ac0c0';
      ctx.beginPath();
      ctx.moveTo(ax, ay);
      ctx.lineTo(ax + 6, ay);
      ctx.lineTo(ax + 3, ay + 4);
      ctx.closePath();
      ctx.fill();
    }
  }

  function overlay(alpha = 0.6) {
    ctx.fillStyle = `rgba(8, 8, 14, ${alpha})`;
    ctx.fillRect(0, 0, VIEW_W, VIEW_H);
  }

  function centerText(str, y, color, font) {
    ctx.font = font || '8px monospace';
    const w = ctx.measureText(str).width;
    text(str, Math.round((VIEW_W - w) / 2), y, color, font);
  }

  function drawTitle() {
    overlay(0.66);
    // rising ember motes behind the logotype
    for (let i = 0; i < 14; i++) {
      const seed = i * 137.5;
      const py = ((seed * 7 - g.time * (8 + (i % 5) * 3)) % 260 + 260) % 260 - 10;
      const px = (seed % VIEW_W) + Math.sin(g.time * 0.8 + i) * 6;
      ctx.fillStyle = i % 3 === 0 ? 'rgba(255, 170, 80, 0.5)' : 'rgba(230, 90, 60, 0.35)';
      ctx.fillRect(px, VIEW_H - py, i % 4 === 0 ? 2 : 1.5, i % 4 === 0 ? 2 : 1.5);
    }
    // logotype: ember gradient with glow + hard shadow
    ctx.save();
    ctx.font = '22px PixelDisplay, monospace';
    ctx.textBaseline = 'top';
    const title = 'EMBERWOOD';
    const tw = ctx.measureText(title).width;
    const tx = Math.round((VIEW_W - tw) / 2);
    ctx.shadowColor = 'rgba(255, 140, 40, 0.55)';
    ctx.shadowBlur = 14;
    ctx.fillStyle = '#0c0c12';
    ctx.fillText(title, tx + 2, 54 + 2);
    const grad = ctx.createLinearGradient(0, 52, 0, 80);
    grad.addColorStop(0, '#ffe8a3');
    grad.addColorStop(0.5, '#ffb347');
    grad.addColorStop(1, '#e05a3a');
    ctx.fillStyle = grad;
    ctx.fillText(title, tx, 54);
    ctx.restore();
    centerText('the signal has gone dark', 84, '#8fd0d0', '8px monospace');

    plate(VIEW_W / 2 - 82, 108, 164, 52);
    const rows = [['WASD', 'move'], ['SPACE', 'talk / open / attack'], ['J / M', 'journal / music']];
    rows.forEach(([k, v], i) => {
      const ry = 115 + i * 13;
      ctx.font = '7px PixelDisplay, monospace';
      const kw = ctx.measureText(k).width;
      text(k, VIEW_W / 2 - 24 - kw, ry, '#ffb347', '7px PixelDisplay, monospace');
      text(v, VIEW_W / 2 - 14, ry + 1, '#c5c9d4');
    });

    const pulse = 0.55 + 0.45 * Math.sin(g.time * 3);
    ctx.globalAlpha = pulse;
    centerText('- PRESS SPACE TO BEGIN -', 174, '#ffb347', '8px PixelDisplay, monospace');
    ctx.globalAlpha = 1;
  }

  function drawDead() {
    overlay(0.7);
    plate(VIEW_W / 2 - 100, 86, 200, 56);
    centerText('SYSTEMS FAILING...', 98, '#e64539', '10px PixelDisplay, monospace');
    centerText('The settlers drag you back to Emberwood.', 124);
  }

  function drawWin() {
    overlay(0.72);
    // rising embers behind the panel — the beacon is alive again
    for (let i = 0; i < 18; i++) {
      const seed = i * 97.3;
      const py = ((seed * 5 - g.time * (10 + (i % 5) * 4)) % 260 + 260) % 260 - 10;
      const px = (seed % VIEW_W) + Math.sin(g.time + i) * 8;
      ctx.fillStyle = i % 3 === 0 ? 'rgba(255, 190, 90, 0.55)' : 'rgba(230, 100, 60, 0.4)';
      ctx.fillRect(px, VIEW_H - py, i % 4 === 0 ? 2 : 1.5, i % 4 === 0 ? 2 : 1.5);
    }
    plate(VIEW_W / 2 - 110, 48, 220, 118);
    centerText('THE SIGNAL BURNS AGAIN!', 60, '#ffb347', '9px PixelDisplay, monospace');
    centerText('Emberwood is safe. You are its hero.', 86);
    const m = Math.floor(g.time / 60), s = Math.floor(g.time % 60);
    centerText(`time ${m}m ${s}s   scrap ${g.quest.coins}   foes ${g.quest.kills}`, 110, '#c5c9d4');
    const logs = ['log1', 'log2', 'log3'].filter((k) => g.quest.flags[k]).length;
    centerText(g.quest.flags.logsDone ? 'You know why the beacon matters. Rowan does too.'
      : `archive logs found: ${logs} of 3 — the why is still out there`, 128, '#8fd0d0');
    centerText('Space: keep exploring    N: new game', 150, '#4ac0c0');
  }

  // ---------- loop ----------

  let last = performance.now();
  function frame(now) {
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    update(dt);
    render();
    requestAnimationFrame(frame);
  }

  return {
    start(roomId) {
      if (roomId && MAPS[roomId]) {
        g.quest = newQuestState();
        loadMap(roomId, MAPS[roomId].spawnX, MAPS[roomId].spawnY);
        g.mode = 'play';
      } else if (!load()) {
        loadMap(START.map, START.x, START.y);
        g.pendingIntro = true;
      }
      requestAnimationFrame(frame);
    },
    newGame,
  };
}
