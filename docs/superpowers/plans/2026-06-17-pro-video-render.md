# Pro Video Render (Styles / Voices / Music) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the AIUI video render from a flat narrated slideshow to a professional video with 3 user-selectable styles, a user-selectable voice, per-scene narration sync, per-style ducked music, color grade, smooth motion, animated captions, and intro/outro cards.

**Architecture:** Extend the existing single-invocation ffmpeg builder (`video_render.py`), parameterized by a per-style `StyleConfig` registry. `style`/`voice` are user choices stored on the job (migration 024) and passed to the renderer; the model's `template_id` stays as the content template only. Render filter-string builders are pure and unit-tested offline; the real render is benchmarked on prod (720p safety valve).

**Tech Stack:** Python 3.11, ffmpeg (xfade/zoompan/eq/curves/vignette/noise/sidechaincompress/loudnorm/amix), Pillow (captions + cards), Piper TTS (multi-voice), FastAPI, async SQLAlchemy + asyncpg, vanilla JS form.

**Spec:** `docs/superpowers/specs/2026-06-17-pro-video-render-design.md`

---

## Conventions (read first)

- Run tests from `mcp-servers/tasks/`: `cd "mcp-servers/tasks" && python -m pytest tests/<file> -v`. Async tests use pytest-asyncio auto mode (no decorator).
- **The render filter-string builders are PURE and fully unit-testable OFFLINE** (assert the emitted filtergraph strings / argv). This is the bulk of Phase 1 and needs no ffmpeg or DB. Caption/card PNG rendering is testable with Pillow offline. DB tests (migration/job columns/routes) use `@pytest.mark.skipif(not _HAVE_DB)` (skip locally). The real ffmpeg render is verified by a prod benchmark, not a unit test.
- Current code map (verified): `video_render.py` has `RESOLUTIONS`, `FPS=30`, `resolution_size`, `render_caption_png` (L144), `render_all_captions` (L216, keys off `get_style(plan["template_id"])`), `_scale_pad_filter` (L255), `_zoompan_filter` (L263), `_overlay_filter` (L271), `_scene_filter_stmts` (L281), `_chain_stmts` (L300), `build_filtergraph` (L336), `build_render_script` (L362). `video_plan.py` has `TEMPLATES`, `MAX_TOTAL_SECONDS=60`, `MIN_SCENE_SECONDS=0.5`, `MAX_SCENE_SECONDS=15.0`, `PLAN_SCHEMA` (L24), `validate_plan` (L51), `clamp_plan` (L69), `generate_plan`. `templates_video/__init__.py` has `CaptionStyle` (frozen: font_size_ratio, position, band_color, band_opacity, fade_duration), `STYLES`, `get_style(template_id)`. `video_executor.py` has `VideoRenderExecutor` with `_voice` + `render`.
- Migrations re-run every startup (db.py), so migration 024 MUST be idempotent (`ADD COLUMN IF NOT EXISTS`).
- PEP8 + type hints. No `print`. **No em-dashes.** Commit per task; **no AI attribution / Co-Authored-By**; never `--no-verify`. Never touch `.env` or `templates.py`.
- Deploy (per phase) = `docker cp` changed files into the `tasks` container + `docker restart tasks` (preserves `VIDEO_ENABLED`), per the established pattern; host asset installs (voices/music) are separate steps.

## File structure

**New files**
- `mcp-servers/tasks/templates_video/style_config.py` — `StyleConfig` dataclass + sub-configs (transitions, motion, grade, letterbox, cards, music) and `STYLE_CONFIGS` registry + `get_style_config(style_id)`.
- `mcp-servers/tasks/templates_video/cinematic.py`, `snappy_social.py`, `clean_product_demo.py` — per-style `STYLE` dicts.
- `mcp-servers/tasks/video_cards.py` — Pillow renderers for the intro title card + outro CTA card PNGs (injection-safe text).
- `mcp-servers/tasks/migrations/024_video_style_voice.sql` — `style`/`voice` columns.
- `mcp-servers/tasks/assets/music/` — 3 CC0 tracks + `LICENSE`; `assets/logo.png`; an embeddable font.
- Tests: `tests/test_style_config.py`, `tests/test_video_cards.py`, and additions to `tests/test_video_render.py`, `tests/test_video_plan.py`, `tests/test_video_executor.py`, `tests/test_routes_video_*`.

**Modified files**
- `video_render.py` — `_scene_filter_stmts` restructured to a labeled subgraph; `_chain_stmts` transition palette; `_zoompan_filter`/`_scale_pad_filter` become subgraph builders; grade; animated captions; `render_caption_png` style-driven design; intro/outro stitching; encode tail. Keys visual config off the job `style`.
- `video_plan.py` — per-scene `narration`; widened `transition` enum; `clamp_plan` total re-check; `validate_plan` updates.
- `video_models.py` — `style`/`voice` columns on `VideoJob`.
- `routes_video.py` — `style`/`voice` upload fields + allowlist validation; pass to worker.
- `video_worker.py` — pass `style`/`voice` into the render; voice-first flow (Phase 2).
- `video_executor.py` — per-scene voice synth + ffprobe durations + loudnorm + ducked music (Phase 2).
- `static/video.html` — Style + Voice dropdowns.
- `templates_video/__init__.py` — keep `CaptionStyle`/`get_style`; re-export the new style config.

---

# PHASE 1 — THE LOOK (16:9, no audio changes)

### Task 1.1: StyleConfig registry

**Files:** Create `templates_video/style_config.py`, `templates_video/cinematic.py`, `snappy_social.py`, `clean_product_demo.py`; Modify `templates_video/__init__.py`; Test `tests/test_style_config.py`

- [ ] **Step 1: Failing test** — `test_style_config.py`:
```python
from templates_video.style_config import get_style_config, STYLE_CONFIGS

def test_three_styles_registered():
    assert set(STYLE_CONFIGS) == {"cinematic", "snappy_social", "clean_product_demo"}

def test_get_style_config_fallback():
    c = get_style_config("nope")            # unknown -> default clean_product_demo
    assert c.id == "clean_product_demo"

def test_style_shapes():
    c = get_style_config("cinematic")
    assert c.grade                          # cinematic has a grade chain (non-empty)
    assert c.letterbox in ("none", "blurfill", "cinema239")
    assert c.motion in ("eased", "gentle", "minimal")
    assert "crossfade" in c.transitions     # transitions maps logical->xfade name
    assert c.music                          # a music track id
    cp = get_style_config("clean_product_demo")
    assert cp.grade == ""                   # product-demo: no grade
```

- [ ] **Step 2: Run -> fail** (`pytest tests/test_style_config.py -v` -> ImportError).
- [ ] **Step 3: Implement** `style_config.py` with a frozen `StyleConfig` dataclass: `id, caption (CaptionStyle), transitions: dict[str,str], motion: str, grade: str, letterbox: str, cards: dict, music: str, music_level: float`, plus the 3 per-style modules and `STYLE_CONFIGS` + `get_style_config(style_id)` (fallback to `clean_product_demo`). Cinematic: motion="eased", grade=the eq/curves/vignette/noise chain, letterbox="cinema239" or "blurfill", glass caption, music="ambient". snappy_social: motion="minimal", grade punchy-eq, letterbox="none", bold caption, music="energetic". clean_product_demo: motion="gentle", grade="", letterbox="blurfill", rounded-band caption + logo, music="neutral". Re-export from `__init__.py`.
- [ ] **Step 4: Run -> pass.**
- [ ] **Step 5: Commit** `feat(video): StyleConfig registry for 3 pro styles`.

### Task 1.2: Plan schema — per-scene narration, transition enum, clamp fix

**Files:** Modify `video_plan.py`; Test `tests/test_video_plan.py`

- [ ] **Step 1: Failing tests**: (a) `PLAN_SCHEMA` scene items include a `narration` string property and the scene `transition` enum is `{cut,crossfade,dissolve,next,section}`; (b) `validate_plan` accepts a plan whose scenes carry `narration`; (c) `clamp_plan` on a many-tiny-scene plan that floor-bumps over 60s returns total `<= 60`.
- [ ] **Step 2: Run -> fail.**
- [ ] **Step 3: Implement**: add `narration` (string) to the scene schema; widen the `transition` enum; in `validate_plan` allow/ignore `narration` (no hard requirement, for back-compat); in `clamp_plan` add a final pass: after the floor re-clamp, if `sum > MAX_TOTAL_SECONDS`, trim the longest scenes down (never below `MIN_SCENE_SECONDS`) until `<= 60`.
- [ ] **Step 4: Run -> pass.**
- [ ] **Step 5: Commit** `feat(video): per-scene narration + wider transitions + clamp total re-check`.

### Task 1.3: Job columns (migration 024 + ORM)

**Files:** Create `migrations/024_video_style_voice.sql`; Modify `video_models.py`; Test `tests/test_video_models.py`

- [ ] **Step 1: Migration** (idempotent):
```sql
-- 024_video_style_voice.sql
ALTER TABLE tasks.video_jobs
  ADD COLUMN IF NOT EXISTS style TEXT NOT NULL DEFAULT 'clean_product_demo',
  ADD COLUMN IF NOT EXISTS voice TEXT;
```
- [ ] **Step 2: Failing test** — `VideoJob` has `style`/`voice` columns (offline `__table__.columns`).
- [ ] **Step 3: Implement** — add `style = Column(Text, nullable=False, default="clean_product_demo")` and `voice = Column(Text, nullable=True)` to `VideoJob`.
- [ ] **Step 4: Run -> pass.**
- [ ] **Step 5: Commit** `feat(video): style/voice columns on video_jobs (migration 024)`.

### Task 1.4: Transitions palette (`_chain_stmts`)

**Files:** Modify `video_render.py:300-333`; Test `tests/test_video_render.py`

- [ ] **Step 1: Failing tests**: a `dissolve` scene emits `xfade=transition=dissolve`; `next` -> `smoothleft`; `section` -> `fadeblack` with a fade clamped `< min(adjacent durations)`; `cut` emits `concat`; the accumulating `offset`/`acc_duration` math is unchanged for the existing cases.
- [ ] **Step 2: Run -> fail.**
- [ ] **Step 3: Implement** the `XFADE` map + `fade = min(fade, 0.9*min(prev_dur, cur_dur))` clamp, per the spec snippet; keep offset math verbatim. Add a startup feature-detect helper (`ffmpeg -h filter=xfade`) that downgrades unavailable names to `fade`; unit-test the mapping with the detector stubbed.
- [ ] **Step 4: Run -> pass.**
- [ ] **Step 5: Commit** `feat(video): expanded xfade transition palette`.

### Task 1.5: Smooth + varied Ken Burns (`_zoompan_filter` -> subgraph)

**Files:** Modify `video_render.py:263-268`; Test `tests/test_video_render.py`

- [ ] **Step 1: Failing tests**: even scene index emits a cosine push-in `z='1+0.16*(1-cos(PI*on/{frames}))/2'` with centered `x`/`y` and a `scale={2*width}:-2` supersample prefix; odd index emits the pull-out variant; `minimal` motion style emits a static (no zoompan) or gentle path.
- [ ] **Step 2: Run -> fail.**
- [ ] **Step 3: Implement** `_zoompan_filter(width,height,frames,index,motion,fps)` per the spec snippet (2x supersample, cosine ease, alternate in/out); `motion="minimal"` returns a plain `scale` (no zoompan) and `gentle` a slow push.
- [ ] **Step 4: Run -> pass.**
- [ ] **Step 5: Commit** `feat(video): smooth supersampled eased Ken Burns with per-scene variety`.

### Task 1.6: Blurred-fill letterbox (`_scale_pad_filter` -> subgraph)

**Files:** Modify `video_render.py:255-260`; Test `tests/test_video_render.py`

- [ ] **Step 1: Failing test**: for `letterbox="blurfill"` the builder emits the `split` + blurred cover (`boxblur`) background + contained foreground overlay subgraph (per spec snippet) producing a labeled `[base{i}]`; `letterbox="none"` emits a plain scale-to-cover/crop; `cinema239` adds the 2.39 framing.
- [ ] **Step 2: Run -> fail.**
- [ ] **Step 3: Implement** the blurfill subgraph builder returning labeled statements (input `[{i}:v]` -> `[base{i}]`).
- [ ] **Step 4: Run -> pass.**
- [ ] **Step 5: Commit** `feat(video): blurred-fill letterbox instead of black bars`.

### Task 1.7: Restructure `_scene_filter_stmts` (labeled subgraph)

**Files:** Modify `video_render.py:281-297`; Test `tests/test_video_render.py`

- [ ] **Step 1: Failing test**: for scene `i` (with `n` screenshots) the emitted statements connect `[{i}:v]->[base{i}]->[mot{i}]->[grad{i}]`, caption `[{n+i}:v]->[cap{i}]`, then `[grad{i}][cap{i}]overlay=0:0,format=yuv420p[v{i}]` — assert the label chain has no orphan and ends in `[v{i}]`.
- [ ] **Step 2: Run -> fail.**
- [ ] **Step 3: Implement** the restructured `_scene_filter_stmts` wiring the blurfill (1.6) -> zoompan (1.5) -> grade (1.8) -> caption-fade (1.9) -> overlay, using the StyleConfig for the scene's job style.
- [ ] **Step 4: Run -> pass.**
- [ ] **Step 5: Commit** `feat(video): per-scene labeled subgraph (base/mot/grad/cap/v)`.

### Task 1.8: Color grade per style

**Files:** Modify `video_render.py` (`_scene_filter_stmts`); Test `tests/test_video_render.py`

- [ ] **Step 1: Failing test**: cinematic emits the `eq=...,curves=...,vignette=...,noise=...` chain into `[grad{i}]`; clean_product_demo emits a pass-through (grade == "" -> `[mot{i}]` aliased to `[grad{i}]` with `null`/`copy` or direct relabel).
- [ ] **Step 2-4:** implement grade insertion from `StyleConfig.grade`; pass-through when empty; tests pass.
- [ ] **Step 5: Commit** `feat(video): per-style color grade`.

### Task 1.9: Animated + designed captions

**Files:** Modify `video_render.py` (`render_caption_png` + caption-fade in `_scene_filter_stmts`); Test `tests/test_video_render.py`, `tests/test_video_cards.py`

- [ ] **Step 1: Failing tests**: (a) the caption input gets `fade=t=in...alpha=1,fade=t=out...alpha=1` with fade durations scaled to the scene (`fin=fout=min(0.3, dur/3)`) so a 0.5s scene does not overlap; (b) `render_caption_png` honors the StyleConfig caption design (band shape glass/rounded/flat, drop shadow, title-safe margins) and produces a valid RGBA PNG of the target size.
- [ ] **Step 2-4:** implement the caption alpha-fade (scaled) + upgrade `render_caption_png(text, size, style.caption)` (rounded/gradient/glass band + shadow pass); render a PNG in the test and assert mode/size + non-empty alpha.
- [ ] **Step 5: Commit** `feat(video): animated, designed captions per style`.

### Task 1.10: Intro + outro cards (single invocation)

**Files:** Create `video_cards.py`; Modify `video_render.py` (`build_filtergraph`/`build_render_script`); Test `tests/test_video_cards.py`, `tests/test_video_render.py`

- [ ] **Step 1: Failing tests**: (a) `video_cards.render_title_card_png(title, size, style.cards)` and `render_outro_card_png(cta, size, style.cards)` produce valid PNGs with the title/CTA text drawn (Pillow, injection-safe — text with `:'"\\` does not break); (b) `build_render_script` adds lavfi color inputs for intro+outro and xfade-stitches them as the first/last segments of the chain (assert the chain references the intro/outro labels), and the total adds ~intro+outro seconds.
- [ ] **Step 2-4:** implement Pillow card renderers + lavfi color inputs (`-f lavfi -i color=...`) overlaid with the card PNG, xfade-stitched onto the body in one invocation; title from `plan.title`, CTA = the site URL.
- [ ] **Step 5: Commit** `feat(video): intro title card + outro CTA card`.

### Task 1.11: Delivery-grade encode tail

**Files:** Modify `video_render.py:401-412`; Test `tests/test_video_render.py`

- [ ] **Step 1: Failing test**: `build_render_script` argv tail contains `-crf 21`, `-preset veryfast`, `-pix_fmt yuv420p`, `-threads 2`, `-movflags +faststart`, `-c:a aac`, `-b:a 192k`, `-r 30`. (Phase 1 still maps the single voice; the music `-map [aout]` lands in Phase 2.)
- [ ] **Step 2-4:** implement; tests pass.
- [ ] **Step 5: Commit** `feat(video): delivery-grade encode (crf/faststart/threads/aac)`.

### Task 1.12: Wire job `style` into the render + create form (Style dropdown)

**Files:** Modify `video_render.py` (`build_render_script`/`render_all_captions` to key off the passed style id), `video_worker.py` (pass `job.style`), `routes_video.py` (upload `style` field + allowlist), `static/video.html` (Style dropdown); Test `tests/test_routes_video_*`, `tests/test_video_render.py`

- [ ] **Step 1: Failing tests**: `build_render_script(plan, workdir, style="cinematic")` selects the cinematic StyleConfig (visual config independent of `template_id`); upload rejects an unknown `style` with 400; offline form test that the Style `<select>` exists with the 3 options.
- [ ] **Step 2-4:** thread `style` from the job -> worker -> `build_render_script`/`render_all_captions` (replace the `get_style(plan["template_id"])` styling call with `get_style_config(style)`); add `style` Form field (allowlist) on upload; add the Style dropdown to `video.html` (default clean_product_demo) and send it in the FormData.
- [ ] **Step 5: Commit** `feat(video): user-selected style drives the render + Style dropdown`.

### Task 1.13: Phase 1 deploy + benchmark (runbook, not TDD)

- [ ] Run the full offline render/plan/style/cards test suite green: `cd mcp-servers/tasks && python -m pytest tests/test_video_render.py tests/test_video_plan.py tests/test_style_config.py tests/test_video_cards.py -v`.
- [ ] Deploy changed files (`video_render.py`, `video_plan.py`, `video_models.py`, `routes_video.py`, `video_worker.py`, `templates_video/*`, `video_cards.py`, `migrations/024`, `static/video.html`, `assets/logo.png` + font) via `docker cp` + `docker restart tasks`; confirm `DB initialized` + healthz 200; drift-check first (per the established pattern).
- [ ] **Benchmark on prod:** render one video per style at 720p AND 1080p, worst-case ~12 scenes, watch `free -h`/`df -h`, confirm under the 600s budget with no container restart. If 1080p is tight, keep 720p as default and flag.
- [ ] Have Ralph eyeball one render per style; iterate on look.

---

# PHASE 2 — THE SOUND

### Task 2.1: Per-scene voice synthesis + durations (host)

**Files:** Modify `video_executor.py` (`_voice` -> per-scene); Test `tests/test_video_executor.py`

- [ ] **Step 1: Failing test** (offline, mock subprocess/ffprobe): given a plan with per-scene `narration`, `_voice` builds one Piper call per scene to the chosen voice model (resolved via an allowlist dict, never user path), then ffprobes each clip; returns a list of per-scene spoken lengths + concatenates the clips to `voice.wav`. Unknown voice id -> falls back to default.
- [ ] **Step 2-4:** implement per-scene synth + ffprobe + concat; voice allowlist `{id: model_path}`.
- [ ] **Step 5: Commit** `feat(video): per-scene voice synthesis + measured durations`.

### Task 2.2: Controller marshalling — durations follow audio + cap/atempo

**Files:** Modify `video_executor.py` (`render`) + `video_render.py` (consume durations); Test `tests/test_video_executor.py`

- [ ] **Step 1: Failing tests**: after voice synth, each `scene.duration_s = max(MIN_SCENE_SECONDS, spoken_len + 0.4)`, re-clamped; if total spoken > 60s a global `atempo` factor (<=1.2) is applied; the filtergraph `-t` and caption `st` timings match the updated durations. (Mock the per-scene lengths.)
- [ ] **Step 2-4:** reorder `render` to voice-first; update plan durations from measured lengths; compute atempo; rebuild script.
- [ ] **Step 5: Commit** `feat(video): scene durations follow the spoken audio (no mid-sentence cuts)`.

### Task 2.3: Loudnorm voice pre-pass

**Files:** Modify `video_executor.py`; Test `tests/test_video_executor.py`

- [ ] **Step 1-4:** two-pass `loudnorm=I=-16:TP=-1.5:LRA=11` (measure -> apply) + `highpass=f=90,acompressor,...` clarity chain producing `voice_normalized.wav`; unit-test the constructed filter strings + the measured-JSON parse (mock).
- [ ] **Step 5: Commit** `feat(video): two-pass loudnorm + clarity on the voice`.

### Task 2.4: Per-style ducked music

**Files:** Create `assets/music/*` + `LICENSE`; Modify `video_render.py` (audio chain + `-stream_loop -1 -i bed`, `-map [aout]`), `video_executor.py`; Test `tests/test_video_render.py`

- [ ] **Step 1: Failing test**: when a style has music, the filtergraph emits the `asplit`/`volume`/`afade`/`sidechaincompress`/`amix=...:normalize=0[aout]` chain and the encode maps `[aout]`; with music disabled it maps the voice directly.
- [ ] **Step 2-4:** implement the ducked-music chain (level from StyleConfig); add the music input + `-map [aout]`; bundle 3 CC0 tracks + LICENSE; gate behind a flag.
- [ ] **Step 5: Commit** `feat(video): per-style ducked music bed`.

### Task 2.5: Voice dropdown + host voice install

**Files:** Modify `routes_video.py` (voice allowlist), `static/video.html` (Voice dropdown), `video_worker.py` (pass voice); host provision script for multi-voice Piper; Test `tests/test_routes_video_*`

- [ ] **Step 1-4:** add the Voice `<select>` (the allowlisted voices), validate on upload (400 unknown), thread `job.voice` to the executor; add the Piper voice downloads to the agent-VM provision script; document the install.
- [ ] **Step 5: Commit** `feat(video): user-selected voice + multi-voice install`.

### Task 2.6: Phase 2 deploy + benchmark (runbook)

- [ ] Full suite green; install the extra Piper voices + music assets on the host.
- [ ] Deploy (`docker cp` + restart); benchmark one render per style+voice with music, confirm audio sync + under budget + `loudnorm` levels sane.
- [ ] Ralph reviews audio; iterate.

---

## Definition of done
- Three user-selectable styles render with their distinct transitions/motion/captions/grade/cards; user-selectable voice; per-scene synced narration (no cuts); per-style ducked music; delivery-grade encode.
- All offline builder/schema/style/card tests pass; prod benchmark per style+voice under the 600s budget at 720p (1080p if it fits), no container restarts.
- `style`/`voice` user-owned (migration 024), allowlist-validated; all user text rendered via Pillow (no `drawtext` injection surface); music is CC0.
- No regression to the existing create/refine/upload flow.
