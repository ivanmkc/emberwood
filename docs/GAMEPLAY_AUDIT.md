# Gameplay audit (2026-07-27)

Deterministic analysis from real game data (`node tools/audit_gameplay.mjs`):

```
== ECONOMY
 chest scrap: 48   quest rewards: 38   expected enemy drops: ~10
 total inflow ~96 vs sinks: Vitality Module 10
 !! SURPLUS 86 scrap with a single 10-scrap sink — economy is trivial

== COMBAT (player dmg 1, or 2 with Arc Capacitor; swing ~0.25s cycle)
 slime: 2 hits base / 1 upgraded; contact dmg 1 vs 3-4 hearts
 bat: 1 hits base / 1 upgraded; contact dmg 1 vs 3-4 hearts
 boss: 10 hits base / 5 upgraded; contact dmg 1 vs 3-4 hearts
 boss + 2 minions at <=4hp; player heal sources: drops 25%, respawn full

== TRAVEL (walk seconds, BFS shortest path, doors open)
 spawn -> cave mouth: 30 tiles (~7s)
 spawn -> biodome hatch: 47 tiles (~10s)
 spawn -> isle cell chest: 24 tiles (~5s)
 spawn -> ring sparkle: 22 tiles (~5s)
 cave entry -> mine2 door: 24 tiles (~5s)
 mine2 entry -> filter: 20 tiles (~4s)
 filter quest round trip: ~145 tiles (~0.5 min)

== DEATH: respawn at village spawn, full heal, keep everything
 from mine2 depths that is ~15s of re-walking — the only real penalty

== QUEST GATES
 ring -> keycard -> blast door -> {cell 3, mine2(filter, logB)} : single hard gate chain
 ember cells: overworld:shard1, overworld:shard2, cave:shard3
 logs: biodome(A) + mine2(B, behind gate) + home(C) -> Rowan synthesis
```

## Findings -> actions
- Economy surplus (~96 in vs 10 sink) -> added second sink: MARO-7 Arc Capacitor, 30 scrap, +1 slash damage (amber slash core when fitted)
- Boss slog at 8 hits -> boss HP 10; 5 hits with capacitor, 10 without (both viable)
- Travel times all <=10s and filter round-trip ~0.5min -> healthy, no fast travel needed
- Death penalty ~15s re-walk, full heal, keep items -> accepted (cozy tone)
- Single hard gate (ring->keycard) is double-hinted by Finn + Rowan + journal -> accepted by design
- 60.5 fps measured with full prop/glow load -> no perf work needed
