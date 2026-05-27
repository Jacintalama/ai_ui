"""Format scheduled-task run results for Discord using the AIUI brand.

AIUI palette (Cyan Circuit): primary #22D3EE, base #0B1221, text #E6F1FF.
Embeds use the single cyan accent — run status is conveyed by the title emoji
and the STATUS field, not by colour, so the brand stays to three colours.
"""
from datetime import datetime, timedelta, timezone

AIUI_CYAN = 0x22D3EE  # AIUI primary brand colour
_MANILA = timezone(timedelta(hours=8))  # Philippine time (PHT) — no DST

# status -> (title emoji, STATUS field label)
_STATUS = {
    "completed": ("✅", "COMPLETE"),
    "skipped": ("⏭️", "SKIPPED"),
}


def _status_parts(status: str) -> tuple[str, str]:
    return _STATUS.get(status, ("⚠️", (status or "FAILED").upper()))


def build_schedule_embed(name: str, status: str, result: str) -> dict:
    """Build the AIUI-branded Discord embed for a finished scheduled run.

    Anything that isn't 'completed'/'skipped' is treated as a failure/warning.
    The agent's output is shown as clean prose in the description.
    """
    emoji, label = _status_parts(status)
    body = (result or "").strip() or "_(no output)_"
    manila = datetime.now(_MANILA).strftime("%Y-%m-%d %H:%M GMT+8")
    return {
        "author": {"name": "⬢ AIUI · Autonomous Agent"},
        "title": f"{emoji} {name}".strip()[:256],
        "description": body[:4000],
        "color": AIUI_CYAN,
        "fields": [
            {"name": "STATUS", "value": label, "inline": True},
            {"name": "TIME", "value": manila, "inline": True},
        ],
        "footer": {"text": "AIUI"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def short_summary(name: str, status: str) -> str:
    """One-line notification fallback shown as the message content."""
    emoji, _ = _status_parts(status)
    return f"{emoji} {name}".strip()[:256]
