"""Async client for the video-remotion render service (POST /render)."""
import os
import httpx

_DEFAULT_TIMEOUT = 240.0  # wall-clock cap, mirrors the in-process render cap


async def render_remotion(job_dir: str, *, theme: str, fps: int, width: int,
                          height: int, host: str, title: str,
                          scenes: list[dict], base_url: str | None = None,
                          _transport: httpx.AsyncBaseTransport | None = None) -> str:
    """POST a render request to the video-remotion service and return the output
    mp4 path it wrote. Raises RuntimeError on a non-200 response or an ok:false
    body. base_url defaults to env VIDEO_REMOTION_URL or the compose service name."""
    url = (base_url or os.environ.get("VIDEO_REMOTION_URL",
                                      "http://video-remotion:8090")).rstrip("/") + "/render"
    payload = {"jobDir": job_dir, "theme": theme, "fps": fps, "width": width,
               "height": height, "host": host, "title": title, "scenes": scenes}
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
