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


def build_ready_components(slug: str, preview_url: str = "") -> list[dict]:
    """Action row for the build-ready message: green Publish + blurple Enhance,
    plus an 'Open preview' link button when preview_url is set."""
    buttons: list[dict] = [
        _button("\U0001f7e2 Publish", f"{PUBLISH_PREFIX}{slug}", STYLE_SUCCESS),
        _button("✏️ Enhance", f"{ENHANCE_PREFIX}{slug}", STYLE_PRIMARY),
    ]
    if preview_url:
        buttons.append({"type": BUTTON, "style": STYLE_LINK,
                        "label": "\U0001f517 Open preview", "url": preview_url})
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


# --- Schedules (Discord cron jobs): panel, modal, confirm card, list ---
TEXT_SHORT = 1  # Discord short text-input style (paragraph is 2)

SCHED_NEW_ID = "aiuisched:new"        # New-schedule button (exact match)
SCHED_LIST_ID = "aiuisched:list"      # My-schedules button (exact match)
SCHED_MODAL_ID = "aiuisched:modal"    # create modal custom_id (exact match)
SCHED_CONFIRM_PREFIX = "aiuisched:confirm:"   # confirm:<token>
SCHED_CANCEL_PREFIX = "aiuisched:cancel:"     # cancel:<token>
SCHED_RUN_PREFIX = "aiuisched:run:"           # run:<schedule_id>
SCHED_PAUSE_PREFIX = "aiuisched:pause:"       # pause:<schedule_id>
SCHED_RESUME_PREFIX = "aiuisched:resume:"     # resume:<schedule_id>
SCHED_DEL_PREFIX = "aiuisched:del:"           # del:<schedule_id>
SCHED_WHAT_INPUT = "what"
SCHED_WHEN_INPUT = "when"

SCHEDULES_PANEL_CONTENT = (
    "⏰ **Scheduled tasks**\n"
    "Set up a recurring task in plain English — e.g. *summarize my unread "
    "emails* / *every morning*. Results land in your private thread. "
    "No coding, no cron syntax."
)

_MAX_SCHED_ROWS = 5  # Discord allows at most 5 action rows per message


def build_schedules_panel() -> dict:
    """Pinned panel message: 'New schedule' + 'My schedules' buttons."""
    row = {"type": ACTION_ROW, "components": [
        _button("⏰ New schedule", SCHED_NEW_ID, STYLE_SUCCESS),
        _button("\U0001f4cb My schedules", SCHED_LIST_ID, STYLE_SECONDARY),
    ]}
    return {"content": SCHEDULES_PANEL_CONTENT, "components": [row]}


def build_schedule_modal() -> dict:
    """Type-9 MODAL data: 'what' (paragraph) + 'when' (short natural language)."""
    return {
        "title": "New scheduled task"[:45],
        "custom_id": SCHED_MODAL_ID,
        "components": [
            {"type": ACTION_ROW, "components": [{
                "type": TEXT_INPUT, "custom_id": SCHED_WHAT_INPUT,
                "label": "What should it do?", "style": TEXT_PARAGRAPH,
                "required": True, "max_length": 2000,
                "placeholder": "e.g. summarize my unread emails and list the top 3",
            }]},
            {"type": ACTION_ROW, "components": [{
                "type": TEXT_INPUT, "custom_id": SCHED_WHEN_INPUT,
                "label": "How often?", "style": TEXT_SHORT,
                "required": True, "max_length": 60,
                "placeholder": "every morning  /  every Monday 9am  /  every 30 minutes",
            }]},
        ],
    }


def build_confirm_components(token: str) -> list[dict]:
    """Confirmation-card buttons: Confirm (carries token) + Cancel."""
    return [{"type": ACTION_ROW, "components": [
        _button("✅ Confirm", f"{SCHED_CONFIRM_PREFIX}{token}", STYLE_SUCCESS),
        _button("✖ Cancel", f"{SCHED_CANCEL_PREFIX}{token}", STYLE_SECONDARY),
    ]}]


def build_schedule_list(schedules: list[dict]) -> dict:
    """Ephemeral 'My schedules' message: a text summary + up to 5 rows of
    Run / Pause-or-Resume / Delete buttons (one row per schedule)."""
    if not schedules:
        return {
            "content": "You have no schedules yet. Hit **⏰ New schedule** to make one.",
            "components": [],
        }
    lines = ["\U0001f4c5 **Your schedules**"]
    rows: list[dict] = []
    for sch in schedules[:_MAX_SCHED_ROWS]:
        sid = str(sch.get("id", ""))
        name = sch.get("name") or sid
        enabled = bool(sch.get("enabled", True))
        status = sch.get("last_run_status")
        state = "active" if enabled else "paused"
        tail = f", last run: {status}" if status else ""
        lines.append(f"• {name}  *({state}{tail})*")
        buttons = [_button("▶️ Run now", f"{SCHED_RUN_PREFIX}{sid}", STYLE_SECONDARY)]
        if enabled:
            buttons.append(_button("⏸ Pause", f"{SCHED_PAUSE_PREFIX}{sid}", STYLE_SECONDARY))
        else:
            buttons.append(_button("▶️ Resume", f"{SCHED_RESUME_PREFIX}{sid}", STYLE_SUCCESS))
        buttons.append(_button("\U0001f5d1 Delete", f"{SCHED_DEL_PREFIX}{sid}", STYLE_DANGER))
        rows.append({"type": ACTION_ROW, "components": buttons})
    if len(schedules) > _MAX_SCHED_ROWS:
        lines.append(f"…and {len(schedules) - _MAX_SCHED_ROWS} more.")
    return {"content": "\n".join(lines), "components": rows}


def is_sched_new(custom_id: str) -> bool:
    return custom_id == SCHED_NEW_ID


def is_sched_list(custom_id: str) -> bool:
    return custom_id == SCHED_LIST_ID


def is_sched_modal(custom_id: str) -> bool:
    return custom_id == SCHED_MODAL_ID


def _suffix_after(custom_id: str, prefix: str) -> str:
    if not custom_id.startswith(prefix):
        raise ValueError(f"not a {prefix!r} custom_id: {custom_id!r}")
    suffix = custom_id[len(prefix):]
    if not suffix:
        raise ValueError(f"{prefix!r} custom_id has no value: {custom_id!r}")
    return suffix


def is_sched_confirm(custom_id: str) -> bool:
    return custom_id.startswith(SCHED_CONFIRM_PREFIX)


def token_from_confirm(custom_id: str) -> str:
    return _suffix_after(custom_id, SCHED_CONFIRM_PREFIX)


def is_sched_cancel(custom_id: str) -> bool:
    return custom_id.startswith(SCHED_CANCEL_PREFIX)


def token_from_cancel(custom_id: str) -> str:
    return _suffix_after(custom_id, SCHED_CANCEL_PREFIX)


def is_sched_run(custom_id: str) -> bool:
    return custom_id.startswith(SCHED_RUN_PREFIX)


def id_from_run(custom_id: str) -> str:
    return _suffix_after(custom_id, SCHED_RUN_PREFIX)


def is_sched_pause(custom_id: str) -> bool:
    return custom_id.startswith(SCHED_PAUSE_PREFIX)


def id_from_pause(custom_id: str) -> str:
    return _suffix_after(custom_id, SCHED_PAUSE_PREFIX)


def is_sched_resume(custom_id: str) -> bool:
    return custom_id.startswith(SCHED_RESUME_PREFIX)


def id_from_resume(custom_id: str) -> str:
    return _suffix_after(custom_id, SCHED_RESUME_PREFIX)


def is_sched_del(custom_id: str) -> bool:
    return custom_id.startswith(SCHED_DEL_PREFIX)


def id_from_del(custom_id: str) -> str:
    return _suffix_after(custom_id, SCHED_DEL_PREFIX)
