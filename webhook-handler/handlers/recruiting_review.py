"""Pure builders for the Discord recruiting review/select/edit/send UI.

No I/O. custom_id scheme: aiuiout:<action>:<task_id>[:<cid>]. task_id is a UUID
(no colons) so editmodal ids rsplit cleanly into (task_id, cid). Unit-tested in
tests/test_recruiting_review.py.
"""
from __future__ import annotations

from handlers.app_builder_panel import (
    ACTION_ROW, BUTTON, SELECT_MENU, TEXT_INPUT, TEXT_SHORT, TEXT_PARAGRAPH,
    STYLE_SUCCESS, STYLE_SECONDARY, ROBOTIC_CYAN, _button,
)
from handlers.recruiting_labels import labels_for

SEL_PREFIX = "aiuiout:sel:"
EDIT_PREFIX = "aiuiout:edit:"
SEND_PREFIX = "aiuiout:send:"
REFRESH_PREFIX = "aiuiout:refresh:"
EDITMODAL_PREFIX = "aiuiout:editmodal:"
_MAX = 25


def _emailable(candidates: list[dict]) -> list[dict]:
    return [c for c in candidates if (c.get("email") or "").strip()]


def build_review_message(task_id: str, candidates: list[dict], *,
                         role: str = "", location: str = "",
                         kind: str = "hire") -> dict:
    """Overview message: embed list + recipient multi-select (emailable only) +
    edit dropdown (all) + Send/Refresh buttons. ``kind`` ∈ {"hire","reverse"}
    selects engineer- vs company-oriented copy (recruiting_labels.labels_for)."""
    lab = labels_for(kind)
    lines = []
    for c in candidates:
        email = (c.get("email") or "").strip()
        icon = "✅" if (c.get("selected") and email) else ("⚠️" if not email else "⬜")
        lines.append(f"{icon} **{c.get('name', '?')}** — {email or '(no email)'}")
    if kind == "reverse":
        title = f"{lab['found_prefix']} {len(candidates)} companies for {role}"
    else:
        where = role + (f" · {location}" if location else "")
        title = f"{lab['found_prefix']} {len(candidates)} · {where}"
    embed = {
        "title": title[:256],
        "color": ROBOTIC_CYAN,
        "description": ("\n".join(lines) or lab["none_found"])[:4000],
        "footer": {"text": lab["footer"]},
    }
    rows: list[dict] = []
    emailable = _emailable(candidates)[:_MAX]
    if emailable:
        rows.append({"type": ACTION_ROW, "components": [{
            "type": SELECT_MENU, "custom_id": f"{SEL_PREFIX}{task_id}",
            "placeholder": lab["select_placeholder"],
            "min_values": 0, "max_values": len(emailable),
            "options": [{
                "label": (c.get("name") or c["id"])[:100], "value": c["id"],
                "description": c["email"][:100], "default": bool(c.get("selected")),
            } for c in emailable],
        }]})
    rows.append({"type": ACTION_ROW, "components": [{
        "type": SELECT_MENU, "custom_id": f"{EDIT_PREFIX}{task_id}",
        "placeholder": lab["edit_placeholder"],
        "min_values": 1, "max_values": 1,
        "options": [{
            "label": (c.get("name") or c["id"])[:100], "value": c["id"],
            "description": ((c.get("email") or "").strip() or "no email")[:100],
        } for c in candidates[:_MAX]],
    }]})
    selected = sum(1 for c in candidates if c.get("selected") and (c.get("email") or "").strip())
    rows.append({"type": ACTION_ROW, "components": [
        _button(f"{lab['send_button']} ({selected})", f"{SEND_PREFIX}{task_id}", STYLE_SUCCESS),
        _button("♻ Refresh", f"{REFRESH_PREFIX}{task_id}", STYLE_SECONDARY),
    ]})
    return {"embeds": [embed], "components": rows}


def build_sent_message(text: str, sheet_url: str = "", *, kind: str = "hire") -> dict:
    """Final locked message after Send (no components)."""
    body = f"✅ {text}" + (f"\n\U0001f449 {sheet_url}" if sheet_url else "")
    return {"content": body[:2000], "embeds": [], "components": []}


def build_edit_modal(task_id: str, candidate: dict) -> dict:
    """Edit popup prefilled with email/subject/body for one candidate."""
    def _ti(cid, label, style, maxlen, value):
        return {"type": ACTION_ROW, "components": [{
            "type": TEXT_INPUT, "custom_id": cid, "label": label, "style": style,
            "required": False, "max_length": maxlen, "value": (value or "")[:maxlen],
        }]}
    return {
        "title": f"Edit: {candidate.get('name', '')}"[:45],
        "custom_id": f"{EDITMODAL_PREFIX}{task_id}:{candidate['id']}",
        "components": [
            _ti("email", "Email (blank = don't email)", TEXT_SHORT, 200, candidate.get("email")),
            _ti("subject", "Subject", TEXT_SHORT, 200, candidate.get("subject")),
            _ti("body", "Message", TEXT_PARAGRAPH, 4000, candidate.get("body")),
        ],
    }


def is_out_sel(cid: str) -> bool: return cid.startswith(SEL_PREFIX)
def is_out_edit(cid: str) -> bool: return cid.startswith(EDIT_PREFIX)
def is_out_send(cid: str) -> bool: return cid.startswith(SEND_PREFIX)
def is_out_refresh(cid: str) -> bool: return cid.startswith(REFRESH_PREFIX)
def is_out_editmodal(cid: str) -> bool: return cid.startswith(EDITMODAL_PREFIX)
def task_id_from_sel(cid: str) -> str: return cid[len(SEL_PREFIX):]
def task_id_from_edit(cid: str) -> str: return cid[len(EDIT_PREFIX):]
def task_id_from_send(cid: str) -> str: return cid[len(SEND_PREFIX):]
def task_id_from_refresh(cid: str) -> str: return cid[len(REFRESH_PREFIX):]


def ids_from_editmodal(cid: str) -> tuple[str, str]:
    """aiuiout:editmodal:<task_id>:<cid> -> (task_id, cid)."""
    rest = cid[len(EDITMODAL_PREFIX):]
    task_id, _, candidate_id = rest.rpartition(":")
    return task_id, candidate_id
