"""Pure builders for the Discord App Builder channel panel and modal.

No I/O. Imported by the interaction handler (handlers/discord_commands.py) and
the one-shot setup script (scripts/setup_app_builder_channel.py); unit tested in
tests/test_app_builder_panel.py.
"""
from __future__ import annotations

# Discord component types
ACTION_ROW = 1
BUTTON = 2
TEXT_INPUT = 4

# Discord button styles
STYLE_PRIMARY = 1    # blurple ("blue")
STYLE_SECONDARY = 2  # grey
STYLE_SUCCESS = 3    # green
STYLE_LINK = 5       # link button (opens a URL; carries `url`, not custom_id)
STYLE_DANGER = 4     # red (destructive action, e.g. Unpublish)

# Text input styles
TEXT_SHORT = 1
TEXT_PARAGRAPH = 2

# custom_id schemes
TEMPLATE_PREFIX = "aiuibuild:tpl:"   # button -> aiuibuild:tpl:<key>  ("" = Blank)
BUILD_PREFIX = "aiuibuild:build:"    # modal  -> aiuibuild:build:<key>
DESCRIPTION_INPUT_ID = "description"

_MAX_PER_ROW = 5
_MAX_ROWS = 5
_MAX_BUTTONS = _MAX_PER_ROW * _MAX_ROWS  # 25

PANEL_CONTENT = (
    "\U0001f680 **AIUI App Builder**\n"
    "Pick a template and I'll open a **private space** just for you to build, "
    "preview, and publish your app — only you and the bot see it. Or hit "
    "**Blank** to start from scratch."
)


def _button(label: str, custom_id: str, style: int) -> dict:
    return {"type": BUTTON, "style": style, "label": label[:80], "custom_id": custom_id}


def build_panel_payload(templates: list[dict]) -> dict:
    """Pinned panel message: one green/blue button per template plus a grey Blank
    button, laid out 5 per row. Templates beyond the 24-button budget (room left
    for Blank) are dropped — the slash command still reaches them."""
    buttons: list[dict] = []
    for t in templates[: _MAX_BUTTONS - 1]:
        key = t.get("key")
        if not key:
            continue  # tolerate a malformed row rather than crash
        emoji = (t.get("emoji") or "").strip()
        label = t.get("label", key)
        text = f"{emoji} {label}".strip()
        style = STYLE_SUCCESS if len(buttons) % 2 == 0 else STYLE_PRIMARY
        buttons.append(_button(text, f"{TEMPLATE_PREFIX}{key}", style))
    buttons.append(_button("⬜ Blank", TEMPLATE_PREFIX, STYLE_SECONDARY))

    rows: list[dict] = []
    for start in range(0, len(buttons), _MAX_PER_ROW):
        rows.append({"type": ACTION_ROW, "components": buttons[start : start + _MAX_PER_ROW]})
    rows = rows[:_MAX_ROWS]
    return {"content": PANEL_CONTENT, "components": rows}


def build_modal_payload(template_key: str | None, template_label: str | None = None) -> dict:
    """Type-9 MODAL `data`: a single paragraph 'Describe your app' field. The
    custom_id carries the template key so the submit handler knows what to build."""
    key = template_key or ""
    what = template_label or template_key or "app"
    return {
        "title": f"Build: {what}"[:45],
        "custom_id": f"{BUILD_PREFIX}{key}",
        "components": [
            {
                "type": ACTION_ROW,
                "components": [
                    {
                        "type": TEXT_INPUT,
                        "custom_id": DESCRIPTION_INPUT_ID,
                        "label": "Describe your app",
                        "style": TEXT_PARAGRAPH,
                        "required": True,
                        "max_length": 4000,
                        "placeholder": "e.g. a portfolio site for Maya, a UX designer",
                    }
                ],
            }
        ],
    }


def is_panel_button(custom_id: str) -> bool:
    return custom_id.startswith(TEMPLATE_PREFIX)


def is_panel_modal(custom_id: str) -> bool:
    return custom_id.startswith(BUILD_PREFIX)


def template_key_from_button(custom_id: str) -> str | None:
    """Button custom_id -> template key. Bare prefix (Blank) -> None."""
    if not is_panel_button(custom_id):
        raise ValueError(f"not a panel button custom_id: {custom_id!r}")
    return custom_id[len(TEMPLATE_PREFIX):] or None


def template_key_from_modal(custom_id: str) -> str | None:
    """Modal custom_id -> template key. Bare prefix -> None."""
    if not is_panel_modal(custom_id):
        raise ValueError(f"not a panel modal custom_id: {custom_id!r}")
    return custom_id[len(BUILD_PREFIX):] or None


PUBLISH_PREFIX = "aiuibuild:publish:"  # ready-msg button -> aiuibuild:publish:<slug>
ENHANCE_PREFIX = "aiuibuild:enhance:"
UNPUBLISH_PREFIX = "aiuibuild:unpublish:"
ENHANCE_MODAL_PREFIX = "aiuibuild:enhancemodal:"


def build_ready_components(slug: str, preview_url: str, *, owner: str) -> list[dict]:
    """Action row for the build-ready message: green Publish + blurple Enhance,
    plus an 'Open preview' link button, plus a 'Visual edit' link button that
    deep-links into the tasks service editor with a signed token."""
    from config import settings  # local import — avoid top-level cycle
    from handlers.visual_edit_token import sign_edit_token

    buttons: list[dict] = [
        _button("\U0001f7e2 Publish", f"{PUBLISH_PREFIX}{slug}", STYLE_SUCCESS),
        _button("✏️ Enhance", f"{ENHANCE_PREFIX}{slug}", STYLE_PRIMARY),
    ]
    if preview_url:
        buttons.append({"type": BUTTON, "style": STYLE_LINK,
                        "label": "\U0001f517 Open preview", "url": preview_url})

    token = sign_edit_token(slug, owner)
    edit_url = (
        f"{settings.tasks_public_url.rstrip('/')}/tasks/edit/{slug}?token={token}"
    )
    buttons.append({"type": BUTTON, "style": STYLE_LINK,
                    "label": "Visual edit", "url": edit_url})
    return [{"type": ACTION_ROW, "components": buttons}]


def is_publish_button(custom_id: str) -> bool:
    return custom_id.startswith(PUBLISH_PREFIX)


def slug_from_publish_button(custom_id: str) -> str:
    """Publish-button custom_id -> slug. Raises ValueError if not a publish id
    or if the slug portion is empty."""
    if not is_publish_button(custom_id):
        raise ValueError(f"not a publish button custom_id: {custom_id!r}")
    slug = custom_id[len(PUBLISH_PREFIX):]
    if not slug:
        raise ValueError(f"publish button custom_id has no slug: {custom_id!r}")
    return slug


def build_published_components(slug: str, public_url: str = "") -> list[dict]:
    """Buttons on the 'Published!' message: blurple Enhance + red Unpublish,
    plus an 'Open live' link button."""
    buttons: list[dict] = [
        _button("✏️ Enhance", f"{ENHANCE_PREFIX}{slug}", STYLE_PRIMARY),
        _button("\U0001f50c Unpublish", f"{UNPUBLISH_PREFIX}{slug}", STYLE_DANGER),
    ]
    if public_url:
        buttons.append({"type": BUTTON, "style": STYLE_LINK,
                        "label": "\U0001f517 Open live", "url": public_url})
    return [{"type": ACTION_ROW, "components": buttons}]


def build_enhance_modal(slug: str) -> dict:
    """Type-9 MODAL data: a paragraph 'What do you want to change?' field."""
    return {
        "title": "Enhance your app"[:45],
        "custom_id": f"{ENHANCE_MODAL_PREFIX}{slug}",
        "components": [{
            "type": ACTION_ROW,
            "components": [{
                "type": TEXT_INPUT,
                "custom_id": "change",
                "label": "What do you want to change?",
                "style": TEXT_PARAGRAPH,
                "required": True,
                "max_length": 2000,
                "placeholder": "e.g. make the header green and add an About section",
            }],
        }],
    }


def _slug_after(custom_id: str, prefix: str) -> str:
    if not custom_id.startswith(prefix):
        raise ValueError(f"not a {prefix!r} custom_id: {custom_id!r}")
    slug = custom_id[len(prefix):]
    if not slug:
        raise ValueError(f"{prefix!r} custom_id has no slug: {custom_id!r}")
    return slug


def is_enhance_button(custom_id: str) -> bool:
    return custom_id.startswith(ENHANCE_PREFIX)


def slug_from_enhance_button(custom_id: str) -> str:
    return _slug_after(custom_id, ENHANCE_PREFIX)


def is_unpublish_button(custom_id: str) -> bool:
    return custom_id.startswith(UNPUBLISH_PREFIX)


def slug_from_unpublish_button(custom_id: str) -> str:
    return _slug_after(custom_id, UNPUBLISH_PREFIX)


def is_enhance_modal(custom_id: str) -> bool:
    return custom_id.startswith(ENHANCE_MODAL_PREFIX)


def slug_from_enhance_modal(custom_id: str) -> str:
    return _slug_after(custom_id, ENHANCE_MODAL_PREFIX)


# --- Selectable "Your apps" list: dropdown + per-project menu ---
SELECT_MENU = 3  # Discord string-select component type

APP_SELECT_ID = "aiuibuild:appselect"  # the dropdown's custom_id (exact match)
STATUS_PREFIX = "aiuibuild:status:"     # status button -> aiuibuild:status:<slug>
_MAX_SELECT_OPTIONS = 25                 # Discord hard limit


def is_app_select(custom_id: str) -> bool:
    return custom_id == APP_SELECT_ID


def is_status_button(custom_id: str) -> bool:
    return custom_id.startswith(STATUS_PREFIX)


def slug_from_status_button(custom_id: str) -> str:
    return _slug_after(custom_id, STATUS_PREFIX)


def build_apps_select_components(projects: list[dict]) -> list[dict]:
    """One action row holding a string select of the user's apps. value=slug,
    description shows publish state. Caps at 25 options (Discord max). Caller must
    NOT pass an empty list (Discord rejects a 0-option select)."""
    options: list[dict] = []
    for p in projects[:_MAX_SELECT_OPTIONS]:
        slug = p.get("slug")
        if not slug:
            continue  # tolerate a malformed row rather than crash
        published = bool(p.get("public_url"))
        options.append({
            "label": (p.get("name") or slug)[:100],
            "value": slug[:100],
            "description": ("published" if published else "not published")[:100],
        })
    select = {
        "type": SELECT_MENU,
        "custom_id": APP_SELECT_ID,
        "placeholder": "Select an app to manage…",
        "min_values": 1,
        "max_values": 1,
        "options": options,
    }
    return [{"type": ACTION_ROW, "components": [select]}]


def build_project_menu_components(
    slug: str, *, published: bool, public_url: str = "", preview_url: str = "",
) -> list[dict]:
    """State-aware action row for a selected app:
    Enhance + (Publish | Unpublish) + an Open link (only when its URL is set) + Status.
    Max 5 buttons per row; we emit at most 4."""
    buttons: list[dict] = [
        _button("✏️ Enhance", f"{ENHANCE_PREFIX}{slug}", STYLE_PRIMARY),
    ]
    if published:
        buttons.append(_button("\U0001f50c Unpublish", f"{UNPUBLISH_PREFIX}{slug}", STYLE_DANGER))
        if public_url:
            buttons.append({"type": BUTTON, "style": STYLE_LINK,
                            "label": "\U0001f517 Open live", "url": public_url})
    else:
        buttons.append(_button("\U0001f7e2 Publish", f"{PUBLISH_PREFIX}{slug}", STYLE_SUCCESS))
        if preview_url:
            buttons.append({"type": BUTTON, "style": STYLE_LINK,
                            "label": "\U0001f517 Open preview", "url": preview_url})
    buttons.append(_button("ℹ️ Status", f"{STATUS_PREFIX}{slug}", STYLE_SECONDARY))
    return [{"type": ACTION_ROW, "components": buttons}]


# ============================================================================
# RECOVERY STUBS — lost v2 polish for the scheduler / connections panels
#
# These symbols were written in earlier session work and deployed live to the
# VPS production webhook-handler container, but were lost from local working
# tree during a subagent's destructive filesystem operation on 2026-05-28.
# Production VPS (Hetzner) IP is currently blocked at Hetzner's edge pending
# an abuse-team unblock request, so the canonical copies in
# `webhook-handler:/app/handlers/app_builder_panel.py` are unreachable.
#
# These STUBS exist solely so that:
#   1. The module imports cleanly (downstream code/tests don't ImportError).
#   2. The 9 tests that exercise this surface area FAIL with assertion errors
#      (not collection errors), making the regression obvious.
#
# DO NOT treat any function below as finished code. After Hetzner unblocks,
# replace this whole block by `docker cp` of the live VPS file, then re-run
# the 9 currently-broken tests to confirm restoration.
#
# Tracking: see commit history around 97e450869 / 2b0d3c28c.
# ============================================================================

# --- schedule create flow ---
SCHED_NEW_ID = "aiuisched:new"
SCHED_LIST_ID = "aiuisched:list"
SCHED_OPEN_ID = "aiuisched:open"
SCHED_SELECT_ID = "aiuisched:select"
SCHED_MODAL_ID = "aiuisched:modal"
SCHED_WHAT_INPUT = "what"
SCHED_WHEN_INPUT = "when"
SCHED_CONFIRM_PREFIX = "aiuisched:confirm:"
SCHED_CANCEL_PREFIX = "aiuisched:cancel:"
SCHED_RUN_PREFIX = "aiuisched:run:"
SCHED_PAUSE_PREFIX = "aiuisched:pause:"
SCHED_RESUME_PREFIX = "aiuisched:resume:"
SCHED_DEL_PREFIX = "aiuisched:del:"
SCHED_EDIT_PREFIX = "aiuisched:edit:"
SCHED_EDITMODAL_PREFIX = "aiuisched:editmodal:"
SCHED_RETRYMODAL_PREFIX = "aiuisched:retrymodal:"
CONNECT_RESUME_PREFIX = "aiuisched:connectresume:"

# --- account linking ---
LINK_EMAIL_INPUT = "email"
LINK_START_ID = "aiuilink:start"
LINK_MODAL_ID = "aiuilink:modal"
LINK_APPROVE_PREFIX = "aiuilink:approve:"
LINK_REJECT_PREFIX = "aiuilink:reject:"

# --- connections panel ---
CONN_OPEN_ID = "aiuiconn:open"
CONN_REFRESH_ID = "aiuiconn:refresh"
CONN_DISCONNECT_PREFIX = "aiuiconn:disconnect:"
CONN_DISCONNECT_CONFIRM_PREFIX = "aiuiconn:dccfm:"
CONN_DISCONNECT_CANCEL_ID = "aiuiconn:dccx"

# --- template select ---
TEMPLATE_SELECT_ID = "aiuibuild:tplselect"


def _stub_id_match(prefix_or_id: str, custom_id: str) -> bool:
    """Predicate stub: exact-match for IDs, startswith for prefixes."""
    if prefix_or_id.endswith(":"):
        return custom_id.startswith(prefix_or_id)
    return custom_id == prefix_or_id


def _stub_extract(custom_id: str, prefix: str) -> str:
    if not custom_id.startswith(prefix):
        raise ValueError(f"not a {prefix} custom_id: {custom_id!r}")
    return custom_id[len(prefix):]


# --- predicates / extractors (stubbed) ---

def is_sched_new(custom_id: str) -> bool:           return custom_id == SCHED_NEW_ID
def is_sched_list(custom_id: str) -> bool:          return custom_id == SCHED_LIST_ID
def is_sched_open(custom_id: str) -> bool:          return custom_id == SCHED_OPEN_ID
def is_sched_select(custom_id: str) -> bool:        return custom_id == SCHED_SELECT_ID
def is_sched_modal(custom_id: str) -> bool:         return custom_id == SCHED_MODAL_ID

def is_sched_confirm(custom_id: str) -> bool:       return custom_id.startswith(SCHED_CONFIRM_PREFIX)
def token_from_confirm(custom_id: str) -> str:      return _stub_extract(custom_id, SCHED_CONFIRM_PREFIX)
def is_sched_cancel(custom_id: str) -> bool:        return custom_id.startswith(SCHED_CANCEL_PREFIX)
def token_from_cancel(custom_id: str) -> str:       return _stub_extract(custom_id, SCHED_CANCEL_PREFIX)

def is_sched_run(custom_id: str) -> bool:           return custom_id.startswith(SCHED_RUN_PREFIX)
def id_from_run(custom_id: str) -> str:             return _stub_extract(custom_id, SCHED_RUN_PREFIX)
def is_sched_pause(custom_id: str) -> bool:         return custom_id.startswith(SCHED_PAUSE_PREFIX)
def id_from_pause(custom_id: str) -> str:           return _stub_extract(custom_id, SCHED_PAUSE_PREFIX)
def is_sched_resume(custom_id: str) -> bool:        return custom_id.startswith(SCHED_RESUME_PREFIX)
def id_from_resume(custom_id: str) -> str:          return _stub_extract(custom_id, SCHED_RESUME_PREFIX)
def is_sched_del(custom_id: str) -> bool:           return custom_id.startswith(SCHED_DEL_PREFIX)
def id_from_del(custom_id: str) -> str:             return _stub_extract(custom_id, SCHED_DEL_PREFIX)

def is_sched_edit(custom_id: str) -> bool:          return custom_id.startswith(SCHED_EDIT_PREFIX)
def id_from_edit(custom_id: str) -> str:            return _stub_extract(custom_id, SCHED_EDIT_PREFIX)
def is_sched_editmodal(custom_id: str) -> bool:     return custom_id.startswith(SCHED_EDITMODAL_PREFIX)
def id_from_editmodal(custom_id: str) -> str:       return _stub_extract(custom_id, SCHED_EDITMODAL_PREFIX)

def is_sched_retrymodal(custom_id: str) -> bool:    return custom_id.startswith(SCHED_RETRYMODAL_PREFIX)
def token_from_retrymodal(custom_id: str) -> str:   return _stub_extract(custom_id, SCHED_RETRYMODAL_PREFIX)

def is_connect_resume(custom_id: str) -> bool:      return custom_id.startswith(CONNECT_RESUME_PREFIX)
def token_from_connect_resume(custom_id: str) -> str: return _stub_extract(custom_id, CONNECT_RESUME_PREFIX)

def is_link_start(custom_id: str) -> bool:          return custom_id == LINK_START_ID
def is_link_modal(custom_id: str) -> bool:          return custom_id == LINK_MODAL_ID
def is_link_approve(custom_id: str) -> bool:        return custom_id.startswith(LINK_APPROVE_PREFIX)
def id_from_link_approve(custom_id: str) -> str:    return _stub_extract(custom_id, LINK_APPROVE_PREFIX)
def is_link_reject(custom_id: str) -> bool:         return custom_id.startswith(LINK_REJECT_PREFIX)
def id_from_link_reject(custom_id: str) -> str:     return _stub_extract(custom_id, LINK_REJECT_PREFIX)

def is_template_select(custom_id: str) -> bool:     return custom_id == TEMPLATE_SELECT_ID

def is_connections_open(custom_id: str) -> bool:    return custom_id in (CONN_OPEN_ID, CONN_REFRESH_ID)
def is_connections_refresh(custom_id: str) -> bool: return custom_id == CONN_REFRESH_ID
def is_connections_disconnect(custom_id: str) -> bool:           return custom_id.startswith(CONN_DISCONNECT_PREFIX)
def connector_from_disconnect(custom_id: str) -> str:            return _stub_extract(custom_id, CONN_DISCONNECT_PREFIX)
def is_connections_disconnect_confirm(custom_id: str) -> bool:   return custom_id.startswith(CONN_DISCONNECT_CONFIRM_PREFIX)
def connector_from_disconnect_confirm(custom_id: str) -> str:    return _stub_extract(custom_id, CONN_DISCONNECT_CONFIRM_PREFIX)
def is_connections_disconnect_cancel(custom_id: str) -> bool:    return custom_id == CONN_DISCONNECT_CANCEL_ID


# --- builders (stubbed — return shape-empty payloads) ---

def _stub_empty_panel() -> dict:
    return {"content": "[stubbed — lost v2 polish, recovery pending VPS unblock]",
            "embeds": [], "components": []}


def build_schedule_modal(*, what: str = "", when: str = "") -> dict:
    return {"title": "New scheduled task", "custom_id": SCHED_MODAL_ID,
            "components": [
                {"type": ACTION_ROW, "components": [{
                    "type": TEXT_INPUT, "custom_id": SCHED_WHAT_INPUT,
                    "label": "What should it do?", "style": TEXT_PARAGRAPH,
                    "required": True, "max_length": 2000,
                    **({"value": what[:2000]} if what else {})}]},
                {"type": ACTION_ROW, "components": [{
                    "type": TEXT_INPUT, "custom_id": SCHED_WHEN_INPUT,
                    "label": "How often?", "style": TEXT_SHORT,
                    "required": True, "max_length": 60,
                    **({"value": when[:60]} if when else {})}]},
            ]}


def build_confirm_components(token: str) -> list[dict]:
    return [{"type": ACTION_ROW, "components": [
        _button("Confirm", f"{SCHED_CONFIRM_PREFIX}{token}", STYLE_SUCCESS),
        _button("Cancel", f"{SCHED_CANCEL_PREFIX}{token}", STYLE_SECONDARY),
    ]}]


def build_connect_components(*, token: str, links: list[tuple[str, str]]) -> list[dict]:
    buttons = [{"type": BUTTON, "style": STYLE_LINK,
                "label": f"Connect {name}"[:80], "url": url}
               for name, url in links]
    buttons.append(_button("I've connected, create it",
                           f"{CONNECT_RESUME_PREFIX}{token}", STYLE_SUCCESS))
    return [{"type": ACTION_ROW, "components": buttons[i:i + 5]}
            for i in range(0, len(buttons), 5)]


def build_retry_prompt_components(token: str) -> list[dict]:
    return [{"type": ACTION_ROW, "components": [
        _button("Edit and retry", f"{SCHED_RETRYMODAL_PREFIX}{token}", STYLE_PRIMARY),
    ]}]


def build_schedule_edit_modal(schedule_id: str, *, what: str, when: str) -> dict:
    return {"title": "Edit schedule"[:45],
            "custom_id": f"{SCHED_EDITMODAL_PREFIX}{schedule_id}",
            "components": [
                {"type": ACTION_ROW, "components": [{
                    "type": TEXT_INPUT, "custom_id": SCHED_WHAT_INPUT,
                    "label": "What should it do?", "style": TEXT_PARAGRAPH,
                    "required": True, "max_length": 2000, "value": (what or "")[:2000]}]},
                {"type": ACTION_ROW, "components": [{
                    "type": TEXT_INPUT, "custom_id": SCHED_WHEN_INPUT,
                    "label": "How often?", "style": TEXT_SHORT,
                    "required": True, "max_length": 60, "value": (when or "")[:60]}]},
            ]}


def build_link_modal() -> dict:
    return {"title": "Link your account"[:45], "custom_id": LINK_MODAL_ID,
            "components": [{"type": ACTION_ROW, "components": [{
                "type": TEXT_INPUT, "custom_id": LINK_EMAIL_INPUT,
                "label": "Email", "style": TEXT_SHORT,
                "required": True, "max_length": 254}]}]}


def build_link_request_components(discord_id: str) -> list[dict]:
    return [{"type": ACTION_ROW, "components": [
        _button("Approve", f"{LINK_APPROVE_PREFIX}{discord_id}", STYLE_SUCCESS),
        _button("Reject", f"{LINK_REJECT_PREFIX}{discord_id}", STYLE_DANGER),
    ]}]


def build_connections_panel(statuses: dict, owner: str, connect_links: dict) -> dict:
    return _stub_empty_panel()


def build_disconnect_confirm(connector_key: str, connector_name: str) -> dict:
    return _stub_empty_panel()


def build_schedule_list(schedules: list[dict]) -> dict:
    return _stub_empty_panel()


def build_schedules_dashboard(schedules: list[dict]) -> dict:
    return _stub_empty_panel()


def build_schedule_card(s: dict) -> dict:
    return _stub_empty_panel()


def build_schedules_panel() -> dict:
    return _stub_empty_panel()


def build_retry_components(schedule_id: str) -> list[dict]:
    return [{"type": ACTION_ROW, "components": [
        _button("Retry", f"{SCHED_RUN_PREFIX}{schedule_id}", STYLE_SECONDARY),
    ]}]


def validate_schedule_prompt(what: str) -> str | None:
    """Stub — real validator was 'too short / too vague' rules. Passes everything for now."""
    return None


# --- build_*_embed stubs (the agent's app_builder_panel.py also removed these) ---

def build_ready_embed(slug: str, preview_url: str = "", message: str = "") -> dict:
    return {"title": "Build ready", "description": message or f"`{slug}` ready"}


def build_published_embed(slug: str, public_url: str = "") -> dict:
    return {"title": "Published!",
            "description": f"`{slug}` is live." + (f"\n{public_url}" if public_url else "")}
