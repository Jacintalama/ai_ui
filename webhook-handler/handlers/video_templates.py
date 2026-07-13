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
            "Click through the site page by page like a guided tour. Introduce each page as it appears and highlight what a visitor can do there.\n"
            "\n"
            "Opening: start on the homepage with a slow, confident push-in. State the site name and its promise in one short line of large, clean type, and hold it just long enough to read comfortably.\n"
            "\n"
            "For every page that follows: announce it with a small kicker label plus one headline that says what the page is FOR, not what it is called. Move the animated cursor deliberately toward the element that leads onward, pause a beat so the eye can catch up, click with a subtle pulse, and let the next page arrive through a smooth transition. While each page is on screen, call out one or two concrete things a visitor can do there, phrased as actions they could take right now.\n"
            "\n"
            "Cursor rules: keep the cursor visible and natural on every screenshot scene, ease it along a gentle curved path, never let it teleport, and time each click so the narration and the motion land together.\n"
            "\n"
            "Type and rhythm: one idea per scene, generous margins, high contrast captions that never cover the region being demonstrated. Keep scenes around three to five seconds and hold the most important screens slightly longer.\n"
            "\n"
            "Ending: land on the strongest page, summarize the journey in a single line, and close with a warm, clear invitation to visit and explore the site."
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
            "A crisp product demo. Present the key features confidently and end with a clear call to action.\n"
            "\n"
            "Opening: cold open on the product itself, no long preamble. One bold headline that names the product and the single outcome it delivers for the user, then move straight into the proof.\n"
            "\n"
            "Feature run: pick the three or four strongest features visible in the screenshots and give each one its own scene. Lead every feature with a short benefit headline, then let the interface prove the claim: zoom or pan into the exact region that matters, quiet down everything around it, and add one tight caption of ten words or fewer. Never list features in the abstract; always demonstrate them on screen.\n"
            "\n"
            "Motion: purposeful and restrained. Slow push-ins on wide shots, quick precise zooms on details, clean directional transitions between features so the story keeps moving forward. No gimmicks, no bouncing text, no clutter.\n"
            "\n"
            "Type and look: modern, minimal, confident. Short labels or big numerals to count the features off, one consistent accent color drawn from the product palette, and everything aligned to a calm grid.\n"
            "\n"
            "Pacing: brisk but readable, roughly three seconds per beat, with one deliberate breather on the hero screen midway through.\n"
            "\n"
            "Ending: recap the top benefits in a single composed frame, then a strong call to action with the product name, held long enough to act on."
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
            "A cinematic showcase with dramatic pacing. Build atmosphere, sweep through the visuals, and land on a memorable closing line.\n"
            "\n"
            "Opening: begin in near darkness. Let the first image fade up slowly beneath a wide, weighty title in elegant type, as if a film is beginning. Give the moment air; do not rush it.\n"
            "\n"
            "Journey: treat each screenshot as a scene in a short film. Sweep across the imagery with slow, continuous camera moves: long push-ins, gentle drifts, graceful reveals. Alternate scale for drama, one vast wide establishing shot, then an intimate close detail. Shape the frame with light and shadow: soft vignettes, subtle gradients, and a restrained color grade that makes every visual feel rich and deliberate.\n"
            "\n"
            "Text: sparse and powerful. At most one short evocative line per scene, entering with a slow fade or a letter-spaced reveal, never with playful motion. The silence between lines is part of the rhythm.\n"
            "\n"
            "Transitions: long crossfades between scenes and cinematic dips to black at chapter breaks. Nothing abrupt, nothing decorative.\n"
            "\n"
            "Pacing: unhurried and rising. Start slow, let the middle build momentum scene by scene, then hold the single strongest visual a little longer than feels safe.\n"
            "\n"
            "Ending: cut to a quiet final frame, one memorable closing line in large type, a beat of stillness, then fade to black completely."
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
            "A fast, punchy social clip. Short energetic lines, quick cuts, a hook in the first seconds, and a call to action at the end.\n"
            "\n"
            "Hook: the first two seconds must stop the scroll. Open on the boldest visual available with a huge one-line hook in heavy type, a question or a claim that demands the next beat.\n"
            "\n"
            "Body: rapid-fire beats of one to two seconds each. Every beat pairs one screenshot moment with one short punchy line of five to eight words. Cut hard on the rhythm: snap zooms, quick pushes, tight crops on the most interesting part of each screen instead of polite wide shots. Let the energy come from the editing, not from decoration, and make each line answer or escalate the one before it.\n"
            "\n"
            "Type: oversized, high contrast, safe for small screens and silent viewing. Words may pop in one at a time to hit the beat, but every line stays instantly readable. Emphasize one key word per line with the accent color.\n"
            "\n"
            "Look: bright, saturated, confident. Keep the composition clean even at speed; energy is not the same as mess.\n"
            "\n"
            "Pacing: relentless but controlled. If a beat cannot justify its second on screen, cut it.\n"
            "\n"
            "Ending: slam into the call to action within the final two seconds, one imperative line plus the site name, big and centered, no slow fade."
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
    # _fetched_at == 0.0 is the "never fetched" sentinel — always stale,
    # regardless of the monotonic clock's absolute value (on a short uptime
    # `monotonic() - 0` can be < TTL and wrongly read as fresh).
    if not _fetched_at:
        return False
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
