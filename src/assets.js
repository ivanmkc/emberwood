// PNG asset loader for the sci-fi art set. Loads assets/manifest.json and
// resolves every referenced image. Anything missing resolves to null and the
// renderer falls back to the procedural pixel-string art, so the game never
// hard-fails on art.

import { PLATE_ROOM_NAMES } from './rooms/index.js';

async function jobsRooms(art, base, loadImg) {
  const names = [...new Set(['anchorroom', ...PLATE_ROOM_NAMES])];
  const dataJobs = [];
  for (const name of names) {
    loadImg(`rooms/${name}.jpg`).then((img) => { art.rooms[name] = img; });
    loadImg(`rooms/${name}.collision.png`).then((img) => { art.roomMasks[name] = img; });
    loadImg(`rooms/${name}.emissive.png`).then((img) => { art.roomEmissive[name] = img; });
    loadImg(`rooms/${name}.overhead.png`).then((img) => { if (img) art.roomOverhead[name] = img; });
    fetch(`${base}rooms/${name}.hotspots.json`).then(async (r) => {
      if (r.ok) art.roomHotspots[name] = await r.json();
    }).catch(() => {});
    dataJobs.push((async () => {
    try {
      const res = await fetch(`${base}rooms/${name}.instances.json`);
      if (res.ok) {
        const data = await res.json();
        art.roomData[name] = data;
        for (const f of data.fg || []) {
          loadImg(f.img).then((img) => { f.image = img; });
        }
      }
    } catch { /* room data optional */ }
    })());
  }
}

export async function loadArt(base = 'assets/') {
  let manifest;
  try {
    const res = await fetch(base + 'manifest.json');
    if (!res.ok) return null;
    manifest = await res.json();
  } catch {
    return null;
  }

  const loadImg = (path) => new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = base + path;
  });

  const art = { tiles: {}, props: {}, chars: {}, rooms: {}, roomMasks: {}, roomEmissive: {}, roomOverhead: {}, roomData: {}, roomHotspots: {} };
  await jobsRooms(art, base, loadImg);
  const jobs = [];
  for (const [name, variants] of Object.entries(manifest.tiles || {})) {
    art.tiles[name] = [];
    variants.forEach((p, i) => jobs.push(
      loadImg(p).then((img) => { art.tiles[name][i] = img; }),
    ));
  }
  for (const [name, p] of Object.entries(manifest.props || {})) {
    jobs.push(loadImg(p).then((img) => { art.props[name] = img; }));
  }
  for (const [name, val] of Object.entries(manifest.chars || {})) {
    if (typeof val === 'string') {
      jobs.push(loadImg(val).then((img) => { art.chars[name] = img; }));
    } else {
      art.chars[name] = {};
      for (const [dir, p] of Object.entries(val)) {
        jobs.push(loadImg(p).then((img) => { art.chars[name][dir] = img; }));
      }
    }
  }
  await Promise.all(jobs);
  // prune failed loads
  for (const [k, v] of Object.entries(art.tiles)) {
    art.tiles[k] = v.filter(Boolean);
    if (!art.tiles[k].length) delete art.tiles[k];
  }
  return art;
}
