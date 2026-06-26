# AI-authored Remotion videos — Stage 1 (contained proof)

**Date:** 2026-06-26
**Status:** Approved (brainstorm) → spec
**Parent goal:** Replace the single fixed Remotion template with AI-authored Remotion compositions per video, built in stages, with the template kept as a guaranteed fallback.

## Stage 1 goal (this spec)
Prove the riskiest unknown: **a Claude model, grounded in Remotion's own rules, can generate a real Remotion composition that passes a determinism check, compiles, and renders to a clean MP4** — with an automatic validate→repair loop. Nothing user-facing; the live template is untouched.

## Decisions (from brainstorm)
- **Staged**, template stays as fallback; build/prove one stage at a time.
- **Input = a text brief only** (e.g. "a 15s launch intro for a coffee app"). No screenshots in Stage 1 (that's Stage 1.5).
- **Approach A — full freedom + validate/repair**: the AI writes a complete single-file composition; we catch problems by checking the output, not by constraining it.
- **Heavy sandbox deferred to Stage 2.** Stage 1 input is the author's (trusted), so security hardening is not required to prove the concept.

## Pipeline
```
brief
  │
  ▼ GENERATE  — Claude (Opus) with Remotion's OFFICIAL AI system prompt
  │            (https://www.remotion.dev/docs/ai/system-prompt + llms.txt) plus
  │            project constraints → ONE self-contained composition file (TSX)
  ▼ VALIDATE
  │   1. determinism lint  (reject the forbidden set below)
  │   2. compile check     (esbuild/tsc — must build clean)
  ▼ REPAIR LOOP — on failure, send the exact lint/compile errors back to Claude
  │              and regenerate; max 3 attempts
  ▼ RENDER     — bundle + render via the existing video-remotion engine → out.mp4
  ▼ REPORT     — brief, generated code, per-gate pass/fail, attempts, render time, MP4
```

## Components (each independently testable)
1. **`generate(brief, feedback?) → tsx`** — one Anthropic call. System prompt = Remotion's AI system prompt + constraints: single file; export `RemotionRoot` registering exactly one `<Composition id="Video" fps={30} width={1280} height={720} durationInFrames=…>`; import ONLY from `remotion` / `@remotion/*` / `react`; all animation from `useCurrentFrame()`; no assets (Stage 1 is pure motion-graphics). `feedback` carries prior errors for the repair loop.
2. **`lintComposition(tsx) → string[]`** — pure, unit-testable. Flags: `Math.random`, `Date.now`, `new Date(`, `performance.now`, `setTimeout`, `setInterval`, `requestAnimationFrame`, `fetch(`, `XMLHttpRequest`, `useState`, `useEffect`, `useRef`-driven animation, CSS `transition:`/`animation:`/`@keyframes`/`animate-` classes, and any `import`/`require` from a module not in the allow-list (`remotion`, `@remotion/*`, `react`, `react/jsx-runtime`).
3. **`compileCheck(tsx) → {ok, errors}`** — esbuild transform/bundle (already a video-remotion dep) over the file; returns compile errors.
4. **`render(tsx) → mp4Path`** — drop the file into a throwaway copy of the video-remotion project (or a temp entry), `bundle()` + `renderMedia()` with the existing config (jpeg/h264, concurrency cap). Reuses the proven render path.
5. **`runProof(brief) → report`** — orchestrates generate → validate → repair(≤3) → render; returns the report.

## Where it runs / how the proof executes
A self-contained script (not wired to the job pipeline). `generate` needs `ANTHROPIC_API_KEY` and `render` needs the Remotion render env (Chromium + `@remotion/renderer`), both of which live on the server's `video-remotion` container — so the proof runs there (or locally if local rendering is reliable). The lint + compile gates are pure and run anywhere.

## Success criteria
- For ≥2 distinct briefs, the loop yields a composition that passes lint + compile and renders to a clean MP4 (`ffprobe` shows a valid h264 stream; no render errors; visually watchable — not blank/flickering).
- The repair loop demonstrably fixes at least one injected/observed violation (evidence the validate→repair design works).
- Deliverable: the MP4(s) + the generated code + the report, shown to the user.

## Out of scope (Stage 1)
- Screenshots/assets (Stage 1.5), user wiring (web/Discord), production deploy, hardened sandbox (Stage 2), making it the default (Stage 4).
- The current fixed template and the live generator are untouched.

## Review fixes (incorporated)
- **API key location (HIGH):** `ANTHROPIC_API_KEY` is on the `tasks` service, NOT `video-remotion`. Add `ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}` to the `video-remotion` compose env (references existing `.env`; never edits `.env`), and run the whole proof as a one-off node script there. Generation = a single `fetch()` POST to `api.anthropic.com/v1/messages` (no SDK). Verify `video-remotion` has runtime outbound internet first.
- **Render failures feed the repair loop (HIGH):** lint+compile miss runtime errors (NaN ranges, null derefs) — the dominant AI-codegen failure. The repair loop covers lint **+ compile + render**: do a `renderStill` (frames 0 and 45) before full `renderMedia`; on throw, feed the error back and regenerate (max 3).
- **Compile gate = the real `bundle()`** from `@remotion/bundler` (truthful: catches unresolved imports/missing exports). Drop the esbuild transform (too weak) and do NOT use `tsc` (Remotion's bundler doesn't type-check, so type errors still render — gating on tsc would false-reject). Add `esbuild`/`typescript` as explicit `video-remotion` devDeps if relied on.
- **Render integration:** do NOT reuse `renderJob()` (it caches a fixed `./index.ts` entry + hardcodes `id`/scene inputProps). The generated file is a COMPLETE entry: one `<Composition id="Video" fps={30} width={1280} height={720} durationInFrames={<literal>}/>`, no `calculateMetadata`/required props, and it **calls `registerRoot()` itself**. Write it to a gitignored `video-remotion/src/__ai_tmp__/comp.tsx`, then `bundle({entryPoint})` → `selectComposition({id:"Video", inputProps:{}})` → `renderMedia(...)` with explicit config constants (`renderConcurrency()`, `codec:"h264"`, `imageFormat:"jpeg"`, `pixelFormat:"yuv420p"`). Reuses the render **libraries + config**, not `renderJob()`.
- **Determinism is PROVEN, not claimed:** require duration ≥90 frames and motion; render frame 45 **twice** via `renderStill` and assert byte-identical PNGs. (Regex lint is a heuristic, not a determinism guarantee.)
- **Lint corrections:** add camelCase CSS (`animationName`/`animationDuration`/`animationTimingFunction`/`transitionProperty`/`transitionDuration`), `crypto.getRandomValues`/`randomUUID`, bare `Date(` ; use `\bfetch\s*\(`; DROP the `useRef` rule (false positive). Allow-list stays `remotion`/`@remotion/*`/`react`.
- **Prompt:** VENDOR a focused single-file system prompt in-repo (don't live-fetch Remotion's official one — it assumes a multi-file scaffold and is a network dep). Include a one-shot few-shot of the exact single-file shape; extract exactly one fenced code block from the model output and reject multi-file responses.
- **Isolation:** `video-remotion` has no memory limit and the box is 3.8GB — run the proof as a one-off when no live render is in flight; clean up `src/__ai_tmp__/`.

## Testing
- `lintComposition` + `compileCheck`: unit tests (TDD) — known-bad snippets flagged, known-good passes.
- `runProof`: integration — a stubbed generator returning a known-good composition renders; a stubbed generator returning a bad-then-good sequence exercises the repair loop.
- Live: real generation on ≥2 briefs producing rendered MP4s.
