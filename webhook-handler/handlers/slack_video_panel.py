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
DEFAULT_MODE = "slideshow"

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
) -> dict:
    element: dict = {
        "type": "plain_text_input",
        "action_id": action_id,
        "multiline": multiline,
    }
    if placeholder:
        element["placeholder"] = {"type": "plain_text", "text": placeholder}
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

def build_video_modal(channel_id: str) -> dict:
    """Create-video modal (callback_id == CREATE_CALLBACK).

    channel_id is stashed in private_metadata so the submit handler knows
    where to post the result (modal submits do not carry the channel).
    """
    return {
        "type": "modal",
        "callback_id": CREATE_CALLBACK,
        "private_metadata": channel_id,
        "title": {"type": "plain_text", "text": "New video"},
        "submit": {"type": "plain_text", "text": "Generate"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            _plain_input(
                "url",
                "Website URL",
                "url",
                placeholder="https://yoursite.com",
            ),
            _plain_input(
                "prompt",
                "What should the walkthrough show?",
                "prompt",
                multiline=True,
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
        ],
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

    return {
        "url": url,
        "prompt": prompt,
        "title": title,
        "style": style,
        "voice": voice,
        "mode": mode,
        "channel_id": channel_id,
    }


# ---------------------------------------------------------------------------
# Result blocks (posted when a render completes)
# ---------------------------------------------------------------------------

def build_result_blocks(job_id: str, title: str, share_url: str) -> list[dict]:
    """Blocks for the render-done message: section with link + Refine button."""
    return [
        _section(f"Your video is ready: *{title}*\n<{share_url}|Watch it here>"),
        {
            "type": "actions",
            "elements": [
                _button("Refine", f"{REFINE_PREFIX}{job_id}"),
            ],
        },
    ]


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

def build_list_blocks(jobs: list[dict]) -> list[dict]:
    """Header + one section per job (title + status) with a Refine button when
    status == 'done'. Capped at _MAX_LIST_JOBS jobs."""
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
        blocks.append(_section(f"*{title}* - {status}"))
        if status == "done" and job_id:
            blocks.append({
                "type": "actions",
                "elements": [_button("Refine", f"{REFINE_PREFIX}{job_id}")],
            })

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


def job_from_refine(a: str) -> str:
    return a[len(REFINE_PREFIX):]


def job_from_apply(a: str) -> str:
    return a[len(APPLY_PREFIX):]
