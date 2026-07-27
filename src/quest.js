// Quest + dialogue logic. Pure functions over the state object so node tests
// can drive the whole quest line without a DOM.
//
// Sci-fi theme: the settlement's signal beacon is dark; three Ember Cells
// (power cells) will reignite it. State fields keep their original names
// (shards/coins/hearts) — they are engine currency; only the fiction changed.

export const HEART_PRICE = 10;

export function newQuestState() {
  return {
    coins: 0,     // scrap
    hearts: 3,
    maxHearts: 3,
    shards: 0,    // ember cells
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
            'Overseer Rowan: Ah, you came. The signal beacon has gone dark, and the wastes grow bold.',
            'Its three Ember Cells were scattered: one deep in the bio-dome overgrowth, one on the coolant-canal isle, one in the derelict mine.',
            'Bring them to the beacon in the plaza and reignite it. Take my old arc-cutter — and watch yourself out there.',
          ],
          effects: { set: { talkedElder: true } },
        };
      }
      if (state.shards >= 3 && !f.beaconLit) {
        return { lines: ['Overseer Rowan: You have all three cells! Quick — to the beacon in the plaza!'] };
      }
      if (f.beaconLit) {
        return { lines: ['Overseer Rowan: The signal burns again. Emberwood owes you everything, hero.'] };
      }
      return {
        lines: [
          `Overseer Rowan: ${state.shards} of 3 cells so far.`,
          'The overgrowth maze lies northwest. The isle cache waits past the east walkway. The mine... you will need a keycard. Ask along the shore.',
        ],
      };

    case 'fisherman':
      if (!f.hasRing && !f.hasCaveKey) {
        return {
          lines: [
            'Old Finn: Bah! Dropped my wife\'s ring somewhere in this dust. Fifty years I kept it safe...',
            'If you spot a glint on the shore, bring it to me. I\'d trade you the old mine keycard for it, and gladly.',
          ],
        };
      }
      if (f.hasRing && !f.hasCaveKey) {
        return {
          lines: [
            'Old Finn: My ring! You wonderful wanderer!',
            'Here — the keycard to the derelict mine, as promised. Mind the drones. And the big one.',
          ],
          effects: { set: { hasCaveKey: true, gaveRing: true } },
        };
      }
      return { lines: ['Old Finn: The canal fish bite better now that the sludge keeps its distance. Mind the mine, friend.'] };

    case 'merchant':
      if (!f.boughtHeart) {
        if (state.coins >= HEART_PRICE) {
          return {
            lines: [
              `MARO-7: A Vitality Module, for just ${HEART_PRICE} scrap? For you — deal!`,
              'You feel sturdier. Max hearts +1, and topped right up.',
            ],
            effects: { coins: -HEART_PRICE, heartContainer: true, set: { boughtHeart: true } },
          };
        }
        return { lines: [`MARO-7: A genuine Vitality Module! Yours for ${HEART_PRICE} scrap. Caches and sludge, friend — the wastes provide.`] };
      }
      return { lines: ['MARO-7: Best customer this cycle. Alas, that was my only Vitality Module.'] };

    case 'villager':
      return {
        lines: [
          'Pip: Sludge got the isle cache surrounded — take the walkway on the east side of the canal.',
          'And whatever glows in the mine... Pip is NOT going in there to check.',
        ],
      };

    default:
      return { lines: ['...'] };
  }
}

export function beaconInteract(state) {
  if (state.flags.beaconLit) {
    return { lines: ['The signal beacon roars with warm ember light.'] };
  }
  if (state.shards >= 3) {
    return {
      lines: [
        'You slot the three Ember Cells into the cold cradle...',
        'FWOOM! The beacon core ignites in glorious flame!',
      ],
      effects: { set: { beaconLit: true } },
    };
  }
  return { lines: [`The beacon is cold. Sockets for three cells — you carry ${state.shards}.`] };
}

export function lockedDoorInteract(state) {
  if (state.flags.hasCaveKey) {
    return { lines: ['The keycard reader blinks green. The blast door grinds open.'], effects: { set: { doorOpen: true } } };
  }
  return { lines: ['Sealed tight. A keycard reader blinks red. Someone must still hold the card.'] };
}

export function sparkleInteract(state) {
  return { lines: ['You dig in the dust... a golden ring! Old Finn will want to see this.'], effects: { set: { hasRing: true } } };
}

export function chestLootLines(loot) {
  if (loot.shard) return [`You found an EMBER CELL! (${loot.shard} of 3)`];
  if (loot.coins) return [`You salvaged ${loot.coins} scrap!`];
  return ['Empty. How disappointing.'];
}
