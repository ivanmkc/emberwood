# Emberwood

A tiny top-down exploration RPG that runs entirely in the browser — no
dependencies, no build step, no binary assets. Every sprite and tile is drawn
procedurally from pixel-string arrays.

**Play it:** https://ivanmkc.github.io/emberwood/

The signal beacon of the Emberwood settlement has gone dark. Recover the three
Ember Cells — one lost in the bio-dome overgrowth, one on the coolant-canal
isle, one sealed deep in the derelict mine — and reignite it.

Art direction: Eastward-style sci-fi. Tiles, props and characters are
generated per-asset by Nano Banana Pro against a style anchor, then pass
deterministic gates (chroma key integrity, seam error, coverage) and Gemini
vision rubrics (style match, perspective, tileability) before
`tools/art-pipeline/install_assets.py` will admit them into `assets/`.

## Controls

| Input | Action |
|---|---|
| Arrows / WASD | Move |
| Space / Enter | Talk, read, open, attack |
| N | New game (on title/win screen) |
| Touch | On-screen d-pad + A button on mobile |

Progress saves automatically to localStorage.

## Hints

- Talk to Overseer Rowan in the habitat block first.
- Old Finn on the shore lost something shiny in the dust. He has a keycard.
- MARO-7 sells one Vitality Module for 10 scrap.
- Sludge guards the isle cache; something much bigger guards the mine.

## Development

```
python3 -m http.server 8787   # play at http://localhost:8787/
node --test                   # map integrity + BFS reachability + quest logic
```

The test suite proves every quest-critical entity and portal is reachable from
spawn by BFS over the real map data, and that the cave shard is properly gated
behind the locked door. Design notes in `docs/DESIGN.md`.
