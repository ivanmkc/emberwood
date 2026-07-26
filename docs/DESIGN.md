# Emberwood — design

A top-down exploration RPG playable in the browser. Zero dependencies, zero
build step, zero binary assets: vanilla ES modules + Canvas, with every sprite
drawn procedurally from pixel-string arrays.

## Premise & quest

The beacon of Emberwood village has gone out and monsters creep in from the
woods. The Elder asks you to recover the **3 Ember Shards** and relight it.

- **Shard 1 — Forest**: chest hidden in the northwest forest maze.
- **Shard 2 — Lake isle**: chest across the lake bridge, guarded by slimes.
- **Shard 3 — Cave**: past the locked cave door in the northern mountains,
  guarded by the Ember Guardian (boss slime).
- **Side quest**: the fisherman lost his ring on the lake shore (sparkle in the
  sand). Return it and he gives you the **Cave Key**.
- **Merchant**: sells a Heart Container (max HP +1) for 10 coins.
- Return all 3 shards to the beacon → it relights → win screen with play stats.

## Systems

| System | Decision |
|---|---|
| World | 3 maps: overworld 48×36, cave 24×18, elder's house 12×10; ASCII tile grids |
| Movement | 4-direction, pixel movement with AABB tile collision, camera follow with map clamp |
| Combat | Sword arc in facing direction (Space); enemies deal contact damage with knockback + i-frames |
| Enemies | Slime (wander/chase), Bat (fast, erratic, cave), Ember Guardian (big, 8 HP, spawns slimes at half health) |
| Interaction | Space when facing NPC/sign/chest/beacon interacts instead of attacking |
| Dialogue | Typewriter textbox, multi-page, advance with Space |
| Inventory | Hearts, coins, key items (shards, ring, cave key) shown in HUD |
| Save | localStorage snapshot on map change + quest events; auto-restore on load; New Game button |
| Rendering | 16 px tiles at 3× integer scale, `image-rendering: pixelated`, cave darkness vignette |
| Input | Arrows/WASD + Space/Enter; on-screen touch d-pad + action button on coarse pointers |

## Structure

```
index.html        shell + HUD/touch DOM
src/tiles.js      tile ids, solidity, procedural tile art
src/sprites.js    pixel-string sprite registry + palette
src/maps.js       ASCII grids, portals, entity spawns  (pure data — node-testable)
src/quest.js      quest/flag logic                     (pure — node-testable)
src/game.js       loop, state, collision, combat, AI, dialogue, HUD, save
src/input.js      keyboard + touch
src/main.js       boot
test/*.test.js    node --test: BFS reachability from spawn to every quest
                  entity + portal; portal integrity; combat/quest math
```

## Verification gates

1. `node --test` green — including BFS proof that every quest-critical entity
   and portal is reachable from spawn on every map (no hermetic rooms).
2. Playable locally via `python3 -m http.server`.
3. Live on GitHub Pages, URL curl-checked before reporting.
