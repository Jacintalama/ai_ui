"""Deterministic Remotion plan for the Default flow: turn a captured site walk
into an intro card -> clicked-page scenes -> outro card, using the real click
coordinates so the smart cursor lands on the element that advanced each page."""
from urllib.parse import urlparse

from video_plan import sanitize_anim_clicks

_MOTIONS = ["zoom-in", "fade", "pan-up", "zoom-out"]
_CARD_S = 2.6
_PAGE_S = 4.0
_SEP = (" | ", " - ", " \u2013 ", " :: ", " \u00b7 ")


def _clean_headline(title: str) -> str:
    text = " ".join((title or "").split())
    for sep in _SEP:
        i = text.find(sep)
        if i > 0:
            text = text[:i]
            break
    return text.strip()[:48]


def _subtext(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return path.split("/")[0].replace("-", " ").title() if path else "Home"


def build_walk_plan(
    walk: list[dict],
    screenshot_names: list[str],
    site_context: dict,
    *,
    fps: int = 24,
    max_duration_s: float = 40.0,
) -> dict:
    """Intro card + one screenshot scene per walked page (with its real click) +
    outro card. Drops trailing page scenes so the total fits max_duration_s."""
    host = (site_context or {}).get("host") or "your site"
    # How many page scenes fit alongside the two cards.
    budget = max_duration_s - 2 * _CARD_S
    max_pages = max(0, int(budget // _PAGE_S))
    pairs = list(zip(walk, screenshot_names))[:max_pages]

    scenes = [{
        "kind": "intro", "headline": host, "subtext": "A quick tour",
        "motion": "fade", "duration_s": _CARD_S,
    }]
    for i, (w, name) in enumerate(pairs):
        scene = {
            "kind": "screenshot",
            "screenshot": name,
            "headline": _clean_headline(w.get("title", "")) or host,
            "subtext": _subtext(w.get("url", "")),
            "motion": _MOTIONS[i % len(_MOTIONS)],
            "duration_s": _PAGE_S,
        }
        click = w.get("click")
        if isinstance(click, dict) and "x" in click and "y" in click:
            scene["click"] = {"x": click["x"], "y": click["y"], "label": click.get("label", "")}
        scenes.append(scene)
    scenes.append({
        "kind": "outro", "headline": host, "subtext": "Watch anytime",
        "motion": "fade", "duration_s": _CARD_S,
    })
    return sanitize_anim_clicks({"scenes": scenes})
