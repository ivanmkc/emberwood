import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..', 'src');

// Pixel-string art is coordinate data: a lookalike Unicode char (Cyrillic
// 'о' vs Latin 'o') silently corrupts a sprite. Em-dashes etc. in dialogue
// strings are allowed; art rows and code must stay ASCII except in quest.js
// prose. Gate: no invisible/confusable codepoints anywhere in src/.
const ALLOWED_NON_ASCII = new Set(['—', '’', '‘', '“', '”', '…', '·', '→']);

test('src/ contains no unexpected non-ASCII characters', () => {
  for (const f of readdirSync(SRC)) {
    if (!f.endsWith('.js')) continue;
    const body = readFileSync(join(SRC, f), 'utf8');
    const bad = [];
    for (let i = 0; i < body.length; i++) {
      const c = body[i];
      if (c.charCodeAt(0) > 126 && !ALLOWED_NON_ASCII.has(c)) {
        const line = body.slice(0, i).split('\n').length;
        bad.push(`${f}:${line} U+${c.charCodeAt(0).toString(16).toUpperCase()} '${c}'`);
      }
    }
    assert.deepEqual(bad, [], `confusable/non-ASCII chars found:\n${bad.join('\n')}`);
  }
});
