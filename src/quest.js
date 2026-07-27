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
      if (f.log1 && f.log2 && f.log3 && !f.logsDone) {
        return {
          lines: [
            'Overseer Rowan: All three logs. Sit down, engineer. I have read these a hundred times in fragments and never once in order.',
            'The strain was ordered hungry. The cells came back drained. And the Quiet... the Quiet was a quarantine. They switched the network off on purpose — to starve whatever was feeding on it.',
            'Emberwood kept its beacon lit anyway. Not out of ignorance — out of stubbornness. "Someone has to leave a light on for the ones still out there." That is what this place is. Take this — archive pay, two centuries late.',
          ],
          effects: { coins: 10, set: { logsDone: true } },
        };
      }
      if (f.beaconLit) {
        return { lines: ['Overseer Rowan: The signal burns again. Emberwood owes you everything, hero.'] };
      }
      {
        const logCount = (f.log1 ? 1 : 0) + (f.log2 ? 1 : 0) + (f.log3 ? 1 : 0);
        const logLine = logCount > 0 && !f.logsDone
          ? `And those archive logs you keep finding — ${logCount} of 3. Bring me all three and I will tell you what they mean.`
          : 'If you find any old data terminals out there, read them. The archive is all we have left of the why.';
        return {
          lines: [
            `Overseer Rowan: ${state.shards} of 3 cells so far.`,
            'The overgrowth maze lies northwest. The isle cache waits past the east walkway. The mine... you will need a keycard. Ask along the shore.',
            logLine,
          ],
        };
      }

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
      if (f.filterPart && !f.filterGiven) {
        return {
          lines: [
            'Old Finn: That\'s a casting-line filter, right off the old foundry rig! The canal pump\'s been coughing for a decade.',
            'Twenty scrap, and I won\'t hear a word against it. Bea would\'ve liked you.',
          ],
          effects: { coins: 20, set: { filterGiven: true } },
        };
      }
      if (f.filterGiven) {
        return { lines: ['Old Finn: Pump runs clean as a hymn now. The fish are confused. So am I. Good work.'] };
      }
      return {
        lines: [
          'Old Finn: The canal fish bite better now that the sludge keeps its distance. Mind the mine, friend.',
          'Say — if you\'re headed down the foundry anyway... the casting line kept spare pump filters in the lower gallery. My canal pump is dying for one.',
        ],
      };

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
      if (f.petFound && !f.petReturned) {
        return {
          lines: [
            'Pip: BOLT! You found Bolt! Come here, you dumb little light bulb!',
            'Pip presses eight scrap into your hands. "It\'s all I have. It\'s worth it."',
          ],
          effects: { coins: 8, set: { petReturned: true } },
        };
      }
      if (f.petReturned) {
        return {
          lines: [
            'Pip: Bolt keeps trying to fly toward the dome again. NO, Bolt.',
            f.beaconLit ? 'Pip: When the beacon lit up, Bolt spun in circles for an hour. Same, honestly.'
              : 'Pip: Mom says the old dome used to feed the whole station. Hard to picture.',
          ],
        };
      }
      return {
        lines: [
          'Pip: Sludge got the isle cache surrounded — take the walkway on the east side of the canal.',
          'Pip: ...also, if you see a little round drone out there? That\'s Bolt. He\'s mine. He chased a glow into the overgrowth and never came home.',
        ],
      };

    case 'keeper':
      if (!f.metKeeper) {
        return {
          lines: [
            'Keeper Ivy: A visitor. The garden lets so few of you through these days.',
            'I keep the Eden Shelf. My predecessor hid one of the beacon\'s cells out in the overgrowth — "for safekeeping", the old fool. The maze took it like it takes everything.',
            'The sludge, the vines, all of it — none of it is evil, engineer. Just hungry, and nobody left to tell it when to stop.',
          ],
          effects: { set: { metKeeper: true } },
        };
      }
      if (f.petFound && !f.petReturned) {
        return { lines: ['Keeper Ivy: That little drone has been nesting by the east vats for days. Take it home to its child.'] };
      }
      if (f.beaconLit) {
        return { lines: ['Keeper Ivy: The light reaches even here, through the dome glass. The garden turned its leaves toward it. So did I.'] };
      }
      return {
        lines: [
          'Keeper Ivy: Mind the spores, and leave the vats be — they\'re graves of a sort.',
          'A small light zips around the east vats at night. Not one of mine. Someone misses it, I\'d wager.',
        ],
      };

    case 'mara':
      if (f.log3 && !f.beaconLit) {
        return { lines: ['Mara: You read the letter? Then you know. The Quiet wasn\'t a failure — it was a door closed on purpose. Rowan should hear all three logs.'] };
      }
      if (f.beaconLit) {
        return { lines: ['Mara: Pip fell asleep by the window watching the beacon. First time in years the dark outside looked... friendly.'] };
      }
      return {
        lines: [
          'Mara Harroway: Mind the mess — I salvage the station archive. Paper, chips, anything with a voice left in it.',
          'The terminal there holds a letter that was never sent. Read it, if you want to know what Emberwood really is.',
        ],
      };

    default:
      return { lines: ['...'] };
  }
}

// Archive terminals — the truth of the Quiet, in three pieces.
export function terminalText(id, state) {
  switch (id) {
    case 'logA':
      return {
        lines: [
          'AGRONOMY TERMINAL — LOG A (fragment):',
          '"Directive 9: double cell output. Waste digestion is the bottleneck. We are ordered to make the strain HUNGRIER. I want it on record that I objected." — E. Voss, agronomist',
          'The Bloom Error was not an accident.',
        ],
        effects: { set: { log1: true } },
      };
    case 'logB':
      return {
        lines: [
          'FOUNDRY TERMINAL — LOG B (last shift):',
          '"Cells we ship upstream come back DRAINED. Something on the network pulls charge faster than any town could burn it. Foreman says ship anyway. Shipping anyway." — shift log, unsigned',
          'The network was bleeding out long before the Quiet.',
        ],
        effects: { set: { log2: true } },
      };
    case 'logC':
      return {
        lines: [
          'HARROWAY ARCHIVE — LOG C (letter, never sent):',
          '"They didn\'t fail, love. We switched them off — every beacon upstream, to starve the thing that was draining us. The Quiet is a quarantine. We kept ours lit because someone has to leave a light on for the ones still out there." — signal officer, Station EMB-R-WD',
        ],
        effects: { set: { log3: true } },
      };
    default:
      return { lines: ['The screen is dead.'] };
  }
}

// walk-over quest items
export function itemPickup(id) {
  if (id === 'petdrone') {
    return {
      lines: ['A small round drone peeks out from behind a vat, one big cyan eye blinking. It bumps your shoulder gently and follows. This must be Bolt.'],
      effects: { set: { petFound: true } },
    };
  }
  return { lines: ['You pick it up.'] };
}

// Quest journal — pure render of quest state, drawn by the J-key overlay.
export function questJournal(state) {
  const f = state.flags;
  const lines = [];
  lines.push(['MAIN — REIGNITE THE BEACON',
    f.beaconLit ? 'done. The signal burns again.'
      : `${state.shards} of 3 Ember Cells found. ` + (state.shards >= 3 ? 'Take them to the beacon!' : 'Overgrowth maze - canal isle - foundry.')]);
  if (!f.gaveRing) {
    lines.push(['BEA\'S RING',
      f.hasRing ? 'Return the ring to Old Finn on the shore.'
        : 'Old Finn lost his wife\'s ring in the shore dust. He\'d trade the foundry keycard for it.']);
  } else {
    lines.push(['BEA\'S RING', 'done. Finn traded you the foundry keycard.']);
  }
  lines.push(['BOLT COME HOME',
    f.petReturned ? 'done. Bolt hovers beside Pip again.'
      : f.petFound ? 'Bolt follows you. Take it home to Pip.'
        : 'Pip\'s pet drone chased a glow into the Eden Shelf overgrowth.']);
  lines.push(['THE CANAL FILTER',
    f.filterGiven ? 'done. Finn\'s pump runs clean.'
      : f.filterPart ? 'Bring the pump filter to Old Finn.'
        : f.hasCaveKey ? 'A spare pump filter waits in the foundry\'s lower gallery.'
          : 'locked - Finn will mention it once you hold the keycard.']);
  const logs = (f.log1 ? 1 : 0) + (f.log2 ? 1 : 0) + (f.log3 ? 1 : 0);
  lines.push(['THE ARCHIVE LOGS',
    f.logsDone ? 'done. Rowan knows the truth of the Quiet.'
      : `${logs} of 3 terminals read. ` + (logs >= 3 ? 'Tell Overseer Rowan.' : 'Eden Shelf - foundry gallery - the Harroways\'.')]);
  return lines;
}

export const INTRO_LINES = [
  'TRANSMISSION — OVERSEER ROWAN, EMBERWOOD LANDING:',
  '"Engineer. The beacon died at dusk — all three Ember Cells gone. The dark out here has teeth. Find my office in the plaza habitat. Please hurry."',
  'Two centuries ago, the beacons of the Ember Network went quiet, one by one. Emberwood kept its light burning. Until tonight.',
];

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
  if (loot.item === 'filter') return ['A sealed casting-line pump filter, still in its wrap. Old Finn would trade his hat for this.'];
  return ['Empty. How disappointing.'];
}
