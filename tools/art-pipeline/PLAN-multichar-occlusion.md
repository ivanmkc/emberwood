# Multi-character occlusion probing → per-object z-index

Ivan's directive: "Do multiple characters at once to probe. Also presegment the
scene. Instead of needing to find z-index of each pixel independently, we just
need to figure out z-index per object (even a portion sampled per object is
enough to establish z-index relative to characters). Can we sample with many
characters at once?"

## Core idea

The single-character probe (run 27) proved NBP inserts a character with
physically correct occlusion (noodle counter over legs, judge-confirmed).
Two scaling moves:

1. **Many characters per NBP call** — each roll yields K probes instead of 1.
2. **Object-level inference** — we already have per-pixel instance ids for all
   3 scenes (`_srcmasks_<room>.npz`, 35-89 objects/room, full 2400x1792 res).
   Any occlusion evidence that touches an object resolves the WHOLE object's
   z relative to the character's ground-y. Per-pixel density is unnecessary.

## Evidence model (per probe at ground position g = (gx, gy))

For each character probe, classify pixels inside the character's expected
silhouette region:

- `visible(probe)` = changed pixels (character appeared) → for each instance O
  whose mask overlaps these pixels: **character drew OVER O** → O is BEHIND a
  character standing at gy → constraint `z(O) < gy` (O sorts behind actors at gy).
- `occluded(probe)` = column-fill silhouette holes (unchanged pixels inside the
  visible span) → attribute to instance O at those pixels → **O drew over the
  character** → constraint `z(O) > gy` (O sorts in front of actors at gy).

Aggregating constraints per object gives an interval:
`lo(O) = max gy of probes O occluded`, `hi(O) = min gy of probes that covered O`.

- Consistent interval (`lo < hi`): object behaves like a y-sorted sprite with
  effective sort line in `[lo, hi]` — matches the engine's y-sort model; the
  footprint-base sort key should fall inside the interval (validation!).
- `lo = +∞` pattern (occludes at EVERY probed gy, never covered): overhead
  class (wires, hanging signs, awnings) → always-on-top layer. This is the
  cross-check for MASK 3.
- Contradiction (`lo > hi`): non-scalar depth (archways, bridges — object is
  both in front and behind at different columns) → flag for split or manual
  review, do NOT force a scalar z.

## Sampling design (object-targeted, not uniform)

For each blocking instance O with base row `b(O)` and top row `t(O)`:
- **Behind-band probes**: walkable positions with `gy ∈ [t(O), b(O))` in the
  columns O spans, standing in O's occlusion shadow → expect O to occlude.
- **Front-band probes**: walkable `gy > b(O)` just below → expect char covers O.
Walkable = consensus walk ∩ magenta-v4 ground (both agree), eroded by half char
width so the character fits. Target: ≥2 behind + ≥1 front probe per object
where such positions exist; many objects share probes (a probe constrains every
object whose mask intersects its silhouette region).
Estimated need: ~25-40 probe positions per room to cover all reachable objects.

## Multi-character arms (A/B on night-bazaar)

- **Arm A — multi-char crops**: 800px crops, 2-3 markers per crop (spacing
  ≥ 1.5 char widths, ≥ 60px from crop edge). ~10-14 calls per room.
  Proven noise budget (8% outside bboxes) carries over.
- **Arm B — full-frame multi-char**: one 2K call with 12-20 markers on the
  full plate. Risk: full-frame edits historically re-render (kidsgame lesson);
  the magenta pass's stability suggests "add-only" instructions may hold.
  Gate: same noise budget computed outside the union of bboxes; require ≥80%
  of markers to produce a character (count distinct visible blobs).
- Marker scheme: numbered colored crosses (magenta outline + distinct core
  color per marker); prompt says "place one copy of the character standing on
  EACH cross". Attribution primarily by nearest-marker bbox; core colors are a
  fallback attribution signal if bboxes ever overlap.
- Character identity: the player sprite for all (identity consistency beats
  variety; we do not need distinct characters for attribution thanks to
  spacing + bbox rules).

## Gates & verification

- Deterministic: noise budget outside bboxes; per-marker character-present
  check (visible blob ≥ 800px within bbox); spacing validator before calling.
- Judge (gemini-3.1-pro): per crop/frame — characters present at markers?
  which objects occlude which characters? scene otherwise identical?
  Median-of-3 ONLY for contested constraints (disagreement between diff
  evidence and judge, or |evidence px| < 300).
- Cross-validation: for objects with consistent intervals, check the engine's
  current footprint-base sort key ∈ [lo, hi]. Report agreement rate.
  Disagreements + overhead detections are the actionable output.
- Contradiction audit: list all `lo > hi` objects with their probe evidence.

## Outputs

- `occprobe2-<room>-constraints.json`: per-object {id, label, lo, hi, verdict:
  ysort|overhead|contradiction|no-evidence, evidence probe list, px counts}.
- `occprobe2-sheet-<room>.jpg`: contact sheet (crops or frame with per-marker
  verdicts).
- `occprobe2-zmap-<room>.jpg`: objects colored by verdict/z-band over plate.
- Board: new cards on the Z-Index Evidence page.
- Engine consumption (later, gated): per-object `zOverride` / `overhead` flags
  in instances.json for objects where evidence contradicts footprint y-sort.

## Phases

- P0 (deterministic prep, no API): sampling plan per room from inst npz +
  walk∩magenta masks; spacing validator; expected-constraint dry-run report
  (which objects get behind/front coverage; which are unreachable).
- P1: A/B pilot on night-bazaar (Arm A ~12 calls, Arm B ~3 calls x K=15).
  Pick arm by: valid-char rate, noise rate, constraints/object coverage, calls.
- P2: constraint aggregation + judge pass on contested; cross-validation vs
  engine sort keys; contradiction audit.
- P3: winning arm on anchorroom + plaza; z-map overlays; board page update;
  STATUS.md; commit.

## Open questions for expert review

1. Is the interval model (`lo/hi` from behind/front evidence) the right
   aggregation, or should constraints be weighted by evidence pixel count with
   a robust vote (some probes will be noisy)?
2. Contradiction handling: split objects by column bands (archway case), or
   just flag-and-default to y-sort?
3. Arm B full-frame: is 12-20 characters per frame beyond NBP's reliable
   instruction-following? Better K? Better marker scheme?
4. Attribution: is nearest-marker bbox sufficient, or do we need per-marker
   character color-coding as primary attribution?
5. Sampling: is 2-behind + 1-front per object enough for a reliable interval,
   given per-roll silhouette jitter? Should behind-band probes be repeated
   across 2 rolls for the same position?
6. Any failure mode we're not gating: character drawn at wrong marker, two
   characters merged, character replacing (deleting) scene objects, marker
   residue mistaken for character pixels?

---

# v2 — Panel-adopted amendments (3 expert reviews, 2026-07-28)

## From experimental design (exp-design)
- **Robust aggregation** replaces raw max/min: a probe contributes a constraint
  for object O only with ≥50 evidence px (anti-alias speckle is <20px; 2.5x
  margin). With ≥4 probes per direction use 90th/10th percentile for lo/hi;
  below 4, require 2 concordant probes (gy within 20px); singletons are
  "provisional" and excluded from cross-validation scoring.
- **Sampling target is 2 behind + 2 front** (was 2+1): drops object-level
  error from ~5.2% to ~0.5% at a 5% per-probe failure rate. Front probes must
  be ≥30px apart in gy or hi is flagged "tight-sampled".
- **Contradictions: flag-and-default** to footprint y-sort, but record the
  column ranges where behind vs front evidence concentrates (~10 lines) so
  splitting stays possible later. No automatic splitting in P2.
- **Cross-validation metrics**: containment rate (engine baseY ∈ [lo,hi],
  expect >85%) AND Spearman rank correlation of interval midpoints vs engine
  sort keys (expect ρ>0.90) — containment alone misses ordering errors.

## From generation pragmatics (genai-review)
- **Arm B K-ramp with gates**: K=3 (3/3 placed) → 6 (≥5/6) → 10 (≥8/10), two
  consecutive passing rolls to advance, hard cap 12 (not 15-20). If K=6 fails
  4 rolls, abort Arm B, commit to Arm A crops.
- **Diff against the MARKED plate**, not the clean plate — marker pixels
  cancel in the diff whether or not the model erases them. No erase
  instruction in the prompt. Plain identical magenta crosses (no numbering/
  per-marker colors); attribution = nearest-bbox centroid.
- **Shadow apron gate**: 20px below / 30px wider than each char bbox; reject
  the roll if mean max-channel diff in the apron exceeds 25 (soft shadows sit
  below DIFF_T=42 but corrupt ground-line evidence).
- **Swap gate**: ≥600 visible px per marker bbox AND blob centroid within
  40px of its own marker. **Merge gate**: visible blobs claimed by two bboxes
  invalidate the roll. Full-frame off-bbox noise budget tightens to
  0.08·(1 − K·bbox_area/frame_area).
- Crop arm: characters may pose facing each other — harmless for silhouette
  diff; keep the spacing validator.

## From engine graphics (gfx-review)
- **Output = corrected `baseY` (sort-line), NOT a zOverride**: the engine is
  pure y-sort (game.js sortY from baseY); a corrected baseY slots in with zero
  engine changes. Collapse [lo,hi] to a sort-line only when the existing baseY
  falls OUTSIDE the interval; direction semantics: baseY<lo = sorts too far
  back, baseY>hi = too far forward.
- **Overhead criterion corrected**: overhead = hi UNDEFINED (never covered)
  AND lo finite AND ≥1 front-band probe whose silhouette actually overlaps
  O's mask (otherwise verdict is "no-evidence", not "overhead"). P0 must
  verify front-probe silhouette overlap per object.
- **Split candidates pre-flagged in P0**: instances with vertical extent >3×
  char height (stall canopy+counter, hanging sign+pole are the real cases in
  these scenes; archway/bridge = flag only). Wires/pipes are blocking:false →
  never probed, already in the overhead composite.
- **Coordinate space**: probe gy and [lo,hi] in art-resolution px, matching
  instances.json baseY; /DS only at render time.

## P0 dry-run results (occprobe2_plan.py, feet-only erosion, walk∩magenta)
- night-bazaar: 74 blocking objects → 36 probes; 14 full / 15 partial /
  45 no-overlap. anchorroom: 26 → 16 probes (4/6/16). plaza: 67 → 16 probes
  (3/14/50). "No-overlap" objects (buildings, shelf props, tanks) are ones the
  character can NEVER overlap from walkable ground → z-irrelevant by
  construction; they keep default y-sort. The planner needs a 2+2 rerun (was
  2+1) + front-overlap verification per the amendments.
