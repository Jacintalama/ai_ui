"""Best-effort detection of which connectors a scheduled-task prompt will need.

Keyword-based and intentionally simple — the bot uses it to prompt the user to
connect Gmail/Drive before saving a schedule that clearly needs them. False
negatives just mean the agent degrades gracefully at run time; false positives
just mean an unnecessary connect prompt, so err toward precision.
"""

_GMAIL = ("email", "inbox", "gmail")
_DRIVE = ("drive", "google doc", "spreadsheet")
_WEB = ("scrape", "website", "webpage", "web page", "http://", "https://")


def detect(text: str) -> set[str]:
    """Return the set of connector names ({"gmail","drive","web"}) the text implies."""
    t = (text or "").lower()
    found: set[str] = set()
    if any(k in t for k in _GMAIL):
        found.add("gmail")
    if any(k in t for k in _DRIVE):
        found.add("drive")
    if any(k in t for k in _WEB):
        found.add("web")
    return found
