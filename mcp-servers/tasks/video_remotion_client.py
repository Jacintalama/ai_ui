"""Async client for the video-remotion render service (POST /render)."""
import os
import httpx

_DEFAULT_TIMEOUT = 240.0  # wall-clock cap, mirrors the in-process render cap
# AI-authored compositions render slower (bundle + heavier scenes) and can run
# tens of seconds long; give them a much larger budget on the small box.
_AI_RENDER_TIMEOUT = 600.0


async def render_remotion(job_dir: str, *, theme: str, fps: int, width: int,
                          height: int, host: str, title: str,
                          scenes: list[dict],
                          animationPreset: str = "cursor_click",
                          base_url: str | None = None,
                          _transport: httpx.AsyncBaseTransport | None = None) -> str:
    """POST a render request to the video-remotion service and return the output
    mp4 path it wrote. Raises RuntimeError on a non-200 response or an ok:false
    body. base_url defaults to env VIDEO_REMOTION_URL or the compose service name."""
    url = (base_url or os.environ.get("VIDEO_REMOTION_URL",
                                      "http://video-remotion:8090")).rstrip("/") + "/render"
    payload = {"jobDir": job_dir, "theme": theme, "fps": fps, "width": width,
               "height": height, "host": host, "title": title, "scenes": scenes,
               "animationPreset": animationPreset}
    kwargs: dict = {"timeout": _DEFAULT_TIMEOUT}
    if _transport is not None:
        kwargs["transport"] = _transport
    async with httpx.AsyncClient(**kwargs) as client:
        try:
            resp = await client.post(url, json=payload)
        except httpx.HTTPError as e:
            raise RuntimeError(f"remotion render request failed: {e}") from e
    if resp.status_code != 200:
        raise RuntimeError(
            f"remotion render returned {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if not data.get("ok") or not data.get("outPath"):
        raise RuntimeError(f"remotion render not ok: {str(data)[:300]}")
    return data["outPath"]


async def render_ai(job_dir: str, source: str, assets: list[str] | None = None, *,
                    base_url: str | None = None,
                    _transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """POST an AI-authored composition to the sandbox (/render-ai) and return the
    STRUCTURED result dict {ok, outPath|error, stage} — NOT raising on a gate
    failure, so the codegen repair loop can read the error and regenerate. Network
    failures are returned as {ok: False, stage: "render", error: ...}."""
    url = (base_url or os.environ.get("VIDEO_REMOTION_URL",
                                      "http://video-remotion:8090")).rstrip("/") + "/render-ai"
    payload = {"jobDir": job_dir, "source": source, "assets": assets or []}
    kwargs: dict = {"timeout": _AI_RENDER_TIMEOUT}
    if _transport is not None:
        kwargs["transport"] = _transport
    async with httpx.AsyncClient(**kwargs) as client:
        try:
            resp = await client.post(url, json=payload)
        except httpx.HTTPError as e:
            return {"ok": False, "stage": "render", "error": f"render-ai request failed: {e}"}
    try:
        return resp.json()
    except Exception:  # noqa: BLE001 - a non-JSON body is still a failure we can feed back
        return {"ok": False, "stage": "render",
                "error": f"render-ai returned {resp.status_code}: {resp.text[:300]}"}
