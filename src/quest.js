// Quest + dialogue logic. Pure functions over the state object so node tests
// can drive the whole quest line without a DOM.
//
// Each result: { lines: string[], effects: {...} } — effects are applied by
// the game loop (and by tests) via applyEffects.

export const HEART_PRICE = 10;

export function newQuestState() {
  return {
    coins: 0,
    hearts: 3,
    maxHearts: 3,
    shards: 0,
    flags: {}, // talkedElder, hasRing, hasCaveKey, boughtHeart, doorOpen, beaconLit, bossDefeated
    opened: {}, // chest id -> true
    kills: 0,
  };
}

export function applyEffects(state, effects) {
  if (!effects) return;
  if (effects.set) Object.assign(state.flags, effects.set);
  if (effects.coins) state.coins = Math.max(0, state.coins + effects.coins);
  if (effects.shard) state.shards += 1;
  if (effects.heartContainer) {
    state.maxHearts += 1;
    state.hearts = state.maxHearts;
  }
  if (effects.heal) state.hearts = state.maxHearts;
}

export function npcDialogue(id, state) {
  const f = state.flags;
  switch (id) {
    case 'elder':
      if (!f.talkedElder) {
        return {
          lines: [
            'Elder Rowan: Ah, you came. The beacon has gone dark, and the woods grow bold.',
            'Three Ember Shards were scattered: one deep in the forest maze, one on the lake isle, one in the mountain cave.',
            'Bring them to the beacon in the square and light it once more. Take my old sword — and be careful out there.',
          ],
          effects: { set: { talkedElder: true } },
        };
      }
      if (state.shards >= 3 && !f.beaconLit) {
        return { lines: ['Elder Rowan: You have all three shards! Quick — to the beacon in the square!'] };
      }
      if (f.beaconLit) {
        return { lines: ['Elder Rowan: The beacon burns again. Emberwood owes you everything, hero.'] };
      }
      return {
        lines: [
          `Elder Rowan: ${state.shards} of 3 shards so far.`,
          'The forest maze lies northwest. The isle chest waits past the east bridge. The cave... you will need a key. Ask around the shore.',
        ],
      };

    case 'fisherman':
      if (!f.hasRing && !f.hasCaveKey) {
        return {
          lines: [
            'Old Finn: Bah! Dropped my wife\'s ring somewhere in this sand. Fifty years I kept it safe...',
            'If you spot a glint on the shore, bring it to me. I\'d trade you the old cave key for it, and gladly.',
          ],
        };
      }
      if (f.hasRing && !f.hasCaveKey) {
        return {
          lines: [
            'Old Finn: My ring! You wonderful wanderer!',
            'Here — the key to the mountain cave, as promised. Mind the bats. And the big one.',
          ],
          effects: { set: { hasCaveKey: true, gaveRing: true } },
        };
      }
      return { lines: ['Old Finn: The fish bite better now that the slimes keep their distance. Mind the cave, friend.'] };

    case 'merchant':
      if (!f.boughtHeart) {
        if (state.coins >= HEART_PRICE) {
          return {
            lines: [
              `Maro: A Heart Container, for just ${HEART_PRICE} coins? For you — deal!`,
              'You feel sturdier. Max hearts +1, and topped right up.',
            ],
            effects: { coins: -HEART_PRICE, heartContainer: true, set: { boughtHeart: true } },
          };
        }
        return { lines: [`Maro: A genuine Heart Container! Yours for ${HEART_PRICE} coins. Chests and slimes, friend — the land provides.`] };
      }
      return { lines: ['Maro: Best customer I\'ve had all season. Alas, that was my only Heart Container.'] };

    case 'villager':
      return {
        lines: [
          'Pip: Slimes got the isle chest surrounded — take the bridge on the east side of the lake.',
          'And whatever glows in the cave... Pip is NOT going in there to check.',
        ],
      };

    default:
      return { lines: ['...'] };
  }
}

export function beaconInteract(state) {
  if (state.flags.beaconLit) {
    return { lines: ['The beacon roars with warm ember light.'] };
  }
  if (state.shards >= 3) {
    return {
      lines: [
        'You set the three Ember Shards into the cold bowl...',
        'FWOOSH! The beacon erupts in glorious flame!',
      ],
      effects: { set: { beaconLit: true } },
    };
  }
  return { lines: [`The beacon is cold. Sockets for three shards — you carry ${state.shards}.`] };
}

export function lockedDoorInteract(state) {
  if (state.flags.hasCaveKey) {
    return { lines: ['The old key turns with a heavy CLUNK. The door grinds open.'], effects: { set: { doorOpen: true } } };
  }
  return { lines: ['Locked tight. The keyhole is worn but sturdy. Someone must have the key.'] };
}

export function sparkleInteract(state) {
  return { lines: ['You dig in the sand... a golden ring! Old Finn will want to see this.'], effects: { set: { hasRing: true } } };
}

export function chestLootLines(loot) {
  if (loot.shard) return [`You found an EMBER SHARD! (${loot.shard} of 3)`];
  if (loot.coins) return [`You found ${loot.coins} coins!`];
  return ['Empty. How disappointing.'];
}
