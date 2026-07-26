# Emberwood

A tiny top-down exploration RPG that runs entirely in the browser — no
dependencies, no build step, no binary assets. Every sprite and tile is drawn
procedurally from pixel-string arrays.

**Play it:** https://ivanmkc.github.io/emberwood/

The beacon of Emberwood village has gone dark. Recover the three Ember Shards
— one lost in the forest maze, one on the lake isle, one locked deep in the
mountain cave — and relight it.

## Controls

| Input | Action |
|---|---|
| Arrows / WASD | Move |
| Space / Enter | Talk, read, open, attack |
| N | New game (on title/win screen) |
| Touch | On-screen d-pad + A button on mobile |

Progress saves automatically to localStorage.

## Hints

- Talk to Elder Rowan in the village house first.
- Old Finn on the shore lost something shiny in the sand. He has a key.
- The merchant sells one Heart Container for 10 coins.
- Slimes guard the isle chest; something much bigger guards the cave.

## Development

```
python3 -m http.server 8787   # play at http://localhost:8787/
node --test                   # map integrity + BFS reachability + quest logic
```

The test suite proves every quest-critical entity and portal is reachable from
spawn by BFS over the real map data, and that the cave shard is properly gated
behind the locked door. Design notes in `docs/DESIGN.md`.
