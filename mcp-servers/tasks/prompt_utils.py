"""Recover the user's original prompt from a stored task description.

``create_task`` wraps a build prompt as ``"<rules>\n\nUSER REQUEST:\n<prompt>"``;
``enhance`` stores ``"Enhance apps/<slug>/: <prompt>"``. Anything else is already
clean.

The structural marker is matched at its FIRST occurrence. The rules block that
precedes it is server-controlled and never contains the marker, so a user whose
own text happens to contain "USER REQUEST:" is preserved intact (unlike the old
client-side ``lastIndexOf`` strip, which mis-sliced such prompts).
"""
from __future__ import annotations

_MARKER = "\n\nUSER REQUEST:\n"


def clean_user_prompt(description: str | None) -> str:
    """Return just the text the user typed, stripped of any server wrapper."""
    text = (description or "").strip()
    if not text:
        return ""
    idx = text.find(_MARKER)
    if idx != -1:
        return text[idx + len(_MARKER):].strip()
    if text.startswith("Enhance apps/"):
        _, sep, rest = text.partition(": ")
        if sep:
            return rest.strip() or text
    return text
