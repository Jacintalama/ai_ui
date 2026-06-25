# Remotion Render Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a new `video-remotion` container that renders a job's plan to an mp4 with visual parity to the current animated renderer, wired into the tasks worker as `render_mode: "remotion"` (opt-in).

**Architecture:** A new Node/Remotion (React) project + Fastify `POST /render` service in its own container, sharing the repo bind-mount so it reads screenshots and writes a video-only mp4 into the job dir. The Python `tasks` worker gains a `remotion` branch: it runs the existing brain, synthesizes Piper narration, calls the render service, then muxes audio (narration + ducked ambient bed) onto the Remotion video with `-c:v copy`. `animated`/`slideshow` modes are untouched.

**Tech Stack:** Remotion 4.x (React 19 + TypeScript), `@remotion/renderer` + `@remotion/bundler`, Fastify; Python 3.11 / FastAPI / httpx / pytest; ffmpeg; Docker Compose.

**Spec:** `docs/superpowers/specs/2026-06-25-remotion-foundation-design.md`

**Branch:** `feat/remotion-foundation` (already created; spec committed).

**Reference (current look to reproduce):** `mcp-servers/tasks/video_anim.py` `build_composition` (dark gradient + glow + vignette, browser-chrome frame with capped height + address pill, eyebrow hidden on screenshot scenes, kinetic per-word headline, Ken Burns, smootherstep, fade-through).

**Env notes for implementers:**
- A memory hook truncates the `Read` tool to line 1 on `mcp-servers/tasks/*` files; use `Grep` with `-A/-C` to read them. `Edit` may fail "modified since read" on those files; if so, apply the change via a small Python script in a Bash call (`open().read()` -> `str.replace` with a `count==1` assert -> `open("w").write`). New files (the whole `video-remotion/` tree, new test files) are unaffected.
- Python tests run from `cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks"` with `python -m pytest tests/<file> -v`. `asyncio_mode = auto` (no `@pytest.mark.asyncio`). DB-gated tests skip offline (`_HAVE_DB`).
- Node/Remotion work runs from `cd "C:/All/Work - Code/ai_ui/video-remotion"`.
- No AI/Claude attribution in commits. No em-dashes anywhere.

---

## File structure

New (`video-remotion/`, Node):
- `package.json`, `tsconfig.json`, `remotion.config.ts`, `.dockerignore`, `.gitignore`
- `src/index.ts` - `registerRoot(Root)`
- `src/Root.tsx` - registers the `Video` composition + its schema
- `src/Video.tsx` - the composition: maps scenes -> `<Series>` of scene components
- `src/theme-parity.tsx` - the parity scene component (frame, headline, etc.) + easing helpers
- `src/render.ts` - pure helper that builds `renderMedia` params from a request (testable)
- `src/server.ts` - Fastify service (`POST /render`, `GET /healthz`, mutex)
- `src/render.test.ts`, `src/server.test.ts` - tests (vitest)
- `Dockerfile`

New (Python, `mcp-servers/tasks/`):
- `video_remotion_client.py` - httpx client to the render service
- `video_remotion_render.py` - `render_remotion_job(...)` orchestrator
- `tests/test_video_remotion_client.py`, `tests/test_video_remotion_render.py`

Modified:
- `mcp-servers/tasks/video_anim.py` - add `_build_audio_mux_args` (video-in mux helper)
- `mcp-servers/tasks/routes_video.py` - widen 3 `render_mode` regex validators
- `mcp-servers/tasks/video_worker.py` - plan selection + render dispatch for `remotion`
- `docker-compose.unified.yml` - add `video-remotion` service
- tests: `tests/test_video_anim.py`, `tests/test_routes_video_draft.py`, `tests/test_video_worker.py`

Build order: Part A (Node engine) -> Part B (Python integration) -> Part C (deploy). Each Python task is independently testable; the Node engine is verified by its own tests + a real render at deploy.

---

## Part A: Remotion engine (`video-remotion/`)

### Task 1: Scaffold the Remotion project + render smoke

**Files:** create `video-remotion/package.json`, `tsconfig.json`, `remotion.config.ts`, `.gitignore`, `.dockerignore`, `src/index.ts`, `src/Root.tsx`, `src/Video.tsx` (minimal), `src/render.ts`, `src/render.test.ts`.

- [ ] **Step 1: Create `package.json`** with Remotion 4.x + React 19 + vitest:

```json
{
  "name": "video-remotion",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "test": "vitest run",
    "render": "remotion render Video out/video.mp4",
    "server": "tsx src/server.ts"
  },
  "dependencies": {
    "@remotion/bundler": "4.0.*",
    "@remotion/renderer": "4.0.*",
    "fastify": "^5",
    "react": "19.0.0",
    "react-dom": "19.0.0",
    "remotion": "4.0.*"
  },
  "devDependencies": {
    "@remotion/cli": "4.0.*",
    "tsx": "^4",
    "typescript": "^5",
    "vitest": "^2"
  }
}
```

- [ ] **Step 2: Create `tsconfig.json`** (standard Remotion/React JSX):

```json
{
  "compilerOptions": {
    "target": "ES2022", "module": "ESNext", "moduleResolution": "Bundler",
    "jsx": "react-jsx", "strict": true, "esModuleInterop": true,
    "skipLibCheck": true, "noEmit": true, "lib": ["DOM", "ES2022"]
  },
  "include": ["src"]
}
```

- [ ] **Step 3: `remotion.config.ts`** - set the output codec/pixel format so the later `-c:v copy` mux is safe:

```ts
import { Config } from "@remotion/cli/config";
Config.setVideoImageFormat("jpeg");
Config.setCodec("h264");
Config.setPixelFormat("yuv420p");
```

- [ ] **Step 4: `src/Root.tsx` + `src/index.ts` + minimal `src/Video.tsx`** - one composition `Video`, 1280x720, fps 30, defaulting to a 1-second solid background so a render smoke works before the theme exists:

```tsx
// src/Video.tsx (minimal placeholder; Task 2 replaces the body)
import {AbsoluteFill} from "remotion";
export type Scene = { kind: string; screenshot?: string; headline?: string;
  subtext?: string; motion?: string; durInFrames: number };
export type VideoProps = { theme: string; host: string; title: string; scenes: Scene[] };
export const Video: React.FC<VideoProps> = () => (
  <AbsoluteFill style={{backgroundColor: "#0b0b10"}} />
);
```
```tsx
// src/Root.tsx
import {Composition} from "remotion";
import {Video} from "./Video";
// BLOCKING-FIX (review): the composition MUST derive its real duration/fps/size
// from inputProps via calculateMetadata, else selectComposition() returns the
// static defaults and renderMedia produces a 1-second clip regardless of scenes.
const calc = ({props}: {props: any}) => {
  const fps = props.fps || 24;
  const total = (props.scenes || []).reduce(
    (a: number, s: any) => a + Math.max(1, s.durInFrames || 0), 0);
  return { durationInFrames: Math.max(1, total), fps,
           width: props.width || 1280, height: props.height || 720 };
};
export const Root: React.FC = () => (
  <Composition id="Video" component={Video} durationInFrames={1} fps={24}
    width={1280} height={720} calculateMetadata={calc}
    defaultProps={{theme: "parity", host: "", title: "", fps: 24,
      width: 1280, height: 720, scenes: []}} />
);
```
Note: `VideoProps`/`inputProps` now also carry `fps`, `width`, `height` (so
`calculateMetadata` can read them); add those fields to the `Video.tsx` prop type
and include them in `buildRenderConfig`'s `inputProps`.
```ts
// src/index.ts
import {registerRoot} from "remotion";
import {Root} from "./Root";
registerRoot(Root);
```

- [ ] **Step 5: `src/render.ts`** - a PURE helper that, given a render request, returns the props + total `durationInFrames` (so total duration is testable and clamped). This is the unit under test:

```ts
export const MAX_DURATION_S = 40;
export type RenderRequest = { jobDir: string; theme: string; fps: number;
  width: number; height: number; host: string; title: string; outFile?: string;
  scenes: { kind: string; screenshot?: string; headline?: string;
    subtext?: string; motion?: string; durationS: number }[] };

export function buildRenderConfig(req: RenderRequest) {
  const fps = req.fps || 24;  // match the animated path's fps for parity
  // clamp total duration; convert per-scene seconds -> frames (min 1 frame)
  let totalS = 0;
  const scenes = req.scenes.map((s) => {
    const remaining = Math.max(0, MAX_DURATION_S - totalS);
    const durS = Math.min(Math.max(0.5, s.durationS || 3), remaining || 0.0001);
    totalS += durS;
    return { ...s, durInFrames: Math.max(1, Math.round(durS * fps)) };
  }).filter((s) => s.durInFrames > 0);
  const durationInFrames = Math.max(1, scenes.reduce((a, s) => a + s.durInFrames, 0));
  const width = req.width || 1280, height = req.height || 720;
  // DATA-URI TRANSPORT (decided post Task 2): pass the screenshot ABS PATH through
  // unchanged (no file:// prefix). The render service converts the path to a
  // data: URI before rendering, because Chromium refuses file:// from the bundle.
  const screenshotUrl = (p?: string) => (p ? p : undefined);
  // inputProps carries fps/width/height so the composition's calculateMetadata
  // can derive the real duration (see Root.tsx).
  const inputProps = { theme: req.theme, host: req.host, title: req.title,
    fps, width, height,
    scenes: scenes.map((s) => ({ kind: s.kind, screenshot: screenshotUrl(s.screenshot),
      headline: s.headline ?? "", subtext: s.subtext ?? "", motion: s.motion ?? "fade",
      durInFrames: s.durInFrames })) };
  return { fps, width, height, durationInFrames, inputProps,
    outFile: req.outFile || (req.jobDir + "/remotion-video.mp4") };
}
```

- [ ] **Step 6: `src/render.test.ts`** (vitest) - assert clamping + file:// + frame math:

```ts
import {describe, it, expect} from "vitest";
import {buildRenderConfig} from "./render";
describe("buildRenderConfig", () => {
  it("converts seconds to frames and builds file:// urls", () => {
    const c = buildRenderConfig({jobDir: "/j", theme: "parity", fps: 30,
      width: 1280, height: 720, host: "x.com", title: "X",
      scenes: [{kind: "screenshot", screenshot: "/j/s/screenshot-1.png",
        headline: "Hi", motion: "zoom-in", durationS: 3}]});
    expect(c.inputProps.scenes[0].durInFrames).toBe(90);
    expect(c.inputProps.scenes[0].screenshot).toBe("/j/s/screenshot-1.png"); // abs path, service converts to data URI
    expect(c.durationInFrames).toBe(90);
  });
  it("clamps total duration to MAX_DURATION_S", () => {
    const scenes = Array.from({length: 30}, () => ({kind: "screenshot", durationS: 5}));
    const c = buildRenderConfig({jobDir: "/j", theme: "parity", fps: 30,
      width: 1280, height: 720, host: "", title: "", scenes});
    expect(c.durationInFrames).toBeLessThanOrEqual(40 * 30);
  });
});
```

- [ ] **Step 7: install + run tests + a CLI render smoke**

Run: `cd video-remotion && npm install`
Run: `npm test` -> expect the 2 buildRenderConfig tests PASS.
Run: `npx remotion render Video out/smoke.mp4 --props='{"theme":"parity","host":"","title":"","scenes":[{"kind":"title","headline":"Hi","durInFrames":30}]}'`
Expected: produces `out/smoke.mp4` (proves Remotion + headless Chromium + ffmpeg work). If Chromium is missing locally, run `npx remotion browser ensure` first. (If the local box can't render, this is re-verified in the container at deploy.)

- [ ] **Step 8: Commit**

```bash
git add video-remotion/
git commit -m "feat(remotion): scaffold video-remotion project + render config helper"
```

### Task 2: Parity theme composition

**Files:** rewrite `video-remotion/src/Video.tsx`; create `video-remotion/src/theme-parity.tsx`.

Reproduce `build_composition`'s look in React/Remotion. Use `<Series>` with one `<Series.Sequence durationInFrames={scene.durInFrames}>` per scene; inside, a `SceneParity` component drives all visuals from `useCurrentFrame()` (0..durInFrames) so it is frame-deterministic. Use `interpolate()` + the easing below (NO spring, NO CSS transitions - matches Remotion best practices and our determinism rule).

- [ ] **Step 1: `src/theme-parity.tsx`** - implement `SceneParity({scene, host, title})`:
  - Background: an `AbsoluteFill` with the dark radial gradient + a blurred glow `div` + a vignette `div` (port the CSS values from `video_anim.py:117-125`).
  - Screenshot scenes (`scene.screenshot` set): a `.frame` (`<Img src={scene.screenshot}>`) with a top bar (3 dots + an address pill showing `host`), rounded corners, big shadow, `max-height` capped (port `video_anim.py:127-141` incl. the shipped `max-height:58%` + `top:5.5%` + `width:64%` tuning), `overflow:hidden`. Apply always-on Ken Burns (scale 1.0->1.06 + drift) layered on the scene motion (zoom-in/out, pan-up, pan-left) via transforms driven by frame progress `p`.
  - Eyebrow (uppercase `title`) only on NON-screenshot scenes (matches the shipped tuning that hides it on screenshot scenes).
  - Headline: kinetic per-word reveal - split `scene.headline` into words, each word's opacity + translateY offset by word index and `p` (port the per-word logic from `video_anim.py:210-217`). Subtext below when present.
  - Fade-through envelope: opacity ramps in over the first ~18% and out over the last ~18% of the scene (port `env` from `video_anim.py:194`).
  - Easing helpers: `smoothstep` and `smootherstep` (`p*p*p*(p*(6p-15)+10)`).
  - All text via React children/props (Remotion renders to canvas via DOM; no injection concern, but keep text as props).

- [ ] **Step 2: `src/Video.tsx`** - map `scenes` to a `<Series>`:

```tsx
import {AbsoluteFill, Series} from "remotion";
import {SceneParity} from "./theme-parity";
import type {VideoProps} from "./types"; // or inline the type
export const Video: React.FC<VideoProps> = ({host, title, scenes}) => (
  <AbsoluteFill style={{backgroundColor: "#0b0b10"}}>
    <Series>
      {scenes.map((s, i) => (
        <Series.Sequence key={i} durationInFrames={s.durInFrames}>
          <SceneParity scene={s} host={host} title={title} />
        </Series.Sequence>
      ))}
    </Series>
  </AbsoluteFill>
);
```

- [ ] **Step 3: Add the Inter font** - install Inter for the canvas. Use `@remotion/google-fonts/Inter` (add to deps) and load it in the composition, OR rely on the container's system Inter (Task 9 Dockerfile installs fonts-inter) and set `font-family: Inter`. Prefer `@remotion/google-fonts` so it is deterministic and not container-dependent; if added, include it in `package.json`.

- [ ] **Step 4: Structural test** `src/theme-parity.test.ts` - render `SceneParity` to static markup via `@remotion/renderer`'s React or a light react-dom/server render and assert the address-pill host text and an eyebrow render for the right scene kinds. (If server-rendering Remotion components is awkward, instead assert via a CLI single-frame render in Step 5 and keep this test minimal - e.g. import the module and assert it exports `SceneParity`.)

- [ ] **Step 5: Single-frame visual check**

Run: `npx remotion still Video out/frame.png --frame=45 --props='{"theme":"parity","host":"example.com","title":"Example","scenes":[{"kind":"screenshot","screenshot":"file:///<an existing screenshot abs path>","headline":"A clean dashboard","subtext":"Everything in one place","motion":"zoom-in","durInFrames":90}]}'`
View `out/frame.png`; confirm frame + capped height + address pill + kinetic headline read like the current renderer. Iterate the CSS values. (Re-verified on the box at deploy.)

- [ ] **Step 6: Commit**

```bash
git add video-remotion/
git commit -m "feat(remotion): parity theme (browser frame, kinetic type, depth, Ken Burns)"
```

### Task 3: Render service (`src/server.ts`)

**Files:** create `video-remotion/src/server.ts`, `video-remotion/src/server.test.ts`.

- [ ] **Step 1: Write `server.test.ts`** (vitest) - validation only (no real render): POST `/render` with an empty `scenes` array -> 400; missing `jobDir` -> 400. Mock the renderer module so no Chromium is needed. (Test the route's validation + that it calls the renderer with `buildRenderConfig` output.)

- [ ] **Step 2: Implement `server.ts`** with Fastify:
  - `GET /healthz` -> `{status:"ok"}`.
  - `POST /render` -> validate body (`jobDir` non-empty string; `scenes` non-empty array), build config via `buildRenderConfig`, acquire a module-level async mutex (a simple promise chain) so only ONE render runs at a time, then:
    - `bundle()` the project once (cache the bundle URL across requests), `selectComposition({serveUrl, id:"Video", inputProps})` (this RUNS `calculateMetadata`, so `composition.durationInFrames` is the real total), `renderMedia({composition, serveUrl, codec:"h264", outputLocation: outFile, inputProps, ...})`.
    - return `{ok:true, outPath: outFile, frames: composition.durationInFrames}`.
  - SCREENSHOT TRANSPORT = DATA URIs (decided after Task 2): headless Chromium
    refuses `file://` images from the http-served Remotion bundle
    (`ERR_UNKNOWN_URL_SCHEME`), but data URIs render fine (this is exactly what the
    current HTML engine does). So: the HTTP payload still carries small ABS PATHS,
    and THIS SERVICE converts each scene's screenshot path to a `data:image/png;base64,...`
    URI (read the file from the shared volume mount, base64-encode) BEFORE rendering,
    rewriting `inputProps.scenes[i].screenshot` to the data URI. Keep `buildRenderConfig`
    PURE (it just passes the abs path through, no `file://`); the data-URI conversion
    is the service's one impure I/O step (a small `toDataUri(absPath)` helper). The
    payload stays tiny (paths, not megabytes of base64) and there is no scheme issue.
  - BLOCKING-FIX (review) - the `renderMedia` call MUST pin format so the later
    `-c:v copy` mux is safe:
    ```ts
    await renderMedia({
      composition, serveUrl, codec: "h264", outputLocation: outFile, inputProps,
      pixelFormat: "yuv420p", imageFormat: "jpeg",
    });
    ```
    `remotion.config.ts` (Task 1) only affects the CLI, NOT programmatic `renderMedia`, so these must be passed here explicitly.
  - On validation error -> 400; on render error -> 500 with `{ok:false, error: <message tail>}` and log the full error.
  - Listen on `0.0.0.0:${PORT||8090}`.

- [ ] **Step 3: Run tests**

Run: `cd video-remotion && npm test` -> all pass (render mocked).

- [ ] **Step 4: GATE - prove the screenshot actually appears (do not skip).**
  Run a REAL render through the service with a scene whose `screenshot` is an abs
  path to a real PNG and confirm the screenshot is VISIBLE inside the frame (not
  blank). The service converts the path to a data URI (per Step 2), which Chromium
  renders reliably (Task 2 already verified data URIs work locally; `file://` does
  not). If local Chromium works, `npm run server` + POST; otherwise do this in the
  container at deploy (Task 10) - but since data URIs are already proven, this is
  low risk now rather than the former lynchpin.

- [ ] **Step 5: Commit**

```bash
git add video-remotion/
git commit -m "feat(remotion): fastify render service with mutex + validation"
```

---

## Part B: tasks integration (Python)

### Task 4: Allow `render_mode="remotion"` in the API

**Files:** modify `mcp-servers/tasks/routes_video.py` (three `pattern="^(slideshow|animated)$"` validators, around lines 184, 214, 940); test in `tests/test_routes_video_draft.py`.

- [ ] **Step 1: Write the failing test** - add to `tests/test_routes_video_draft.py` (mirror its existing draft tests; this one is offline-safe if draft creation 201s without DB, else DB-gate it like siblings). Assert `POST /api/video-jobs/draft` with `{"render_mode":"remotion"}` does NOT 422 (FastAPI validation error). If draft creation needs DB, instead unit-test that the Pydantic model accepts the value:

```python
def test_draft_request_accepts_remotion_render_mode():
    from routes_video import DraftRequest  # or the actual model name
    m = DraftRequest(render_mode="remotion")
    assert m.render_mode == "remotion"
```
(Grep routes_video.py for the model class names holding the `render_mode` Field; use the real names.)

- [ ] **Step 2: Run it -> FAIL** (regex rejects "remotion").
Run: `python -m pytest tests/test_routes_video_draft.py -k remotion -v`

- [ ] **Step 3: Widen the three regexes** from `^(slideshow|animated)$` to `^(slideshow|animated|remotion)$` (all 3 occurrences: DraftRequest field, the multipart `Form(...)` param, and the draft-set update model). Use Grep to find exact occurrences; apply via Python script if Edit is blocked by the hook.

- [ ] **Step 4: Run -> PASS**; also run the full draft suite for no regressions.
Run: `python -m pytest tests/test_routes_video_draft.py -v`

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_video.py mcp-servers/tasks/tests/test_routes_video_draft.py
git commit -m "feat(video): accept render_mode=remotion in the draft API"
```

### Task 5: Audio-mux helper for a video input

**Files:** modify `mcp-servers/tasks/video_anim.py` (add `_build_audio_mux_args` near `_build_ffmpeg_args`); test in `tests/test_video_anim.py`.

Mirror `_build_ffmpeg_args` (Grep it, ~lines 245-275) but input 0 is an existing VIDEO file, video is `-c:v copy`, audio is the same lavfi ambient bed + ducked narration mix.

- [ ] **Step 1: Write the failing tests** in `tests/test_video_anim.py`:

```python
def test_audio_mux_args_with_narration():
    from video_anim import _build_audio_mux_args
    args = _build_audio_mux_args("in.mp4", "out.mp4", audio_path="narration.wav")
    j = " ".join(args)
    assert "in.mp4" in args
    assert "lavfi" in j and "amix" in j
    assert "-c:v" in args and "copy" in args
    assert "-map" in args and "[aout]" in j
    assert "-shortest" in args
    assert "+faststart" in j

def test_audio_mux_args_without_narration():
    from video_anim import _build_audio_mux_args
    args = _build_audio_mux_args("in.mp4", "out.mp4", audio_path=None)
    j = " ".join(args)
    assert "lavfi" in j and "[aout]" in j
    assert "copy" in args and "-shortest" in args
    assert "narration" not in j
```

- [ ] **Step 2: Run -> FAIL** (`_build_audio_mux_args` undefined).
Run: `python -m pytest tests/test_video_anim.py -k audio_mux -v`

- [ ] **Step 3: Implement `_build_audio_mux_args(video_in, out_path, *, audio_path)`** - input 0 = `video_in`; input 1 = `-f lavfi -i _AMBIENT_LAVFI`; input 2 = `audio_path` (if set). filter_complex: ducked bed + amix when narration, else bed alone -> `[aout]`. Then `-map 0:v -map [aout] -c:v copy -c:a aac -b:a 192k -shortest -movflags +faststart out_path`. Reuse `_AMBIENT_LAVFI` and `_BED_DUCK_VOLUME`.

- [ ] **Step 4: Run -> PASS**; run full anim suite.
Run: `python -m pytest tests/test_video_anim.py -v`

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/video_anim.py mcp-servers/tasks/tests/test_video_anim.py
git commit -m "feat(video): ffmpeg audio-mux helper for a pre-rendered video input"
```

### Task 6: Render-service client

**Files:** create `mcp-servers/tasks/video_remotion_client.py`, `tests/test_video_remotion_client.py`.

- [ ] **Step 1: Write the failing test** using httpx MockTransport (no network):

```python
import httpx, pytest
from video_remotion_client import render_remotion

async def test_render_remotion_posts_and_returns_path():
    captured = {}
    def handler(request):
        captured["url"] = str(request.url); captured["json"] = __import__("json").loads(request.content)
        return httpx.Response(200, json={"ok": True, "outPath": "/j/remotion-video.mp4", "frames": 90})
    transport = httpx.MockTransport(handler)
    out = await render_remotion("/j", theme="parity", fps=30, width=1280, height=720,
        host="x.com", title="X", scenes=[{"kind":"title","headline":"Hi","durationS":2}],
        base_url="http://video-remotion:8090", _transport=transport)
    assert out == "/j/remotion-video.mp4"
    assert captured["json"]["jobDir"] == "/j"

async def test_render_remotion_raises_on_error():
    transport = httpx.MockTransport(lambda r: httpx.Response(500, json={"ok": False, "error": "boom"}))
    with pytest.raises(RuntimeError):
        await render_remotion("/j", theme="parity", fps=30, width=1280, height=720,
            host="", title="", scenes=[{"kind":"title","durationS":2}],
            base_url="http://x", _transport=transport)
```

- [ ] **Step 2: Run -> FAIL.**
Run: `python -m pytest tests/test_video_remotion_client.py -v`

- [ ] **Step 3: Implement `render_remotion(...)`** - build the payload (`jobDir, theme, fps, width, height, host, title, scenes`), POST `base_url + "/render"` with an `httpx.AsyncClient` (allow a `_transport` injection for tests; `base_url` default from `os.environ.get("VIDEO_REMOTION_URL", "http://video-remotion:8090")`), a wall-clock `timeout` (e.g. 240s), parse `{ok, outPath}`; raise `RuntimeError` on non-200 or `ok != True`.

- [ ] **Step 4: Run -> PASS.**

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/video_remotion_client.py mcp-servers/tasks/tests/test_video_remotion_client.py
git commit -m "feat(video): httpx client for the remotion render service"
```

### Task 7: `render_remotion_job` orchestrator

**Files:** create `mcp-servers/tasks/video_remotion_render.py`, `tests/test_video_remotion_render.py`.

Mirror `render_animated_job` (Grep `video_anim.py:357+`) but delegate visuals to the service and mux audio locally.

- [ ] **Step 1: Write the failing test** - monkeypatch the client + narration synth + the ffmpeg subprocess so no Chromium/ffmpeg/Piper runs; assert it builds scenes from the plan, loads site_context host/title, calls the client, muxes audio, and returns the out path:

```python
import os, video_remotion_render as vrr

async def test_render_remotion_job_orchestrates(tmp_path, monkeypatch):
    slug, jid = "vid-x", "11111111-1111-1111-1111-111111111111"
    base = tmp_path / slug / ".video" / jid
    (base / "screenshots").mkdir(parents=True)
    (base / "screenshots" / "screenshot-1.png").write_bytes(b"x")
    (base / "site_context.json").write_text('{"host":"example.com","title":"Example"}')
    seen = {}
    async def fake_client(job_dir, **kw):
        seen.update(kw); seen["job_dir"] = job_dir
        open(os.path.join(job_dir, "remotion-video.mp4"), "wb").write(b"vid")
        return os.path.join(job_dir, "remotion-video.mp4")
    async def fake_synth(text, voice, out_wav): return None
    async def fake_mux(video_in, out_path, audio_path):  # writes out.mp4
        open(out_path, "wb").write(b"final"); return out_path
    monkeypatch.setattr(vrr, "render_remotion", fake_client)
    monkeypatch.setattr(vrr, "_synthesize_narration", fake_synth)
    monkeypatch.setattr(vrr, "_run_audio_mux", fake_mux)
    plan = {"narration_script": "", "scenes": [
        {"kind":"screenshot","screenshot":"screenshot-1.png","headline":"h","motion":"zoom-in","duration_s":3.0}]}
    out = await vrr.render_remotion_job(str(tmp_path), slug, jid, plan, voice=None)
    assert out.endswith("out.mp4") and os.path.exists(out)
    assert seen["host"] == "example.com" and seen["title"] == "Example"
    assert seen["scenes"][0]["screenshot"].endswith("screenshot-1.png")
```

- [ ] **Step 2: Run -> FAIL.**

- [ ] **Step 3: Implement `render_remotion_job(apps_dir, slug, job_id, plan, *, fps=24, voice=None)`:**
  IMPORT STYLE (so the Task-7 test's monkeypatch works): use module-level
  from-imports at the top of `video_remotion_render.py` -
  `from video_remotion_client import render_remotion` and
  `from video_anim import _synthesize_narration` - so they are attributes of
  `video_remotion_render` that `monkeypatch.setattr(vrr, "render_remotion", ...)`
  can replace. (fps=24 matches the animated path for parity.)
  - `job_dir = os.path.join(apps_dir, slug, ".video", job_id)`.
  - Load `site_context.json` (default `{}`); host/title from it.
  - Build `scenes` from `plan["scenes"]`: each `{kind, screenshot: <abs path to job_dir/screenshots/<name>> if screenshot else None, headline, subtext, motion, durationS: duration_s}`. (Pass ABS paths; the client/service turns them into `file://` URLs.)
  - `narration = await _synthesize_narration(plan.get("narration_script") or "", voice, os.path.join(job_dir, "narration.wav"))` (import from `video_anim`).
  - `video_only = await render_remotion(job_dir, theme="parity", fps=fps, width=1280, height=720, host=host, title=title, scenes=scenes)`.
  - `out = os.path.join(job_dir, "out.mp4")`; `await _run_audio_mux(video_only, out, narration)` where `_run_audio_mux` builds args via `_build_audio_mux_args` and runs ffmpeg as a subprocess (factor it as a module function so the test can monkeypatch it). Return `out`.

- [ ] **Step 4: Run -> PASS;** run the full video suite.
Run: `python -m pytest tests/test_video_remotion_render.py tests/test_video_anim.py -v`

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/video_remotion_render.py mcp-servers/tasks/tests/test_video_remotion_render.py
git commit -m "feat(video): render_remotion_job orchestrator (service render + local audio mux)"
```

### Task 8: Worker dispatch for `remotion`

**Files:** modify `mcp-servers/tasks/video_worker.py` (plan selection ~:131-137 and render dispatch ~:152-155); test in `tests/test_video_worker.py`.

- [ ] **Step 1: Write/extend a worker test** - Grep `tests/test_video_worker.py` for how it drives a job through the worker with mocks. Add a case: a job with `render_mode="remotion"` uses `generate_anim_plan` for planning and calls `render_remotion_job` (monkeypatched) for the render, reaching `done`. Mock `render_remotion_job`, `generate_anim_plan`, and DB as the existing tests do.

- [ ] **Step 2: Run -> FAIL** (worker has no remotion branch).

- [ ] **Step 3: Implement** two edits in `video_worker.py`:
  - Plan selection: change the condition so `render_mode in ("animated", "remotion")` uses `generate_anim_plan` (else slideshow). (Grep the current ternary at ~:131-137.)
  - Render dispatch: add a branch. Use a TOP-LEVEL import (no circular dep:
    `video_remotion_render` imports `video_anim`/`video_remotion_client`, neither
    imports `video_worker`), matching the `render_animated_job` import pattern:
    add `from video_remotion_render import render_remotion_job` near
    `from video_anim import render_animated_job` (~:27), then:
    ```python
    if render_mode == "animated":
        out = await render_animated_job(APPS_DIR, slug, str(job_id), plan, voice=voice)
    elif render_mode == "remotion":
        out = await render_remotion_job(APPS_DIR, slug, str(job_id), plan, voice=voice)
    else:
        out = await VideoRenderExecutor().render(slug, str(job_id), plan, style=style, voice=voice)
    ```
  - The worker test patches `video_worker.render_remotion_job` (the name bound into
    the worker module by the top-level import).

- [ ] **Step 4: Run -> PASS;** run the worker + pipeline suites.
Run: `python -m pytest tests/test_video_worker.py tests/test_video_pipeline.py -v`

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/video_worker.py mcp-servers/tasks/tests/test_video_worker.py
git commit -m "feat(video): worker renders render_mode=remotion via the remotion engine"
```

---

## Part C: container + deploy

### Task 9: Dockerfile + compose service

**Files:** create `video-remotion/Dockerfile`; modify `docker-compose.unified.yml`.

- [ ] **Step 1: `video-remotion/Dockerfile`** - a Node base with Chromium deps + Inter font:
  - `FROM node:20-bookworm-slim`
  - install Remotion's Chromium OS deps + `fontconfig fonts-inter fonts-liberation2` + `fc-cache -f` (same font discipline as the tasks image), and ffmpeg (Remotion bundles its own ffmpeg, but install the system one as a fallback for the mux-side parity; the actual audio mux runs in tasks, so ffmpeg here is only for Remotion if needed).
  - `WORKDIR /app`, copy `package.json` + `package-lock.json`, `npm ci`, copy `src/` + configs, `npx remotion browser ensure` to pre-install the headless Chromium at build time, expose `8090`, `CMD ["npm","run","server"]`.
  - `npm ci` requires a committed `package-lock.json` - ensure Task 1's `npm install` generated it and that `.gitignore`/`.dockerignore` do NOT exclude it (only `node_modules/` and `out/`). If no lockfile is committed, use `npm install` instead.
  - Compose snippet: use the file's LIST-form network style to match `tasks` (`networks:` then `- backend`), not the map form.

- [ ] **Step 2: Add the compose service** to `docker-compose.unified.yml` (mirror the `tasks` service's volume + network; Grep the `tasks:` block ~:267-300 for the exact mount/network keys):
  ```yaml
  video-remotion:
    logging: *logging
    build: ./video-remotion
    restart: unless-stopped
    environment:
      - PORT=8090
    volumes:
      - ./:/workspace/ai_ui
    networks:
      - backend
    expose:
      - "8090"
  ```
  And set `VIDEO_REMOTION_URL=http://video-remotion:8090` in the `tasks` service `environment`.

- [ ] **Step 3: Commit**

```bash
git add video-remotion/Dockerfile video-remotion/.dockerignore docker-compose.unified.yml
git commit -m "build(remotion): video-remotion container + compose wiring"
```

### Task 10: Deploy + end-to-end verification

Deploy discipline (CLAUDE.md + memory): SSH key `~/.ssh/aiui_vps`, host `root@46.224.193.25`, repo `/root/proxy-server`, compose `docker-compose.unified.yml`. NEVER touch `.env` or deploy `templates.py`. Normalize CRLF (`tr -d '\r'`) when drift-checking; upload LF via `git show HEAD:path | ssh ... "cat > ..."` (<=3 files per ssh call). New `video-remotion/` tree: upload the files (or `git archive` the dir) then build.

- [ ] **Step 1: Pre-flight** - `git` clean; SSH ok; HARD free-disk check: `df -h /` must show >= ~5GB free, else `docker builder prune -af` + `docker image prune -f` first (the Node+Chromium image is large).
- [ ] **Step 2: Upload** the new `video-remotion/` tree + changed files (routes_video.py, video_anim.py, video_worker.py, video_remotion_client.py, video_remotion_render.py, docker-compose.unified.yml) to `/root/proxy-server`, LF, <=3 files/ssh call. Drift-check the modified tasks files first.
- [ ] **Step 3: Build + start** `video-remotion`, then rebuild `tasks`:
  ```bash
  ssh -i ~/.ssh/aiui_vps -o IdentitiesOnly=yes root@46.224.193.25 \
    "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build video-remotion tasks"
  ```
- [ ] **Step 4: Verify health** - `video-remotion` `GET /healthz` from the tasks container (`docker compose exec -T tasks curl -fsS http://video-remotion:8090/healthz`), tasks `https://ai-ui.coolestdomain.win/tasks/healthz`.
- [ ] **Step 5: E2E render** - create a draft with `render_mode=remotion` (via draft-set), add screenshots from a URL (capture), queue, watch the worker reach `done`; pull `out.mp4`, `ffprobe` (h264 video + aac audio), extract a frame and view it.
- [ ] **Step 6: Parity check** - render the same job in `animated` vs `remotion`; eyeball the frames match. Tune `theme-parity.tsx` if needed; redeploy `video-remotion`.
- [ ] **Step 7: Post-deploy** - `docker builder prune -af` to reclaim space; update memory `project_video_branches_2026-06-24.md` (Remotion foundation shipped, branch, how to select remotion mode).

---

## Notes / risks
- Disk: the Node+Chromium image is the biggest risk on the ~85%-full box; the hard pre-build free check + prune discipline is mandatory.
- Cross-container Chromium overlap (capture vs render): bounded by single-job worker + service mutex; `enough_free_ram` does not cover the capture path - acceptable for v1.
- `-c:v copy` requires Remotion output pinned to h264/yuv420p (set in `remotion.config.ts`); keep `+faststart` on the mux.
- Parity is judged by viewing real frames; budget a couple of CSS iterations in `theme-parity.tsx`.
- v1 only: no cursor, no extra themes, no UI for picking remotion mode (set via draft-set/dev path). Those are sub-projects 2 and 3.
