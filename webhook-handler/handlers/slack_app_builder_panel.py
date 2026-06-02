"""Pure builders for the Slack App Builder channel panel and modal.

Block Kit analog of handlers/app_builder_panel.py. No I/O. Imported by the
interaction handler (handlers/slack_interactions.py) and the one-shot setup
script (scripts/setup_slack_app_builder_channel.py); unit tested in
tests/test_slack_panel.py.

The custom-id prefixes match the Discord panel for consistency, but Slack uses
them as `action_id` (buttons) and `callback_id` (modal views).
"""
from __future__ import annotations

# custom_id schemes (shared shape with the Discord panel)
TEMPLATE_PREFIX = "aiuibuild:tpl:"   # button action_id -> aiuibuild:tpl:<key>  ("" = Blank)
BUILD_PREFIX = "aiuibuild:build:"    # modal callback_id -> aiuibuild:build:<key>
DESCRIPTION_BLOCK_ID = "description_block"
DESCRIPTION_INPUT_ID = "description"

# B4 — dropdown panel constants
TEMPLATE_SELECT_ACTION_ID = "aiuibuild:tpl_select"
BLANK_ACTION_ID = TEMPLATE_PREFIX  # bare prefix == Blank
_SELECT_OPTION_MAX = 100
_OPT_TEXT_MAX = 75

# B5 — management action_id prefixes
PUBLISH_PREFIX = "aiuibuild:publish:"
ENHANCE_PREFIX = "aiuibuild:enhance:"
ENHANCE_MODAL_PREFIX = "aiuibuild:enhmodal:"
UNPUBLISH_PREFIX = "aiuibuild:unpublish:"
STATUS_PREFIX = "aiuibuild:status:"

# B6 — card colours
COLOR_READY = "#36a64f"
COLOR_PUBLISHED = "#2eb67d"

# B7 — app-list cap
_MAX_LIST_ROWS = 10

# Slack Block Kit limits
_BUTTON_TEXT_MAX = 75
_TITLE_MAX = 24           # modal title plain_text hard limit

PANEL_TEXT = (
    "*AIUI App Builder*\n"
    "Pick a template to start - a short form opens where you describe your app, "
    "and I'll build it in a private DM with you. Or choose Blank to start from scratch."
)

# Plain-language descriptions shown under each template in the dropdown, so any
# user (non-technical included) understands what they're picking. Keyed by the
# catalog `key`; falls back to the catalog's own description for unknown keys.
# Kept <= 75 chars (Slack's option-description limit).
FRIENDLY_DESCRIPTIONS = {
    "landing": "A one-page site to promote a product or service",
    "dashboard": "Charts and key numbers at a glance",
    "crud": "Add, edit, and keep track of a list of records",
    "crm": "Track contacts, leads, and deals",
    "portfolio": "Show off your work or personal profile",
    "docs": "A documentation or help site",
    "ecommerce": "An online store with a product catalog and cart",
    "booking": "Let people book appointments or time slots",
    "chat": "A real-time messaging app",
    "auth": "An app with login and members-only pages",
    "blog": "Publish articles and blog posts",
    "invoice": "Create, edit, and print invoices or quotes",
    "project-tracker": "Track tasks on a board with stages and a timeline",
    "ai-chatbot": "An AI assistant that answers from your own docs",
    "expense-tracker": "Track spending by category against budgets",
    "form-builder": "Build forms by drag-and-drop and collect responses",
    "social-feed": "A mini social network: posts, likes, and follows",
    "flight-booking": "Search flights and walk through booking",
    "food-delivery": "Browse restaurants and order food to a cart",
    "job-board": "Post jobs, or search and apply for them",
    "movie-tickets": "Pick cinema seats and check out tickets",
    "recipe-site": "Browse recipes with a step-by-step cook mode",
    "agency": "A bold marketing site for a studio or agency",
    "restaurant": "A site for a restaurant or cafe (menu, hours)",
    "photography": "A photo portfolio for a photographer",
    "event": "A site for a conference, festival, or event",
    "real-estate": "Browse property listings for sale or rent",
}


def _button(text: str, action_id: str, *, primary: bool = False) -> dict:
    btn = {
        "type": "button",
        "text": {"type": "plain_text", "text": (text or "?")[:_BUTTON_TEXT_MAX]},
        "action_id": action_id,
    }
    if primary:
        btn["style"] = "primary"
    return btn


def _link_button(text: str, url: str) -> dict:
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": text[:_BUTTON_TEXT_MAX]},
        "url": url,
    }


# ---------------------------------------------------------------------------
# B4 — dropdown panel
# ---------------------------------------------------------------------------

def build_panel_blocks(templates: list[dict]) -> list[dict]:
    """Header + a 'Pick a template' dropdown (one option per template) + a Blank
    button. static_select allows up to 100 options, so no template is dropped."""
    options = []
    for t in templates[:_SELECT_OPTION_MAX]:
        key = t.get("key")
        if not key:
            continue
        label = (t.get("label") or key)[:_OPT_TEXT_MAX]
        opt = {"text": {"type": "plain_text", "text": label},
               "value": f"{TEMPLATE_PREFIX}{key}"}
        # A short second line so any user understands what the template builds.
        # Prefer the plain-language override; fall back to the catalog's own
        # description. Slack caps option descriptions at 75 chars.
        desc = (FRIENDLY_DESCRIPTIONS.get(key) or t.get("description") or "").strip()
        if desc:
            opt["description"] = {"type": "plain_text", "text": desc[:_OPT_TEXT_MAX]}
        options.append(opt)
    select = {
        "type": "static_select",
        "action_id": TEMPLATE_SELECT_ACTION_ID,
        "placeholder": {"type": "plain_text", "text": "Pick a template..."},
        "options": options or [{"text": {"type": "plain_text", "text": "Blank"}, "value": TEMPLATE_PREFIX}],
    }
    blank = _button("Blank", BLANK_ACTION_ID)
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": PANEL_TEXT}},
        {"type": "actions", "elements": [select, blank]},
    ]


# ---------------------------------------------------------------------------
# Build description modal
# ---------------------------------------------------------------------------

def build_modal_view(
    template_key: str | None,
    template_label: str | None = None,
    channel_id: str = "",
) -> dict:
    """A Slack modal `view`. callback_id carries the template key; the
    originating channel is stashed in private_metadata so the submit handler
    knows where to post the result (modal submits don't carry the channel)."""
    key = template_key or ""
    what = template_label or template_key or "app"
    return {
        "type": "modal",
        "callback_id": f"{BUILD_PREFIX}{key}",
        "private_metadata": channel_id or "",
        "title": {"type": "plain_text", "text": f"Build: {what}"[:_TITLE_MAX]},
        "submit": {"type": "plain_text", "text": "Build"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": DESCRIPTION_BLOCK_ID,
                "label": {"type": "plain_text", "text": "Describe your app"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": DESCRIPTION_INPUT_ID,
                    "multiline": True,
                    "max_length": 3000,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "e.g. a portfolio site for Maya, a UX designer",
                    },
                },
            }
        ],
    }


def description_from_view(view: dict) -> str:
    """Pull the typed description out of a view_submission payload's view.
    view.state.values[DESCRIPTION_BLOCK_ID][DESCRIPTION_INPUT_ID].value."""
    values = (view or {}).get("state", {}).get("values", {})
    block = values.get(DESCRIPTION_BLOCK_ID, {})
    element = block.get(DESCRIPTION_INPUT_ID, {})
    return (element.get("value") or "").strip()


# ---------------------------------------------------------------------------
# Panel button / modal id parsers
# ---------------------------------------------------------------------------

def is_panel_button(action_id: str) -> bool:
    return bool(action_id) and action_id.startswith(TEMPLATE_PREFIX)


def is_panel_modal(callback_id: str) -> bool:
    return bool(callback_id) and callback_id.startswith(BUILD_PREFIX)


def template_key_from_button(action_id: str) -> str | None:
    """Button action_id -> template key. Bare prefix (Blank) -> None."""
    if not is_panel_button(action_id):
        raise ValueError(f"not a panel button action_id: {action_id!r}")
    return action_id[len(TEMPLATE_PREFIX):] or None


def template_key_from_modal(callback_id: str) -> str | None:
    """Modal callback_id -> template key. Bare prefix -> None."""
    if not is_panel_modal(callback_id):
        raise ValueError(f"not a panel modal callback_id: {callback_id!r}")
    return callback_id[len(BUILD_PREFIX):] or None


# ---------------------------------------------------------------------------
# B5 — management action_id parsers
# ---------------------------------------------------------------------------

def is_action(action_id: str, prefix: str) -> bool:
    return bool(action_id) and action_id.startswith(prefix)


def slug_from_action(action_id: str, prefix: str) -> str:
    if not is_action(action_id, prefix):
        raise ValueError(f"not a {prefix!r} action_id: {action_id!r}")
    return action_id[len(prefix):]


def is_enhance_modal(callback_id: str) -> bool:
    return bool(callback_id) and callback_id.startswith(ENHANCE_MODAL_PREFIX)


def slug_from_enhance_modal(callback_id: str) -> str:
    if not is_enhance_modal(callback_id):
        raise ValueError(f"not an enhance modal callback_id: {callback_id!r}")
    return callback_id[len(ENHANCE_MODAL_PREFIX):]


# ---------------------------------------------------------------------------
# B6 — build-ready + published card attachments
# ---------------------------------------------------------------------------

def build_ready_attachment(slug: str, preview_url: str = "") -> dict:
    """Green build-ready card: Publish / Enhance + optional Open preview link."""
    elements: list[dict] = [
        _button("Publish", f"{PUBLISH_PREFIX}{slug}", primary=True),
        _button("Enhance", f"{ENHANCE_PREFIX}{slug}"),
    ]
    if preview_url:
        elements.append(_link_button("Open preview", preview_url))
    return {
        "color": COLOR_READY,
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Build ready: {slug}*\nYour app is ready to preview and publish.",
                },
            },
            {"type": "actions", "elements": elements},
        ],
    }


def build_published_attachment(slug: str, public_url: str = "") -> dict:
    """Blue published card: Enhance / Unpublish + optional Open link."""
    elements: list[dict] = [
        _button("Enhance", f"{ENHANCE_PREFIX}{slug}"),
        _button("Unpublish", f"{UNPUBLISH_PREFIX}{slug}"),
    ]
    if public_url:
        elements.append(_link_button("Open", public_url))
    desc = f"*Published: {slug}*" + (f"\n{public_url}" if public_url else "")
    return {
        "color": COLOR_PUBLISHED,
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": desc}},
            {"type": "actions", "elements": elements},
        ],
    }


# ---------------------------------------------------------------------------
# B7 — app-list blocks (state-aware) + enhance modal
# ---------------------------------------------------------------------------

def build_apps_list_blocks(apps: list[dict]) -> list[dict]:
    """One section + one actions row per app, capped at _MAX_LIST_ROWS.

    Published apps get: Status, Enhance, Unpublish.
    Draft apps get: Status, Publish, Enhance.
    Empty list -> single 'no apps' section.
    More than 10 apps -> context block noting truncation.
    """
    if not apps:
        return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "You have no apps yet. "
                        "Use the App Builder panel to create one."
                    ),
                },
            }
        ]

    visible = apps[:_MAX_LIST_ROWS]
    blocks: list[dict] = []
    for app in visible:
        slug = app.get("slug") or ""
        if not slug:
            continue
        published = bool(app.get("published"))
        state_label = "published" if published else "draft"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{slug}* - {state_label}"},
        })
        if published:
            row_buttons = [
                _button("Status", f"{STATUS_PREFIX}{slug}"),
                _button("Enhance", f"{ENHANCE_PREFIX}{slug}"),
                _button("Unpublish", f"{UNPUBLISH_PREFIX}{slug}"),
            ]
        else:
            row_buttons = [
                _button("Status", f"{STATUS_PREFIX}{slug}"),
                _button("Publish", f"{PUBLISH_PREFIX}{slug}", primary=True),
                _button("Enhance", f"{ENHANCE_PREFIX}{slug}"),
            ]
        blocks.append({"type": "actions", "elements": row_buttons})

    if len(apps) > _MAX_LIST_ROWS:
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"Showing first {_MAX_LIST_ROWS}. "
                        "Use `/aiui aiuibuilder status <slug>` for others."
                    ),
                }
            ],
        })

    return blocks


def build_enhance_modal_view(slug: str) -> dict:
    """Modal for requesting an enhancement on an existing app."""
    return {
        "type": "modal",
        "callback_id": f"{ENHANCE_MODAL_PREFIX}{slug}",
        "private_metadata": slug,
        "title": {"type": "plain_text", "text": f"Enhance: {slug}"[:_TITLE_MAX]},
        "submit": {"type": "plain_text", "text": "Apply"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "enhance_block",
                "label": {"type": "plain_text", "text": "What should change?"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "enhance_input",
                    "multiline": True,
                    "max_length": 3000,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "What should change?",
                    },
                },
            }
        ],
    }


def enhance_text_from_view(view: dict) -> str:
    """Pull the typed enhancement request out of a view_submission payload's view.
    view.state.values['enhance_block']['enhance_input'].value."""
    values = (view or {}).get("state", {}).get("values", {})
    block = values.get("enhance_block", {})
    element = block.get("enhance_input", {})
    return (element.get("value") or "").strip()
