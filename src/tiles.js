// Tile definitions. Maps are ASCII grids; each char is a tile.
// `art` is 16 rows of 16 chars indexing into `pal`.

export const TILE_SIZE = 16;

const grass = {
  pal: { a: '#3e8948', b: '#468f4f', c: '#63ab3f' },
  art: [
    'aaaaaaaaaaaaaaaa',
    'aabaaaaaaabaaaaa',
    'aaaaaaacaaaaaaaa',
    'aaaaaaaaaaaaabaa',
    'abaaaaaaaaaaaaaa',
    'aaaaaacaaaaaaaaa',
    'aaaaaaaaaaabaaaa',
    'aaabaaaaaaaaaaaa',
    'aaaaaaaaaacaaaaa',
    'aaaaaaabaaaaaaaa',
    'acaaaaaaaaaaabaa',
    'aaaaaaaaaaaaaaaa',
    'aaaabaaaacaaaaaa',
    'aaaaaaaaaaaaaaaa',
    'aabaaaaaaaaabaaa',
    'aaaaaaacaaaaaaaa',
  ],
};

const flowers = {
  pal: { a: '#3e8948', b: '#468f4f', r: '#e64539', y: '#f7c948', w: '#f4f4f4' },
  art: [
    'aaaaaaaaaaaaaaaa',
    'aabaaaaaaabaaaaa',
    'aaaaaaryaaaaaaaa',
    'aaaaaaraaaaaabaa',
    'abaaaaaaaaaaaaaa',
    'aaaaaaaaaaawaaaa',
    'aaaaaaaaaawwwaaa',
    'aaabaaaaaaawaaaa',
    'aaaaaaaaaaaaaaaa',
    'aayraaabaaaaaaaa',
    'aaryaaaaaaaaabaa',
    'aaaaaaaaaaaaaaaa',
    'aaaabaaaaaaawaaa',
    'aaaaaaaaaaawwaaa',
    'aabaaaaaaaaabaaa',
    'aaaaaaaaaaaaaaaa',
  ],
};

const tree = {
  pal: { a: '#3e8948', d: '#1e5128', e: '#2e7d32', f: '#61b752', t: '#6d4c2f' },
  art: [
    'aaaadddddddaaaaa',
    'aaddeeeeeeeddaaa',
    'adeeffeeeeeeedaa',
    'adeffeeeeeeeedaa',
    'deefeeeeeeefeeda',
    'deeeeeeeeeffeeda',
    'deeeeeeeeeeeeeda',
    'adeeeeeeeeeeedaa',
    'adeeeeeeeeeedaaa',
    'aaddeeeeeeddaaaa',
    'aaaaddtdddaaaaaa',
    'aaaaaatdaaaaaaaa',
    'aaaaaatdaaaaaaaa',
    'aaaaattddaaaaaaa',
    'aaaaaaaaaaaaaaaa',
    'aaaaaaaaaaaaaaaa',
  ],
};

const water = {
  pal: { a: '#2389da', b: '#1d78c1', c: '#5fb4e8' },
  art: [
    'aaaaaaaaaaaaaaaa',
    'aaaaaaaaaaaaaaaa',
    'aaccaaaaaaaaaaaa',
    'aaaaaaaaaaccaaaa',
    'aaaaaaaaaaaaaaaa',
    'abaaaaaaaaaaaaba',
    'aaaaaaccaaaaaaaa',
    'aaaaaaaaaaaaaaaa',
    'aaaaaaaaaaaaaaaa',
    'aaccaaaaaaaccaaa',
    'aaaaaaaaaaaaaaaa',
    'aaaaaabaaaaaaaaa',
    'aaaaaaaaaaaaaaaa',
    'accaaaaaaaaaccaa',
    'aaaaaaaaaaaaaaaa',
    'aaaaaaaaaaaaaaaa',
  ],
};

const bridge = {
  pal: { a: '#8a5a2b', b: '#6d4c2f', c: '#a06a37' },
  art: [
    'bbbbbbbbbbbbbbbb',
    'acacacacacacacac',
    'aaaaaaaaaaaaaaaa',
    'cacacacacacacaca',
    'aaaaaaaaaaaaaaaa',
    'acacacacacacacac',
    'aaaaaaaaaaaaaaaa',
    'bbbbbbbbbbbbbbbb',
    'bbbbbbbbbbbbbbbb',
    'aaaaaaaaaaaaaaaa',
    'cacacacacacacaca',
    'aaaaaaaaaaaaaaaa',
    'acacacacacacacac',
    'aaaaaaaaaaaaaaaa',
    'cacacacacacacaca',
    'bbbbbbbbbbbbbbbb',
  ],
};

const sand = {
  pal: { a: '#e8d5a3', b: '#dcc794', c: '#f2e4bb' },
  art: [
    'aaaaaaaaaaaaaaaa',
    'aabaaaaaacaaaaaa',
    'aaaaaaaaaaaaaaaa',
    'aaaaacaaaaaabaaa',
    'aaaaaaaaaaaaaaaa',
    'abaaaaaabaaaaaaa',
    'aaaaaaaaaaaaacaa',
    'aaaaaaaaaaaaaaaa',
    'aacaaaabaaaaaaaa',
    'aaaaaaaaaaaaaaaa',
    'aaaaaaaaaacaaaba',
    'aaaabaaaaaaaaaaa',
    'aaaaaaaaaaaaaaaa',
    'aacaaaaaabaaaaaa',
    'aaaaaaaaaaaaaaaa',
    'aaaaaaacaaaaabaa',
  ],
};

const rock = {
  pal: { a: '#7d7d85', b: '#5c5c66', c: '#9a9aa2', d: '#4a4a52' },
  art: [
    'bbcaabbbbbcaabbb',
    'bcaaaabbcaaaabbb',
    'caaaaaacaaaaaabb',
    'aaaaaaaaaaaaaabb',
    'aaaaaaaaaaaaaacb',
    'baaaaaaaaaaaaabb',
    'bbaaaaaabaaaabbb',
    'dbbaaaabdbaabbdb',
    'ddbbbbbdddbbbddd',
    'bbcaabbbbbcaabbb',
    'bcaaaabbcaaaabbb',
    'caaaaaacaaaaaabb',
    'aaaaaaaaaaaaaabb',
    'baaaaaaaaaaaaabb',
    'bbaaaaaabaaaabbb',
    'ddbbbbbdddbbbddd',
  ],
};

const path = {
  pal: { a: '#c2a878', b: '#b39a6b', c: '#d1ba8c' },
  art: [
    'aaaaaaaaaaaaaaaa',
    'aabaaaaaaaaacaaa',
    'aaaaaaaaaaaaaaaa',
    'aaaaaacaaaaaaaaa',
    'acaaaaaaaaabaaaa',
    'aaaaaaaaaaaaaaaa',
    'aaaabaaaaaaaaaca',
    'aaaaaaaaacaaaaaa',
    'aaaaaaaaaaaaaaaa',
    'abaaaaacaaaaabaa',
    'aaaaaaaaaaaaaaaa',
    'aaaacaaaaaabaaaa',
    'aaaaaaaaaaaaaaaa',
    'aaaaaaabaaaaaaac',
    'aacaaaaaaaaaaaaa',
    'aaaaaaaaaacaaaaa',
  ],
};

const wall = {
  pal: { a: '#8d7761', b: '#75634f', c: '#a08a72', d: '#5c4c3c' },
  art: [
    'aaaaaaadaaaaaaad',
    'aaaaaaadaaaaaaad',
    'aaaaaaadaaaaaaad',
    'dddddddddddddddd',
    'aaadaaaaaaadaaaa',
    'aaadaaaaaaadaaaa',
    'aaadaaaaaaadaaaa',
    'dddddddddddddddd',
    'aaaaaaadaaaaaaad',
    'aaaaaaadaaaaaaad',
    'aaaaaaadaaaaaaad',
    'dddddddddddddddd',
    'aaadaaaaaaadaaaa',
    'aaadaaaaaaadaaaa',
    'aaadaaaaaaadaaaa',
    'dddddddddddddddd',
  ],
};

const floor = {
  pal: { a: '#c9b795', b: '#bfab87', c: '#d6c6a6' },
  art: [
    'aaaaaaabaaaaaaab',
    'aaaaaaabaaaaaaab',
    'aaaaaaabaaaaaaab',
    'bbbbbbbbbbbbbbbb',
    'aaabaaaaaaabaaaa',
    'aaabaaaaaaabaaaa',
    'aaabaaaaaaabaaaa',
    'bbbbbbbbbbbbbbbb',
    'aaaaaaabaaaaaaab',
    'aaaaaaabaaaaaaab',
    'aaaaaaabaaaaaaab',
    'bbbbbbbbbbbbbbbb',
    'aaabaaaaaaabaaaa',
    'aaabaaaaaaabaaaa',
    'aaabaaaaaaabaaaa',
    'bbbbbbbbbbbbbbbb',
  ],
};

const houseRoof = {
  pal: { a: '#b0413e', b: '#8f3330', c: '#c95a52' },
  art: [
    'cccccccccccccccc',
    'abababababababab',
    'babababababababa',
    'abababababababab',
    'babababababababa',
    'abababababababab',
    'babababababababa',
    'abababababababab',
    'babababababababa',
    'abababababababab',
    'babababababababa',
    'abababababababab',
    'babababababababa',
    'abababababababab',
    'babababababababa',
    'bbbbbbbbbbbbbbbb',
  ],
};

const houseWall = {
  pal: { w: '#e9dfc9', b: '#8f3330', d: '#c9bda3', t: '#6d4c2f' },
  art: [
    'wwwwwwwwwwwwwwww',
    'wwwwwwwwwwwwwwww',
    'wwwbbbbwwbbbbwww',
    'wwwbddbwwbddbwww',
    'wwwbddbwwbddbwww',
    'wwwbbbbwwbbbbwww',
    'wwwwwwwwwwwwwwww',
    'wwwwwwwwwwwwwwww',
    'wwwwwwwwwwwwwwww',
    'wwwwwwwwwwwwwwww',
    'wwwwwwwwwwwwwwww',
    'wwwwwwwwwwwwwwww',
    'wwwwwwwwwwwwwwww',
    'wwwwwwwwwwwwwwww',
    'ttttwwwwwwwwtttt',
    'ttttwwwwwwwwtttt',
  ],
};

const houseDoor = {
  pal: { w: '#e9dfc9', t: '#6d4c2f', a: '#8a5a2b', g: '#f7c948' },
  art: [
    'wwwwwwwwwwwwwwww',
    'wwwwwwwwwwwwwwww',
    'wwwwttttttttwwww',
    'wwwttaaaaaattwww',
    'wwwtaaaaaaaatwww',
    'wwwtaaaaaaaatwww',
    'wwwtaaaaaaaatwww',
    'wwwtaaaaaaaatwww',
    'wwwtaaaaaagatwww',
    'wwwtaaaaaagatwww',
    'wwwtaaaaaaaatwww',
    'wwwtaaaaaaaatwww',
    'wwwtaaaaaaaatwww',
    'wwwtaaaaaaaatwww',
    'ttttaaaaaaaatttt',
    'ttttaaaaaaaatttt',
  ],
};

const doormat = {
  pal: { a: '#c2a878', d: '#6d4c2f', e: '#8a5a2b' },
  art: [
    'aaaaaaaaaaaaaaaa',
    'aaaaaaaaaaaaaaaa',
    'aaddddddddddddaa',
    'aadeeeeeeeeeedaa',
    'aadeddddddddedaa',
    'aadedaaaaaadedaa',
    'aadedaaaaaadedaa',
    'aadedaaaaaadedaa',
    'aadedaaaaaadedaa',
    'aadedaaaaaadedaa',
    'aadedaaaaaadedaa',
    'aadeddddddddedaa',
    'aadeeeeeeeeeedaa',
    'aaddddddddddddaa',
    'aaaaaaaaaaaaaaaa',
    'aaaaaaaaaaaaaaaa',
  ],
};

const caveMouth = {
  pal: { a: '#7d7d85', b: '#5c5c66', k: '#14141c', d: '#4a4a52' },
  art: [
    'bbbbbbbbbbbbbbbb',
    'bbaaabbbbbaaabbb',
    'baabbkkkkkkbbaab',
    'babkkkkkkkkkkbab',
    'abkkkkkkkkkkkkba',
    'abkkkkkkkkkkkkba',
    'bkkkkkkkkkkkkkkb',
    'bkkkkkkkkkkkkkkb',
    'bkkkkkkkkkkkkkkb',
    'bkkkkkkkkkkkkkkb',
    'dkkkkkkkkkkkkkkd',
    'dkkkkkkkkkkkkkkd',
    'dkkkkkkkkkkkkkkd',
    'dkkkkkkkkkkkkkkd',
    'dkkkkkkkkkkkkkkd',
    'dkkkkkkkkkkkkkkd',
  ],
};

const caveFloor = {
  pal: { a: '#4b4653', b: '#413c48', c: '#57515f' },
  art: [
    'aaaaaaaaaaaaaaaa',
    'aabaaaaaacaaaaaa',
    'aaaaaaaaaaaaaaaa',
    'aaaaacaaaaaabaaa',
    'aaaaaaaaaaaaaaaa',
    'abaaaaaabaaaaaaa',
    'aaaaaaaaaaaaacaa',
    'aaaaaaaaaaaaaaaa',
    'aacaaaabaaaaaaaa',
    'aaaaaaaaaaaaaaaa',
    'aaaaaaaaaacaaaba',
    'aaaabaaaaaaaaaaa',
    'aaaaaaaaaaaaaaaa',
    'aacaaaaaabaaaaaa',
    'aaaaaaaaaaaaaaaa',
    'aaaaaaacaaaaabaa',
  ],
};

const caveWall = {
  pal: { a: '#2b2833', b: '#211f28', c: '#3a3644', d: '#14141c' },
  art: [
    'bbcaabbbbbcaabbb',
    'bcaaaabbcaaaabbb',
    'caaaaaacaaaaaabb',
    'aaaaaaaaaaaaaabb',
    'aaaaaaaaaaaaaacb',
    'baaaaaaaaaaaaabb',
    'bbaaaaaabaaaabbb',
    'dbbaaaabdbaabbdb',
    'ddbbbbbdddbbbddd',
    'bbcaabbbbbcaabbb',
    'bcaaaabbcaaaabbb',
    'caaaaaacaaaaaabb',
    'aaaaaaaaaaaaaabb',
    'baaaaaaaaaaaaabb',
    'bbaaaaaabaaaabbb',
    'ddbbbbbdddbbbddd',
  ],
};

const carpet = {
  pal: { a: '#a34b4b', b: '#8c3d3d', c: '#c19a49' },
  art: [
    'cccccccccccccccc',
    'caaaaaaaaaaaaaac',
    'cabbbbbbbbbbbbac',
    'cabaaaaaaaaaabac',
    'cabaaaaaaaaaabac',
    'cabaaaccaaaaabac',
    'cabaaacaaaaaabac',
    'cabaaaccaaaaabac',
    'cabaaaaacaaaabac',
    'cabaaaccaaaaabac',
    'cabaaaaaaaaaabac',
    'cabaaaaaaaaaabac',
    'cabbbbbbbbbbbbac',
    'caaaaaaaaaaaaaac',
    'cccccccccccccccc',
    'cccccccccccccccc',
  ],
};

const voidTile = {
  pal: { k: '#0c0c12' },
  art: Array(16).fill('kkkkkkkkkkkkkkkk'),
};

const fence = {
  pal: { a: '#3e8948', b: '#468f4f', t: '#8a5a2b', d: '#6d4c2f' },
  art: [
    'aaaaaaaaaaaaaaaa',
    'aataaaaaaaaataaa',
    'aatdaaaaaaaatdaa',
    'aatdaaaaaaaatdaa',
    'atttttttttttttta',
    'adddddddddddddda',
    'aatdaaaaaaaatdaa',
    'aatdaaaaaaaatdaa',
    'atttttttttttttta',
    'adddddddddddddda',
    'aatdaaaaaaaatdaa',
    'aatdaaaaaaaatdaa',
    'aatdaaaaaaaatdaa',
    'aataaaaaaaaataaa',
    'aabaaaaaaaaaaaaa',
    'aaaaaaaaaaaaaaaa',
  ],
};

export const TILES = {
  '.': { name: 'grass', solid: false, def: grass },
  ',': { name: 'flowers', solid: false, def: flowers },
  '#': { name: 'tree', solid: true, def: tree },
  '~': { name: 'water', solid: true, def: water },
  '=': { name: 'bridge', solid: false, def: bridge },
  's': { name: 'sand', solid: false, def: sand },
  'M': { name: 'rock', solid: true, def: rock },
  'p': { name: 'path', solid: false, def: path },
  'w': { name: 'wall', solid: true, def: wall },
  'f': { name: 'floor', solid: false, def: floor },
  'h': { name: 'houseRoof', solid: true, def: houseRoof },
  'H': { name: 'houseWall', solid: true, def: houseWall },
  'D': { name: 'houseDoor', solid: true, def: houseDoor },
  'o': { name: 'doormat', solid: false, def: doormat },
  'C': { name: 'caveMouth', solid: false, def: caveMouth },
  'd': { name: 'caveFloor', solid: false, def: caveFloor },
  'W': { name: 'caveWall', solid: true, def: caveWall },
  'c': { name: 'carpet', solid: false, def: carpet },
  ' ': { name: 'void', solid: true, def: voidTile },
  'F': { name: 'fence', solid: true, def: fence },
};

export function isSolidChar(ch) {
  const t = TILES[ch];
  return !t || t.solid;
}
