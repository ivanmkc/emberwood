// Procedural pixel-art sprites: 16 rows x 16 chars, chars index into pal.
// '.' is transparent everywhere.

const humanDown = [
  '................',
  '................',
  '.....HHHHHH.....',
  '....HHHHHHHH....',
  '....HSSSSSSH....',
  '....SSeSSeSS....',
  '....SSSSSSSS....',
  '.....SSSSSS.....',
  '....BBBBBBBB....',
  '...BBBBBBBBBB...',
  '...SBBBBBBBBS...',
  '...SBBBBBBBBS...',
  '....LLL..LLL....',
  '....LLL..LLL....',
  '....DDD..DDD....',
  '................',
];

const humanUp = [
  '................',
  '................',
  '.....HHHHHH.....',
  '....HHHHHHHH....',
  '....HHHHHHHH....',
  '....HHHHHHHH....',
  '....HHHHHHHH....',
  '.....HHHHHH.....',
  '....BBBBBBBB....',
  '...BBBBBBBBBB...',
  '...SBBBBBBBBS...',
  '...SBBBBBBBBS...',
  '....LLL..LLL....',
  '....LLL..LLL....',
  '....DDD..DDD....',
  '................',
];

const humanLeft = [
  '................',
  '................',
  '.....HHHHHH.....',
  '....HHHHHHHH....',
  '....SSSSHHHH....',
  '....SeSSSHHH....',
  '....SSSSSHHH....',
  '.....SSSSSS.....',
  '....BBBBBBBB....',
  '....BBBBBBBB....',
  '...SSBBBBBBB....',
  '....BBBBBBBB....',
  '....LLL.LLL.....',
  '....LLL.LLL.....',
  '....DDD.DDD.....',
  '................',
];

function mirror(art) {
  return art.map((row) => row.split('').reverse().join(''));
}

function humanoid(hair, tunic, tunicDark) {
  const pal = {
    H: hair, S: '#eec39a', e: '#26232a', B: tunic, L: tunicDark, D: '#3b3345',
  };
  return {
    down: { pal, art: humanDown },
    up: { pal, art: humanUp },
    left: { pal, art: humanLeft },
    right: { pal, art: mirror(humanLeft) },
  };
}

const slimeArt = [
  '................',
  '................',
  '................',
  '................',
  '................',
  '......gggg......',
  '....gghggggg....',
  '...ghggggggga...',
  '...ggwgggggwg...',
  '..ggwkgggggwkg..',
  '..gggggggggggg..',
  '..ggggggmmgggg..',
  '..gggggggggggg..',
  '...gggggggggg...',
  '....agggggga....',
  '................',
];

const batArt = [
  '................',
  '................',
  '................',
  '..b..........b..',
  '..bb........bb..',
  '..bbb.bbbb.bbb..',
  '..bbbbbbbbbbbb..',
  '...bbBBBBBBbb...',
  '....BrBBBBrB....',
  '....BBBBBBBB....',
  '.....BBBBBB.....',
  '.....B.BB.B.....',
  '......B..B......',
  '................',
  '................',
  '................',
];

const chestClosed = [
  '................',
  '................',
  '................',
  '................',
  '...oooooooooo...',
  '..oaaaaaaaaaao..',
  '..oaaaaaaaaaao..',
  '..oaaaaggaaaao..',
  '..oooooooooooo..',
  '..obbbbggbbbbo..',
  '..obbbbggbbbbo..',
  '..obbbbbbbbbbo..',
  '..obbbbbbbbbbo..',
  '..oooooooooooo..',
  '................',
  '................',
];

const chestOpen = [
  '................',
  '................',
  '..oooooooooooo..',
  '..oaaaaaaaaaao..',
  '..oaaaaaaaaaao..',
  '..oooooooooooo..',
  '..okkkkkkkkkko..',
  '..okkkkkkkkkko..',
  '..oooooooooooo..',
  '..obbbbggbbbbo..',
  '..obbbbggbbbbo..',
  '..obbbbbbbbbbo..',
  '..obbbbbbbbbbo..',
  '..oooooooooooo..',
  '................',
  '................',
];

const chestPal = {
  o: '#4a3421', a: '#a06a37', b: '#8a5a2b', g: '#f7c948', k: '#1c1410',
};

const sparkleArt = [
  '................',
  '................',
  '................',
  '................',
  '.......y........',
  '.......y........',
  '......ywy.......',
  '....yywwwyy.....',
  '......ywy.......',
  '.......y........',
  '.......y........',
  '................',
  '................',
  '................',
  '................',
  '................',
];

const beaconBase = [
  '................',
  '................',
  '................',
  '................',
  '................',
  '................',
  '...bssssssssb...',
  '...bs######sb...',
  '....bssssssb....',
  '.....bssssb.....',
  '.....bssssb.....',
  '.....bssssb.....',
  '....bssssssb....',
  '...bssssssssb...',
  '...bbbbbbbbbb...',
  '................',
];

const beaconLit = [
  '................',
  '......r..r......',
  '.....ryrryr.....',
  '.....ryyyyr.....',
  '....ryywwyyr....',
  '.....ryywyr.....',
  '...bssssssssb...',
  '...bs&&&&&&sb...',
  '....bssssssb....',
  '.....bssssb.....',
  '.....bssssb.....',
  '.....bssssb.....',
  '....bssssssb....',
  '...bssssssssb...',
  '...bbbbbbbbbb...',
  '................',
];

const lockedDoor = [
  'ssssssssssssssss',
  'sbbbbbbbbbbbbbbs',
  'sbaaaaaaaaaaaabs',
  'sbaaaaaaaaaaaabs',
  'sbaabaabaabaabbs',
  'sbaaaaaaaaaaaabs',
  'sbaaaaggaaaaaabs',
  'sbaaaggggaaaaabs',
  'sbaaaaggaaaaaabs',
  'sbaaaaagaaaaaabs',
  'sbaabaabaabaabbs',
  'sbaaaaaaaaaaaabs',
  'sbaaaaaaaaaaaabs',
  'sbaaaaaaaaaaaabs',
  'sbbbbbbbbbbbbbbs',
  'ssssssssssssssss',
];

const heartArt = [
  '................',
  '................',
  '................',
  '................',
  '...rr....rr.....',
  '..rwrr..rrrr....',
  '..rwrrrrrrrr....',
  '..rrrrrrrrrr....',
  '...rrrrrrrr.....',
  '....rrrrrr......',
  '.....rrrr.......',
  '......rr........',
  '................',
  '................',
  '................',
  '................',
];

const coinArt = [
  '................',
  '................',
  '................',
  '................',
  '.....gggg.......',
  '....gywwyg......',
  '...gywggyyg.....',
  '...gwgggggg.....',
  '...gwgggggg.....',
  '...gygggggg.....',
  '....gyggyg......',
  '.....gggg.......',
  '................',
  '................',
  '................',
  '................',
];

const keyArt = [
  '................',
  '................',
  '................',
  '................',
  '....ggg.........',
  '...g...g........',
  '...g...g........',
  '....ggg.........',
  '.....g..........',
  '.....g..........',
  '.....gg.........',
  '.....g..........',
  '.....gg.........',
  '................',
  '................',
  '................',
];

// ember cell: armored capsule with a glowing orange core
const shardArt = [
  '................',
  '................',
  '................',
  '.....ooo........',
  '....ossso.......',
  '....osyso.......',
  '....oyryo.......',
  '....oyrro.......',
  '....oyrro.......',
  '....osyso.......',
  '....ossso.......',
  '.....ooo........',
  '................',
  '................',
  '................',
  '................',
];

const signArt = [
  '................',
  '................',
  '................',
  '...oooooooooo...',
  '..oaaaaaaaaaao..',
  '..oabbabbabbao..',
  '..oaaaaaaaaaao..',
  '..oabbbabbaaao..',
  '..oaaaaaaaaaao..',
  '...oooooooooo...',
  '......odao......',
  '......odao......',
  '......odao......',
  '......odao......',
  '................',
  '................',
];

const ringArt = [
  '................',
  '................',
  '................',
  '................',
  '................',
  '......ww........',
  '.....wggw.......',
  '....g....g......',
  '....g....g......',
  '....g....g......',
  '.....gggg.......',
  '................',
  '................',
  '................',
  '................',
  '................',
];

export const SPRITES = {
  player: humanoid('#7a4a21', '#2e7d5b', '#1e5a41'),
  elder: humanoid('#d8d8d8', '#e9dfc9', '#b9ae93'),
  merchant: humanoid('#33272e', '#7b4b94', '#5a3370'),
  fisherman: humanoid('#c95a1e', '#2e5d8d', '#1d3f63'),
  villager: humanoid('#3b2a1a', '#b0413e', '#8f3330'),
  slime: {
    idle: {
      pal: { g: '#4fa64f', h: '#7fd07f', a: '#3a8a3a', w: '#f4f4f4', k: '#1c1c24', m: '#2f6f2f' },
      art: slimeArt,
    },
  },
  boss: {
    idle: {
      pal: { g: '#d95d39', h: '#f2a65a', a: '#a8402a', w: '#ffe8a3', k: '#341009', m: '#8a2f1d' },
      art: slimeArt,
    },
  },
  bat: {
    idle: { pal: { b: '#4a3b63', B: '#6b5591', r: '#ff5a5a' }, art: batArt },
  },
  chestClosed: { pal: chestPal, art: chestClosed },
  chestOpen: { pal: chestPal, art: chestOpen },
  sparkle: { pal: { y: '#f7c948', w: '#fff7d6' }, art: sparkleArt },
  beacon: {
    pal: { b: '#5c5c66', s: '#9a9aa2', '#': '#2b2833' },
    art: beaconBase,
  },
  beaconLit: {
    pal: { b: '#5c5c66', s: '#9a9aa2', '&': '#ff9e2c', r: '#e64539', y: '#f7c948', w: '#fff7d6' },
    art: beaconLit,
  },
  lockedDoor: {
    pal: { s: '#2b2833', b: '#5c4c3c', a: '#8d7761', g: '#f7c948' },
    art: lockedDoor,
  },
  heart: { pal: { r: '#e64539', w: '#ff9e9e' }, art: heartArt },
  coin: { pal: { g: '#c19a49', y: '#f7c948', w: '#fff7d6' }, art: coinArt },
  key: { pal: { g: '#f7c948' }, art: keyArt },
  shard: { pal: { o: '#3a4652', s: '#7d8d99', r: '#e64539', y: '#ff9e2c' }, art: shardArt },
  sign: { pal: { o: '#4a3421', a: '#a06a37', b: '#4a3421', d: '#6d4c2f' }, art: signArt },
  ring: { pal: { w: '#fff7d6', g: '#f7c948' }, art: ringArt },
};

// Render a {pal, art} def onto a 2D context at (dx, dy), pixel size px.
export function drawDef(ctx, def, dx, dy, px = 1) {
  const { pal, art } = def;
  for (let y = 0; y < art.length; y++) {
    const row = art[y];
    for (let x = 0; x < row.length; x++) {
      const ch = row[x];
      if (ch === '.') continue;
      const color = pal[ch];
      if (!color) continue;
      ctx.fillStyle = color;
      ctx.fillRect(dx + x * px, dy + y * px, px, px);
    }
  }
}
