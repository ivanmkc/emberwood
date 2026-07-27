# Verification matrix

Every gate: deterministic checks + Gemini rubric (median-of-3 vote).


## Props

- ✅ `beacon` — style_match=8, perspective_ok=True, theme_fit=9
- ✅ `chest` — style_match=8, perspective_ok=True, theme_fit=9 — Slightly blurry, likely due to upscaling without nearest-neighbor interpolation, but style and theme fit well.
- ✅ `house` — style_match=8, perspective_ok=True, theme_fit=9 — The asset fits the theme well and uses a similar palette. Perspective is front-facing, matching the buildings 
- ✅ `lamp` — style_match=8, perspective_ok=True, theme_fit=9
- ✅ `rack` — style_match=8, perspective_ok=True, theme_fit=9 — Slightly blurry, lacks sharp pixel definition compared to anchor.
- ✅ `rock` — style_match=8, perspective_ok=True, theme_fit=9
- ✅ `terminal` — style_match=8, perspective_ok=True, theme_fit=9 — Style matches well, maybe slightly larger pixel size than some small details in anchor, but overall good.
- ✅ `tree` — style_match=8, perspective_ok=True, theme_fit=9 — Slightly more rounded and detailed base than the planar/boxy planters in the anchor, but generally fits well.
- ✅ `vat` — style_match=8, perspective_ok=True, theme_fit=9 — Slightly more purple/magenta in the glass glow than seen in the anchor, but matches the pixel art style well.

## Terrain tiles

- ✅ `carpet` — style_match=8, tileable=10 — Good pattern, fits pixel style well
- ✅ `coolant` — style_match=8, tileable=6 — A bit too dark and plain, lacks the glowing bright teal quality of the coolant in the reference image. Has sli
- ✅ `domefloor` — style_match=8, tileable=10 — Good grid pattern, fits the sci-fi setting.
- ✅ `dust` — style_match=8, tileable=6 — Obvious repetition grid creates diagonal patterns, color is slightly too drab compared to the vibrant anchor s
- ✅ `floorpanel` — style_match=8, tileable=10 — A bit plain, but matches the intended panel style well and tiles perfectly.
- ✅ `ground` — style_match=8, tileable=9
- ✅ `minefloor` — style_match=8, tileable=6 — Noticeable diagonal repetition pattern makes it less seamlessly tileable.
- ✅ `minewall` — style_match=8, tileable=6 — Visible vertical seams in tiling
- ✅ `overgrowth` — style_match=8, tileable=9 — A bit noisy and generic, could read as moss or just abstract noise rather than distinct overgrowth in the scen
- ✅ `plate` — style_match=8, tileable=10 — A bit plain, but fits the context of floor panels perfectly.
- ✅ `rubble` — style_match=8, tileable=6 — Noticeable repeating diagonal pattern
- ✅ `walkway` — style_match=8, tileable=10 — Good panel texture, matches the sci-fi industrial setting.
- ✅ `wallpanel` — style_match=8, tileable=6 — Harsh seams where panel edges misalign, noticeable grid repetition

## Characters

- ✅ `angler` — style_match=8, theme_fit=7
- ❌ `angler-down` — style_match=4, theme_fit=5 — Art style is very different, lacking the outline and specific shading of the anchor. Theme is a bit too realis
- ❌ `angler-left` — style_match=1, theme_fit=1 — Wrong perspective (side-scroller, not top-down), style heavily clashes (messy pixels, very different art style
- ❌ `angler-right` — style_match=4, theme_fit=3 — Too low resolution/lacks outline, shading style differs from anchor.
- ❌ `angler-up` — style_match=4, theme_fit=3 — Too blurry/pixelated, lacks the crisp lineart and specific sci-fi/cyberpunk aesthetic of the style anchor.
- ✅ `boss` — style_match=8, theme_fit=9 — Too large in scale/resolution compared to the style anchor, shading style is a bit too smooth/soft for the cri
- ✅ `chief` — style_match=8, theme_fit=9
- ✅ `chief-down` — style_match=8, theme_fit=7
- ❌ `chief-left` — style_match=4, theme_fit=5 — Art style is completely different, low resolution pixel art instead of high resolution clean lines. Character 
- ❌ `chief-right` — style_match=4, theme_fit=7 — Perspective mismatch (profile/side-scroller view vs top-down JRPG), blurry upscaled pixels
- ❌ `chief-up` — style_match=4, theme_fit=3 — Art style is blurry/low resolution compared to the crisp pixel art of the anchor. The theme (scientist/doctor)
- ✅ `drone` — style_match=8, theme_fit=9 — None. Good match.
- ✅ `keeper` — style_match=8, theme_fit=6 — Style is somewhat more detailed/textured than the flatter, cleaner anchor style; theme is a bit too fantasy/ru
- ✅ `petdrone` — style_match=8, theme_fit=9 — Good style match with appropriate shading and palette, captures the friendly round drone concept well.
- ✅ `player` — style_match=8, theme_fit=9
- ❌ `player-down` — style_match=4, theme_fit=3 — Art style is generic pixel art, lacking the detailed linework and distinctive shading of the anchor. The theme
- ❌ `player-left` — style_match=4, theme_fit=3 — Art style is too simple and lacks the outline and shading style of the anchor. Theme is mundane modern, not sc
- ❌ `player-right` — style_match=4, theme_fit=5 — Art style is very different, lacking the specific shading and outline style of the anchor. Theme is generic mo
- ❌ `player-up` — style_match=4, theme_fit=5 — Resolution too low/blurry, lacks detail compared to anchor. Style leans more Stardew Valley than Eastward/cybe
- ✅ `settler` — style_match=8, theme_fit=8
- ❌ `settler-down` — style_match=4, theme_fit=7 — Art style is generic pixel art, lacking the detailed lighting, specific palette, and cyberpunk/sci-fi elements
- ❌ `settler-left` — style_match=4, theme_fit=3 — Too basic, colors are muddy, lacks the high-contrast lighting and sci-fi details of the anchor. Theme fit is l
- ❌ `settler-right` — style_match=4, theme_fit=5 — Resolution too low/blurry, lacks shading depth and outline style of anchor. Proportions are okay but sprite is
- ❌ `settler-up` — style_match=4, theme_fit=3 — Art style is generic RPG maker style, not the detailed pixel art style of the reference image. The clothing (r
- ✅ `sludge` — style_match=8, theme_fit=9 — The slime creature matches the intended design perfectly. The pixel art style is consistent with the anchor im
- ✅ `trader` — style_match=8, theme_fit=9 — Slightly blurry upscaling compared to the crisp pixel art of the anchor, but captures the intended boxy tracke

## In-game screenshots

- ✅ `biodome` — style_score=3, perspective_ok=True — Tileset pattern is very repetitive and grid-like, lacks lighting/shadow nuance compared to anchor, UI text ove
- ✅ `home` — style_score=3, perspective_ok=True — Lighting is very flat, lacking the directional dusk glows and colored highlights of the anchor. The room is to
- ✅ `house` — style_score=3, perspective_ok=True — Lighting is completely flat (no ambient occlusion or localized glows), textures look like unmodified basic til
- ✅ `intro` — style_score=4, perspective_ok=True — Lighting gradients look simplistic (soft circular halos around lamps). The large bush/wall on the right feels 
- ✅ `lake` — style_score=3, perspective_ok=True — Visuals look very placeholder. UI elements (hearts, coins) lack the stylized sci-fi feel of the anchor. Overal
- ✅ `mine` — style_score=3, perspective_ok=True — The terrain texture (dark grey noise) looks very repetitive and placeholder. The black void outside the light 
- ✅ `mine2` — style_score=5, perspective_ok=True — Signpost sprite feels a bit flat compared to other assets. UI elements (hearts, coin) are very generic/placeho
- ✅ `village` — style_score=4, perspective_ok=True — Signpost and interactive object scaling feels slightly off, missing the rich ambient occlusion and glowing acc
- ✅ `win` — style_score=4, perspective_ok=True — Floor texture is very basic/placeholder. The large open area lacks detail. The UI elements in the top corners 
