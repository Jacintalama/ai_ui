"""Cached copy of the tasks service's video template registry.

Slack/Discord interactions must answer within ~3 seconds, so panels read a
module-level cache synchronously and spawn refresh_templates() in the
background. FALLBACK_TEMPLATES mirrors the server registry and covers the
window before the first successful refresh (and outages).
"""
import logging
import time

logger = logging.getLogger(__name__)

FALLBACK_TEMPLATES: list[dict] = [
    {
        "key": "walkthrough",
        "emoji": "\U0001f5b1️",
        "name": "Website Walkthrough",
        "badge": "Recommended",
        "desc": "A cursor clicks through your pages like a guided tour.",
        "style": "clean_product_demo",
        "remotion": True,
        "prompt": (
            "Click through the site page by page like a guided tour. "
            "Introduce each page as it appears and highlight what a "
            "visitor can do there."
        ),
    },
    {
        "key": "product",
        "emoji": "\U0001f4e6",
        "name": "Product Demo",
        "desc": "Crisp and confident. Features front and center.",
        "style": "clean_product_demo",
        "remotion": True,
        "prompt": (
            "A crisp product demo. Present the key features confidently "
            "and end with a clear call to action."
        ),
    },
    {
        "key": "cinematic",
        "emoji": "\U0001f3ac",
        "name": "Cinematic Showcase",
        "desc": "Dramatic pacing, sweeping visuals, big finish.",
        "style": "cinematic",
        "remotion": True,
        "prompt": (
            "A cinematic showcase with dramatic pacing. Build atmosphere, "
            "sweep through the visuals, and land on a memorable closing line."
        ),
    },
    {
        "key": "social",
        "emoji": "⚡",
        "name": "Snappy Social",
        "desc": "Fast cuts and punchy lines, made for feeds.",
        "style": "snappy_social",
        "remotion": True,
        "prompt": (
            "A fast, punchy social clip. Short energetic lines, quick cuts, "
            "a hook in the first seconds, and a call to action at the end."
        ),
    },
]

DEFAULT_TEMPLATE_KEY = "walkthrough"
_TTL_SECONDS = 600.0

_cache: list[dict] = list(FALLBACK_TEMPLATES)
_fetched_at: float = 0.0


def cached_templates() -> list[dict]:
    """The current template list - never blocks, never empty."""
    return [dict(t) for t in _cache]


def get_template(key: str) -> dict | None:
    for t in _cache:
        if t.get("key") == key:
            return dict(t)
    return None


def template_prompts() -> set[str]:
    """Known template prompts (cache + fallback) - detects unedited prompts."""
    return ({t.get("prompt", "") for t in _cache}
            | {t["prompt"] for t in FALLBACK_TEMPLATES}) - {""}


def cache_is_fresh(now: float | None = None) -> bool:
    return ((now if now is not None else time.monotonic()) - _fetched_at) < _TTL_SECONDS


async def refresh_templates(tasks_client) -> bool:
    """Pull the registry from the tasks service. True on success; on any
    failure the previous cache (or fallback) stays in place."""
    global _cache, _fetched_at
    try:
        data = await tasks_client.get_video_templates()
        templates = [t for t in (data.get("templates") or []) if t.get("key")]
        if templates:
            _cache = templates
            _fetched_at = time.monotonic()
            return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("video template refresh failed: %s", exc)
    return False
