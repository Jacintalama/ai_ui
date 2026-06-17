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
- `video_plan.py` schema gains `style` (enum of the 3 ids) and `voice` (enum of installed voice ids); `transition` enum widens to `{cut,crossfade,dissolve,next,section}`. `title` is now consumed (intro card). `clamp_plan` unchanged.
- `routes_video.py` upload form gains `style` and `voice` fields (validated against the registries). `static/video.html` create form gains a **Style** dropdown and a **Voice** dropdown.
- The worker passes `style`/`voice` through to the executor/renderer.

### Render engine (`video_render.py`) - concrete changes
Keep the single-invocation filtergraph + the accumulating-offset xfade math verbatim. Add:

1. **Transitions palette** (widen enum, map in `_chain_stmts`, offset math UNCHANGED):
```python
XFADE = {"crossfade":"fade", "dissolve":"dissolve", "next":"smoothleft", "section":"fadeblack"}
xf = XFADE.get(scene.transition)            # 'cut' -> None (concat)
if xf:
    fade = 0.7 if xf == "fadeblack" else fade
    offset = max(0.0, round(acc_duration - fade, 4))
    stmts.append(f"{prev}{nxt}xfade=transition={xf}:duration={fade}:offset={offset}{out}")
    acc_duration += scene_dur - fade
else:
    stmts.append(f"{prev}{nxt}concat=n=2:v=1:a=0{out}")
    acc_duration += scene_dur
# validate fade < min(adjacent scene durations); feature-detect smooth*/fadeblack at startup via `ffmpeg -h filter=xfade`
```

2. **Smooth + varied Ken Burns** (replace `_zoompan_filter`; 2x supersample, cosine ease, alternate in/out):
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

3. **Blurred-background letterbox fill** (replace black pad in `_scale_pad_filter`):
```python
f"[{i}:v]split=2[fg{i}][bgsrc{i}];"
f"[bgsrc{i}]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=20:1[bg{i}b];"
f"[fg{i}]scale={W}:{H}:force_original_aspect_ratio=decrease,setsar=1[fg{i}c];"
f"[bg{i}b][fg{i}c]overlay=(W-w)/2:(H-h)/2,format=yuv420p[bg{i}]"
```

4. **Color grade** per style (append in `_scene_filter_stmts` BEFORE the caption overlay so text stays crisp; ARM-safe `noise`, never `geq`):
```
eq=contrast=1.06:saturation=1.12:brightness=0.01,
curves=all='0/0 0.25/0.22 0.75/0.80 1/1',
vignette=angle=PI/5:eval=init,
noise=alls=8:allf=t+u
```
(Product-demo: light or no grade. Cinematic: full chain. Social: punchy eq, no vignette.)

5. **Animated captions** (timed alpha fade on the caption PNG input before overlay; keeps the Pillow PNG path):
```python
f"[{n+i}:v]format=rgba,fade=t=in:st=0:d=0.3:alpha=1,fade=t=out:st={round(dur-0.4,3)}:d=0.4:alpha=1[cap{i}];"
f"[bg{i}][cap{i}]overlay=0:0:format=auto,format=yuv420p[v{i}]"
```
Plus upgrade `render_caption_png`: rounded/gradient (or glass) band + a drop-shadow pass before the main text + title-safe placement, parameterized by the style's `caption` config. Snappy social uses a bold scale-pop reveal.

6. **Intro title card + outro CTA card** (uses `plan.title`; lavfi color card + drawtext + logo overlay, xfade-stitched onto the body):
```
ffmpeg -f lavfi -i color=c=0x0E1116:s={W}x{H}:r=30:d=3 -i logo.png -filter_complex \
 "[0:v]drawtext=fontfile=/fonts/Inter-Bold.ttf:text='{title}':fontsize=96:fontcolor=white:\
  x=(w-text_w)/2:y=(h-text_h)/2-30:alpha='min(t/0.8,1)',fade=t=in:st=0:d=0.4,fade=t=out:st=2.4:d=0.5[bg];\
  [bg][1:v]overlay=(W-w)/2:H-160:enable='gte(t,0.4)'[v]" -map "[v]" ... intro.mp4
# outro = same card with CTA 'ai-ui.coolestdomain.win'; stitched via the xfade chain
```
Title text must be escaped/sanitized for drawtext (no shell/text injection); prefer rendering the title card text via Pillow (same injection-safe path as captions) if drawtext escaping is fragile.

7. **Delivery-grade encode** (replace the argv tail):
```
-c:v libx264 -preset veryfast -crf 21 -pix_fmt yuv420p -threads 2 -movflags +faststart -c:a aac -b:a 192k -r 30 -shortest out.mp4
```

### Audio (`video_executor.py`)
1. **Per-scene narration sync (biggest perceived win):** split `plan.narration_script` per scene (one line per scene, or sentence-aligned), run the chosen voice per scene, `ffprobe` each clip's length, set/adjust scene durations from the spoken length (clamped to 0.5-15, total <=60), then concat the voice clips so captions/visuals track the words.
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
Music level + track come from the style config; gated behind a config flag so it can be disabled.

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
- Validate `style`/`voice` against allowlists (400 on unknown); never interpolate user values into ffmpeg argv or file paths (voices resolved via a dict; title/caption text rendered via Pillow or shlex-escaped drawtext).
- If music/voice asset missing, render without it (log a warning) rather than failing.
- Keep the existing render timeout + the 720p safety valve; on timeout/failure the job goes `failed` with the error, as today.
- Per-scene voice sync must clamp to the duration rules and the 60s cap (reuse `clamp_plan`).

## Security
No new secrets. User-supplied text (title, captions, prompt) never reaches a shell unescaped: captions/title via Pillow PNGs (current injection-safe path) or shlex-escaped drawtext. Voice/style/music resolved via server-side allowlists, not user paths. Music is CC0 only.

## Testing
- Unit-test the pure builder: each style config -> expected filtergraph fragments (transition mapping, motion expr, grade chain, letterbox, caption fade, encode tail). Offline, no ffmpeg.
- Plan-schema tests: `style`/`voice`/widened-`transition` enums validate; unknown values rejected; `clamp_plan` still holds.
- Audio: per-scene split + duration-from-audio logic (mock ffprobe); voice allowlist resolution; loudnorm/duck filter strings well-formed.
- Real-render benchmark on prod: one render per style at 720p and 1080p, worst-case ~12 scenes, confirm under the 600s budget and no container restart, watch `free -h`.

## Out of scope (deferred)
- Vertical/square export (9:16, 1:1).
- Advanced SSML prosody/pause control.
- Per-scene different styles (one style per video).

## Decisions log
- 3 selectable styles, user-picks at create (default product-demo); user-picks voice; per-style CC0 ducked music; per-scene voice sync; 16:9 only; extend the single-ffmpeg builder; `-threads 2` + 2x supersample + 720p safety valve as the perf guardrails; phased (look, then sound).
