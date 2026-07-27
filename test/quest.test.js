import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  newQuestState, applyEffects, npcDialogue, beaconInteract,
  lockedDoorInteract, sparkleInteract, terminalText, itemPickup,
  INTRO_LINES, HEART_PRICE, questJournal,
  BASE_PROJECTS, projectStatus, buyProject, rankFor, grantXp,
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

test('merchant sells one heart container, then one arc capacitor', () => {
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

  // second sink: arc capacitor pitch when broke, sale at 30+
  assert.match(talk(s, 'merchant').lines[0], /Arc Capacitor/i);
  assert.ok(!s.flags.boughtDamage);
  s.coins = 35;
  talk(s, 'merchant');
  assert.ok(s.flags.boughtDamage, 'capacitor purchased');
  assert.equal(s.coins, 5);

  s.coins = 90;
  talk(s, 'merchant');
  assert.equal(s.coins, 90, 'shelves bare after both purchases');
  assert.equal(s.maxHearts, 4);
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

test('quest journal tracks every quest through its states', () => {
  const s = newQuestState();
  let j = Object.fromEntries(questJournal(s));
  assert.equal(Object.keys(j).length, 6, 'journal lists rank + main + 4 side quests');
  assert.match(j['SALVAGE RANK — DRIFTER'], /xp 0 \/ 20/);
  assert.match(j['MAIN — REIGNITE THE BEACON'], /0 of 3/);
  assert.match(j['THE CANAL FILTER'], /locked/);

  s.flags.hasRing = true;
  j = Object.fromEntries(questJournal(s));
  assert.match(j["BEA'S RING"], /Return the ring/);

  s.flags.gaveRing = true;
  s.flags.hasCaveKey = true;
  s.flags.petFound = true;
  s.flags.filterPart = true;
  s.flags.log1 = true;
  s.shards = 3;
  j = Object.fromEntries(questJournal(s));
  assert.match(j['MAIN — REIGNITE THE BEACON'], /Take them to the beacon/);
  assert.match(j['BOLT COME HOME'], /Take it home/);
  assert.match(j['THE CANAL FILTER'], /Bring the pump filter/);
  assert.match(j['THE ARCHIVE LOGS'], /1 of 3/);

  s.flags.beaconLit = true;
  s.flags.petReturned = true;
  s.flags.filterGiven = true;
  s.flags.log2 = true;
  s.flags.log3 = true;
  s.flags.logsDone = true;
  j = Object.fromEntries(questJournal(s));
  for (const [k, v] of Object.entries(j)) {
    if (k.startsWith('SALVAGE RANK')) continue;
    assert.match(v, /done\./);
  }
});

test('salvage ranks: thresholds, rank-up detection, Beacon-Keeper heart', () => {
  const s = newQuestState();
  assert.equal(rankFor(0), 0);
  assert.equal(rankFor(19), 0);
  assert.equal(rankFor(20), 1);
  assert.equal(rankFor(119), 3);
  assert.equal(rankFor(500), 4);
  assert.equal(grantXp(s, 10), null, 'no rank-up at 10xp');
  const up = grantXp(s, 12);
  assert.equal(up.name, 'Scrapper');
  s.xp = 118;
  const bk = grantXp(s, 10);
  assert.equal(bk.name, 'Beacon-Keeper');
  assert.equal(s.maxHearts, 4, 'max rank grants +1 heart');
  assert.equal(s.hearts, 4);
});

test('base projects: statuses, purchase, no double-build', () => {
  const s = newQuestState();
  const lamps = BASE_PROJECTS[0];
  assert.equal(projectStatus(s, lamps), 'NEED SCRAP');
  s.coins = 100;
  assert.equal(projectStatus(s, lamps), 'AVAILABLE');
  const built = buyProject(s, 'baseLamps');
  assert.equal(built.id, 'baseLamps');
  assert.equal(s.coins, 85);
  assert.ok(s.flags.baseLamps);
  assert.equal(s.xp, 8, 'building grants xp');
  assert.equal(projectStatus(s, lamps), 'BUILT');
  assert.equal(buyProject(s, 'baseLamps'), null, 'cannot build twice');
  for (const id of ['baseGreenhouse', 'baseRelay', 'baseInfirmary']) buyProject(s, id);
  assert.equal(s.coins, 0, 'all four projects cost exactly 100 scrap');
  const total = BASE_PROJECTS.reduce((a, p) => a + p.cost, 0);
  assert.equal(total, 100);
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
