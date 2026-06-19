"""Pure Block Kit builders for the Slack recruiting review/select/edit/send UI.

Block Kit analog of handlers/recruiting_review.py (Discord). No I/O. The
custom-id scheme is identical (aiuiout:sel|edit|send|refresh|editmodal:<task_id>
[:<cid>]) so the Slack interaction router and the platform/direction-aware
command router methods key off the same ids as Discord. Direction-aware copy
comes from recruiting_labels.labels_for(kind). Unit-tested in
tests/test_slack_recruiting_review.py.
"""
from __future__ import annotations

import json

from handlers.slack_app_builder_panel import _button
from handlers.recruiting_labels import labels_for

__all__ = [
    "SEL_PREFIX", "EDIT_PREFIX", "SEND_PREFIX", "REFRESH_PREFIX", "EDITMODAL_PREFIX",
    "build_review_message", "build_edit_modal_view", "build_sent_message",
    "edit_fields_from_view", "ids_from_editmodal", "response_url_from_meta",
    "sample_edit_state",
]

SEL_PREFIX = "aiuiout:sel:"
EDIT_PREFIX = "aiuiout:edit:"
SEND_PREFIX = "aiuiout:send:"
REFRESH_PREFIX = "aiuiout:refresh:"
EDITMODAL_PREFIX = "aiuiout:editmodal:"

_MAX = 25
_OPT_TEXT_MAX = 75      # Slack select-option text hard limit
_PLACEHOLDER_MAX = 150  # Slack placeholder hard limit
_SECTION_MAX = 2900     # keep section text under Slack's 3000-char cap
_TITLE_MAX = 24         # Slack modal title hard limit

# Edit-modal input block/action ids.
_EMAIL_BLOCK_ID = "edit_email"
_EMAIL_INPUT_ID = "edit_email_input"
_SUBJECT_BLOCK_ID = "edit_subject"
_SUBJECT_INPUT_ID = "edit_subject_input"
_BODY_BLOCK_ID = "edit_body"
_BODY_INPUT_ID = "edit_body_input"


def _emailable(candidates: list[dict]) -> list[dict]:
    return [c for c in candidates if (c.get("email") or "").strip()]


def _opt(c: dict) -> dict:
    """A select option for one candidate (value = candidate id)."""
    label = (c.get("name") or c.get("id") or "?")[:_OPT_TEXT_MAX]
    return {"text": {"type": "plain_text", "text": label}, "value": c["id"]}


def build_review_message(task_id: str, candidates: list[dict], *,
                         role: str = "", location: str = "",
                         kind: str = "hire") -> dict:
    """Block Kit review overview. Returns {"text", "blocks"}.

    Mirrors recruiting_review.build_review_message (same signature, same id
    scheme) but renders Block Kit instead of an embed + components:
      - a header section ("<found_prefix> N · role · location"),
      - a section listing every candidate (status icon + name + email),
      - a multi_static_select of EMAILABLE candidates only (aiuiout:sel:<task_id>),
      - a static_select to edit/add-email for ONE candidate (aiuiout:edit:<task_id>),
      - Send / Refresh buttons (aiuiout:send|refresh:<task_id>),
      - a context footer.
    Company-oriented copy for kind="reverse" comes from labels_for(kind)."""
    lbl = labels_for(kind)
    n = len(candidates)
    # Header parity with Discord recruiting_review.build_review_message: derive the
    # title from labels_for(kind)["found_prefix"] + role/location. found_prefix carries
    # the emoji policy (no leading magnifying-glass for the reverse kind).
    if kind == "reverse":
        header = f"{lbl['found_prefix']} {n} companies for {role}"
    else:
        where = role + (f" · {location}" if location else "")
        header = f"{lbl['found_prefix']} {n} · {where}"

    lines = []
    for c in candidates:
        email = (c.get("email") or "").strip()
        icon = "✅" if (c.get("selected") and email) else ("⚠️" if not email else "⬜")
        lines.append(f"{icon} *{c.get('name', '?')}* — {email or '(no email)'}")
    body = ("\n".join(lines) or lbl["none_found"])[:_SECTION_MAX]

    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header[:_SECTION_MAX]}},
        {"type": "section", "text": {"type": "mrkdwn", "text": body}},
    ]

    emailable = _emailable(candidates)[:_MAX]
    if emailable:
        options = [_opt(c) for c in emailable]
        initial = [o for o, c in zip(options, emailable) if c.get("selected")]
        sel: dict = {
            "type": "multi_static_select",
            "action_id": f"{SEL_PREFIX}{task_id}",
            "placeholder": {"type": "plain_text",
                            "text": lbl["select_placeholder"][:_PLACEHOLDER_MAX]},
            "options": options,
        }
        if initial:
            sel["initial_options"] = initial
        blocks.append({"type": "actions", "elements": [sel]})

    if candidates:
        blocks.append({"type": "actions", "elements": [{
            "type": "static_select",
            "action_id": f"{EDIT_PREFIX}{task_id}",
            "placeholder": {"type": "plain_text",
                            "text": lbl["edit_placeholder"][:_PLACEHOLDER_MAX]},
            "options": [_opt(c) for c in candidates[:_MAX]],
        }]})

    selected = sum(1 for c in candidates
                   if c.get("selected") and (c.get("email") or "").strip())
    blocks.append({"type": "actions", "elements": [
        _button(f"{lbl['send_button']} ({selected})", f"{SEND_PREFIX}{task_id}", primary=True),
        _button("Refresh", f"{REFRESH_PREFIX}{task_id}"),
    ]})
    blocks.append({"type": "context",
                   "elements": [{"type": "mrkdwn", "text": lbl["footer"]}]})

    return {"text": header[:_SECTION_MAX], "blocks": blocks}


def build_edit_modal_view(task_id: str, candidate: dict, *,
                          response_url: str = "", kind: str = "hire") -> dict:
    """Placeholder — implemented in a later task."""
    raise NotImplementedError


def build_sent_message(task_id: str, sent: list[dict], *,
                       role: str = "", location: str = "",
                       kind: str = "hire") -> dict:
    """Placeholder — implemented in a later task."""
    raise NotImplementedError


def edit_fields_from_view(view: dict) -> dict:
    """Placeholder — implemented in a later task."""
    raise NotImplementedError


def ids_from_editmodal(action_id: str) -> tuple[str, str]:
    """Placeholder — implemented in a later task."""
    raise NotImplementedError


def response_url_from_meta(view: dict) -> str:
    """Placeholder — implemented in a later task."""
    raise NotImplementedError


def sample_edit_state(task_id: str, cid: str) -> dict:
    """Placeholder — implemented in a later task."""
    raise NotImplementedError
