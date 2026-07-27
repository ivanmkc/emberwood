# Sci-fi Eastward build-out — autonomous run status

Directive (Ivan, 2026-07-27): build out the sci-fi re-theme end to end with
robust verification at every step — deterministic gates AND Gemini/NBP judge
rubrics. 12 hours. No questions. No OpenAI APIs.

## Fixed decisions
- Theme: futuristic sci-fi in Eastward's visual language (approved anchor:
  docs/art-options/nbp-scifi-anchor.png — perspective-correct v2).
- Perspective law: axis-aligned straight-on 3/4; buildings = flat front
  elevations ("stage-set flat" prompt phrasing); NO rotation/iso.
- Image gen: gemini-3-pro-image (GA id; -preview aliases 404 on Vertex).
- Judge: gemini-3.1-pro-preview or newest available 3-series (NEVER 2.5),
  ThinkingConfig(thinking_level='low'), max_output_tokens>=2048,
  json raw_decode parsing.
- Assets ONLY from NBP (one object per call, magenta key); scenes = anchors.
- Theme mapping: beacon→signal-pylon energy core, shards→power cells,
  coins→scrap, lake→coolant canal, cave→derelict mine, forest→bio-overgrowth,
  village→settlement. Quest logic unchanged.
- Game stays at 16px logical tiles; internal canvas 640x480 (2x); art at 32px/tile.
- Collision/maps/BFS tests unchanged by art integration.

## Pipeline gates (every asset/tile must pass ALL before integration)
Deterministic: key-color≈magenta (scene-failure detector) · alpha coverage
20–90% · seam error < 8 after wrap-blend (tiles) · size sanity.
Gemini rubric: style_match>=7 · perspective_ok · single_object ·
silhouette_clean · theme_fit>=7 (assets); flat_plan_view · tileable>=7 (tiles).

## Workstreams
1. [todo] judge.py + gates — Gemini rubric harness with retry loop
2. [todo] Terrain tiles batch 1 (8 generated, crop method in; coolant too
   bright + rubble busy → judge loop); batch 2 interior (floorpanel,
   wallpanel, carpet) + decals (doormat, cave mouth)
3. [todo] Characters: player 4-dir + 4 NPCs + 3 enemies, identity-gated;
   fallback = procedural sci-fi recolors if gates keep failing
4. [todo] Engine integration: PNG loader, 2x canvas, prop y-sort rendering,
   house-block detection, dusk lighting/grade pass
5. [todo] Theme text rewrite (quest.js, index.html, README) + test updates
6. [todo] Final verify: node tests, Playwright drives, Gemini screenshot
   judge, live deploy, board update

## Current state (UPDATE AS YOU GO — this file must never claim more than is true)
- Gates infra DONE: judge.py (median-of-3 vote, rubrics: asset/tile/character/
  creature/facing/screenshot), gate_all.py (det gates: coverage, fringe, seam,
  blob-count dup-figure detector; CLI cat=name,name), install_assets.py
  (verdict-gated), verify_game.mjs + gate_final.py (in-game screenshot judge)
- PASSING so far: assets beacon/chest/house/lamp/tree; tiles carpet/dust/
  minefloor/minewall/rubble/wallpanel; chars player/boss/trader/sludge/drone
- Round 5 (bg): resegment chief/angler/settler (content-aware facing-judge
  slicing — NBP sheets have arbitrary layouts, quadrant slicing broken);
  panel tiles plate/walkway/floorpanel regenerated as border-aligned single
  panels (correct by construction); ground regen subtle; rock regen attempt 3
  (drop prop if it fails again); coolant waived (documented in WAIVERS)
- Engine INTEGRATED (committed): 2x scale, PNG loader+fallback, props y-sort,
  house-block detection, dusk lighting; smoke-tested clean in fallback mode
- Theme text DONE (quest.js/maps signs/README/title/win); 11 node tests green
- Remaining: round-5 gate results -> install_assets -> verify_game drives ->
  gate_final screenshot judge -> push/deploy -> board update
