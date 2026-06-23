# Animated Video Engine — Phase 2 (LLM authoring) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The LLM authors a *bounded* animated plan from the prompt + screenshots, a deterministic Python builder turns it into a seek-safe HTML composition, and the Phase-1 runtime renders it to MP4 — proving real prompt-driven animation end-to-end.

**Architecture:** `video_plan.py` gains an `animated` plan path (`ANIM_PLAN_SCHEMA` + `generate_anim_plan` with motion best-practices injected at the existing best-practices hook = #6, plus retry + deterministic fallback). `video_anim.py` gains `build_composition(plan, shots)` — a deterministic HTML builder over a fixed motion vocabulary (no LLM-authored HTML/JS; text set via JS `textContent`, so no injection). Worker/executor wiring + UI are deferred to Phase 3.

**Tech Stack:** Python 3.11, anthropic SDK (structured outputs), Playwright+ffmpeg (Phase 1), pytest (asyncio auto).

All paths in the `IO-integrate` worktree, branch `fix/video-thread-image-intake`.

---

## File Structure

- Modify `mcp-servers/tasks/video_plan.py` — add the animated plan: `ANIM_PLAN_SCHEMA`, `validate_anim_plan`, `_anim_fallback_plan`, `ANIM_BEST_PRACTICES`, `build_anim_system_prompt`, `generate_anim_plan`. (Slideshow plan untouched.)
- Modify `mcp-servers/tasks/video_anim.py` — add `build_composition(plan, shots)` (the bounded, deterministic HTML builder).
- Modify `mcp-servers/tasks/tests/test_video_plan.py` and `tests/test_video_anim.py` — unit tests.

---

## Task 1: Animated plan — schema, validate, fallback, generate

**Files:** Modify `mcp-servers/tasks/video_plan.py`; Modify `mcp-servers/tasks/tests/test_video_plan.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_video_plan.py`:

```python
def test_anim_schema_bounds_scenes_and_motion():
    from video_plan import ANIM_PLAN_SCHEMA
    sc = ANIM_PLAN_SCHEMA["properties"]["scenes"]
    assert sc["minItems"] == 1 and sc["maxItems"] == 8
    motions = set(sc["items"]["properties"]["motion"]["enum"])
    assert {"zoom-in", "pan-up", "fade"} <= motions


def test_anim_fallback_plan_is_valid():
    from video_plan import _anim_fallback_plan, validate_anim_plan
    shots = ["screenshot-1.png", "screenshot-2.png"]
    p = _anim_fallback_plan("show my portfolio", shots)
    validate_anim_plan(p, shots)  # no raise
    assert p["scenes"]                     # non-empty
    # every screenshot-kind scene references an available file
    for s in p["scenes"]:
        if s["kind"] == "screenshot":
            assert s["screenshot"] in shots


def test_validate_anim_plan_rejects_bad():
    from video_plan import validate_anim_plan, PlanInvalid
    import pytest
    with pytest.raises(PlanInvalid):
        validate_anim_plan({"title": "t", "scenes": [], "narration_script": ""}, ["a.png"])
    with pytest.raises(PlanInvalid):
        validate_anim_plan({"title": "t", "narration_script": "", "scenes": [
            {"kind": "screenshot", "screenshot": "missing.png", "headline": "h",
             "motion": "zoom-in", "duration_s": 3}]}, ["a.png"])


async def test_generate_anim_plan_falls_back_on_empty(monkeypatch):
    import anthropic, json
    from video_plan import generate_anim_plan, validate_anim_plan
    empty = {"title": "x", "scenes": [], "narration_script": ""}
    fake = _FakeClient(json.dumps(empty))
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: fake)
    shots = ["screenshot-1.png"]
    plan = await generate_anim_plan("walk my site", shots, attempts=2)
    validate_anim_plan(plan, shots)        # fallback is valid
    assert len(fake.messages.calls) == 2   # tried the model before fallback
```

- [ ] **Step 2: Run (fails — names undefined)**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_video_plan.py -q -k anim`
Expected: FAIL — `ImportError`/`AttributeError` for `ANIM_PLAN_SCHEMA`.

- [ ] **Step 3: Implement in `video_plan.py`**

Add after the existing slideshow plan code (e.g. after `generate_plan`):

```python
# --- Animated (HTML-composition) plan path -------------------------------------
ANIM_MOTIONS = ["zoom-in", "zoom-out", "pan-up", "pan-left", "rise", "fade"]
ANIM_MAX_SCENES = 8
ANIM_MAX_TOTAL_SECONDS = 40.0

ANIM_PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "scenes", "narration_script"],
    "properties": {
        "title": {"type": "string"},
        "scenes": {
            "type": "array", "minItems": 1, "maxItems": ANIM_MAX_SCENES,
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["kind", "headline", "motion", "duration_s"],
                "properties": {
                    "kind": {"type": "string", "enum": ["title", "screenshot", "outro"]},
                    "screenshot": {"type": "string"},
                    "headline": {"type": "string"},
                    "subtext": {"type": "string"},
                    "motion": {"type": "string", "enum": ANIM_MOTIONS},
                    "duration_s": {"type": "number"},
                },
            },
        },
        "narration_script": {"type": "string"},
    },
}

ANIM_BEST_PRACTICES = (
    "ANIMATED-VIDEO BEST PRACTICES (HyperFrames/Remotion-style motion design) — "
    "follow for every plan:\n"
    "- Arc: open with a short TITLE beat (what it is), then SCREENSHOT scenes that "
    "show the product with motion, then a brief OUTRO. You need NOT use every "
    "screenshot — pick the ones that tell the story.\n"
    "- One idea per scene. Headline = punchy kinetic text, <= ~8 words, benefit-led "
    "(not the UI read verbatim). Optional subtext is a short supporting line.\n"
    "- Motion choreographs AROUND the screenshot (it is the hero): pick a motion that "
    "suits the beat (zoom-in to focus, pan-up/pan-left to reveal, rise/fade for text). "
    "Don't reuse the same motion every scene.\n"
    "- Pacing: 2.5-5s per scene; keep the whole video tight (20-35s is ideal, hard "
    "cap 40s). Narration must be speakable within the total (~2.5 words/second).\n"
    "- Reference ONLY the provided screenshot filenames, exactly as given, and only "
    "on scenes with kind 'screenshot'."
)


def build_anim_system_prompt() -> str:
    return (
        "You produce a JSON plan for a short ANIMATED motion video built from the "
        "given screenshots. kind 'title'/'outro' scenes show kinetic text only; "
        "kind 'screenshot' scenes animate one provided screenshot with a headline. "
        f"Use ONLY the provided screenshot filenames. Keep total duration under "
        f"{ANIM_MAX_TOTAL_SECONDS:.0f}s.\n\n" + ANIM_BEST_PRACTICES
    )


def validate_anim_plan(plan: dict, available: list[str]) -> None:
    scenes = plan.get("scenes") or []
    if not scenes:
        raise PlanInvalid("animated plan has no scenes")
    have = set(available)
    total = 0.0
    for sc in scenes:
        if sc.get("kind") == "screenshot":
            if sc.get("screenshot") not in have:
                raise PlanInvalid(f"scene references missing screenshot {sc.get('screenshot')!r}")
        if sc.get("motion") not in ANIM_MOTIONS:
            raise PlanInvalid(f"unknown motion {sc.get('motion')!r}")
        d = float(sc.get("duration_s") or 0)
        if not (0.5 <= d <= 15):
            raise PlanInvalid("scene duration out of range")
        total += d
    if total > ANIM_MAX_TOTAL_SECONDS + 0.01:
        raise PlanInvalid(f"animated video too long ({total}s)")


def _anim_fallback_plan(prompt: str, screenshots: list[str]) -> dict:
    """Deterministic valid animated plan: title -> one scene per screenshot -> outro."""
    clean = (prompt or "").strip()
    shots = list(screenshots[:6])
    scenes = [{"kind": "title", "headline": (clean[:60] or "A quick look"),
               "motion": "rise", "duration_s": 2.5}]
    for i, s in enumerate(shots):
        scenes.append({"kind": "screenshot", "screenshot": s, "headline": "",
                       "motion": ("zoom-in" if i % 2 == 0 else "pan-up"),
                       "duration_s": 3.5})
    scenes.append({"kind": "outro", "headline": (clean[:40] or "Thanks for watching"),
                   "motion": "fade", "duration_s": 2.5})
    # Trim to the scene cap and the time cap.
    scenes = scenes[:ANIM_MAX_SCENES]
    while sum(s["duration_s"] for s in scenes) > ANIM_MAX_TOTAL_SECONDS and len(scenes) > 1:
        scenes.pop(-2 if len(scenes) > 2 else -1)
    return {"title": (clean[:60] or "Walkthrough"), "scenes": scenes,
            "narration_script": clean}


async def generate_anim_plan(prompt: str, screenshots: list[str], *, attempts: int = 3) -> dict:
    """LLM-authored animated plan, resilient (retry + deterministic fallback),
    mirroring generate_plan. Motion best-practices injected via build_anim_system_prompt."""
    client = anthropic.Anthropic()
    sys = build_anim_system_prompt()
    last_err: Exception | None = None
    for i in range(max(1, attempts)):
        try:
            msg = client.messages.create(
                model="claude-opus-4-8", max_tokens=2048, system=sys,
                output_config={"format": {"type": "json_schema", "schema": ANIM_PLAN_SCHEMA}},
                messages=[{"role": "user",
                           "content": f"Prompt: {prompt}\nScreenshots: {screenshots}"}],
            )
            text = next(b.text for b in msg.content if b.type == "text")
            plan = json.loads(text)
            validate_anim_plan(plan, screenshots)
            return plan
        except Exception as e:  # noqa: BLE001 - retry on bad plan / API hiccup
            last_err = e
            logger.warning("generate_anim_plan attempt %d/%d failed: %s: %s",
                           i + 1, attempts, type(e).__name__, e)
    logger.warning("generate_anim_plan falling back after %d attempts (%s)", attempts, last_err)
    plan = _anim_fallback_plan(prompt, screenshots)
    validate_anim_plan(plan, screenshots)
    return plan
```

- [ ] **Step 4: Run (passes)**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_video_plan.py -q -k anim`
Expected: PASS (4 new tests).

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/video_plan.py mcp-servers/tasks/tests/test_video_plan.py
git commit -m "feat(video-anim): animated plan (bounded schema + best-practices + retry/fallback)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `build_composition(plan, shots)` — deterministic HTML from the plan

**Files:** Modify `mcp-servers/tasks/video_anim.py`; Modify `mcp-servers/tasks/tests/test_video_anim.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_video_anim.py`:

```python
def test_build_composition_is_deterministic_and_safe():
    from video_anim import build_composition, composition_duration
    plan = {"title": "Demo", "narration_script": "", "scenes": [
        {"kind": "title", "headline": "Hello </script><b>x", "motion": "rise", "duration_s": 2.0},
        {"kind": "screenshot", "screenshot": "screenshot-1.png", "headline": "Look",
         "motion": "zoom-in", "duration_s": 3.0},
        {"kind": "outro", "headline": "Bye", "motion": "fade", "duration_s": 2.0},
    ]}
    shots = {"screenshot-1.png": _png()}
    html = build_composition(plan, shots)
    assert "window.__seek" in html
    assert "data:image/png;base64," in html              # the screenshot embedded
    # Raw text is NOT injected into markup (it is delivered via JS textContent/JSON).
    assert "</script><b>x" not in html
    # Total duration is the sum of scene durations.
    assert abs(composition_duration(plan) - 7.0) < 0.01
```

- [ ] **Step 2: Run (fails — no `build_composition`)**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_video_anim.py::test_build_composition_is_deterministic_and_safe -q`
Expected: FAIL — `ImportError: cannot import name 'build_composition'`.

- [ ] **Step 3: Implement in `video_anim.py`**

Add (uses `json`, `_data_uri` already present; add `import json`):

```python
import json as _json


def composition_duration(plan: dict) -> float:
    return float(sum(float(s.get("duration_s") or 0) for s in (plan.get("scenes") or [])))


def build_composition(plan: dict, shots: dict[str, bytes],
                      *, width: int = 1280, height: int = 720) -> str:
    """Deterministic, seek-safe HTML for an animated plan. Text is delivered to the
    page via a JSON SCENES array + JS textContent (never interpolated into markup),
    and screenshots as data URIs — so it is self-contained and injection-safe."""
    scenes = []
    for sc in (plan.get("scenes") or []):
        img = ""
        if sc.get("kind") == "screenshot":
            png = shots.get(sc.get("screenshot") or "")
            if png:
                img = _data_uri(png)
        scenes.append({
            "kind": sc.get("kind", "screenshot"),
            "img": img,
            "headline": str(sc.get("headline") or ""),
            "subtext": str(sc.get("subtext") or ""),
            "motion": sc.get("motion", "fade"),
            "dur": max(0.5, float(sc.get("duration_s") or 3.0)),
        })
    data = _json.dumps(scenes).replace("</", "<\\/")  # safe to embed in <script>
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
  html,body{{margin:0;width:{width}px;height:{height}px;background:#0b0b10;overflow:hidden;
    font-family:Inter,Segoe UI,system-ui,sans-serif;color:#fff}}
  #img{{position:absolute;top:7%;left:50%;width:66%;border-radius:14px;
    box-shadow:0 24px 80px rgba(0,0,0,.6);opacity:0;transform:translate(-50%,0)}}
  #headline{{position:absolute;bottom:13%;left:6%;right:6%;text-align:center;font-size:56px;
    font-weight:800;letter-spacing:-1px;opacity:0;transform:translateY(24px)}}
  #subtext{{position:absolute;bottom:8%;left:6%;right:6%;text-align:center;font-size:28px;
    font-weight:600;opacity:0}}
  .center #headline{{bottom:auto;top:44%}}
</style></head><body>
  <img id="img"><div id="headline"></div><div id="subtext"></div>
<script>
  var SCENES={data};
  function clamp(x){{return Math.max(0,Math.min(1,x));}}
  function lerp(a,b,p){{return a+(b-a)*p;}}
  function ease(p){{p=clamp(p);return p*p*(3-2*p);}}
  var IMG=document.getElementById('img'), H=document.getElementById('headline'),
      SUB=document.getElementById('subtext'), BODY=document.body;
  // Precompute scene start times.
  var starts=[],acc=0; for(var i=0;i<SCENES.length;i++){{starts.push(acc);acc+=SCENES[i].dur;}}
  window.__seek=function(t){{
    var idx=0; for(var i=0;i<SCENES.length;i++){{if(t>=starts[i])idx=i;}}
    var sc=SCENES[idx]||SCENES[SCENES.length-1]; if(!sc){{return;}}
    var p=clamp((t-starts[idx])/Math.max(0.001,sc.dur));      // local progress 0..1
    var env=ease(p/0.25)*(1-ease((p-0.8)/0.2));               // fade in/out envelope
    // image
    if(sc.img){{IMG.src=sc.img; var tx='translate(-50%,0)';
      if(sc.motion==='zoom-in')tx+=' scale('+lerp(1.0,1.1,ease(p))+')';
      else if(sc.motion==='zoom-out')tx+=' scale('+lerp(1.1,1.0,ease(p))+')';
      else if(sc.motion==='pan-up')tx='translate(-50%,'+lerp(20,-20,ease(p))+'px)';
      else if(sc.motion==='pan-left')tx='translate(calc(-50% + '+lerp(30,-30,ease(p))+'px),0)';
      IMG.style.opacity=env; IMG.style.transform=tx;}}
    else {{IMG.style.opacity=0;}}
    // text (textContent — injection-safe)
    BODY.className=(sc.kind==='screenshot')?'':'center';
    H.textContent=sc.headline||''; SUB.textContent=sc.subtext||'';
    var hy=(sc.motion==='rise')?lerp(24,0,ease(p)):0;
    H.style.opacity=env; H.style.transform='translateY('+hy+'px)';
    SUB.style.opacity=sc.subtext?env:0;
  }};
  window.__seek(0);
</script></body></html>"""
```

- [ ] **Step 4: Run (passes)**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_video_anim.py -q`
Expected: PASS (the demo + new composition test; real-render test skips without ffmpeg).

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/video_anim.py mcp-servers/tasks/tests/test_video_anim.py
git commit -m "feat(video-anim): build_composition — deterministic HTML from a bounded animated plan

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Deploy + end-to-end LLM-authored render proof (in-container)

**Files:** none (deploy + verification)

- [ ] **Step 1: Full tasks suite (no regressions)**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_video_plan.py tests/test_video_anim.py -q`
Expected: PASS (anim tests green; real-render skips locally).

- [ ] **Step 2: Drift-check + scp**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO-integrate"
for f in video_plan.py video_anim.py; do
  git show HEAD~2:mcp-servers/tasks/$f | tr -d '\r' | sha256sum | cut -c1-16
  ssh root@46.224.193.25 "tr -d '\r' < /root/proxy-server/mcp-servers/tasks/$f | sha256sum | cut -c1-16"
done   # each pair should match (server = last-deployed)
scp mcp-servers/tasks/video_plan.py root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/video_plan.py
scp mcp-servers/tasks/video_anim.py root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/video_anim.py
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build tasks 2>&1 | tail -5"   # background if slow
```

- [ ] **Step 3: End-to-end proof in-container (real LLM)**

Pipe a script into the container: a sample prompt + a Pillow screenshot → `generate_anim_plan` → `build_composition` → `render_html_to_mp4` → MP4; print scene count + frames + size + ffprobe duration:
```bash
ssh root@46.224.193.25 'cd /root/proxy-server && CID=$(docker compose -f docker-compose.unified.yml ps -q tasks) && docker exec -i "$CID" python -' <<'PY'
import asyncio, io, os, subprocess
from PIL import Image
from video_plan import generate_anim_plan
from video_anim import build_composition, render_html_to_mp4, composition_duration
b=io.BytesIO(); Image.new("RGB",(1200,750),(28,30,46)).save(b,"PNG"); png=b.getvalue()
shots={"screenshot-1.png":png}
async def main():
    plan=await generate_anim_plan("Walk through my portfolio and highlight the projects",["screenshot-1.png"])
    print("SCENES",len(plan["scenes"]),"TITLE",repr(plan.get("title")))
    html=build_composition(plan, shots)
    dur=min(40.0, composition_duration(plan))
    n=await render_html_to_mp4(html,"/tmp/anim_e2e.mp4",fps=24,duration_s=dur)
    sz=os.path.getsize("/tmp/anim_e2e.mp4")
    pd=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0","/tmp/anim_e2e.mp4"],capture_output=True,text=True).stdout.strip()
    print("RESULT FRAMES",n,"SIZE",sz,"DURATION",pd)
asyncio.run(main())
PY
```
Expected: `SCENES >=3`, `RESULT FRAMES ...`, a valid MP4 with duration ~= the plan total — proving the LLM authored a real animated video end-to-end. Confirm healthz ok + no OOM.

- [ ] **Step 4: Push branch + main**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO-integrate"
gh auth switch -u Jacintalama
git push fork fix/video-thread-image-intake
git push fork HEAD:main
```

---

## Deferred to Phase 3 (NOT in this plan)
- A `render_mode` field on the VideoJob + the worker/executor branch (animated runs in-container; slideshow stays on the agent VM).
- Narration: Piper audio muxed into animated renders (Phase 1 `render_html_to_mp4` already accepts `audio_path`).
- Surfacing "animated" mode in the web create page + Discord (slideshow stays default).
- Adding a "Remotion best practices" entry to the Open WebUI Skills page (visibility; functional wiring is the `ANIM_BEST_PRACTICES` injection done here).

## Self-Review (filled by author)
- **Spec coverage:** LLM authoring with bounded schema + best-practices injection (#6) + retry/fallback (T1); deterministic injection-safe HTML builder (T2); end-to-end LLM->MP4 proof (T3). Matches the Phase-2 scope in the animated-engine spec. Phase-3 items explicitly deferred. ✓
- **Placeholders:** none — full code/commands throughout. ✓
- **Name consistency:** `ANIM_PLAN_SCHEMA`, `validate_anim_plan`, `_anim_fallback_plan`, `generate_anim_plan`, `build_anim_system_prompt`, `ANIM_BEST_PRACTICES`, `ANIM_MOTIONS`, `build_composition`, `composition_duration` used identically across module + tests + the in-container proof. `_FakeClient` reused from the existing test_video_plan.py. ✓
