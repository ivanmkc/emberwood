import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const ROOMS_DIR = join(ROOT, 'assets', 'rooms');

function platePath(room) {
  if (room === 'anchorroom') {
    const clean = join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor-clean.png');
    if (existsSync(clean)) return clean;
    return join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor.png');
  }
  return join(ROOT, 'docs', 'art-options', 'rooms', room, 'plate.png');
}

test('every room with plateHash was built from its current plate', () => {
  const files = readdirSync(ROOMS_DIR).filter((f) => f.endsWith('.instances.json'));
  let checked = 0;
  for (const f of files) {
    const room = f.replace('.instances.json', '');
    const inst = JSON.parse(readFileSync(join(ROOMS_DIR, f), 'utf8'));
    if (!inst.plateHash) continue;
    const pp = platePath(room);
    assert.ok(existsSync(pp), `${room}: plate file missing at ${pp}`);
    const actual = createHash('sha256').update(readFileSync(pp)).digest('hex');
    assert.equal(actual, inst.plateHash,
      `${room}: collision built from stale plate (plateHash mismatch)`);
    checked++;
  }
  assert.ok(checked > 0, 'no rooms carry plateHash — pipeline not producing it');
});
