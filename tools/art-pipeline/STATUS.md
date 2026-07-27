# Sci-fi Eastward build-out — autonomous run status

## BASE + PROGRESSION SHIPPED 2026-07-27 (sixth run)
Settlement Charter (entity in plaza, menu mode 'base'): 4 projects = 100 scrap
(lamps deco, greenhouse heart pickup, signal-relay same-map fast-travel pads
plaza(40,28)<->pass(31,7), infirmary regen on settlement tiles). Salvage Rank:
xp on kills/quests/builds, 5 ranks w/ perks (drop 0.62, reach 26px, knockback
55, +1 heart + ember trail); rank-up pages appended to dialogue; HUD pip +
journal rank row. 25/25 tests; charter purchase + relay warp verified headless.

## UI ROUND 3 + GAMEPLAY AUDIT SHIPPED 2026-07-27 (fifth run)
NPCs face player on talk; beacon core pulse (lit) + red distress blink (dead);
looted-chest slot; pulsing pads; aligned title columns; journal status chips.
Gameplay audit harness tools/audit_gameplay.mjs (economy/combat/BFS travel from
real data) -> findings in docs/GAMEPLAY_AUDIT.md; fixes: Arc Capacitor sink
(30 scrap, +1 dmg, amber slash), boss HP 10. 60.5fps measured. 23/23 tests.

## UI ROUND 2 SHIPPED 2026-07-27 (fourth run)
Press Start 2P self-hosted (OFL in assets/fonts) for display text; redrawn
HUD icons (outlined hearts, hex-nut scrap, keycard); synthesized 2-frame walk
cycle; sludge squash / drone jitter; slash glow + hit-stop + screen shake;
coolant ripple drift; win embers; ASCII-source gate test (confusable Unicode
in pixel art was a recurring authoring bug — now deterministic). 23/23 tests,
UI judge: title 8/9/8/7, HUD 8/7/8/7. Live verified.

## UI PASS SHIPPED 2026-07-27 (third run)
Judge-audited (new 'ui' rubric in judge.py) before/after: HUD cohesion 5->8,
polish 4->6; dialogue cohesion 6->8; mobile polish 4->7. Changes: HUD plates
+ cell sockets, speaker name tags on pixel dialogue panel + advance chevron,
ember logotype title w/ motes, hurt vignette, shoreline foam, styled page
shell + favicon + og meta. 22/22 tests, zero console errors, live verified.

## EXPANSION SHIPPED 2026-07-27 (second autonomous run)
Story bible docs/LORE.md; 3 new maps (biodome/mine2/home) with BFS gates;
4 side quests + lore terminals + intro transmission + post-win dialogue;
Field Journal (J) + ambient per-area music (M); 7 new gated NBP assets
(overgrowth, domefloor, terminal, rack, vat, keeper, petdrone);
22/22 tests; 9/9 screenshot gates; live + verified.

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
- SHIPPED 2026-07-27: sci-fi re-theme LIVE at https://ivanmkc.github.io/emberwood/
- All gates green: 6/6 props, 11/11 tiles (coolant waived, documented),
  8/8 characters, 5/5 in-game screenshots (calibrated), 11/11 node tests,
  zero console errors, headless win-path verified.
- Screenshot gate CALIBRATED against ground truth: a real Eastward daylight
  frame scores 3 vs the concept anchor (night frame 6); pass = perspective_ok
  AND style>=4, style==3 passes at documented real-Eastward parity.
- Key pipeline learnings (all encoded in the scripts): stage-flat front-
  elevation prompts prevent iso drift; NBP sheet layouts are arbitrary ->
  content-aware facing-judge slicing; border-aligned single-panel generation
  beats crop-search for manufactured tiles; single judge samples flip-flop ->
  median-of-3 voting; variant brightness must be mean-normalized; border-
  median key color doubles as a scene-failure detector; judges need
  ground-truth calibration before their thresholds mean anything.
- Full gate matrix: tools/art-pipeline/VERIFICATION.md (generated by
  gate_final.py); verdicts: tools/art-pipeline/verdicts.json
