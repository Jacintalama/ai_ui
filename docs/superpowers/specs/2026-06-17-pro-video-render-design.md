# Pro Video Render: Styles, Voices, Music (Design Spec)

**Date:** 2026-06-17
**Status:** Approved (pending self-review + user sign-off)
**Feature area:** `mcp-servers/tasks` video generator render engine

## Goal

Turn the generated video from a flat, basic narrated slideshow into a professional-looking video. The user picks one of three **styles** and a **voice** at create time; the render engine applies style-specific transitions, motion, captions, color grade, intro/outro cards, and a per-style ducked music bed, with the narration synced per scene. Stays within the box budget (2 vCPU / 4GB ARM, 600s render timeout).

## Background (current render, verified)

`video_render.py` builds ONE ffmpeg invocation: N looped screenshots + N full-frame caption PNGs (Pillow) + one Piper `voice.mp3`. Each scene is scaled and **black-bar** letterboxed, given one identical slow `zoompan` push-in (`z=min(zoom+0.0015,1.08)`, top-left anchored, jittery), the static caption PNG overlaid, then scenes folded with `xfade=transition=fade` or `concat`. Encode: `libx264 -preset veryfast -pix_fmt yuv420p -threads 1 -r 30 -shortest` (no `-crf`, no `+faststart`). Voice is one continuous Piper `en_US-amy-medium` blob mapped with `-shortest` (can cut mid-sentence; never synced to scenes). `plan.title` is collected but unused. Styles in `templates_video/` only change caption look + crossfade length. Constraints: `MAX_TOTAL_SECONDS=60`, scenes 0.5-15s, `VIDEO_RENDER_TIMEOUT` default 600s.

## Decisions (approved)

- **Three selectable styles:** Cinematic, Snappy social, Clean product-demo. **User picks per video** (Style dropdown on the create form; default Clean product-demo).
- **User picks the voice** (Voice dropdown backed by several installed voices) and narration is **synced per scene** (no mid-sentence cuts).
- **Per-style background music** (bundled CC0 track per style, ducked under the voice). No copyrighted audio, ever.
- **16:9 only** in this pass. Vertical/square (9:16, 1:1) is deferred.
- **Approach:** extend the existing single-invocation ffmpeg builder, parameterized by a style config. (Rejected MoviePy: documented ~12GB RAM blowups on small boxes. Rejected per-scene-clip rendering for v1 except as the >12-scene fallback.)
- The repo's `huashu-design` / `ui-ux-pro-max` skills inform the visual spec of captions, lower-thirds, and intro/outro cards (type scale, palette, spacing, glass/rounded band). They spec the look; ffmpeg/Pillow render it.

## Architecture

### Style system (`templates_video/`)
A `STYLE` registry keyed by style id. Each style is a frozen config that drives the render:
- `transition_map`: which xfade types this style uses + default durations.
- `motion`: Ken Burns profile (eased supersampled / gentle / minimal-or-cut) and whether to alternate zoom direction.
- `caption`: font, size ratio, band design (glass / rounded / flat), animation (fade/slide-in-out), drop shadow, position, title-safe margins.
- `grade`: the color-grade filter chain (or none).
- `letterbox`: none | blurred-fill | cinematic 2.39 blurred-fill.
- `cards`: intro title card + outro CTA card design (colors, fonts, logo).
- `music`: the bundled track id + target music level.

The three styles:
- **Cinematic:** eased 2x-supersampled Ken Burns; `eq+curves+vignette+noise` grade; optional 2.39 letterbox (blurred fill); glass lower-thirds; `fade`/`fadeblack` section breaks 0.6-0.8s; ambient music.
- **Snappy social:** 2-4s scenes; mostly hard cuts + occasional `smoothleft`; bold pop-in captions; no letterbox; energetic music. (16:9 for now.)
- **Clean product-demo:** gentle push, light/no grade; crisp caption on a rounded band; brand logo + accent; `dissolve`/`fade`; title + outro CTA; low neutral music.

### Plan + create form
- **`style` and `voice` are user choices, not model output.** The user selects them on the create form; they are validated server-side against allowlists (style registry ids; installed voice ids) and stored on the job. They are NOT part of `PLAN_SCHEMA` and the model never emits them. **Source of truth: the user's create-form choice wins, is written to the job row, and is passed to the renderer.**
- **Migration 024** adds `style TEXT` and `voice TEXT` columns to `tasks.video_jobs` (defaults: the Clean product-demo style id and the default voice id). The column approach is chosen over re-deriving from the plan so the choice is durable and auditable. The renderer picks its visual config via an extended `get_style(job.style)` that covers the 3 new style ids.
- `video_plan.py` `PLAN_SCHEMA` gains a per-scene `narration` string (see Audio) and widens the scene `transition` enum to `{cut,crossfade,dissolve,next,section}`. It does NOT gain `style`/`voice`. `title` is now consumed (intro card). `validate_plan` is updated to allow the new per-scene `narration` field.
- The model's existing `template_id` (`product_demo` / `feature_walkthrough`) stays as the CONTENT template (what the script and scenes are about) but NO LONGER controls visual styling. Visual styling is driven solely by the job's `style`. `template_id` and `style` are independent axes.
- `routes_video.py` upload form gains `style` and `voice` fields (validated against the allowlists; 400 on unknown). `static/video.html` create form gains a **Style** dropdown and a **Voice** dropdown. The worker reads `style`/`voice` off the job and passes them to the executor/renderer.
- **`clamp_plan` fix:** after the proportional rescale re-clamps each scene up to the 0.5s floor, it currently does not re-check the total, so a floor-bumped plan can exceed 60s. Add a final pass that re-verifies total <= 60 after the floor re-clamp (trim the longest scenes back down, never below the 0.5s floor).

### Render engine (`video_render.py`) - concrete changes
Keep the single-invocation filtergraph + the accumulating-offset xfade math verbatim. The structural change is how each scene's subgraph is built; the numbered items below are the building blocks, wired together by the labels described next.

**Per-scene subgraph wiring (`_scene_filter_stmts` restructured).** A scene is no longer one comma-chained filter string. The blurred-fill letterbox is a multi-node subgraph (split -> two scales -> centered overlay) that CANNOT be comma-chained, and the 2x supersample + grade + caption overlay add still more nodes, so each scene is emitted as a **multi-statement subgraph with DISTINCT intermediate labels**. Consequently `_scale_pad_filter` and `_zoompan_filter` become **subgraph builders** that emit labeled statements, NOT single inline filters. For scene `i` (with `n` screenshot inputs, so the caption PNG for scene `i` is input `[{n+i}:v]`), the statements are emitted in this exact order and label chain:

- `[{i}:v]` -> blurred-fill cover/contain -> `[base{i}]`
- `[base{i}]` -> 2x-supersample eased zoompan -> `[mot{i}]`
- `[mot{i}]` -> color grade for the job's style (may be a no-op pass-through) -> `[grad{i}]`
- `[{n+i}:v]` -> caption alpha fade in/out -> `[cap{i}]`
- `[grad{i}][cap{i}]overlay=0:0,format=yuv420p` -> `[v{i}]`

The `[v{i}]` outputs are exactly what the xfade/concat chain (item 1) stitches together; the intro/outro cards (item 6) are prepended/appended to that same chain. The snippets in items 1-7 below are the building blocks and the labels above are how they connect. These are subgraphs, not single-filter drop-in replacements.

1. **Transitions palette** (widen enum, map in `_chain_stmts`, offset math UNCHANGED):
```python
XFADE = {"crossfade":"fade", "dissolve":"dissolve", "next":"smoothleft", "section":"fadeblack"}
xf = XFADE.get(scene.transition)            # 'cut' -> None (concat)
if xf:
    fade = 0.7 if xf == "fadeblack" else fade
    # CLAMP (not merely validate): with a 0.5s scene floor an unclamped 0.7s fadeblack is invalid
    fade = min(fade, 0.9 * min(prev_scene_dur, scene_dur))
    offset = max(0.0, round(acc_duration - fade, 4))
    stmts.append(f"{prev}{nxt}xfade=transition={xf}:duration={fade}:offset={offset}{out}")
    acc_duration += scene_dur - fade
else:
    stmts.append(f"{prev}{nxt}concat=n=2:v=1:a=0{out}")
    acc_duration += scene_dur
# fade is CLAMPED above to < min(adjacent scene durations) (with the 0.5s floor an unclamped 0.7s fadeblack would be invalid); feature-detect smooth*/fadeblack at startup via `ffmpeg -h filter=xfade`
```

2. **Smooth + varied Ken Burns** (`_zoompan_filter` becomes a subgraph builder, NOT a single inline filter; 2x supersample, cosine ease, alternate in/out). The builder wraps the chain below as the statement `[base{i}]<chain>[mot{i}]`:
```python
ss = width * 2                       # 2x kills integer-pixel jitter (NOT 8000px -> OOM)
if index % 2 == 0:                   # push-in
    z = f"1+0.16*(1-cos(PI*on/{frames}))/2"
else:                                # pull-out
    z = f"1.16-0.16*(1-cos(PI*on/{frames}))/2"
return (f"scale={ss}:-2,zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={width}x{height}:fps={fps}")
```
(Snappy social uses a minimal/none motion profile; Cinematic uses the full eased version.)

3. **Blurred-background letterbox fill** (`_scale_pad_filter` becomes a subgraph builder, NOT a single inline pad; it emits the multi-node statements below, ending in `[base{i}]`):
```python
f"[{i}:v]split=2[fg{i}][bgsrc{i}];"
f"[bgsrc{i}]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=20:1[bg{i}b];"
f"[fg{i}]scale={W}:{H}:force_original_aspect_ratio=decrease,setsar=1[fg{i}c];"
f"[bg{i}b][fg{i}c]overlay=(W-w)/2:(H-h)/2,format=yuv420p[base{i}]"
```

4. **Color grade** per style, emitted as the statement `[mot{i}]<grade>[grad{i}]` BEFORE the caption overlay so text stays crisp (ARM-safe `noise`, never `geq`). For Product-demo this is a no-op pass-through (`[mot{i}]null[grad{i}]`), so the `[grad{i}]` label always exists:
```
eq=contrast=1.06:saturation=1.12:brightness=0.01,
curves=all='0/0 0.25/0.22 0.75/0.80 1/1',
vignette=angle=PI/5:eval=init,
noise=alls=8:allf=t+u
```
(Product-demo: light or no grade. Cinematic: full chain. Social: punchy eq, no vignette.)

5. **Animated captions** (timed alpha fade on the **Pillow-rendered** caption PNG input before overlay; this is a hard requirement, caption text is NEVER drawn with `drawtext`). Fade durations are scaled to the scene length so in/out never overlap on a 0.5s scene:
```python
fin  = min(0.3, dur / 3)
fout = min(0.4, dur / 3)
f"[{n+i}:v]format=rgba,fade=t=in:st=0:d={fin}:alpha=1,"
f"fade=t=out:st={round(dur-fout,3)}:d={fout}:alpha=1[cap{i}];"
f"[grad{i}][cap{i}]overlay=0:0:format=auto,format=yuv420p[v{i}]"
```
Plus upgrade `render_caption_png`: rounded/gradient (or glass) band + a drop-shadow pass before the main text + title-safe placement, parameterized by the style's `caption` config. Snappy social uses a bold scale-pop reveal.

6. **Intro title card + outro CTA card** (uses `plan.title`; **Pillow-rendered PNGs over lavfi color, in the SAME single ffmpeg invocation**, NOT separate mp4 renders, NOT `drawtext` with user text):
- Add two extra inputs to the one invocation: a `lavfi` color source for the intro and one for the outro. Overlay each with a **Pillow-rendered card PNG** (title text / CTA text plus the bundled logo), the same injection-safe path as captions. `drawtext` with user-supplied text is forbidden (its parser breaks on `:` / `'` / `\` even when shell-safe).
- xfade-stitch the cards as the FIRST and LAST segments of the same accumulating-offset chain: `[intro]` xfades into `[v0]` at the head and `[vN-1]` xfades into `[outro]` at the tail; the offsets fold into the same math as the body.
- The cards carry **no voice** (per-style music bed only). The per-style music bed spans **intro + scenes + outro**.
- Cards are **ADDITIONAL to** the 60s scene cap: total duration is approx 3s intro + (scenes, <= 60s) + 3s outro.
```
# inside the one filter_complex (sketch); intro/outro PNGs are Pillow-rendered:
[introcolor][intropng]overlay=0:0,fade=t=in:st=0:d=0.4,fade=t=out:st=2.4:d=0.5[intro]
[outrocolor][outropng]overlay=0:0,fade=t=in:st=0:d=0.4,fade=t=out:st=2.4:d=0.5[outro]
# then in the single chain: [intro][v0]xfade=...   ...   [vN-1][outro]xfade=...
```

7. **Delivery-grade encode** (replace the argv tail). The music bed is a looped input (`-stream_loop -1 -i bed`) and the final audio map is the ducked-music mix `[aout]`, NOT the bare `-map {voice}:a`. The final video map `[vout]` is the xfade chain's last output. `-shortest` stays only as a safety net: the video length already follows the audio because each scene's `-t` matches its spoken length:
```
# ... -stream_loop -1 -i bed.mp3   (music input, added earlier in the argv)
-map "[vout]" -map "[aout]" \
-c:v libx264 -preset veryfast -crf 21 -pix_fmt yuv420p -threads 2 -movflags +faststart \
-c:a aac -b:a 192k -r 30 -shortest out.mp4
```

### Audio (`video_executor.py`)
1. **Per-scene narration sync + voice-sync data flow (biggest perceived win).** Each scene in `PLAN_SCHEMA` carries its own `narration` string: the model writes one narration line per scene, so N scenes always yield N narration lines and captions/voice/visuals stay aligned. **Fallback:** if per-scene `narration` is absent (older plans), sentence-split `narration_script` across the scenes. The sync flow, in order, with where each step runs and what it returns:
   - **`video_executor.render` (host side)** synthesizes the chosen voice **per scene** (one clip per scene), `ffprobe`s each clip's length, and **RETURNS the per-scene spoken lengths to the controller**.
   - **The controller** sets each `scene.duration_s = max(MIN_SCENE_SECONDS, spoken_len + tail)` (tail ~0.4s), then re-applies the clamp/cap rules (`clamp_plan`, with the floor-then-total re-check fix).
   - **Then** the controller builds the filtergraph with matching per-scene `-t` and caption fade timings, and concatenates the per-scene voice clips into the single voice track.
   - **Video length follows the audio.** We do NOT rely on `-shortest` to truncate to the voice; it stays only as a safety net.
   - **60s cap WITHOUT mid-sentence cuts.** Durations are NEVER shrunk below a scene's spoken length (that would reintroduce the very cuts this change removes). Instead: (a) `generate_plan` targets a **speech budget of <= ~55s total narration**; (b) if the measured total spoken length still exceeds 60s, apply a **mild global voice `atempo` (capped at ~1.2x)** to fit. Budget first, gentle atempo second, that is how the cap is honored.
2. **Voice picker:** several Piper voices installed on the host; the chosen `voice` id maps to a model path (validated against an allowlist; never interpolate user input into the path).
3. **Two-pass loudnorm voice pre-pass** (separate audio-only call) + clarity chain:
```
# pass 1 measure -> parse measured_I/TP/LRA/thresh/offset
ffmpeg -i voice.wav -af loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json -f null -
# pass 2 apply + clarity -> voice_normalized.wav
ffmpeg -i voice.wav -af "highpass=f=90,acompressor=threshold=-18dB:ratio=3:attack=10:release=120,loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=...:linear=true" -ar 48000 voice_normalized.wav
```
4. **Ducked music bed** (per style; `-stream_loop -1 -i bed` as input M):
```
[{V}:a]asplit=2[nkey][nmix];
[{M}:a]volume=0.25,afade=t=in:st=0:d=2[mus];
[mus][nkey]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=400:makeup=1[duck];
[nmix][duck]amix=inputs=2:duration=first:normalize=0[aout]
```
Music level + track come from the style config; gated behind a config flag so it can be disabled. The bed spans intro + scenes + outro (the cards have music but no voice).

### Assets (host + repo)
- Install a curated set of Piper voices on the host (a few `en_US`/`en_GB`, male + female), each upgraded to `*-high` where available. Provisioning added to the agent-VM provision script.
- Bundle 3 CC0 / royalty-free music tracks (one per style) under `mcp-servers/tasks/assets/music/` with a `LICENSE` file documenting source + CC0 status. A bundled `logo.png` + an embeddable font (e.g. Inter) for cards.

## Performance budget (ARM-safe; from research)
Safe on 2 vCPU / 4GB within 600s with `-threads 2`: xfade is per-pixel cheap (only the brief overlap decodes two streams); a **2x** supersample zoompan (`scale=2560/3840:-2`, ~33MB/frame) fixes jitter without the 8000px (~144MB/frame) OOM risk; `eq/curves/vignette`, `noise` grain, drawtext, lavfi cards, and all audio filters are near-free; `+faststart`/`-crf 21` cost nothing. **AVOID:** 8000px supersample (OOM), `geq`/deflate grain (minutes per clip), `minterpolate` 60fps (blows the timeout), x264 preset slower than `medium` or 2-pass at 1080p, and MoviePy. The real RAM ceiling is many simultaneous `-loop` image inputs in one `filter_complex`, so pre-scale PNGs to target resolution and **cap ~12 scenes**; for longer decks, render per-scene clips then concat (only two streams live per overlap). Expected wall time with all upgrades at 1080p30 veryfast `-crf 21` + 2x supersample for a <=60s clip: roughly **2-5 min**. Keep **720p30 as the safety valve** and benchmark a worst-case 12-scene plan before enabling.

## Phasing
- **Phase 1 - the look:** style registry + style picker + transitions palette + smooth/varied Ken Burns + blurred-fill letterbox + animated/designed captions + color grade + intro/outro cards + delivery-grade encode. (Biggest visual jump; no new host assets except logo/font.)
- **Phase 2 - the sound:** per-scene narration sync + voice picker (install multi-voice on host) + two-pass loudnorm + per-style ducked music (bundle CC0 tracks).

Each phase ships, deploys, and is benchmarked on prod before the next.

## Error handling
- Feature-detect xfade transition names at startup; fall back to `fade`/`cut` if a name is unavailable.
- Validate `style`/`voice` against allowlists (400 on unknown); never interpolate user values into ffmpeg argv or file paths (voices resolved via a dict; title/caption/card text rendered via Pillow PNGs only, never `drawtext` with user text).
- If music/voice asset missing, render without it (log a warning) rather than failing.
- Keep the existing render timeout + the 720p safety valve; on timeout/failure the job goes `failed` with the error, as today.
- Per-scene voice sync clamps to the duration rules but NEVER below a scene's spoken length. The 60s cap is honored by the speech budget (`generate_plan` targets <= ~55s) plus a mild global `atempo` (<= ~1.2x) when measured speech still exceeds 60s, not by shrinking scenes under their narration. `clamp_plan` (with the floor-then-total re-check fix) still enforces the per-scene 0.5-15s and total <= 60s bounds, and the section-break `fadeblack` duration is CLAMPED to < min(adjacent scene durations) rather than only validated.

## Security
No new secrets. User-supplied text (title, captions, card text, prompt) never reaches a shell: it is rendered via Pillow PNGs (the injection-safe path), never `drawtext` (whose parser breaks on `:` / `'` / `\`). Voice/style/music resolved via server-side allowlists, not user paths. Music is CC0 only.

## Testing
- Unit-test the pure builder: each style config -> expected filtergraph fragments (transition mapping, motion expr, grade chain, letterbox, caption fade, encode tail). Offline, no ffmpeg.
- Plan-schema tests: the widened `transition` enum validates and unknown values are rejected; per-scene `narration` is accepted and the sentence-split fallback fires when it is absent; `clamp_plan` holds AND re-verifies total <= 60 after the floor re-clamp. `style`/`voice` are NOT in the plan schema; they are covered at the create-form/allowlist layer (valid ids accepted, unknown -> 400).
- Audio: per-scene split + duration-from-audio logic (mock ffprobe); voice allowlist resolution; loudnorm/duck filter strings well-formed.
- Real-render benchmark on prod: one render per style at 720p and 1080p, worst-case ~12 scenes, confirm under the 600s budget and no container restart, watch `free -h`.

## Out of scope (deferred)
- Vertical/square export (9:16, 1:1).
- Advanced SSML prosody/pause control.
- Per-scene different styles (one style per video).

## Decisions log
- 3 selectable styles, user-picks at create (default product-demo); user-picks voice; per-style CC0 ducked music; per-scene voice sync; 16:9 only; extend the single-ffmpeg builder; `-threads 2` + 2x supersample + 720p safety valve as the perf guardrails; phased (look, then sound).
