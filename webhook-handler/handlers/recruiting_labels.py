"""Direction-aware copy for the recruiting review UI.

Pure, no I/O. labels_for(kind) returns the user-facing strings for either the
"hire" (Find Engineers) or "reverse" (Find Jobs / companies) flow. The "hire"
strings are byte-for-byte the ones hard-coded today, so the existing flow is
unchanged. Imported by handlers/recruiting_review.py (Discord),
handlers/slack_recruiting_review.py (Slack, Phase 3), and used by
handlers/commands.py for fallback/watcher text. Unit-tested in
tests/test_recruiting_labels.py.
"""
from __future__ import annotations

_HIRE = {
    "found_prefix": "\U0001f50d Found",
    "select_placeholder": "Select who to email…",
    "edit_placeholder": "Edit / add email for one…",
    "send_button": "\U0001f4e7 Send to selected",
    "footer": "Pick who to email · ✏️ edit/add-email · then Send",
    "none_found": "No engineers found.",
    "ready": "Engineers ready to review.",
    "pick_one": "Pick at least one engineer first.",
}

_REVERSE = {
    "found_prefix": "Found",
    "select_placeholder": "Select who to apply to…",
    "edit_placeholder": "Edit / add email for one…",
    "send_button": "\U0001f4e7 Send applications",
    "footer": "Pick who to apply to · ✏️ edit/add-email · then Send",
    "none_found": "No companies found.",
    "ready": "Companies ready to review.",
    "pick_one": "Pick at least one company first.",
}


def labels_for(kind: str) -> dict:
    """Copy dict for ``kind`` ∈ {"hire","reverse"}. Unknown/empty kinds fall
    back to hire so callers can pass a raw ``direction`` value safely. Returns a
    fresh dict each call so callers may mutate the result without side effects."""
    return dict(_REVERSE if kind == "reverse" else _HIRE)
