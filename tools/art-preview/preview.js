// Art-direction preview harness.
//   ?style=verdant|gameboy|emberdusk|pastel|storybook|twilight
//     -> re-palettes the real game in place and boots it (same scene each time)
//   ?mode=perspective&kind=topdown|iso|side
//     -> hand-drawn canvas mockup of an alternative camera perspective

import { TILES } from '../../src/tiles.js';
import { SPRITES, drawDef } from '../../src/sprites.js';
import { MAPS, buildGrid } from '../../src/maps.js';
import { createInput } from '../../src/input.js';
import { createGame } from '../../src/game.js';

const params = new URLSearchParams(location.search);
const canvas = document.getElementById('game');

// ---------- color utils ----------

function hex2rgb(h) {
  const s = h.replace('#', '');
  return [parseInt(s.slice(0, 2), 16), parseInt(s.slice(2, 4), 16), parseInt(s.slice(4, 6), 16)];
}
function rgb2hex([r, gg, b]) {
  return '#' + [r, gg, b].map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, '0')).join('');
}
function rgb2hsl([r, g, b]) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  let h = 0, s = 0;
  const l = (max + min) / 2;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
    else if (max === g) h = ((b - r) / d + 2) / 6;
    else h = ((r - g) / d + 4) / 6;
  }
  return [h, s, l];
}
function hsl2rgb([h, s, l]) {
  h = ((h % 1) + 1) % 1;
  if (s === 0) return [l * 255, l * 255, l * 255];
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  const f = (t) => {
    t = ((t % 1) + 1) % 1;
    if (t < 1 / 6) return p + (q - p) * 6 * t;
    if (t < 1 / 2) return q;
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
    return p;
  };
  return [f(h + 1 / 3) * 255, f(h) * 255, f(h - 1 / 3) * 255];
}
const lum = (hex) => { const [r, g, b] = hex2rgb(hex); return (0.299 * r + 0.587 * g + 0.114 * b) / 255; };

const STYLES = {
  verdant: (c) => c,
  gameboy: (c) => {
    const P = ['#0f380f', '#306230', '#8bac0f', '#9bbc0f'];
    const l = lum(c);
    return P[l < 0.22 ? 0 : l < 0.45 ? 1 : l < 0.7 ? 2 : 3];
  },
  emberdusk: (c) => {
    const [h, s, l] = rgb2hsl(hex2rgb(c));
    return rgb2hex(hsl2rgb([h + 0.015, s * 0.5, l * 0.72]));
  },
  pastel: (c) => {
    const [r, g, b] = hex2rgb(c);
    const mix = (v) => v + (255 - v) * 0.38;
    return rgb2hex([mix(r), mix(g), mix(b)]);
  },
  storybook: (c) => {
    const [r, g, b] = hex2rgb(c);
    return rgb2hex([
      Math.min(255, r * 0.393 + g * 0.769 + b * 0.189),
      Math.min(255, r * 0.349 + g * 0.686 + b * 0.168),
      Math.min(255, r * 0.272 + g * 0.534 + b * 0.131),
    ]);
  },
  twilight: (c) => {
    const [h, s, l] = rgb2hsl(hex2rgb(c));
    return rgb2hex(hsl2rgb([h - 0.16, Math.min(1, s * 1.2), l * 0.82]));
  },
};

function transformAllPalettes(fn) {
  const pals = new Set();
  const walk = (o) => {
    if (!o || typeof o !== 'object') return;
    if (o.pal && o.art) { pals.add(o.pal); return; }
    for (const v of Object.values(o)) walk(v);
  };
  for (const t of Object.values(TILES)) walk(t.def);
  walk(SPRITES);
  for (const pal of pals) {
    for (const k of Object.keys(pal)) pal[k] = fn(pal[k]);
  }
}

// ---------- mode: restyled real game ----------

function bootStyledGame(styleName) {
  transformAllPalettes(STYLES[styleName] || STYLES.verdant);
  // Same scene every time: mid-village, lake + bridge + sand + plaza in frame.
  const quest = {
    coins: 14, hearts: 3, maxHearts: 3, shards: 1, kills: 3,
    flags: { talkedElder: true, hasCaveKey: true }, opened: { shard1: true },
  };
  localStorage.setItem('emberwood-save-v1', JSON.stringify({
    quest, mapId: 'overworld', x: 32 * 16, y: 24 * 16, time: 120,
  }));
  const game = createGame(canvas, createInput());
  game.start();
  // leave the title screen
  setTimeout(() => window.dispatchEvent(new KeyboardEvent('keydown', { code: 'Space' })), 250);
}

// ---------- mode: perspective mockups ----------

const BASE = {
  '.': '#3e8948', ',': '#3e8948', '#': '#2e7d32', '~': '#2389da', '=': '#8a5a2b',
  's': '#e8d5a3', 'M': '#7d7d85', 'p': '#c2a878', 'h': '#b0413e', 'H': '#e9dfc9',
  'D': '#e9dfc9', 'o': '#c2a878', 'C': '#14141c', 'F': '#8a5a2b',
};

function shade(hex, f) {
  const [r, g, b] = hex2rgb(hex);
  return rgb2hex([r * f, g * f, b * f]);
}

// Pure bird's-eye: flat map, characters as head+shoulders blobs.
function drawTopdown(ctx) {
  const grid = buildGrid(MAPS.overworld);
  const X0 = 24, Y0 = 17;
  for (let y = 0; y < 15; y++) {
    for (let x = 0; x < 20; x++) {
      const ch = grid[Y0 + y][X0 + x];
      const c = BASE[ch] || '#3e8948';
      // houses read as pure roofs from above
      ctx.fillStyle = (ch === 'H' || ch === 'D') ? BASE.h : c;
      ctx.fillRect(x * 16, y * 16, 16, 16);
      ctx.fillStyle = 'rgba(0,0,0,0.07)';
      if ((x + y) % 2 === 0) ctx.fillRect(x * 16, y * 16, 16, 16);
      if (ch === '#') { // canopy blob
        ctx.fillStyle = '#1e5128';
        ctx.beginPath();
        ctx.arc(x * 16 + 8, y * 16 + 8, 7, 0, 7);
        ctx.fill();
        ctx.fillStyle = '#2e7d32';
        ctx.beginPath();
        ctx.arc(x * 16 + 6, y * 16 + 6, 4, 0, 7);
        ctx.fill();
      }
      if (ch === '~' && (x * 7 + y * 13) % 5 === 0) {
        ctx.fillStyle = '#5fb4e8';
        ctx.fillRect(x * 16 + 3, y * 16 + 7, 6, 1);
      }
    }
  }
  // overhead characters: hair circle + shoulder pads
  const head = (px, py, hair, shirt) => {
    ctx.fillStyle = shirt;
    ctx.fillRect(px - 6, py - 4, 12, 8);
    ctx.fillStyle = hair;
    ctx.beginPath();
    ctx.arc(px, py, 4.5, 0, 7);
    ctx.fill();
  };
  head(14 * 16 + 8, 7 * 16 + 8, '#7a4a21', '#2e7d5b');  // player on plaza
  head(15 * 16 + 8, 6 * 16 + 8, '#33272e', '#7b4b94');  // merchant
  head(13 * 16 + 8, 10 * 16 + 8, '#3b2a1a', '#b0413e'); // villager
  head(0 * 16 + 8, 9 * 16 + 8, '#c95a1e', '#2e5d8d');   // fisherman
  // beacon from above: concentric rings
  ctx.fillStyle = '#5c5c66';
  ctx.beginPath(); ctx.arc(14 * 16 + 8, 8 * 16 + 8, 7, 0, 7); ctx.fill();
  ctx.fillStyle = '#ff9e2c';
  ctx.beginPath(); ctx.arc(14 * 16 + 8, 8 * 16 + 8, 3, 0, 7); ctx.fill();
  label(ctx, 'PURE TOP-DOWN (bird\'s-eye) — mockup');
}

// Isometric 2:1 diamonds with extruded trees/houses/rocks.
function drawIso(ctx) {
  ctx.fillStyle = '#171722';
  ctx.fillRect(0, 0, 320, 240);
  const grid = buildGrid(MAPS.overworld);
  const X0 = 22, Y0 = 15, W = 22, H = 16;
  const TW = 20, TH = 10;
  const proj = (x, y) => [160 + (x - y) * (TW / 2), 26 + (x + y) * (TH / 2)];
  const diamond = (sx, sy, c) => {
    ctx.fillStyle = c;
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.lineTo(sx + TW / 2, sy + TH / 2);
    ctx.lineTo(sx, sy + TH);
    ctx.lineTo(sx - TW / 2, sy + TH / 2);
    ctx.closePath();
    ctx.fill();
  };
  const prism = (sx, sy, h, top, left, right) => {
    ctx.fillStyle = left;
    ctx.beginPath();
    ctx.moveTo(sx - TW / 2, sy + TH / 2 - h); ctx.lineTo(sx, sy + TH - h);
    ctx.lineTo(sx, sy + TH); ctx.lineTo(sx - TW / 2, sy + TH / 2);
    ctx.closePath(); ctx.fill();
    ctx.fillStyle = right;
    ctx.beginPath();
    ctx.moveTo(sx + TW / 2, sy + TH / 2 - h); ctx.lineTo(sx, sy + TH - h);
    ctx.lineTo(sx, sy + TH); ctx.lineTo(sx + TW / 2, sy + TH / 2);
    ctx.closePath(); ctx.fill();
    diamond(sx, sy - h, top);
  };
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const ch = grid[Y0 + y][X0 + x];
      const [sx, sy] = proj(x, y);
      const c = BASE[ch] || '#3e8948';
      if (ch === '~') diamond(sx, sy, shade(c, 0.9));
      else diamond(sx, sy, c);
      if (ch === '#') {
        prism(sx, sy, 6, '#6d4c2f', shade('#6d4c2f', 0.7), shade('#6d4c2f', 0.5));
        ctx.fillStyle = '#1e5128';
        ctx.beginPath(); ctx.arc(sx, sy - 12, 8, 0, 7); ctx.fill();
        ctx.fillStyle = '#2e7d32';
        ctx.beginPath(); ctx.arc(sx - 2, sy - 14, 5, 0, 7); ctx.fill();
      }
      if (ch === 'M') prism(sx, sy, 8, '#9a9aa2', '#7d7d85', '#5c5c66');
      if (ch === 'h' || ch === 'H' || ch === 'D') prism(sx, sy, 14, '#b0413e', '#e9dfc9', shade('#e9dfc9', 0.72));
      if (ch === '=') prism(sx, sy, 2, '#8a5a2b', shade('#8a5a2b', 0.7), shade('#8a5a2b', 0.5));
    }
  }
  // billboarded characters
  const dude = (gx, gy, hair, shirt) => {
    const [sx, sy] = proj(gx - X0, gy - Y0);
    ctx.fillStyle = shirt; ctx.fillRect(sx - 3, sy - 10, 6, 8);
    ctx.fillStyle = '#eec39a'; ctx.fillRect(sx - 3, sy - 15, 6, 5);
    ctx.fillStyle = hair; ctx.fillRect(sx - 3, sy - 17, 6, 3);
  };
  dude(32, 24, '#7a4a21', '#2e7d5b'); // player
  dude(39, 23, '#33272e', '#7b4b94'); // merchant
  dude(37, 27, '#3b2a1a', '#b0413e'); // villager
  // beacon
  const [bx, by] = proj(38 - X0, 25 - Y0);
  prism(bx, by, 10, '#9a9aa2', '#7d7d85', '#5c5c66');
  ctx.fillStyle = '#ff9e2c'; ctx.fillRect(bx - 2, by - 16, 4, 5);
  label(ctx, 'ISOMETRIC 2:1 — mockup');
}

// Side-view (Zelda II style) strip.
function drawSide(ctx) {
  const sky = ctx.createLinearGradient(0, 0, 0, 160);
  sky.addColorStop(0, '#7db9e8');
  sky.addColorStop(1, '#cdeffd');
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, 320, 240);
  // far hills
  ctx.fillStyle = '#2e7d32';
  for (const [hx, hw, hh] of [[0, 130, 46], [90, 170, 60], [230, 140, 40]]) {
    ctx.beginPath();
    ctx.ellipse(hx + hw / 2, 176, hw / 2, hh, 0, Math.PI, 0);
    ctx.fill();
  }
  // ground
  ctx.fillStyle = '#6d4c2f';
  ctx.fillRect(0, 184, 320, 56);
  ctx.fillStyle = '#3e8948';
  ctx.fillRect(0, 176, 320, 10);
  // raised ledge
  ctx.fillStyle = '#6d4c2f'; ctx.fillRect(210, 144, 70, 40);
  ctx.fillStyle = '#3e8948'; ctx.fillRect(210, 138, 70, 8);
  // trees
  for (const tx of [30, 260]) {
    ctx.fillStyle = '#6d4c2f'; ctx.fillRect(tx + 12, 120, 8, 58);
    ctx.fillStyle = '#1e5128';
    ctx.beginPath(); ctx.arc(tx + 16, 106, 26, 0, 7); ctx.fill();
    ctx.fillStyle = '#2e7d32';
    ctx.beginPath(); ctx.arc(tx + 8, 98, 16, 0, 7); ctx.fill();
  }
  // house facade
  ctx.fillStyle = '#e9dfc9'; ctx.fillRect(120, 128, 64, 50);
  ctx.fillStyle = '#b0413e';
  ctx.beginPath();
  ctx.moveTo(112, 132); ctx.lineTo(152, 104); ctx.lineTo(192, 132);
  ctx.closePath(); ctx.fill();
  ctx.fillStyle = '#6d4c2f'; ctx.fillRect(146, 146, 16, 32);
  ctx.fillStyle = '#8f3330'; ctx.fillRect(128, 140, 12, 12);
  // player + slime, reusing the real sprites at 2x
  drawDef(ctx, SPRITES.player.right, 60, 148, 2);
  drawDef(ctx, SPRITES.slime.idle, 180, 152, 2);
  // floating coins
  for (const cx of [94, 110, 126]) {
    ctx.fillStyle = '#f7c948';
    ctx.beginPath(); ctx.arc(cx, 120, 4, 0, 7); ctx.fill();
    ctx.fillStyle = '#c19a49';
    ctx.beginPath(); ctx.arc(cx, 120, 4, 0, 7); ctx.stroke();
  }
  label(ctx, 'SIDE VIEW (Zelda II / platformer) — mockup');
}

// Oblique 3/4 "top-down with depth": flat ground plan, vertical objects
// extrude upward showing their front faces (Earthbound/Link's Awakening depth).
function drawOblique(ctx) {
  ctx.fillStyle = '#0c0c12';
  ctx.fillRect(0, 0, 320, 240);
  const grid = buildGrid(MAPS.overworld);
  const X0 = 24, Y0 = 17, W = 20, H = 17;
  const TW = 16, TH = 12, TOP = 26;
  const flat = { '.': 1, ',': 1, '~': 1, '=': 1, 's': 1, 'p': 1, 'o': 1 };
  // ground pass (squashed plan view)
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const ch = grid[Y0 + y][X0 + x];
      const c = BASE[ch] || '#3e8948';
      ctx.fillStyle = (ch === 'h' || ch === 'H' || ch === 'D' || ch === '#' || ch === 'M') ? BASE['.'] : c;
      ctx.fillRect(x * TW, TOP + y * TH, TW, TH);
      if (ch === '~') {
        ctx.fillStyle = '#5fb4e8';
        if ((x * 7 + y * 13) % 4 === 0) ctx.fillRect(x * TW + 4, TOP + y * TH + 5, 6, 1);
      }
      if (flat[ch] && (x * 5 + y * 11) % 7 === 0 && ch !== '~') {
        ctx.fillStyle = shade(c, 1.12);
        ctx.fillRect(x * TW + 6, TOP + y * TH + 4, 2, 2);
      }
    }
  }
  // extrusion pass, back to front
  for (let y = 0; y < H; y++) {
    const base = TOP + (y + 1) * TH;
    for (let x = 0; x < W; x++) {
      const ch = grid[Y0 + y][X0 + x];
      const sx = x * TW;
      if (ch === '#') {
        ctx.fillStyle = '#6d4c2f';
        ctx.fillRect(sx + 6, base - 9, 4, 9);
        ctx.fillStyle = '#1e5128';
        ctx.beginPath(); ctx.arc(sx + 8, base - 15, 8, 0, 7); ctx.fill();
        ctx.fillStyle = '#2e7d32';
        ctx.beginPath(); ctx.arc(sx + 6, base - 18, 5, 0, 7); ctx.fill();
      } else if (ch === 'M') {
        ctx.fillStyle = '#5c5c66';
        ctx.fillRect(sx, base - 8, TW, 8);
        ctx.fillStyle = '#9a9aa2';
        ctx.fillRect(sx, base - 14, TW, 6);
        ctx.fillStyle = '#7d7d85';
        ctx.fillRect(sx + 2, base - 12, TW - 4, 3);
      } else if (ch === 'H' || ch === 'D') {
        // facade rises from the wall row; roof plane above covers the roof row
        ctx.fillStyle = '#e9dfc9';
        ctx.fillRect(sx, base - 20, TW, 20);
        ctx.fillStyle = '#c9bda3';
        ctx.fillRect(sx + 3, base - 15, 4, 5); // window
        if (ch === 'D') {
          ctx.fillStyle = '#6d4c2f';
          ctx.fillRect(sx + 4, base - 12, 8, 12);
        }
        ctx.fillStyle = '#b0413e';
        ctx.fillRect(sx, base - 30, TW, 10);
        ctx.fillStyle = '#8f3330';
        ctx.fillRect(sx, base - 30, TW, 2);
      }
    }
  }
  // props + characters as standing billboards (the real sprites)
  const stand = (gx, gy, def) => {
    const sx = (gx - X0) * TW;
    const base = TOP + (gy - Y0 + 1) * TH;
    drawDef(ctx, def, sx, base - 16, 1);
  };
  stand(38, 25, SPRITES.beacon);
  stand(36, 25, SPRITES.sign);
  stand(34, 19, SPRITES.player.down); // by the elder's door
  stand(32, 24, SPRITES.player.down);
  stand(39, 23, SPRITES.merchant.down);
  stand(37, 27, SPRITES.villager.down);
  stand(24, 26, SPRITES.fisherman.down);
  label(ctx, 'OBLIQUE 3/4 + DEPTH (extruded walls) — mockup');
}

// Tilted-perspective "HD-2D": ground plane foreshortens toward a horizon,
// rows shrink and haze with distance, objects stand upright.
function drawTilt(ctx) {
  const grid = buildGrid(MAPS.overworld);
  const X0 = 24, Y0 = 17, W = 20, H = 15;
  // sky + far silhouettes
  const sky = ctx.createLinearGradient(0, 0, 0, 60);
  sky.addColorStop(0, '#8ecae6');
  sky.addColorStop(1, '#d8ecf8');
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, 320, 60);
  ctx.fillStyle = 'rgba(70, 110, 90, 0.55)';
  for (const [mx, mw, mh] of [[-20, 150, 34], [100, 190, 44], [230, 160, 30]]) {
    ctx.beginPath();
    ctx.moveTo(mx, 52); ctx.lineTo(mx + mw / 2, 52 - mh); ctx.lineTo(mx + mw, 52);
    ctx.closePath(); ctx.fill();
  }
  ctx.fillStyle = '#0c0c12';
  ctx.fillRect(0, 60, 320, 180);
  let yPos = 52;
  for (let y = 0; y < H; y++) {
    const t = y / (H - 1);
    const s = 0.5 + 0.68 * t;
    const rowH = 13 * s;
    const w = 17 * s;
    for (let x = 0; x < W; x++) {
      const ch = grid[Y0 + y][X0 + x];
      const c = BASE[ch] || '#3e8948';
      const sx = 160 + (x - W / 2) * w;
      ctx.fillStyle = (ch === '#' || ch === 'M' || ch === 'H' || ch === 'D' || ch === 'h') ? BASE['.'] : c;
      ctx.fillRect(sx, yPos, w + 0.6, rowH + 0.6);
    }
    // upright objects for this row
    for (let x = 0; x < W; x++) {
      const ch = grid[Y0 + y][X0 + x];
      const sx = 160 + (x - W / 2) * w;
      const base = yPos + rowH;
      if (ch === '#') {
        ctx.fillStyle = '#6d4c2f';
        ctx.fillRect(sx + w / 2 - 1.5 * s, base - 8 * s, 3 * s, 8 * s);
        ctx.fillStyle = '#1e5128';
        ctx.beginPath(); ctx.arc(sx + w / 2, base - 13 * s, 8 * s, 0, 7); ctx.fill();
        ctx.fillStyle = '#2e7d32';
        ctx.beginPath(); ctx.arc(sx + w / 2 - 2 * s, base - 15 * s, 5 * s, 0, 7); ctx.fill();
      } else if (ch === 'M') {
        ctx.fillStyle = '#7d7d85';
        ctx.beginPath();
        ctx.moveTo(sx, base); ctx.lineTo(sx + w / 2, base - 14 * s); ctx.lineTo(sx + w, base);
        ctx.closePath(); ctx.fill();
      } else if (ch === 'H' || ch === 'D') {
        ctx.fillStyle = '#e9dfc9';
        ctx.fillRect(sx, base - 20 * s, w + 0.5, 20 * s);
        if (ch === 'D') { ctx.fillStyle = '#6d4c2f'; ctx.fillRect(sx + w * 0.3, base - 12 * s, w * 0.4, 12 * s); }
        ctx.fillStyle = '#b0413e';
        ctx.fillRect(sx - w * 0.08, base - 29 * s, w * 1.16, 9 * s);
      }
      // characters
      const gx = X0 + x, gy = Y0 + y;
      const who = (gx === 32 && gy === 24) ? ['#7a4a21', '#2e7d5b']
        : (gx === 39 && gy === 23) ? ['#33272e', '#7b4b94']
          : (gx === 37 && gy === 27) ? ['#3b2a1a', '#b0413e']
            : (gx === 24 && gy === 26) ? ['#c95a1e', '#2e5d8d'] : null;
      if (who) {
        const cx = sx + w / 2;
        ctx.fillStyle = who[1];
        ctx.fillRect(cx - 3 * s, base - 9 * s, 6 * s, 7 * s);
        ctx.fillStyle = '#eec39a';
        ctx.fillRect(cx - 3 * s, base - 14 * s, 6 * s, 5 * s);
        ctx.fillStyle = who[0];
        ctx.fillRect(cx - 3 * s, base - 16 * s, 6 * s, 2.5 * s);
      }
      if (gx === 38 && gy === 25) {
        const cx = sx + w / 2;
        ctx.fillStyle = '#7d7d85';
        ctx.fillRect(cx - 3 * s, base - 12 * s, 6 * s, 12 * s);
        ctx.fillStyle = '#ff9e2c';
        ctx.fillRect(cx - 2 * s, base - 17 * s, 4 * s, 5 * s);
      }
    }
    // distance haze
    ctx.fillStyle = `rgba(150, 195, 230, ${(1 - t) * 0.30})`;
    ctx.fillRect(0, yPos, 320, rowH + 0.6);
    yPos += rowH;
  }
  label(ctx, 'TILTED PERSPECTIVE "HD-2D" (angled camera) — mockup');
}

function label(ctx, text) {
  ctx.font = '8px monospace';
  ctx.textBaseline = 'top';
  const w = ctx.measureText(text).width + 8;
  ctx.fillStyle = 'rgba(12,12,18,0.85)';
  ctx.fillRect(4, 228 - 2, w, 12);
  ctx.fillStyle = '#f7c948';
  ctx.fillText(text, 8, 229);
}

// ---------- boot ----------

if (params.get('mode') === 'perspective') {
  const ctx = canvas.getContext('2d');
  ctx.imageSmoothingEnabled = false;
  const kind = params.get('kind') || 'iso';
  if (kind === 'topdown') drawTopdown(ctx);
  else if (kind === 'side') drawSide(ctx);
  else if (kind === 'oblique') drawOblique(ctx);
  else if (kind === 'tilt') drawTilt(ctx);
  else drawIso(ctx);
} else {
  bootStyledGame(params.get('style') || 'verdant');
}
