# Verification matrix

Every gate: deterministic checks + Gemini rubric (median-of-3 vote).


## Props

- ✅ `beacon` — style_match=8, perspective_ok=True, theme_fit=9
- ✅ `chest` — style_match=8, perspective_ok=True, theme_fit=9 — Slightly blurry, likely due to upscaling without nearest-neighbor interpolation, but style and theme fit well.
- ✅ `house` — style_match=8, perspective_ok=True, theme_fit=9 — The asset fits the theme well and uses a similar palette. Perspective is front-facing, matching the buildings 
- ✅ `lamp` — style_match=8, perspective_ok=True, theme_fit=9
- ✅ `rock` — style_match=8, perspective_ok=True, theme_fit=9
- ✅ `tree` — style_match=8, perspective_ok=True, theme_fit=9 — Slightly more rounded and detailed base than the planar/boxy planters in the anchor, but generally fits well.

## Terrain tiles

- ✅ `carpet` — style_match=8, tileable=10 — Good pattern, fits pixel style well
- ✅ `coolant` — style_match=8, tileable=6 — A bit too dark and plain, lacks the glowing bright teal quality of the coolant in the reference image. Has sli
- ✅ `dust` — style_match=8, tileable=6 — Obvious repetition grid creates diagonal patterns, color is slightly too drab compared to the vibrant anchor s
- ✅ `floorpanel` — style_match=8, tileable=10 — A bit plain, but matches the intended panel style well and tiles perfectly.
- ✅ `ground` — style_match=8, tileable=9
- ✅ `minefloor` — style_match=8, tileable=6 — Noticeable diagonal repetition pattern makes it less seamlessly tileable.
- ✅ `minewall` — style_match=8, tileable=6 — Visible vertical seams in tiling
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

- ✅ `house` — style_score=3, perspective_ok=True — Lighting is very basic, lacking the ambient glows and shadows of the anchor. The UI elements (hearts, coin) lo
- ✅ `lake` — style_score=3, perspective_ok=True — Water lacks any texture or shading, ground tiles are repetitive with minimal detail, UI elements are basic and
- ✅ `mine` — style_score=3, perspective_ok=True — The scene is mostly pitch black due to an overly harsh vignette/fog effect, losing all environment detail.
- ✅ `village` — style_score=4, perspective_ok=True — Lighting is flat compared to the anchor's vibrant, localized glows. Assets feel a bit scattered and disconnect
- ✅ `win` — style_score=3, perspective_ok=True — HUD elements look basic/placeholder, lack of shadows and depth, simplistic lighting compared to target
