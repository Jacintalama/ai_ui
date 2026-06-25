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
                      *, width: int = 1280, height: int = 720,
                      site_context: dict | None = None) -> str:
    """Deterministic, seek-safe HTML for an animated plan. Text is delivered to the
    page via a JSON SCENES array + JS textContent / runtime-built nodes (never
    interpolated into markup), and screenshots as data URIs, so it is self-contained
    and injection-safe. The composition reads like a motion-graphics piece: a
    browser-chrome frame around each screenshot, depth (gradient bg, glow, vignette),
    an uppercase eyebrow + bold headline with a kinetic per-word reveal, and an
    always-on Ken Burns layered on each scene's motion. Pure function of t."""
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
    ctx = site_context or {}
    cfg = {"host": str(ctx.get("host") or ""), "title": str(ctx.get("title") or "")}
    data = _json.dumps(scenes).replace("</", "<\\/")     # safe to embed in <script>
    cfg_json = _json.dumps(cfg).replace("</", "<\\/")
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
  html,body{{margin:0;width:{width}px;height:{height}px;overflow:hidden;color:#fff;
    font-family:Inter,Segoe UI,system-ui,sans-serif;
    background:radial-gradient(125% 120% at 50% -10%, #16161f 0%, #0b0b10 55%, #060608 100%)}}
  .bgglow{{position:absolute;top:-18%;left:50%;width:88%;height:72%;
    transform:translateX(-50%);border-radius:50%;pointer-events:none;
    background:radial-gradient(closest-side, rgba(96,108,180,.34), rgba(96,108,180,0));
    filter:blur(46px)}}
  .vignette{{position:absolute;inset:0;pointer-events:none;mix-blend-mode:multiply;
    background:radial-gradient(125% 125% at 50% 48%, rgba(0,0,0,0) 56%, rgba(0,0,0,.6) 100%)}}
  .stage{{position:absolute;inset:0}}
  .frame{{position:absolute;top:5.5%;left:50%;width:64%;max-height:58%;opacity:0;
    transform:translate(-50%,0);transform-origin:50% 50%;
    border-radius:14px;overflow:hidden;background:#0e0e14;
    border:1px solid rgba(255,255,255,.07);
    box-shadow:0 44px 130px rgba(0,0,0,.66),0 10px 28px rgba(0,0,0,.45)}}
  .bar{{height:36px;display:flex;align-items:center;gap:8px;padding:0 14px;
    background:linear-gradient(#24242f,#191921);
    border-bottom:1px solid rgba(255,255,255,.05)}}
  .dot{{width:11px;height:11px;border-radius:50%;background:#3a3a46;flex:0 0 auto}}
  .dot.r{{background:#ff5f57}} .dot.y{{background:#febc2e}} .dot.g{{background:#28c840}}
  .addr{{margin-left:12px;flex:1;height:20px;border-radius:10px;
    background:rgba(255,255,255,.06);font-size:12px;line-height:20px;
    padding:0 12px;color:#aab1c8;letter-spacing:.2px;
    overflow:hidden;white-space:nowrap;text-overflow:ellipsis}}
  #img{{display:block;width:100%}}
  .eyebrow{{position:absolute;bottom:21%;left:6%;right:6%;text-align:center;
    font-size:18px;font-weight:700;letter-spacing:3px;text-transform:uppercase;
    color:#9aa6ff;opacity:0}}
  #headline{{position:absolute;bottom:13%;left:6%;right:6%;text-align:center;
    font-size:56px;font-weight:800;letter-spacing:-1.5px}}
  #headline span{{display:inline-block;white-space:pre;will-change:opacity,transform}}
  #subtext{{position:absolute;bottom:8%;left:6%;right:6%;text-align:center;
    font-size:28px;font-weight:600;opacity:0}}
  body.center .eyebrow{{bottom:auto;top:37%}}
  body.center #headline{{bottom:auto;top:44%}}
  body.center #subtext{{bottom:auto;top:57%}}
</style></head><body>
  <div class="bgglow"></div>
  <div class="stage"><div id="frame" class="frame">
    <div class="bar"><span class="dot r"></span><span class="dot y"></span><span class="dot g"></span><span id="addr" class="addr"></span></div>
    <img id="img">
  </div></div>
  <div id="eyebrow" class="eyebrow"></div>
  <div id="headline"></div>
  <div id="subtext"></div>
  <div class="vignette"></div>
<script>
  var SCENES={data}, CFG={cfg_json};
  function clamp(x){{return Math.max(0,Math.min(1,x));}}
  function lerp(a,b,p){{return a+(b-a)*p;}}
  function ease(p){{p=clamp(p);return p*p*(3-2*p);}}            // smoothstep
  function ease2(p){{p=clamp(p);return p*p*p*(p*(6*p-15)+10);}} // smootherstep
  var IMG=document.getElementById('img'), H=document.getElementById('headline'),
      SUB=document.getElementById('subtext'), EB=document.getElementById('eyebrow'),
      FRAME=document.getElementById('frame'), ADDR=document.getElementById('addr'),
      BODY=document.body;
  ADDR.textContent = CFG.host || '';
  EB.textContent = CFG.title || 'OVERVIEW';
  var starts=[],acc=0; for(var i=0;i<SCENES.length;i++){{starts.push(acc);acc+=SCENES[i].dur;}}
  // Kinetic headline: words are split + built as <span> nodes from the JSON string
  // at runtime (never baked into markup). Cached per scene index for determinism.
  var _wIdx=-1, _wSpans=[];
  function buildWords(text){{
    while(H.firstChild){{H.removeChild(H.firstChild);}}
    _wSpans=[];
    var words=String(text||'').split(" ");
    for(var i=0;i<words.length;i++){{
      var s=document.createElement('span');
      s.textContent=(i>0?' ':'')+words[i];
      H.appendChild(s); _wSpans.push(s);
    }}
  }}
  window.__seek=function(t){{
    var idx=0; for(var i=0;i<SCENES.length;i++){{if(t>=starts[i])idx=i;}}
    var sc=SCENES[idx]; if(!sc){{return;}}
    var p=clamp((t-starts[idx])/Math.max(0.001,sc.dur));
    // Rounded fade-through envelope: scenes cross through the background.
    var env=ease2(clamp(p/0.18))*(1-ease2(clamp((p-0.82)/0.18)));
    EB.style.opacity=sc.img?0:env;
    if(sc.img){{
      IMG.src=sc.img;
      var kb=lerp(1.0,1.06,ease2(p));            // always-on Ken Burns scale
      var kx=lerp(0,-1.2,ease2(p)), ky=lerp(0,-1.0,ease2(p));  // gentle drift (%)
      var mz=1.0, dx=0, dy=0;
      if(sc.motion==='zoom-in')mz=lerp(1.0,1.1,ease2(p));
      else if(sc.motion==='zoom-out')mz=lerp(1.1,1.0,ease2(p));
      else if(sc.motion==='pan-up')dy=lerp(20,-20,ease2(p));
      else if(sc.motion==='pan-left')dx=lerp(30,-30,ease2(p));
      FRAME.style.opacity=env;
      FRAME.style.transform='translate(calc(-50% + '+dx+'px),'+dy+'px) '
        +'translate('+kx+'%,'+ky+'%) scale('+(kb*mz)+')';
    }} else {{FRAME.style.opacity=0;}}
    BODY.className=(sc.kind==='screenshot')?'':'center';
    if(_wIdx!==idx){{buildWords(sc.headline); _wIdx=idx;}}
    var n=_wSpans.length;
    for(var i=0;i<n;i++){{
      var d=(n>1)?(i/n)*0.45:0;                  // earlier words lead later ones
      var wo=ease2(clamp((p-d)/0.4));            // per-word reveal envelope
      _wSpans[i].style.opacity=env*wo;
      _wSpans[i].style.transform='translateY('+lerp(20,0,wo)+'px)';
    }}
    var hy=(sc.motion==='rise')?lerp(24,0,ease2(p)):0;
    H.style.transform='translateY('+hy+'px)';
    SUB.textContent=sc.subtext||''; SUB.style.opacity=sc.subtext?env:0;
  }};
  window.__seek(0);
</script></body></html>"""


# One animated render at a time (mirrors the slideshow heavy-job discipline).
_ANIM_LOCK = asyncio.Lock()

# Phase-1 guardrails: bound frame count so the in-container render stays inside
# the box's RAM/time budget.
MAX_FPS = 24
MAX_DURATION_S = 40.0

# Ambient bed: a cheap, infinite lavfi sine pad with slow tremolo + lowpass so it
# reads as warm room tone rather than a test tone. -shortest bounds the infinite
# stream to the finite PNG-sequence video.
_AMBIENT_LAVFI = (
    "sine=frequency=110:sample_rate=44100,volume=0.18,"
    "tremolo=f=0.15:d=0.5,lowpass=f=600,afade=t=in:st=0:d=1.5"
)
# Bed level when ducked under narration (kept quiet so the voice sits on top).
_BED_DUCK_VOLUME = 0.12


def _build_ffmpeg_args(frames_pattern: str, out_path: str, *, fps: int,
                       audio_path: str | None, duration_s: float) -> list[str]:
    """Pure builder for the ffmpeg argv that encodes the PNG sequence to MP4.

    The render ALWAYS carries an audio stream: an ffmpeg-synthesized ambient pad
    (input 1, lavfi). When narration (audio_path) is present it becomes input 2
    and the bed is ducked under it via amix; otherwise the bed plays alone at a
    moderate level. A named filtergraph label forces explicit stream mapping, so
    the video is taken from input 0 and the audio from [aout]. -shortest always
    bounds the infinite lavfi sine to the finite video."""
    # input 0: PNG sequence (video).  input 1: ambient bed (always).
    args = ["ffmpeg", "-y",
            "-framerate", str(fps), "-i", frames_pattern,
            "-f", "lavfi", "-i", _AMBIENT_LAVFI]
    if audio_path:
        # input 2: narration. Duck the bed, then mix bed + narration.
        args += ["-i", audio_path]
        filtergraph = (
            f"[1:a]volume={_BED_DUCK_VOLUME}[bed];"
            "[bed][2:a]amix=inputs=2:duration=longest:dropout_transition=0[aout]"
        )
    else:
        # Bed alone at a moderate level.
        filtergraph = "[1:a]volume=0.4[aout]"
    args += ["-filter_complex", filtergraph,
             "-map", "0:v", "-map", "[aout]",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
             "-pix_fmt", "yuv420p", "-r", str(fps), "-threads", "2",
             "-c:a", "aac", "-b:a", "192k", "-shortest",
             "-movflags", "+faststart", out_path]
    return args


def _build_audio_mux_args(video_in: str, out_path: str, *, audio_path: str | None) -> list[str]:
    """Pure builder for the ffmpeg argv that muxes audio onto an existing video file.

    The video stream is copied (no re-encode). The audio stream is always
    built from the ambient bed (input 1, lavfi). When narration (audio_path)
    is present it becomes input 2 and the bed is ducked under it via amix;
    otherwise the bed plays alone at a moderate level."""
    # input 0: existing video file.  input 1: ambient bed (always).
    args = ["ffmpeg", "-y",
            "-i", video_in,
            "-f", "lavfi", "-i", _AMBIENT_LAVFI]
    if audio_path:
        # input 2: narration. Duck the bed, then mix bed + narration.
        args += ["-i", audio_path]
        filtergraph = (
            f"[1:a]volume={_BED_DUCK_VOLUME}[bed];"
            "[bed][2:a]amix=inputs=2:duration=longest:dropout_transition=0[aout]"
        )
    else:
        # Bed alone at a moderate level.
        filtergraph = "[1:a]volume=0.4[aout]"
    args += ["-filter_complex", filtergraph,
             "-map", "0:v", "-map", "[aout]",
             "-c:v", "copy",
             "-c:a", "aac", "-b:a", "192k", "-shortest",
             "-movflags", "+faststart", out_path]
    return args


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
            # Encode: ffmpeg PNG sequence + ambient bed (ducked under narration
            # when present) -> H.264 MP4.
            args = _build_ffmpeg_args(
                os.path.join(frames_dir, "f%05d.png"), out_path,
                fps=fps, audio_path=audio_path, duration_s=duration_s)
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
    job_dir = os.path.join(apps_dir, slug, ".video", job_id)
    site_context: dict = {}
    ctx_path = os.path.join(job_dir, "site_context.json")
    if os.path.isfile(ctx_path):
        try:
            with open(ctx_path, encoding="utf-8") as f:
                site_context = _json.load(f)
        except Exception:  # noqa: BLE001 - context is best-effort
            site_context = {}
    html = build_composition(plan, shots, site_context=site_context)
    out = os.path.join(job_dir, "out.mp4")
    dur = min(MAX_DURATION_S, composition_duration(plan) or 8.0)
    audio = await _synthesize_narration(
        plan.get("narration_script") or "", voice, os.path.join(job_dir, "narration.wav"))
    await render_html_to_mp4(html, out, fps=fps, duration_s=dur, audio_path=audio)
    return out
