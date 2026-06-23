"""Animated video runtime (Phase 1 de-risk): render an HTML motion composition to
MP4 in-container via headless Chromium (Playwright) frame-capture + ffmpeg.

The composition is deterministic and seek-safe: a single global window.__seek(t)
positions every element from the timeline time `t` (seconds) — no wall-clock, no
randomness — so frame capture is reproducible. Screenshots are embedded as data
URIs so the HTML is fully self-contained (no asset-path coupling).
"""
from __future__ import annotations

import asyncio
import base64
import html as _html
import json as _json
import logging
import os
import shutil
import tempfile

logger = logging.getLogger("video_anim")

# Piper TTS binary for in-container narration (best-effort; animated renders fall
# back to silent video if Piper or the voice model is unavailable).
_PIPER_BIN = "/opt/piper/piper"


def _data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def build_demo_composition(screenshots: list[bytes], title: str,
                           *, width: int = 1280, height: int = 720) -> str:
    """A HARDCODED kinetic demo composition (Phase 1): animated title -> a
    screenshot pan with a sliding caption -> outro card. Deterministic via
    window.__seek(t). Returns a self-contained HTML string."""
    uris = [_data_uri(p) for p in (screenshots or [])]
    safe_title = _html.escape(title or "Your site")
    imgs = "".join(f'<img class="shot" src="{u}">' for u in uris[:1])
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
  html,body{{margin:0;width:{width}px;height:{height}px;background:#0b0b10;overflow:hidden;
    font-family:Inter,Segoe UI,system-ui,sans-serif;color:#fff}}
  .stage{{position:absolute;inset:0}}
  .title{{position:absolute;top:46%;left:0;right:0;text-align:center;font-size:64px;
    font-weight:800;letter-spacing:-1px;opacity:0;transform:translateY(24px)}}
  .shot{{position:absolute;top:8%;left:50%;width:64%;border-radius:14px;
    box-shadow:0 24px 80px rgba(0,0,0,.6);opacity:0;transform:translate(-50%,0) scale(1)}}
  .cap{{position:absolute;bottom:10%;left:0;right:0;text-align:center;font-size:34px;
    font-weight:700;opacity:0;transform:translateX(-40px)}}
  .outro{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
    font-size:54px;font-weight:800;background:#0b0b10;opacity:0}}
</style></head><body>
  <div class="stage">
    <div class="title" id="title">{safe_title}</div>
    {imgs}
    <div class="cap" id="cap">A quick look</div>
    <div class="outro" id="outro">{safe_title}</div>
  </div>
<script>
  // Pure function of t (seconds): set opacity/transform deterministically.
  function clamp(x){{return Math.max(0,Math.min(1,x));}}
  function lerp(a,b,p){{return a+(b-a)*p;}}
  function ease(p){{p=clamp(p);return p*p*(3-2*p);}}  // smoothstep
  const T=document.getElementById('title'), C=document.getElementById('cap'),
        O=document.getElementById('outro'), S=document.querySelector('.shot');
  window.__seek=function(t){{
    // 0-2s: title in; 1.6-2s title out
    var ti=ease((t-0.2)/1.2)*(1-ease((t-1.6)/0.4));
    T.style.opacity=ti; T.style.transform='translateY('+lerp(24,0,ease((t-0.2)/1.2))+'px)';
    // 2-6s: screenshot pan/zoom + caption slide-in
    var sp=ease((t-2.0)/0.6)*(1-ease((t-5.6)/0.4));
    if(S){{S.style.opacity=sp;
      var k=ease((t-2.0)/4.0);
      S.style.transform='translate(-50%,'+lerp(0,-30,k)+'px) scale('+lerp(1.0,1.08,k)+')';}}
    var cp=ease((t-2.4)/0.5)*(1-ease((t-5.6)/0.4));
    C.style.opacity=cp; C.style.transform='translateX('+lerp(-40,0,ease((t-2.4)/0.5))+'px)';
    // 6-8s: outro
    O.style.opacity=ease((t-6.0)/0.6);
  }};
  window.__seek(0);
</script></body></html>"""


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
  body.center #headline{{bottom:auto;top:44%}}
</style></head><body>
  <img id="img"><div id="headline"></div><div id="subtext"></div>
<script>
  var SCENES={data};
  function clamp(x){{return Math.max(0,Math.min(1,x));}}
  function lerp(a,b,p){{return a+(b-a)*p;}}
  function ease(p){{p=clamp(p);return p*p*(3-2*p);}}
  var IMG=document.getElementById('img'), H=document.getElementById('headline'),
      SUB=document.getElementById('subtext'), BODY=document.body;
  var starts=[],acc=0; for(var i=0;i<SCENES.length;i++){{starts.push(acc);acc+=SCENES[i].dur;}}
  window.__seek=function(t){{
    var idx=0; for(var i=0;i<SCENES.length;i++){{if(t>=starts[i])idx=i;}}
    var sc=SCENES[idx]; if(!sc){{return;}}
    var p=clamp((t-starts[idx])/Math.max(0.001,sc.dur));
    var env=ease(p/0.25)*(1-ease((p-0.8)/0.2));
    if(sc.img){{IMG.src=sc.img; var tx='translate(-50%,0)';
      if(sc.motion==='zoom-in')tx+=' scale('+lerp(1.0,1.1,ease(p))+')';
      else if(sc.motion==='zoom-out')tx+=' scale('+lerp(1.1,1.0,ease(p))+')';
      else if(sc.motion==='pan-up')tx='translate(-50%,'+lerp(20,-20,ease(p))+'px)';
      else if(sc.motion==='pan-left')tx='translate(calc(-50% + '+lerp(30,-30,ease(p))+'px),0)';
      IMG.style.opacity=env; IMG.style.transform=tx;}}
    else {{IMG.style.opacity=0;}}
    BODY.className=(sc.kind==='screenshot')?'':'center';
    H.textContent=sc.headline||''; SUB.textContent=sc.subtext||'';
    var hy=(sc.motion==='rise')?lerp(24,0,ease(p)):0;
    H.style.opacity=env; H.style.transform='translateY('+hy+'px)';
    SUB.style.opacity=sc.subtext?env:0;
  }};
  window.__seek(0);
</script></body></html>"""


# One animated render at a time (mirrors the slideshow heavy-job discipline).
_ANIM_LOCK = asyncio.Lock()

# Phase-1 guardrails: bound frame count so the in-container render stays inside
# the box's RAM/time budget.
MAX_FPS = 24
MAX_DURATION_S = 40.0


async def render_html_to_mp4(html: str, out_path: str, *, fps: int = 24,
                             duration_s: float = 8.0, audio_path: str | None = None,
                             width: int = 1280, height: int = 720) -> int:
    """Render a seekable HTML composition to an MP4. Loads the HTML in the
    in-container headless Chromium, screenshots each seeked frame, then ffmpeg
    encodes the PNG sequence (+ optional audio). Returns the frame count. Raises
    RuntimeError if the engine (Playwright/Chromium) or ffmpeg is unavailable."""
    fps = max(1, min(MAX_FPS, int(fps)))
    duration_s = max(0.5, min(MAX_DURATION_S, float(duration_s)))
    n = int(duration_s * fps)
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise RuntimeError("playwright unavailable") from e

    workdir = tempfile.mkdtemp(prefix="anim-")
    html_path = os.path.join(workdir, "comp.html")
    frames_dir = os.path.join(workdir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    try:
        async with _ANIM_LOCK:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
                try:
                    ctx = await browser.new_context(
                        viewport={"width": width, "height": height})
                    page = await ctx.new_page()
                    await page.goto("file://" + html_path, wait_until="load")
                    for i in range(n):
                        await page.evaluate("window.__seek(%f)" % (i / fps))
                        await page.screenshot(
                            path=os.path.join(frames_dir, "f%05d.png" % i))
                finally:
                    await browser.close()
            # Encode: ffmpeg PNG sequence (+ optional audio) -> H.264 MP4.
            args = ["ffmpeg", "-y", "-framerate", str(fps),
                    "-i", os.path.join(frames_dir, "f%05d.png")]
            if audio_path:
                args += ["-i", audio_path]
            args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                     "-pix_fmt", "yuv420p", "-r", str(fps), "-threads", "2"]
            if audio_path:
                args += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
            args += ["-movflags", "+faststart", out_path]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            except FileNotFoundError as e:
                raise RuntimeError("ffmpeg not found") from e
            _, err = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError("ffmpeg failed: " + err.decode("utf-8", "replace")[-300:])
        return n
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


async def _synthesize_narration(text: str, voice: str | None, out_wav: str) -> str | None:
    """Piper TTS narration.txt -> wav (text via stdin; no shell). Returns the wav
    path, or None if Piper/the model is unavailable or fails — so animated renders
    degrade to silent video rather than crashing."""
    from video_voices import resolve_model
    model = resolve_model(voice)  # allowlisted path; never user input
    if not (text or "").strip() or not os.path.exists(_PIPER_BIN) or not os.path.exists(model):
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            _PIPER_BIN, "-m", model, "-f", out_wav,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE)
        _, err = await proc.communicate(text.encode("utf-8"))
    except Exception as e:  # noqa: BLE001 - never fail the render on narration
        logger.warning("narration synth failed: %s", e)
        return None
    if proc.returncode != 0 or not os.path.exists(out_wav):
        logger.warning("piper returned %s: %s", proc.returncode, err.decode("utf-8", "replace")[-200:])
        return None
    return out_wav


async def render_animated_job(apps_dir: str, slug: str, job_id: str, plan: dict,
                              *, fps: int = 24, voice: str | None = None) -> str:
    """Render an animated job's plan to out.mp4 in-container: read the job's
    screenshots from disk, build the composition, synthesize Piper narration (if
    available), then render via Chromium+ffmpeg. Returns the output path."""
    shots_dir = os.path.join(apps_dir, slug, ".video", job_id, "screenshots")
    shots: dict[str, bytes] = {}
    if os.path.isdir(shots_dir):
        for name in sorted(os.listdir(shots_dir)):
            p = os.path.join(shots_dir, name)
            if os.path.isfile(p):
                with open(p, "rb") as f:
                    shots[name] = f.read()
    html = build_composition(plan, shots)
    job_dir = os.path.join(apps_dir, slug, ".video", job_id)
    out = os.path.join(job_dir, "out.mp4")
    dur = min(MAX_DURATION_S, composition_duration(plan) or 8.0)
    audio = await _synthesize_narration(
        plan.get("narration_script") or "", voice, os.path.join(job_dir, "narration.wav"))
    await render_html_to_mp4(html, out, fps=fps, duration_s=dur, audio_path=audio)
    return out
