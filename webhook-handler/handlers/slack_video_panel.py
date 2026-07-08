"""Pure builders for the Slack Video Studio panel, modals, and result blocks.

Block Kit shapes only (no I/O). action_ids and callback_ids use the
slackvid_ namespace (collision-free, verified).
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NEW_ID = "slackvid_new"
LIST_ID = "slackvid_list"
CREATE_CALLBACK = "slackvid_create"
REFINE_PREFIX = "slackvid_refine:"
REFINE_CALLBACK = "slackvid_refine_submit"
APPLY_PREFIX = "slackvid_apply:"
DELETE_PREFIX = "slackvid_del:"
RETRY_PREFIX = "slackvid_retry:"
WATCH_PREFIX = "slackvid_watch:"

STYLES: list[tuple[str, str]] = [
    ("clean_product_demo", "Clean product demo"),
    ("cinematic", "Cinematic"),
    ("snappy_social", "Snappy social"),
]
VOICES: list[tuple[str, str]] = [
    ("amy", "Amy (US, Female)"),
    ("ryan", "Ryan (US, Male)"),
    ("lessac", "Lessac (US, Female)"),
    ("joe", "Joe (US, Male)"),
    ("alan", "Alan (UK, Male)"),
    ("alba", "Alba (UK, Female)"),
]
MODES: list[tuple[str, str]] = [
    ("slideshow", "Slideshow (screenshots)"),
    ("animated", "Animated (motion graphics)"),
]
DEFAULT_STYLE = "clean_product_demo"
DEFAULT_VOICE = "amy"
DEFAULT_MODE = "animated"

_BUTTON_TEXT_MAX = 75
_TITLE_MAX = 24
_MAX_LIST_JOBS = 10


# ---------------------------------------------------------------------------
# Private helpers (mirror slack_app_builder_panel conventions)
# ---------------------------------------------------------------------------

def _button(text: str, action_id: str, *, primary: bool = False) -> dict:
    btn: dict = {
        "type": "button",
        "text": {"type": "plain_text", "text": text[:_BUTTON_TEXT_MAX]},
        "action_id": action_id,
    }
    if primary:
        btn["style"] = "primary"
    return btn


def _opt(label: str, value: str) -> dict:
    """Build a plain_text option dict for a static_select."""
    return {"text": {"type": "plain_text", "text": label}, "value": value}


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _plain_input(
    block_id: str,
    label: str,
    action_id: str,
    *,
    multiline: bool = False,
    placeholder: str = "",
    optional: bool = False,
    initial_value: str = "",
) -> dict:
    element: dict = {
        "type": "plain_text_input",
        "action_id": action_id,
        "multiline": multiline,
    }
    if placeholder:
        element["placeholder"] = {"type": "plain_text", "text": placeholder}
    if initial_value:
        element["initial_value"] = initial_value
    block: dict = {
        "type": "input",
        "block_id": block_id,
        "label": {"type": "plain_text", "text": label},
        "element": element,
    }
    if optional:
        block["optional"] = True
    return block


def _select_input(
    block_id: str,
    label: str,
    action_id: str,
    options_list: list[tuple[str, str]],
    default_value: str,
    *,
    optional: bool = False,
) -> dict:
    """Build an input block with a static_select element.

    options_list is a list of (value, display_label) tuples.
    """
    opts = [_opt(display, value) for value, display in options_list]
    initial = next((o for o in opts if o["value"] == default_value), opts[0])
    block: dict = {
        "type": "input",
        "block_id": block_id,
        "label": {"type": "plain_text", "text": label},
        "element": {
            "type": "static_select",
            "action_id": action_id,
            "options": opts,
            "initial_option": initial,
        },
    }
    if optional:
        block["optional"] = True
    return block


def _sel(state: dict, block: str, action: str, default: str) -> str:
    """Read selected_option.value from Block Kit view state; fall back to default."""
    el = (state.get(block, {}) or {}).get(action, {}) or {}
    opt = el.get("selected_option")
    return (opt.get("value") if opt else None) or default


def _txt(state: dict, block: str, action: str) -> str:
    """Read plain_text_input.value from Block Kit view state, stripped."""
    el = (state.get(block, {}) or {}).get(action, {}) or {}
    return (el.get("value") or "").strip()


# ---------------------------------------------------------------------------
# Panel (message dict with blocks)
# ---------------------------------------------------------------------------

def build_video_panel() -> dict:
    """Pinned channel panel: header + description section + two action buttons."""
    return {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "AIUI Video Studio", "emoji": True},
            },
            _section("Make a narrated video from a website link."),
            {
                "type": "actions",
                "elements": [
                    _button("New video from a website", NEW_ID, primary=True),
                    _button("My videos", LIST_ID),
                ],
            },
        ]
    }


# ---------------------------------------------------------------------------
# Create modal
# ---------------------------------------------------------------------------

def build_video_modal(channel_id: str, templates: list[dict] | None = None,
                      initial_prompt: str = "", initial_template: str = "") -> dict:
    """Create-video modal (callback_id == CREATE_CALLBACK).

    channel_id is stashed in private_metadata so the submit handler knows
    where to post the result (modal submits do not carry the channel).

    templates (optional) adds a "Template" static_select (block_id/action_id
    "vid_template") between the url and prompt inputs; omit/empty to keep the
    modal template-free. initial_prompt/initial_template prefill the prompt
    text and the selected template option (used by the views.update prefill
    round trip).
    """
    template_block = None
    if templates:
        options = [_opt(f"{t.get('emoji', '')} {t.get('name', t['key'])}".strip()[:75],
                        t["key"]) for t in templates if t.get("key")]
        element = {"type": "static_select", "action_id": "vid_template",
                   "placeholder": {"type": "plain_text", "text": "Custom (no template)"},
                   "options": options}
        if initial_template:
            match = [o for o in options if o["value"] == initial_template]
            if match:
                element["initial_option"] = match[0]
        template_block = {
            "type": "input", "block_id": "vid_template", "optional": True,
            "dispatch_action": True,
            "label": {"type": "plain_text", "text": "Template"},
            "element": element,
        }

    blocks = [
        _plain_input(
            "url",
            "Website URL",
            "url",
            placeholder="https://yoursite.com",
        ),
    ]
    if template_block:
        blocks.append(template_block)
    blocks.extend([
        _plain_input(
            "prompt",
            "What should the walkthrough show?",
            "prompt",
            multiline=True,
            placeholder="Leave blank to let the AI direct it.",
            optional=True,
            initial_value=initial_prompt,
        ),
        _plain_input(
            "title",
            "Title",
            "title",
            optional=True,
        ),
        _select_input(
            "style",
            "Style",
            "style",
            STYLES,
            DEFAULT_STYLE,
            optional=True,
        ),
        _select_input(
            "voice",
            "Voice",
            "voice",
            VOICES,
            DEFAULT_VOICE,
            optional=True,
        ),
        _select_input(
            "mode",
            "Output",
            "mode",
            MODES,
            DEFAULT_MODE,
            optional=True,
        ),
    ])

    return {
        "type": "modal",
        "callback_id": CREATE_CALLBACK,
        "private_metadata": channel_id,
        "title": {"type": "plain_text", "text": "New video"},
        "submit": {"type": "plain_text", "text": "Generate"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def parse_video_modal(view: dict) -> dict:
    """Extract submitted values from a view_submission payload's view dict.

    Returns {"url", "prompt", "title", "style", "voice", "mode", "channel_id"}.
    channel_id comes from view["private_metadata"]. Static selects fall back to
    DEFAULT_* when absent. title is None when blank.

    State access path for static_selects:
        el = (state.get(block, {}) or {}).get(action, {}) or {}
        opt = el.get("selected_option")
        value = (opt.get("value") if opt else None) or default
    """
    state = (view.get("state", {}) or {}).get("values", {}) or {}
    channel_id: str = view.get("private_metadata") or ""

    url = _txt(state, "url", "url")
    prompt = _txt(state, "prompt", "prompt")
    raw_title = _txt(state, "title", "title")
    title: str | None = raw_title if raw_title else None
    style = _sel(state, "style", "style", DEFAULT_STYLE)
    voice = _sel(state, "voice", "voice", DEFAULT_VOICE)
    mode = _sel(state, "mode", "mode", DEFAULT_MODE)
    template = _sel(state, "vid_template", "vid_template", "")

    return {
        "url": url,
        "prompt": prompt,
        "title": title,
        "style": style,
        "voice": voice,
        "mode": mode,
        "channel_id": channel_id,
        "template": template,
    }


# ---------------------------------------------------------------------------
# Result blocks (posted when a render completes)
# ---------------------------------------------------------------------------

def _watch_button(job_id: str, url: str) -> dict:
    """Link-style button that opens the rendered video in the browser."""
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": "▶ Watch"},
        "url": url,
        "action_id": f"{WATCH_PREFIX}{job_id}",
    }


def _delete_button(job_id: str, title: str) -> dict:
    """Danger-styled Delete button with a native Slack confirm dialog."""
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": "Delete"},
        "style": "danger",
        "action_id": f"{DELETE_PREFIX}{job_id}",
        "confirm": {
            "title": {"type": "plain_text", "text": "Delete video?"},
            "text": {"type": "mrkdwn",
                     "text": f"This permanently deletes *{title[:80]}*. No undo."},
            "confirm": {"type": "plain_text", "text": "Delete"},
            "deny": {"type": "plain_text", "text": "Cancel"},
        },
    }


def build_result_blocks(job_id: str, title: str, share_url: str) -> list[dict]:
    """Blocks for the render-done message. Only emits the watch link when a
    share URL actually exists (an empty URL used to render as a dead
    '<|Watch it here>' fragment), and always offers Refine."""
    if share_url:
        text = f"Your video is ready: *{title}*\n<{share_url}|Watch it here>"
    else:
        text = (f"Your video is ready: *{title}*\n"
                "Open the web Video Studio to watch it.")
    elements: list[dict] = []
    if share_url:
        elements.append(_watch_button(job_id, share_url))
    elements.append(_button("Refine", f"{REFINE_PREFIX}{job_id}"))
    return [_section(text), {"type": "actions", "elements": elements}]


# ---------------------------------------------------------------------------
# Refine modal
# ---------------------------------------------------------------------------

def build_refine_modal(job_id: str) -> dict:
    """Refine-video modal (callback_id == REFINE_CALLBACK, private_metadata == job_id)."""
    return {
        "type": "modal",
        "callback_id": REFINE_CALLBACK,
        "private_metadata": job_id,
        "title": {"type": "plain_text", "text": "Refine video"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            _plain_input(
                "change",
                "What should change?",
                "change",
                multiline=True,
            ),
        ],
    }


# ---------------------------------------------------------------------------
# Proposal blocks (posted with the AI change proposal)
# ---------------------------------------------------------------------------

def build_proposal_blocks(job_id: str) -> list[dict]:
    """Actions block with a primary 'Apply this change' button."""
    return [
        {
            "type": "actions",
            "elements": [
                _button("Apply this change", f"{APPLY_PREFIX}{job_id}", primary=True),
            ],
        }
    ]


# ---------------------------------------------------------------------------
# List blocks
# ---------------------------------------------------------------------------

# User-facing status labels: internal states like "collecting" are jargon,
# so the list shows what the state MEANS instead.
_STATUS_LABELS = {
    "collecting": "draft (never started)",
    "queued": "queued",
    "scripting": "writing the script",
    "rendering": "rendering",
    "done": "done",
    "failed": "failed",
}


def build_list_blocks(jobs: list[dict]) -> list[dict]:
    """Header + one section per job with status-appropriate actions:
    done -> Watch (when a share link exists) + Refine + Delete;
    failed -> Retry + Delete; drafts and queued -> Delete;
    scripting/rendering -> no buttons (the API blocks deletion mid-render).
    Capped at _MAX_LIST_JOBS jobs."""
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Your videos", "emoji": True},
        }
    ]

    if not jobs:
        blocks.append(
            _section("You have no videos yet. Create one with *New video from a website*.")
        )
        return blocks

    for job in jobs[:_MAX_LIST_JOBS]:
        job_id = str(job.get("id") or "")
        title = (job.get("title") or "(no title)").strip()
        status = (job.get("status") or "unknown").strip()
        label = _STATUS_LABELS.get(status, status)
        blocks.append(_section(f"*{title}* - {label}"))
        if not job_id:
            continue
        elements: list[dict] = []
        if status == "done":
            share_url = (job.get("share_url") or "").strip()
            if share_url:
                elements.append(_watch_button(job_id, share_url))
            elements.append(_button("Refine", f"{REFINE_PREFIX}{job_id}"))
            elements.append(_delete_button(job_id, title))
        elif status == "failed":
            elements.append(_button("Retry", f"{RETRY_PREFIX}{job_id}", primary=True))
            elements.append(_delete_button(job_id, title))
        elif status in ("collecting", "queued"):
            elements.append(_delete_button(job_id, title))
        if elements:
            blocks.append({"type": "actions", "elements": elements})

    return blocks


# ---------------------------------------------------------------------------
# Predicates / extractors
# ---------------------------------------------------------------------------

def is_vid_new(a: str) -> bool:
    return a == NEW_ID


def is_vid_list(a: str) -> bool:
    return a == LIST_ID


def is_vid_refine(a: str) -> bool:
    return bool(a) and a.startswith(REFINE_PREFIX)


def is_vid_apply(a: str) -> bool:
    return bool(a) and a.startswith(APPLY_PREFIX)


def is_vid_delete(a: str) -> bool:
    return bool(a) and a.startswith(DELETE_PREFIX)


def is_vid_retry(a: str) -> bool:
    return bool(a) and a.startswith(RETRY_PREFIX)


def is_vid_watch(a: str) -> bool:
    return bool(a) and a.startswith(WATCH_PREFIX)


def job_from_refine(a: str) -> str:
    return a[len(REFINE_PREFIX):]


def job_from_apply(a: str) -> str:
    return a[len(APPLY_PREFIX):]


def job_from_delete(a: str) -> str:
    return a[len(DELETE_PREFIX):]


def job_from_retry(a: str) -> str:
    return a[len(RETRY_PREFIX):]
