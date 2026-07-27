// Map data: ASCII tile grids + entities + portals. Pure data, node-testable.
//
// Tile legend (see tiles.js): . grass  , flowers  # tree  ~ water  = bridge
// s sand  M rock  p path  w wall  f floor  h house  o doormat  C cave mouth
// d cave floor  W cave wall  c carpet

const M30 = 'M'.repeat(30);
const D30 = '.'.repeat(30);
const D44 = '.'.repeat(44);

// Forest maze occupies x2..15 (14 wide), y3..12.
const overworldRows = [
  'M'.repeat(48),                                              // y0
  'M'.repeat(48),                                              // y1
  '##' + '##############' + M30 + '##',                        // y2
  '##' + '#............#' + M30 + '##',                        // y3
  '##' + '#.####.#####.#' + 'M'.repeat(14) + 'C' + 'M'.repeat(15) + '##', // y4
  '##' + '#.#........#.#' + 'M'.repeat(14) + '.' + 'M'.repeat(15) + '##', // y5
  '##' + '#.#.######.#.#' + 'M'.repeat(14) + '.' + 'M'.repeat(15) + '##', // y6
  '##' + '#.#........#.#' + 'MM' + '.'.repeat(27) + 'M' + '##',           // y7
  '##' + '#.########.#.#' + D30 + '##',                        // y8
  '##' + '#..........#.#' + D30 + '##',                        // y9
  '##' + '######.#####.#' + D30 + '##',                        // y10
  '##' + '######.#####.#' + D30 + '##',                        // y11
  '##' + '######.#####.#' + D30 + '##',                        // y12
  '##' + D44 + '##',                                           // y13
  '##' + D44 + '##',                                           // y14
  '##' + D44 + '##',                                           // y15
  '##' + '.'.repeat(14) + '~'.repeat(14) + '.'.repeat(16) + '##',           // y16
  '##' + '.'.repeat(14) + '~'.repeat(14) + '...hhhh...hhhh..' + '##',       // y17
  '##' + '.'.repeat(14) + '~'.repeat(14) + '...HDHH...HDHH..' + '##',       // y18
  '##' + '.'.repeat(14) + '~~~' + '.....' + '~~~~~~' + '....o......o....' + '##', // y19
  '##' + '.'.repeat(14) + '~~~' + '.....' + '~~~~~~' + '.'.repeat(16) + '##',     // y20
  '##' + '.'.repeat(14) + '~~~' + '.....' + '======' + '.'.repeat(16) + '##',     // y21
  '##' + '.'.repeat(14) + '~~~' + '.....' + '~~~~~~' + '..pppppppp......' + '##', // y22
  '##' + '.'.repeat(14) + '~'.repeat(14) + '..pppppppp......' + '##',       // y23
  '##' + '.'.repeat(14) + '~'.repeat(14) + '..pppppppp......' + '##',       // y24
  '##' + '.'.repeat(14) + '~'.repeat(14) + '..pppppppp......' + '##',       // y25
  '##' + '.'.repeat(11) + 's'.repeat(16) + '...pppppppp......' + '##',      // y26
  '##' + '.'.repeat(11) + 's'.repeat(16) + '...pppppppp......' + '##',      // y27
  '##' + D44 + '##',                                           // y28
  '##' + D44 + '##',                                           // y29
  '##' + '......##' + '.'.repeat(36) + '##',                   // y30
  '##' + D44 + '##',                                           // y31
  '##' + D44 + '##',                                           // y32
  '##' + D44 + '##',                                           // y33
  '#'.repeat(48),                                              // y34
  '#'.repeat(48),                                              // y35
];

// Flower / decor overrides applied after parsing: [x, y, char]
const overworldDecor = [
  [14, 3, 'o'], // Eden Shelf hatch pad, deep in the overgrowth maze
  [7, 14, ','], [11, 15, ','], [20, 13, ','], [33, 14, ','],
  [5, 29, ','], [14, 31, ','], [25, 30, ','], [36, 31, ','], [42, 30, ','],
  [40, 14, ','], [44, 21, ','], [19, 29, ','], [31, 12, ','],
  [40, 32, '#'], [6, 32, '#'], [22, 32, '#'], [44, 13, '#'],
  // worn trail: plaza -> north field -> mountain pass
  [38, 21, 'p'], [38, 20, 'p'], [38, 19, 'p'], [38, 18, 'p'], [38, 17, 'p'],
  [38, 16, 'p'], [38, 15, 'p'], [38, 14, 'p'], [38, 13, 'p'],
  [37, 13, 'p'], [36, 13, 'p'], [35, 13, 'p'], [34, 13, 'p'], [33, 13, 'p'],
  [32, 13, 'p'], [31, 13, 'p'], [30, 13, 'p'],
  [30, 12, 'p'], [30, 11, 'p'], [30, 10, 'p'], [30, 9, 'p'], [30, 8, 'p'],
  // short spur: plaza -> shore
  [29, 26, 'p'], [30, 26, 'p'], [31, 26, 'p'],
  // lone trees breaking up the fields
  [5, 17, '#'], [9, 19, '#'], [6, 24, '#'], [11, 23, '#'],
  [19, 30, '#'], [26, 31, '#'], [33, 31, '#'], [43, 24, '#'],
  [44, 17, '#'], [32, 9, '#'], [24, 10, '#'], [37, 10, '#'],
  [42, 8, '#'], [20, 15, '#'],
  // glowing lichen spreads
  [4, 20, ','], [13, 17, ','], [8, 26, ','], [18, 12, ','], [27, 8, ','],
  [34, 9, ','], [41, 11, ','], [44, 29, ','], [15, 33, ','], [28, 33, ','],
  [37, 33, ','], [3, 15, ','], [23, 13, ','],
  // dusty west lakeshore
  [13, 16, 's'], [12, 17, 's'], [13, 18, 's'],
  // wreck of freight drone FRT-9 "Pelican" (rubble reef, south field)
  [24, 30, 'M'], [25, 30, 'M'], [25, 31, 'M'],
  // organic coastline: erode the lake rectangle
  [16, 16, '.'], [17, 16, '.'], [27, 16, '.'], [28, 16, '.'], [29, 16, '.'],
  [16, 17, '.'], [29, 17, '.'],
  [29, 24, '.'], [16, 24, 's'],
  [16, 25, 's'], [17, 25, 's'], [28, 25, 's'], [29, 25, '.'],
  [15, 18, '~'], [15, 19, '~'], [30, 22, '~'], [30, 23, '~'],
  // eroded plaza: broken plate edges
  [32, 22, '.'], [39, 22, ','], [32, 27, '.'], [34, 21, 'p'], [35, 21, 'p'],
  [33, 28, 'p'], [37, 28, 'p'], [40, 25, 'p'], [31, 24, 'p'],
  // wavy sand: dune spurs into the grass
  [13, 26, '.'], [14, 27, '.'], [17, 28, 's'], [18, 28, 's'], [19, 28, 's'],
  [26, 28, 's'], [27, 28, 's'], [12, 26, 's'], [11, 27, 's'],
];

const houseRows = [
  'wwwwwwwwwwwwww', // y0
  'wffffffffffffw', // y1
  'wffffffffffffw', // y2
  'wfffccccccfffw', // y3
  'wfffccccccfffw', // y4
  'wfffccccccfffw', // y5
  'wffffffffffffw', // y6
  'wffffffffffffw', // y7
  'wffffffffffffw', // y8
  'wwwwwwoowwwwww', // y9
];

const caveRows = [
  'W'.repeat(26),                          // y0
  'W'.repeat(26),                          // y1
  'WW' + 'd'.repeat(22) + 'WW',            // y2
  'WW' + 'd'.repeat(22) + 'WW',            // y3
  'WW' + 'd'.repeat(22) + 'WW',            // y4
  'WW' + 'd'.repeat(22) + 'WW',            // y5
  'WW' + 'd'.repeat(22) + 'WW',            // y6
  'WW' + 'd'.repeat(22) + 'WW',            // y7
  'W'.repeat(12) + 'd' + 'W'.repeat(13),   // y8
  'W'.repeat(12) + 'd' + 'W'.repeat(13),   // y9  (locked door entity here)
  'W'.repeat(12) + 'd' + 'W'.repeat(13),   // y10
  'WW' + 'd'.repeat(22) + 'WW',            // y11
  'WW' + 'd'.repeat(22) + 'WW',            // y12
  'WW' + 'd'.repeat(22) + 'WW',            // y13
  'WW' + 'd'.repeat(22) + 'WW',            // y14
  'WW' + 'd'.repeat(22) + 'WW',            // y15
  'W'.repeat(12) + 'd' + 'W'.repeat(13),   // y16 (exit portal)
  'W'.repeat(26),                          // y17
];

// The Eden Shelf: sealed agri-research dome, now Keeper Ivy's garden-shrine.
const biodomeRows = [
  'VVVVVVVVVVVVVVVVVVVV', // y0
  'VGGGGGGGGGGGGGGGGGGV', // y1
  'VGGVVGGGGGGGGVVGGGGV', // y2
  'VGGVVGGGVVGGGVVGGGGV', // y3
  'VGGGGGGGVVGGGGGGGGGV', // y4
  'VGVVGGGGGGGGVVGGGGGV', // y5
  'VGVVGGVVGGGGVVGGVVGV', // y6
  'VGGGGGVVGGGGGGGGVVGV', // y7
  'VGGGGGGGGGVVGGGGGGGV', // y8
  'VGVVGGGGGGVVGGGVVGGV', // y9
  'VGGGGGGGGGGGGGGGGGGV', // y10
  'VGGVVGGGVVGGGGVVGGGV', // y11
  'VGGGGGGGGGGGGGGGGGGV', // y12
  'VVVVVVVVVVGVVVVVVVVV', // y13 (hatch at x10)
];

// Foundry Gallery B-2: the casting line, below the boss chamber.
const mine2Rows = [
  'W'.repeat(24),             // y0
  'W'.repeat(24),             // y1
  'W' + 'ddddd' + 'W'.repeat(18),          // y2 (entrance corridor, portal at x1)
  'WWWWW' + 'd' + 'W'.repeat(18),          // y3
  'WW' + 'd'.repeat(18) + 'WWWW',          // y4
  'WW' + 'd'.repeat(20) + 'WW',            // y5
  'WWddWWWWWWddWWWWWWWWddWW',              // y6
  'WW' + 'd'.repeat(20) + 'WW',            // y7
  'WWddWWWWddddWWWWWWWWddWW',              // y8
  'WW' + 'd'.repeat(20) + 'WW',            // y9
  'WWWWWWddddddWWWWWWddddWW',              // y10
  'WW' + 'd'.repeat(20) + 'WW',            // y11
  'WW' + 'd'.repeat(18) + 'WWWW',          // y12
  'W'.repeat(24),             // y13
];

// The Harroways': Pip and Mara's habitat.
const homeRows = [
  'wwwwwwwwwwwwww', // y0
  'wffffffffffffw', // y1
  'wffffffffffffw', // y2
  'wfffccccccfffw', // y3
  'wfffccccccfffw', // y4
  'wfffccccccfffw', // y5
  'wffffffffffffw', // y6
  'wffffffffffffw', // y7
  'wffffffffffffw', // y8
  'wwwwwwoowwwwww', // y9
];

export const MAPS = {
  overworld: {
    id: 'overworld',
    rows: overworldRows,
    decor: overworldDecor,
    dark: false,
    portals: [
      { x: 30, y: 4, to: 'cave', tx: 12, ty: 15 },   // cave mouth
      { x: 34, y: 19, to: 'house', tx: 6, ty: 8 },   // elder's doormat
      { x: 41, y: 19, to: 'home', tx: 6, ty: 8 },    // Harroways' doormat
      { x: 14, y: 3, to: 'biodome', tx: 10, ty: 12 }, // Eden Shelf hatch
    ],
    deco: [
      // plaza lamps line the plating edges
      { type: 'lamp', x: 33, y: 22 }, { type: 'lamp', x: 40, y: 26 },
      { type: 'lamp', x: 31, y: 28 }, { type: 'lamp', x: 36, y: 21 },
      // market row: stall + goods against the Harroways' west wall
      { type: 'stall', x: 40, y: 22 },
      { type: 'crates', x: 43, y: 20 }, { type: 'rack', x: 44, y: 20 },
      // storage against the ops block south wall
      { type: 'crates', x: 33, y: 20 }, { type: 'crates', x: 35, y: 21 },
      // FRT-9 wreck site cluster
      { type: 'rack', x: 23, y: 30 }, { type: 'vat', x: 27, y: 31 },
      { type: 'pipe', x: 26, y: 29 }, { type: 'pipe', x: 22, y: 29 },
      // comms masts on the rock line + village east fence
      { type: 'mast', x: 33, y: 7 }, { type: 'mast', x: 44, y: 19 },
      // bushes hug the forest edge and the shoreline
      { type: 'bush', x: 5, y: 14 }, { type: 'bush', x: 12, y: 14 },
      { type: 'bush', x: 17, y: 13 }, { type: 'bush', x: 14, y: 20 },
      { type: 'tanktree', x: 43, y: 26 }, { type: 'bush', x: 34, y: 32 },
      { type: 'tanktree', x: 32, y: 21 }, { type: 'tanktree', x: 42, y: 24 },
      { type: 'junction', x: 33, y: 19 }, { type: 'junction', x: 39, y: 19 },
      // trailside fittings
      { type: 'pipe', x: 31, y: 14 }, { type: 'pipe', x: 37, y: 16 },
      { type: 'rock', x: 15, y: 20 }, { type: 'rock', x: 44, y: 31 },
      { type: 'rock', x: 29, y: 8 },
    ],
    entities: [
      { kind: 'chest', id: 'shard1', x: 9, y: 7, loot: { shard: 1 } },
      { kind: 'chest', id: 'forestCoins', x: 12, y: 6, loot: { coins: 8 } },
      { kind: 'chest', id: 'shard2', x: 20, y: 20, loot: { shard: 2 } },
      { kind: 'sparkle', id: 'ring', x: 17, y: 27 },
      { kind: 'beacon', id: 'beacon', x: 38, y: 25 },
      { kind: 'sign', id: 'beaconSign', x: 36, y: 25, text: ['Signal Beacon of Emberwood.', 'Dark since its Ember Cells were scattered...'] },
      { kind: 'charter', id: 'charter', x: 36, y: 23 },
      { kind: 'sign', id: 'forestSign', x: 8, y: 13, text: ['Bio-dome overgrowth. KEEP OUT.', 'They say something glints deep in the maze.'] },
      { kind: 'npc', id: 'merchant', x: 39, y: 23, sprite: 'merchant', name: 'MARO-7' },
      { kind: 'npc', id: 'fisherman', x: 24, y: 26, sprite: 'fisherman', name: 'Old Finn' },
      { kind: 'npc', id: 'villager', x: 37, y: 27, sprite: 'villager', name: 'Pip Harroway' },
      { kind: 'enemy', id: 'sl1', x: 10, y: 14, type: 'slime' },
      { kind: 'enemy', id: 'sl2', x: 26, y: 13, type: 'slime' },
      { kind: 'enemy', id: 'sl3', x: 21, y: 21, type: 'slime' },
      { kind: 'enemy', id: 'sl4', x: 22, y: 20, type: 'slime' },
      { kind: 'enemy', id: 'sl5', x: 12, y: 30, type: 'slime' },
      { kind: 'enemy', id: 'sl6', x: 30, y: 10, type: 'slime' },
      { kind: 'enemy', id: 'sl7', x: 36, y: 13, type: 'slime' },
      { kind: 'enemy', id: 'sl8', x: 25, y: 29, type: 'slime' },
      { kind: 'enemy', id: 'sl9', x: 40, y: 12, type: 'slime' },
      { kind: 'chest', id: 'wreckCoins', x: 24, y: 31, loot: { coins: 9 } },
      { kind: 'sign', id: 'wreckSign', x: 26, y: 30, text: ['Freight drone FRT-9 "PELICAN".', 'Last flight: 214 years ago. Cargo: unclaimed. Finders keepers, the wastes say.'] },
    ],
  },
  house: {
    id: 'house',
    rows: houseRows,
    decor: [],
    dark: false,
    portals: [
      { x: 6, y: 9, to: 'overworld', tx: 34, ty: 20 },
      { x: 7, y: 9, to: 'overworld', tx: 34, ty: 20 },
    ],
    entities: [
      { kind: 'npc', id: 'elder', x: 6, y: 3, sprite: 'elder', name: 'Overseer Rowan' },
      { kind: 'chest', id: 'houseCoins', x: 2, y: 1, loot: { coins: 5 } },
    ],
  },
  biodome: {
    id: 'biodome',
    rows: biodomeRows,
    decor: [],
    dark: false,
    portals: [
      { x: 10, y: 13, to: 'overworld', tx: 14, ty: 4 },
    ],
    deco: [
      { type: 'vat', x: 5, y: 2 }, { type: 'vat', x: 7, y: 3 },
      { type: 'vat', x: 14, y: 9 }, { type: 'rack', x: 2, y: 1 },
      { type: 'lamp', x: 11, y: 6 },
      { type: 'bush', x: 6, y: 10 }, { type: 'bush', x: 17, y: 4 },
      { type: 'pipe', x: 12, y: 10 },
    ],
    entities: [
      { kind: 'npc', id: 'keeper', x: 16, y: 1, sprite: 'keeper', name: 'Keeper Ivy' },
      { kind: 'terminal', id: 'logA', x: 3, y: 1 },
      { kind: 'item', id: 'petdrone', x: 18, y: 11 },
      { kind: 'chest', id: 'domeCoins', x: 18, y: 2, loot: { coins: 7 } },
      { kind: 'sign', id: 'domeSign', x: 9, y: 12, text: ['EDEN SHELF — AGRONOMY SECTION.', 'Authorized staff only. The garden does not know that anymore.'] },
      { kind: 'enemy', id: 'dsl1', x: 5, y: 8, type: 'slime' },
      { kind: 'enemy', id: 'dsl2', x: 13, y: 10, type: 'slime' },
      { kind: 'enemy', id: 'ddr1', x: 7, y: 5, type: 'bat' },
    ],
  },
  mine2: {
    id: 'mine2',
    rows: mine2Rows,
    decor: [],
    dark: true,
    portals: [
      { x: 1, y: 2, to: 'cave', tx: 22, ty: 2 },
    ],
    deco: [
      { type: 'rack', x: 4, y: 4 }, { type: 'rack', x: 18, y: 4 },
      { type: 'vat', x: 12, y: 7 },
      { type: 'crates', x: 7, y: 5 }, { type: 'crates', x: 16, y: 11 },
      { type: 'pipe', x: 10, y: 9 },
    ],
    entities: [
      { kind: 'terminal', id: 'logB', x: 19, y: 5 },
      { kind: 'chest', id: 'filterChest', x: 3, y: 11, loot: { item: 'filter' } },
      { kind: 'chest', id: 'foundryCoins', x: 20, y: 11, loot: { coins: 12 } },
      { kind: 'sign', id: 'foundrySign', x: 6, y: 4, text: ['FOUNDRY GALLERY B-2 — CASTING LINE.', 'Cells shipped: 44,801. Last shift never clocked out.'] },
      { kind: 'enemy', id: 'mdr1', x: 8, y: 7, type: 'bat' },
      { kind: 'enemy', id: 'mdr2', x: 15, y: 9, type: 'bat' },
      { kind: 'enemy', id: 'mdr3', x: 18, y: 11, type: 'bat' },
      { kind: 'enemy', id: 'msl1', x: 6, y: 9, type: 'slime' },
      { kind: 'enemy', id: 'msl2', x: 12, y: 11, type: 'slime' },
    ],
  },
  home: {
    id: 'home',
    rows: homeRows,
    decor: [],
    dark: false,
    portals: [
      { x: 6, y: 9, to: 'overworld', tx: 41, ty: 20 },
      { x: 7, y: 9, to: 'overworld', tx: 41, ty: 20 },
    ],
    deco: [
      { type: 'rack', x: 11, y: 1 },
    ],
    entities: [
      { kind: 'npc', id: 'mara', x: 4, y: 3, sprite: 'settler', name: 'Mara Harroway' },
      { kind: 'terminal', id: 'logC', x: 10, y: 1 },
      { kind: 'chest', id: 'homeCoins', x: 2, y: 1, loot: { coins: 6 } },
    ],
  },
  cave: {
    id: 'cave',
    rows: caveRows,
    decor: [],
    dark: true,
    portals: [
      { x: 12, y: 16, to: 'overworld', tx: 30, ty: 5 },
      { x: 23, y: 2, to: 'mine2', tx: 2, ty: 2 },
    ],
    entities: [
      { kind: 'lockedDoor', id: 'caveDoor', x: 12, y: 9 },
      { kind: 'chest', id: 'shard3', x: 12, y: 2, loot: { shard: 3 } },
      { kind: 'chest', id: 'caveCoins', x: 3, y: 3, loot: { coins: 10 } },
      { kind: 'enemy', id: 'boss', x: 12, y: 5, type: 'boss' },
      { kind: 'enemy', id: 'bat1', x: 6, y: 4, type: 'bat' },
      { kind: 'enemy', id: 'bat2', x: 19, y: 5, type: 'bat' },
      { kind: 'enemy', id: 'bat3', x: 5, y: 13, type: 'bat' },
      { kind: 'enemy', id: 'bat4', x: 20, y: 12, type: 'bat' },
    ],
  },
};

export const START = { map: 'overworld', x: 38, y: 26 };

// Parse rows + decor into a 2D char grid.
export function buildGrid(map) {
  const grid = map.rows.map((r) => r.split(''));
  for (const [x, y, ch] of map.decor) grid[y][x] = ch;
  return grid;
}
