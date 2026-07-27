// PNG asset loader for the sci-fi art set. Loads assets/manifest.json and
// resolves every referenced image. Anything missing resolves to null and the
// renderer falls back to the procedural pixel-string art, so the game never
// hard-fails on art.

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

  const art = { tiles: {}, props: {}, chars: {} };
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
