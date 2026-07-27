# Sci-fi Eastward build-out — autonomous run status

## FOOTPRINT MECHANIC 2026-07-27 (sixteenth run)
General collision rule for plate rooms: FREESTANDING instances (det test:
nwalk band above top edge >35% walkable) block only ground-contact band
(max(14px, 28% height)); body above = walkable hidden floor (overhang_all
unioned into walk) occluded by cutout. MIXED structures (inner nwalk >15%,
e.g. bridge) block (mask & ~nwalk) — deck walkable, railings block.
Wall-integrated (buildings) full block. Water full block. ORDER MATTERS:
erode BEFORE island connector (else corridors severed -> deck zero-islanded).
Removed-char ground reopened via spawn-radius yellow-class dilation.
Result: pylon base-only, tanks pedestal-only, bridge crossable, ghosts gone,
islands 1.3k px. 26/26 tests, live.

## LIVING PLATE ROOM 2026-07-27 (fifteenth run)
remove_chars.py: painted characters inpainted out via per-character
magenta-region fills, judge-gated + re-rolled (iterative cleanup per Ivan).
Failure chain fixed en route: yellow class contains curtain highlights ->
verification pass; adjacent chars break single judging -> (group, then)
per-char fills w/ focused judge; feathered paste ghosts chars back -> hard
paste; giant union hole -> mush -> small per-char holes + aspect-matched
output. Real NPCs (Sela/scavA=keeper art, MARO-7/merchant, Dorn/scavB=
villager art entity->settler art) spawned at exact spots w/ dialogue.
Auto-exit on reachable bottom strip; zero-island (spawn component only).
KNOWN: one cloak remnant behind Dorn -> next fill round.

## WALKABILITY PLAYTEST FIXES 2026-07-27 (fourteenth run)
Ivan: wires walk-over (was already true — board showed RAW mask, misleading;
now shows FINAL collision w/ reachability colors), grates must be walkable.
Fixes in segment_room: MORPH_CLOSE 9px (grate slats fragmented walk into
islands), island connector (BFS corridor to large walkable islands routed
only through class-floor pixels -> bridge deck reconnected via shore; cannot
tunnel buildings/water). Islands 267k->17k px. Ground-truth viz:
final-collision-on-source.jpg (green reachable/yellow island/red blocked).

## WALKABILITY MASK LAYERED 2026-07-27 (thirteenth run)
nbp_walk.py: second flat-repaint (binary green/red). GATE LESSON: symmetric
IoU vs class-floor failed the mask; visual review showed the MASK was right
(bridge deck walkable, background floor excluded) -> gate rewritten as
subset-CONTAINMENT (walk ⊆ floor∪structure, 0.981). Integration: cables
class unioned back into walk (step-over; else floor partitions into
islands - reachable cells 510 -> 3739), erosion 7->3, spawn moved to open
plaza. Collision = walk ∧ ¬blocking, BFS+carve. Live, 26/26.

## NBP-NATIVE SEGMENTATION ADOPTED 2026-07-27 (twelfth run)
nbp_mask.py: NBP repaints scene as flat 8-class color map; gates: snap purity
0.981, floor fraction 0.578, edge alignment 0.997 (Canny agreement) — PASS.
segment_room.py now ingests it as primary (instances = per-class components,
pipes walkable-over, characters auto-classed); GrabCut = fallback. Bug fixed:
anisotropic device scale (2400x1792 -> 1280x896 needs dsx!=dsy or cutouts
double-print). SAM3.1 not pursued (kidsgame benchmark + this result).

## SOURCE-RES SEGMENTATION + ON-SOURCE BOARD VIZ 2026-07-27 (eleventh run)
Masks now computed at native source res (GrabCut on 2400x1792; outputs
downsampled to device 1280x896; coords scaled). Debug-mask artifact removed.
Board section 18 replaced with on-source renders (instances/collision/depth/
emissive tinted over the actual image). Source-space masks cached in
_srcmasks_*.npz for viz. Known: teal water mask over-matches glow pools
(safe over-block; refine = largest-components only).

## PIXEL-LEVEL SEGMENTATION SHIPPED 2026-07-27 (tenth run)
Mask stack (segment_room.py): instance map (Gemini boxes -> GrabCut pixel
masks; box-fill fallback when glow defeats GrabCut; 2-call union de-flake) +
collision.png (blocking instances + DETERMINISTIC teal-color water mask,
MinFilter erode, pixel-BFS gate on 8px lattice) + per-instance baseY cutout
PNGs (occlusion) + emissive.png (HSV threshold, runtime pulse). Engine:
per-pixel rectBlocked sampling, cutout drawables, 2x actor scale in plate
rooms, exit rect. Gotchas: Vertex 3.1-pro returns boxes but NO mask field;
GrabCut fails on glowing objects; water detection is run-variant -> color
threshold instead. Remaining for production: hotspot + removal masks
(inpaint painted characters, spawn real entities), per-room scale metadata.

## PLATE-ROOM SPIKE SHIPPED 2026-07-27 (ninth run)
Ivan's idea: use scene images as-is + segmentation masks. Built make_room.py:
grid-overlay -> Gemini walkability votes (3x majority, cached in
_room_*_votes.json) -> border force + BFS carve-to-exit -> PRE-BORDER
component base rows (border ring must not weld components) -> emit
src/rooms/*.js + assets/rooms/*.jpg + mask debug overlay. Engine: plate
render path, buildProps skip (else '#' cells sprout tree props!), per-cell
plate overdraw for occlusion, ?room=anchor boot. Live:
ivanmkc.github.io/emberwood/?room=anchor. Caveats for production: painted
characters are walk-through (inpaint them out + spawn real entities),
object hotspots TBD, room-by-room conversion plan on the board (section 16).

## PROP PHYSICALITY + PLACEMENT SHIPPED 2026-07-27 (eighth run)
Ivan: "seems random placement. also i can walk through objects." Fixed:
PROP_SOLID footprints (12x9 at base) collide for player+enemies via
rectBlocked/g.solidProps; deco list fully re-curated with spatial intent
(walls/edges/trailsides/POI clusters, no mid-field singletons); maps.test
reachable() now blocks solid deco + reserved-route assertions (portals,
relay pads, pass corridor). 26/26 tests; stall collision verified in-browser.

## DENSITY / ANTI-MOCKUP PASS SHIPPED 2026-07-27 (seventh run)
Ivan: "graphics and map are pretty sparse... need Eastward quality... looks
mockup-like". Response: organic coastline/eroded plaza/wavy dunes via decor
overrides (BFS-gated); dithered material transitions; cliff-face shading for
height; trail network; FRT-9 Pelican wreck POI (+chest+lore+2 slimes); 7 new
gated NBP scatter props (bush/mast/crates/pipe/stall/tree2; wallchunk retired
after 2 gate fails); prop clusters; value-noise macro tint; tufts; ambient
motes. Screenshot judge 3->4 (real-Eastward daylight frame = 3 on same rubric).
25/25 tests. Live verified.

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

## Run 17 — 2026-07-27 (footprint mask + 12x expansion, in flight)
- NBP FOOTPRINT mask shipped (nbp_footprint.py, third flat-repaint pass): bases-only
  gates (top-half of tanks/pylon footprint-free after open(9) rim cleanup), NBP-vs-NBP
  walk-conflict subtraction. segment_room composes: mixed-rule first (bridge), fp bases
  block, dilated liberation (13px, outline rings sealed hidden floor), ground-only pipe
  step-over, pinprick fill (<1500 src px), CONFIG-SPACE pass (8x8 hitbox erosion; carve
  box-wide corridors to NBP-standable regions only). Playtest drive 10/10 via window.__ew
  handle (drive script in job tmp). Commit 82e9114 on main. Board section 23 = 4-mask stack.
- EXPANSION 12x: rooms.json = 12 districts + exit graph (pairing-verified). gen_scene.py:
  style-anchored NBP scenes, judge median-of-3, REFLECTIVE retry (critique -> prompt).
  12/12 scenes gated (isometric drift auto-corrected on outskirts/repair-bay/transit).
  Mask scripts + segment_room parameterized (--room; ART=docs/art-options/rooms/<name>).
  Auto-spawn (distance transform), per-edge exit strips (detect-or-carve).
  room_factory.py running (bg task): class/walk/footprint/segment per room + install.
  gen_rooms_index.py -> src/rooms/index.js; assets.js loads PLATE_ROOM_NAMES; maps.js
  registers PLATE_ROOMS; game.js multi-exit (g.roomExits). Anchor keeps legacy S exit.
- Ivan directives: NBP + GEPA-style prompting over flaky deterministic code; post all
  masks on board (done, section 23); NEXT: transition matrix (all pairs both ways) +
  interactable objects in every scene + seamless stitched movement (no loading), then
  12h improve-to-perfect with generous Gemini verification of all masks/generations.

## Run 18 — 2026-07-27/28 (world x25: 12 districts + 12 interiors, in flight)
- ALL 24 new rooms BUILT (12 exteriors + 12 interiors) + anchor = 25 plate rooms.
- Prompt evolution (GEPA-style, per Ivan): walk v2 (flat markings/stains/puddles standable;
  rooftop decks are ground; floor-lying cables step-over), footprint = GROUND-OCCUPANCY
  semantics (full plan-view base incl. hidden floor behind lower body — Ivan's spec),
  anti-dither clause everywhere, play-space purity gate (sky bands don't fail gates),
  class floor-fraction 0.12..0.80 + purity 0.85 (furniture-dense interiors), walk frac
  0.12..0.75. nbp_grid_walk.py = Ivan's grid-cell fallback (transit-office: purity 0.978).
- Compose v2: NO global erode; thin-blocker opening (11src px: posts/wires stop blocking);
  per-component pipe step-over (neighborhood >=25% walkable); walk-authority inside
  full-block instances; LEGAL-ONLY carving (corridors/exits never repaint solid paint);
  spawn-reaches-exit invariant (salvage-shed). Anchor: walk v2 -> 28-row bridge lane,
  natural S exit, 10/10 drive (thresholds re-baselined to occupancy footprint).
- exit_probe.py (LLM passage location per edge), door_probe.py + edit_door.py (4 doorways
  PAINTED into parents via masked inpaint + judge; gate-wall kiosk re-probe), edit_exit.py
  (passage opener, unused yet). doors.json. gen_rooms_index: 25 rooms, 49 exits incl.
  door exits (trigger = door bottom strip) + interior s-exit returns to parent door.
  Engine: 'door' arrives like 'n'; hotspots (gen_hotspots.py -> assets/rooms/*.hotspots.json,
  interactTarget smallest-box, [name] examine dialogue); seamless cross-axis arrival.
- OPEN: world matrix drive shows PHANTOM EXITS (carved strips not hitbox-reachable:
  rooftops n/w, observatory s, others TBD) -> add exit-validity invariant (free-space
  reachability into trigger rect, drop+report), door-ize impossible edges
  (rooftops->observatory stair-door), matrix drive door handling (approach ArrowUp).
  Then: judge sweep all 25, ship, board gallery, NPCs, further expansion (8h window).
