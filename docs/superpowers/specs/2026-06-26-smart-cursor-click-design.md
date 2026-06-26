# Smart cursor-click for animated videos

**Date:** 2026-06-26
**Status:** Approved (brainstorm) → implementation

## Problem

The web video generator's "Animation" picker lists `Cursor click / Smooth scroll / Spotlight / Zoom and pan`. Users find "cursor click" confusing as an *animation option*, and the current cursor is a generic sweep on a fixed path — it does not click anything real. The user wants:

1. The Animation picker **removed** — every video presentable by default (not a slideshow).
2. The cursor to be **smart and default**: the AI looks at each screenshot, finds the most relevant *real clickable element* (button / nav link / CTA), and the cursor moves to it and clicks. The AI already sees the screenshots, so it can locate the target.

## Decisions (from brainstorm)

- **Remove the Animation picker** on the web. The smart cursor is always-on, not a choice.
- **Cursor only appears when there's a real clickable target.** Scenes with no clear clickable element get smooth motion and **no cursor**.
- **Approach A (chosen):** the planning vision-LLM marks the click target itself (it already has the screenshot). No separate detection pass.
- Honest limit: AI coordinates are approximate (good, not pixel-perfect). If unsure, the LLM omits the target → no click that scene (never click empty space).

## Design

The video plan already comes from a vision-LLM (`generate_anim_plan`) and is rendered by the `video-remotion` React composition. Two new pieces of data flow through, plus a UI removal.

### 1. Plan data model — per-scene click target
Add an **optional** `click` to each scene in `ANIM_PLAN_SCHEMA`:
```
click: { x: number (0..1, from left), y: number (0..1, from top), label: string }
```
- `x,y` are fractions of the **screenshot image** (not the canvas).
- Only on `kind:"screenshot"` scenes that have a clear clickable element; omitted otherwise.
- Not in the scene `required` list (optional).

### 2. Authoring prompt
Replace the preset-based cursor hint (`_animation_instruction` / `_with_animation_preference`) with a fixed, always-on instruction: for each screenshot scene, if there is a clear clickable element, set `click` to its center (fractions) + a short `label`; otherwise omit `click`. The motion-design guidance still comes from the editable `remotion-best-practices` skill.

### 3. Validation / fallback (`validate_anim_plan`)
If `click` is present: require `x,y` numbers in `[0,1]`; otherwise drop the `click` (do not fail the plan). Non-screenshot scenes never carry a click.

### 4. Worker → renderer plumbing
Forward `click` through `video_remotion_render.py` scene dict → `video_remotion_client` payload → `render.ts` RenderRequest scene type + `inputProps` → `Video.tsx` Scene type.

### 5. Composition (`theme-parity.tsx`) — the cursor
Replace the preset/`cursorTrajectory` generic cursor with a **target cursor**:
- Render the cursor **inside the screenshot frame, over the image**, positioned at `left: x*100%, top: y*100%` of the image box — so it stays glued to the button as the Ken-Burns frame zooms/pans.
- Animate (using Remotion `interpolate` + `Easing`, per best practices): cursor **moves in** from a small offset toward the target over the scene's first ~45%, then a **click pulse** at ~50–65%.
- Show the cursor only when `scene.click` is present. Remove the `animationPreset === "cursor_click"` gating and the old `cursorTrajectory`/`scaleCursorTrajectory` cursor path.

### 6. Web UI (`static/video.html`)
Remove the Animation `<select id="animation-preset">` and its `_animationPreset()` send. The backend keeps accepting `animation_preset` (defaulted) for back-compat with existing rows/API, but it no longer drives cursor behavior.

## Out of scope
- Removing the `animation_preset` column / API field (kept, defaulted, for back-compat).
- Discord UI (the picker is web-only; Discord exposes Slideshow/Animated mode, not the preset).
- Pixel-perfect element detection (accepted approximate AI coords + omit-on-uncertain).
- Migrating the rest of the composition's easing to `interpolate` (separate, deferred item).

## Testing
- `video_plan`: schema carries optional `click`; `validate_anim_plan` keeps valid clicks and drops out-of-range/garbage; prompt contains the smart-click instruction.
- `render.ts`: `buildRenderConfig` forwards `click` into scene inputProps.
- Composition: a pure helper (e.g. `clickCursor(progress, target)`) returning position + pulse — unit-tested for move-in + pulse timing; vitest + `tsc` green.
- Live: render a real job whose screenshots have buttons; confirm the cursor lands on/near the buttons and is absent on no-target scenes.
