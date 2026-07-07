"""Server-side registry of the video template presets.

Single source of truth for every surface: the web Video Studio grid, the
Slack and Discord panels, cron video schedules, and App Builder. Adding a
template here makes it appear everywhere (the web grid additionally expects
a preview clip at static/tpl-previews/<key>.mp4). No I/O - pure data.
"""

VIDEO_TEMPLATES: list[dict] = [
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


def template_catalog() -> list[dict]:
    """Picker payload for GET /api/video-jobs/templates (returns copies)."""
    return [dict(t) for t in VIDEO_TEMPLATES]


def get_template(key: str) -> dict | None:
    """The template with this key, as a copy. None when unknown/empty."""
    for t in VIDEO_TEMPLATES:
        if t["key"] == key:
            return dict(t)
    return None


def template_prompts() -> set[str]:
    """All template prompts - used to detect a prompt the user has not edited."""
    return {t["prompt"] for t in VIDEO_TEMPLATES}
