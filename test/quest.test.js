import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  newQuestState, applyEffects, npcDialogue, beaconInteract,
  lockedDoorInteract, sparkleInteract, terminalText, itemPickup,
  INTRO_LINES, HEART_PRICE,
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

test('Bolt side quest: find in the dome, return to Pip', () => {
  const s = newQuestState();
  assert.match(talk(s, 'villager').lines[1], /Bolt/);
  applyEffects(s, itemPickup('petdrone').effects);
  assert.ok(s.flags.petFound);
  const ret = talk(s, 'villager');
  assert.match(ret.lines[0], /BOLT/i);
  assert.ok(s.flags.petReturned);
  assert.equal(s.coins, 8);
  assert.match(talk(s, 'villager').lines[0], /Bolt/);
});

test('filter side quest: Finn asks after keycard, pays 20 scrap', () => {
  const s = newQuestState();
  s.flags.hasCaveKey = true;
  s.flags.gaveRing = true;
  assert.match(talk(s, 'fisherman').lines[1], /filter/i);
  s.flags.filterPart = true;
  talk(s, 'fisherman');
  assert.ok(s.flags.filterGiven);
  assert.equal(s.coins, 20);
  assert.match(talk(s, 'fisherman').lines[0], /pump runs clean/i);
});

test('archive logs: three terminals unlock Rowan\'s synthesis + reward', () => {
  const s = newQuestState();
  s.flags.talkedElder = true;
  for (const id of ['logA', 'logB', 'logC']) {
    const t = terminalText(id, s);
    assert.ok(t.lines.length >= 2, `${id} should have lore text`);
    applyEffects(s, t.effects);
  }
  assert.ok(s.flags.log1 && s.flags.log2 && s.flags.log3);
  const synth = talk(s, 'elder');
  assert.match(synth.lines.join(' '), /quarantine/i);
  assert.ok(s.flags.logsDone);
  assert.equal(s.coins, 10);
  // synthesis only fires once
  const again = talk(s, 'elder');
  assert.ok(!again.lines.join(' ').match(/archive pay/i));
});

test('keeper Ivy: intro once, then pet hint, then post-beacon line', () => {
  const s = newQuestState();
  assert.match(talk(s, 'keeper').lines[0], /visitor/i);
  assert.ok(s.flags.metKeeper);
  s.flags.petFound = true;
  assert.match(talk(s, 'keeper').lines[0], /take it home/i);
  s.flags.petReturned = true;
  s.flags.beaconLit = true;
  assert.match(talk(s, 'keeper').lines[0], /light reaches/i);
});

test('intro transmission exists and mentions the beacon', () => {
  assert.ok(INTRO_LINES.length >= 2);
  assert.match(INTRO_LINES.join(' '), /beacon/i);
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
