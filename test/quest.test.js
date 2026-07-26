import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  newQuestState, applyEffects, npcDialogue, beaconInteract,
  lockedDoorInteract, sparkleInteract, HEART_PRICE,
} from '../src/quest.js';

function talk(state, id) {
  const r = npcDialogue(id, state);
  applyEffects(state, r.effects);
  return r;
}

test('full quest line end to end', () => {
  const s = newQuestState();

  // elder intro
  assert.ok(!s.flags.talkedElder);
  const intro = talk(s, 'elder');
  assert.ok(intro.lines.length >= 2);
  assert.ok(s.flags.talkedElder);
  assert.match(talk(s, 'elder').lines[0], /0 of 3/);

  // fisherman wants his ring
  assert.match(talk(s, 'fisherman').lines[0], /ring/i);
  assert.ok(!s.flags.hasCaveKey);

  // find the ring, hand it over
  applyEffects(s, sparkleInteract(s).effects);
  assert.ok(s.flags.hasRing);
  talk(s, 'fisherman');
  assert.ok(s.flags.hasCaveKey, 'fisherman should hand over the cave key');
  assert.ok(s.flags.gaveRing);

  // locked door: opens only with the key
  const fresh = newQuestState();
  assert.ok(!lockedDoorInteract(fresh).effects, 'door must not open without key');
  const doorRes = lockedDoorInteract(s);
  applyEffects(s, doorRes.effects);
  assert.ok(s.flags.doorOpen);

  // beacon refuses until 3 shards
  assert.ok(!beaconInteract(s).effects);
  s.shards = 3;
  const lit = beaconInteract(s);
  applyEffects(s, lit.effects);
  assert.ok(s.flags.beaconLit, 'beacon should light with 3 shards');
  assert.match(talk(s, 'elder').lines[0], /burns again/i);
});

test('merchant sells exactly one heart container for 10 coins', () => {
  const s = newQuestState();
  talk(s, 'merchant');
  assert.equal(s.maxHearts, 3, 'no sale when broke');

  s.coins = HEART_PRICE + 2;
  s.hearts = 1;
  talk(s, 'merchant');
  assert.equal(s.maxHearts, 4);
  assert.equal(s.hearts, 4, 'purchase fully heals');
  assert.equal(s.coins, 2);
  assert.ok(s.flags.boughtHeart);

  s.coins = 50;
  talk(s, 'merchant');
  assert.equal(s.maxHearts, 4, 'only one container in stock');
  assert.equal(s.coins, 50);
});

test('applyEffects clamps and accumulates', () => {
  const s = newQuestState();
  applyEffects(s, { coins: 5 });
  applyEffects(s, { coins: -100 });
  assert.equal(s.coins, 0, 'coins never negative');
  applyEffects(s, { shard: 1 });
  applyEffects(s, { shard: 1 });
  assert.equal(s.shards, 2);
  s.hearts = 1;
  applyEffects(s, { heal: true });
  assert.equal(s.hearts, s.maxHearts);
});
