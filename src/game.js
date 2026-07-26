// Emberwood engine: loop, collision, combat, AI, dialogue, HUD, save.

import { TILES, TILE_SIZE as T } from './tiles.js';
import { SPRITES, drawDef } from './sprites.js';
import { MAPS, START, buildGrid } from './maps.js';
import {
  newQuestState, applyEffects, npcDialogue, beaconInteract,
  lockedDoorInteract, sparkleInteract, chestLootLines,
} from './quest.js';

const VIEW_W = 320;
const VIEW_H = 240;
const SAVE_KEY = 'emberwood-save-v1';

const ENEMY_DEFS = {
  slime: { hp: 2, speed: 22, chaseSpeed: 36, aggroR: 90, sprite: 'slime', size: 16 },
  bat: { hp: 1, speed: 30, chaseSpeed: 56, aggroR: 110, sprite: 'bat', size: 16 },
  boss: { hp: 8, speed: 20, chaseSpeed: 30, aggroR: 220, sprite: 'boss', size: 32 },
};

// ---------- sprite/tile canvas cache ----------

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

export function createGame(canvas, input) {
  const ctx = canvas.getContext('2d');
  ctx.imageSmoothingEnabled = false;
  const cache = buildCaches();
  const sfx = createSfx();

  const HIT = { ox: 4, oy: 7, w: 8, h: 8 }; // hitbox within a 16px body

  const g = {
    mode: 'title', // title | play | dialogue | dead | win
    quest: newQuestState(),
    mapId: START.map,
    grid: null,
    map: null,
    entities: [],
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
  };

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
    loadMap(START.map, START.x, START.y);
    try { localStorage.removeItem(SAVE_KEY); } catch { /* ok */ }
  }

  // ---------- map / entities ----------

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
      || e.kind === 'beacon' || e.kind === 'lockedDoor';
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

  // Boss body is 32px; use a scaled hitbox for it.
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
    const pages = result.lines.map((l) => wrap(l));
    g.dialogue = { pages, page: 0, chars: 0 };
    g.mode = 'dialogue';
    g.afterDialogue = after || null;
    if (result.effects) {
      applyEffects(g.quest, result.effects);
      save();
    }
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
      if (!['npc', 'sign', 'chest', 'beacon', 'lockedDoor'].includes(e.kind)) continue;
      if (p.x >= e.x && p.x < e.x + 16 && p.y >= e.y && p.y < e.y + 16) return e;
    }
    return null;
  }

  function doInteract(e) {
    if (e.kind === 'npc') {
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
    } else if (e.kind === 'chest') {
      if (g.quest.opened[e.id]) {
        openDialogue({ lines: ['Empty. You already cleaned it out.'] });
        return;
      }
      g.quest.opened[e.id] = true;
      if (e.loot.coins) g.quest.coins += e.loot.coins;
      if (e.loot.shard) g.quest.shards += 1;
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
    return { x: p.x - 10, y: p.y - 10, w: 20, h: 20 };
  }

  function hurtPlayer(from) {
    if (g.player.invuln > 0 || g.mode !== 'play') return;
    g.quest.hearts -= 1;
    g.player.invuln = 1.0;
    const ang = Math.atan2(g.player.y - from.y, g.player.x - from.x);
    g.player.kx = Math.cos(ang) * 130;
    g.player.ky = Math.sin(ang) * 130;
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
    burst(e.x + e.def.size / 2, e.y + e.def.size / 2, '#f4f4f4', 10);
    const roll = Math.random();
    if (roll < 0.5) g.drops.push({ type: 'coin', x: e.x + e.def.size / 2 - 8, y: e.y + e.def.size / 2 - 8 });
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

    if (g.mode === 'title') {
      if (input.consumeAction()) g.mode = 'play';
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
      if (input.consumeAction()) g.mode = 'play'; // keep exploring
      updateParticles(dt);
      return;
    }

    const p = g.player;

    // movement
    let dx = 0, dy = 0;
    if (input.held.up) dy -= 1;
    if (input.held.down) dy += 1;
    if (input.held.left) dx -= 1;
    if (input.held.right) dx += 1;
    p.moving = dx !== 0 || dy !== 0;
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
    // knockback
    if (Math.abs(p.kx) > 1 || Math.abs(p.ky) > 1) {
      moveBody(p, p.kx * dt, p.ky * dt, null);
      p.kx *= Math.pow(0.001, dt);
      p.ky *= Math.pow(0.001, dt);
    }
    p.invuln = Math.max(0, p.invuln - dt);
    p.attack = Math.max(0, p.attack - dt);

    // action: interact if something faces us, else swing
    if (input.consumeAction()) {
      const target = interactTarget();
      if (target) doInteract(target);
      else swing();
    }

    // attack collisions
    if (p.attack > 0.06) {
      const hb = attackHitbox();
      for (const e of [...g.entities]) {
        if (e.kind !== 'enemy' || e.invuln > 0 || e.lastSwing === p.swing) continue;
        const size = e.def.size;
        if (aabb(hb.x, hb.y, hb.w, hb.h, e.x, e.y, size, size)) {
          e.lastSwing = p.swing;
          e.hp -= 1;
          e.invuln = 0.25;
          const ang = Math.atan2(e.y - p.y, e.x - p.x);
          e.kx = Math.cos(ang) * 160;
          e.ky = Math.sin(ang) * 160;
          sfx.hit();
          burst(e.x + size / 2, e.y + size / 2, '#fff7d6', 5);
          if (e.hp <= 0) killEnemy(e);
        }
      }
    }

    // enemies
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

      // boss enrage: spawn minions at half health
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

      // contact damage
      if (aabb(p.x + HIT.ox, p.y + HIT.oy, HIT.w, HIT.h, e.x + 2, e.y + 2, size - 4, size - 4)) {
        hurtPlayer({ x: ecx, y: ecy });
      }
    }

    // drops
    for (const d of [...g.drops]) {
      if (aabb(p.x + 2, p.y + 4, 12, 12, d.x + 4, d.y + 4, 8, 8)) {
        if (d.type === 'coin') g.quest.coins += 1;
        if (d.type === 'heart') g.quest.hearts = Math.min(g.quest.maxHearts, g.quest.hearts + 1);
        sfx.pickup();
        g.drops = g.drops.filter((x) => x !== d);
      }
    }

    // sparkle pickup (walk over)
    for (const e of [...g.entities]) {
      if (e.kind !== 'sparkle') continue;
      if (aabb(p.x + 2, p.y + 4, 12, 12, e.x + 2, e.y + 2, 12, 12)) {
        g.entities = g.entities.filter((x) => x !== e);
        sfx.pickup();
        openDialogue(sparkleInteract(g.quest));
      }
    }

    // portals
    const ptx = Math.floor((p.x + 8) / T);
    const pty = Math.floor((p.y + 11) / T);
    for (const portal of g.map.portals) {
      if (portal.x === ptx && portal.y === pty) {
        loadMap(portal.to, portal.tx, portal.ty);
        save();
        break;
      }
    }

    // beacon particles once lit
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

  function render() {
    ctx.fillStyle = '#0c0c12';
    ctx.fillRect(0, 0, VIEW_W, VIEW_H);
    if (!g.grid) return;

    const cx = g.cam.x, cy = g.cam.y;
    const x0 = Math.max(0, Math.floor(cx / T));
    const y0 = Math.max(0, Math.floor(cy / T));
    const x1 = Math.min(g.grid[0].length - 1, Math.ceil((cx + VIEW_W) / T));
    const y1 = Math.min(g.grid.length - 1, Math.ceil((cy + VIEW_H) / T));
    for (let ty = y0; ty <= y1; ty++) {
      for (let tx = x0; tx <= x1; tx++) {
        const c = cache.tiles[g.grid[ty][tx]];
        if (c) ctx.drawImage(c, tx * T - cx, ty * T - cy);
      }
    }

    // drops
    for (const d of g.drops) {
      ctx.drawImage(cache.sprites[d.type === 'coin' ? 'coin' : 'heart'], Math.round(d.x - cx), Math.round(d.y - cy));
    }

    // entities + player, y-sorted
    const drawables = [...g.entities, { kind: 'player' }];
    drawables.sort((a, b) => {
      const ay = a.kind === 'player' ? g.player.y : a.y;
      const by = b.kind === 'player' ? g.player.y : b.y;
      return ay - by;
    });

    for (const e of drawables) {
      if (e.kind === 'player') { drawPlayer(); continue; }
      let img = null;
      let dy = 0;
      if (e.kind === 'npc') img = cache.sprites[`${e.sprite}:down`];
      else if (e.kind === 'sign') img = cache.sprites.sign;
      else if (e.kind === 'beacon') img = cache.sprites[g.quest.flags.beaconLit ? 'beaconLit' : 'beacon'];
      else if (e.kind === 'lockedDoor') img = cache.sprites.lockedDoor;
      else if (e.kind === 'sparkle') {
        if (Math.floor(g.time * 4) % 2 === 0) img = cache.sprites.sparkle;
        else { img = cache.sprites.sparkle; dy = -1; }
      } else if (e.kind === 'chest') {
        img = cache.sprites[g.quest.opened[e.id] ? 'chestOpen' : 'chestClosed'];
      } else if (e.kind === 'enemy') {
        img = cache.sprites[e.def.sprite];
        dy = Math.round(Math.sin(e.anim) * (e.type === 'bat' ? 3 : 1));
        if (e.invuln > 0 && Math.floor(e.invuln * 20) % 2 === 0) continue; // hit flash
      }
      if (img) ctx.drawImage(img, Math.round(e.x - cx), Math.round(e.y - cy + dy));
    }

    // attack arc
    if (g.player.attack > 0) {
      const p = facingPoint();
      ctx.strokeStyle = 'rgba(255, 247, 214, 0.9)';
      ctx.lineWidth = 2;
      ctx.beginPath();
      const base = { up: -Math.PI / 2, down: Math.PI / 2, left: Math.PI, right: 0 }[g.player.dir];
      const prog = 1 - g.player.attack / 0.22;
      ctx.arc(g.player.x + 8 - cx, g.player.y + 11 - cy, 13, base - 1.1 + prog * 0.9, base + 0.2 + prog * 0.9);
      ctx.stroke();
    }

    // particles
    for (const pt of g.particles) {
      ctx.fillStyle = pt.color;
      ctx.fillRect(Math.round(pt.x - cx), Math.round(pt.y - cy), 2, 2);
    }

    // cave darkness
    if (g.map.dark) {
      const px = g.player.x + 8 - cx, py = g.player.y + 11 - cy;
      const grad = ctx.createRadialGradient(px, py, 30, px, py, 110);
      grad.addColorStop(0, 'rgba(6,6,12,0)');
      grad.addColorStop(1, 'rgba(6,6,12,0.93)');
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, VIEW_W, VIEW_H);
    }

    drawHud();
    if (g.mode === 'dialogue') drawDialogue();
    if (g.mode === 'title') drawTitle();
    if (g.mode === 'dead') drawDead();
    if (g.mode === 'win') drawWin();
  }

  function drawPlayer() {
    const p = g.player;
    if (p.invuln > 0 && Math.floor(p.invuln * 14) % 2 === 0) return;
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

  function drawHud() {
    // hearts
    for (let i = 0; i < g.quest.maxHearts; i++) {
      ctx.globalAlpha = i < g.quest.hearts ? 1 : 0.25;
      ctx.drawImage(cache.sprites.heart, 4 + i * 11 - 2, -2);
    }
    ctx.globalAlpha = 1;
    // coins
    ctx.drawImage(cache.sprites.coin, 2, 10);
    text(`${g.quest.coins}`, 16, 15);
    // shards top-right
    for (let i = 0; i < 3; i++) {
      ctx.globalAlpha = i < g.quest.shards ? 1 : 0.22;
      ctx.drawImage(cache.sprites.shard, VIEW_W - 52 + i * 15, -1);
    }
    ctx.globalAlpha = 1;
    // key items
    let kx = VIEW_W - 52;
    if (g.quest.flags.hasRing && !g.quest.flags.gaveRing) { ctx.drawImage(cache.sprites.ring, kx, 11); kx += 14; }
    if (g.quest.flags.hasCaveKey) ctx.drawImage(cache.sprites.key, kx, 11);
  }

  function drawDialogue() {
    const d = g.dialogue;
    const lines = d.pages[d.page];
    const h = 14 + lines.length * 10;
    const y = VIEW_H - h - 6;
    ctx.fillStyle = 'rgba(12, 12, 20, 0.92)';
    ctx.fillRect(6, y, VIEW_W - 12, h);
    ctx.strokeStyle = '#c19a49';
    ctx.lineWidth = 1;
    ctx.strokeRect(6.5, y + 0.5, VIEW_W - 13, h - 1);
    let budget = Math.floor(d.chars);
    lines.forEach((line, i) => {
      const shown = line.slice(0, Math.max(0, budget));
      budget -= line.length;
      text(shown, 12, y + 6 + i * 10);
    });
    if (budget >= 0) {
      const more = d.page < d.pages.length - 1;
      text(more ? '...' : ' ok', VIEW_W - 26, y + h - 9, '#c19a49');
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
    overlay(0.55);
    centerText('E M B E R W O O D', 70, '#f7c948', 'bold 16px monospace');
    centerText('The beacon has gone dark.', 96, '#f4f4f4');
    centerText('Arrows / WASD  move', 122, '#9a9aa2');
    centerText('Space  talk - open - attack', 134, '#9a9aa2');
    centerText('Press Space to begin', 168, '#f7c948');
    if (Math.floor(g.time * 2) % 2 === 0) centerText('v', 180, '#f7c948');
  }

  function drawDead() {
    overlay(0.7);
    centerText('You collapsed...', 100, '#e64539', 'bold 12px monospace');
    centerText('The villagers drag you back to Emberwood.', 124);
  }

  function drawWin() {
    overlay(0.72);
    centerText('THE BEACON BURNS AGAIN!', 62, '#f7c948', 'bold 12px monospace');
    centerText('Emberwood is safe. You are its hero.', 86);
    const m = Math.floor(g.time / 60), s = Math.floor(g.time % 60);
    centerText(`time ${m}m ${s}s   coins ${g.quest.coins}   foes ${g.quest.kills}`, 110, '#9a9aa2');
    centerText('Space: keep exploring    N: new game', 150, '#c19a49');
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
    start() {
      if (!load()) loadMap(START.map, START.x, START.y);
      requestAnimationFrame(frame);
    },
    newGame,
  };
}
