"""Pure builders + custom_id helpers for the #video-generation Discord channel.

No I/O — imported by both the setup script and the interaction router. Namespace:
all component custom_ids start with "aiuivid:". See
docs/superpowers/specs/2026-06-19-discord-video-channel-design.md.
"""
from handlers.app_builder_panel import (  # reuse the shared component constants
    ACTION_ROW, BUTTON, SELECT_MENU, TEXT_INPUT, TEXT_PARAGRAPH, TEXT_SHORT,
    STYLE_PRIMARY, STYLE_SECONDARY, STYLE_SUCCESS, ROBOTIC_CYAN, _button,
)

# --- custom_id namespace ---
NEW_ID = "aiuivid:new"
LIST_ID = "aiuivid:list"
DETAILS_PREFIX = "aiuivid:details:"
DETAILS_MODAL_PREFIX = "aiuivid:detailsmodal:"
CAPTURE_PREFIX = "aiuivid:capture:"
CAPTURE_MODAL_PREFIX = "aiuivid:capturemodal:"
URL_INPUT = "url"
STYLE_PREFIX = "aiuivid:style:"
VOICE_PREFIX = "aiuivid:voice:"
MODE_PREFIX = "aiuivid:mode:"
ANIMATION_PREFIX = "aiuivid:animation:"
GENERATE_PREFIX = "aiuivid:generate:"
GENNOW_PREFIX = "aiuivid:gennow:"
SRC_URL_PREFIX = "aiuivid:srcurl:"
SRC_SHOTS_PREFIX = "aiuivid:srcshots:"
SRC_SHOTS_CONTINUE_PREFIX = "aiuivid:srcshotsgo:"
OPTIONS_PREFIX = "aiuivid:options:"
OPTIONS_BACK_PREFIX = "aiuivid:optionsback:"
REFINE_PREFIX = "aiuivid:refine:"
REFINE_MODAL_PREFIX = "aiuivid:refinemodal:"
APPLY_PREFIX = "aiuivid:apply:"
VERSION_PREFIX = "aiuivid:version:"
TITLE_INPUT = "title"
PROMPT_INPUT = "prompt"
REFINE_INPUT = "change"

STYLES = [
    ("clean_product_demo", "Clean product demo", "Crisp, recommended default"),
    ("cinematic", "Cinematic", "Graded, glassy lower-thirds, ambient bed"),
    ("snappy_social", "Snappy social", "Punchy, bold pop-in captions"),
]

ANIMATIONS = [
    ("cursor_click", "Cursor click", "Mouse cursor moves and clicks the key area"),
    ("smooth_scroll", "Smooth scroll", "Guided page movement for long screens"),
    ("spotlight", "Spotlight", "Highlight the most important UI area"),
    ("zoom_pan", "Zoom and pan", "Stronger camera movement, no cursor"),
]


def _suffix_after(custom_id: str, prefix: str) -> str:
    if not custom_id.startswith(prefix):
        raise ValueError(f"not a {prefix!r} custom_id: {custom_id!r}")
    suffix = custom_id[len(prefix):]
    if not suffix:
        raise ValueError(f"{prefix!r} custom_id has no value: {custom_id!r}")
    return suffix


def build_video_embed() -> dict:
    return {
        "title": "AIUI Video Studio",
        "color": ROBOTIC_CYAN,
        "description": (
            "**Turn a website or screenshots into a narrated walkthrough.**\n"
            "```\n"
            "1. Click New video to open your private thread.\n"
            "2. Choose your source: paste a website link (we screenshot it for you),\n"
            "   or drag your own images in (up to 12).\n"
            "3. Add a short description of what the walkthrough should show.\n"
            "4. Click Generate video. Style and voice are optional - good defaults are set.\n"
            "```"
        ),
        "footer": {"text": "AIUI · video generation"},
    }


def build_video_panel() -> dict:
    return {"content": "", "components": [
        {"type": ACTION_ROW, "components": [
            _button("New video", NEW_ID, STYLE_SUCCESS),
            _button("My videos", LIST_ID, STYLE_PRIMARY),
        ]},
    ]}


def build_details_modal(job_id: str) -> dict:
    return {
        "title": "Title & description"[:45],
        "custom_id": f"{DETAILS_MODAL_PREFIX}{job_id}",
        "components": [
            {"type": ACTION_ROW, "components": [{
                "type": TEXT_INPUT, "custom_id": TITLE_INPUT,
                "label": "Title (optional)", "style": TEXT_SHORT, "required": False,
                "max_length": 200, "placeholder": "e.g. Dashboard walkthrough",
            }]},
            {"type": ACTION_ROW, "components": [{
                "type": TEXT_INPUT, "custom_id": PROMPT_INPUT,
                "label": "Describe the narrated walkthrough",
                "style": TEXT_PARAGRAPH, "required": True, "max_length": 2000,
                "placeholder": "Walk the dashboard, highlight the charts, end on export.",
            }]},
        ],
    }


def build_capture_modal(job_id: str) -> dict:
    return {
        "title": "Paste your site link"[:45],
        "custom_id": f"{CAPTURE_MODAL_PREFIX}{job_id}",
        "components": [
            {"type": ACTION_ROW, "components": [{
                "type": TEXT_INPUT, "custom_id": URL_INPUT,
                "label": "Your site URL", "style": TEXT_SHORT, "required": True,
                "max_length": 500, "placeholder": "https://yoursite.com",
            }]},
        ],
    }


def build_refine_modal(job_id: str) -> dict:
    return {
        "title": "Refine video"[:45],
        "custom_id": f"{REFINE_MODAL_PREFIX}{job_id}",
        "components": [
            {"type": ACTION_ROW, "components": [{
                "type": TEXT_INPUT, "custom_id": REFINE_INPUT,
                "label": "What should change?", "style": TEXT_PARAGRAPH,
                "required": True, "max_length": 2000,
                "placeholder": "e.g. slow down scene 2 and use a warmer tone",
            }]},
        ],
    }


def build_style_select(job_id: str, current: str = "clean_product_demo") -> dict:
    options = [{
        "label": label, "value": key, "description": desc[:100],
        "default": key == current,
    } for key, label, desc in STYLES]
    return {"type": SELECT_MENU, "custom_id": f"{STYLE_PREFIX}{job_id}",
            "placeholder": "Pick a style…", "min_values": 1, "max_values": 1,
            "options": options}


def build_voice_select(job_id: str, voices: list[dict], current: str = "amy") -> dict:
    options = []
    for v in voices[:25]:
        vid = v.get("id")
        if not vid:
            continue
        label = f"{v.get('label', vid)} — {v.get('accent','')} {v.get('gender','')}".strip()
        options.append({"label": label[:100], "value": vid[:100],
                        "default": vid == current})
    return {"type": SELECT_MENU, "custom_id": f"{VOICE_PREFIX}{job_id}",
            "placeholder": "Pick a voice…", "min_values": 1, "max_values": 1,
            "options": options}


def build_mode_select(job_id: str, current: str = "remotion") -> dict:
    options = [
        {"label": "Animated (recommended)", "value": "remotion",
         "description": "Remotion kinetic text, cursor, and motion"[:100],
         "default": current == "remotion"},
        {"label": "Simple animation", "value": "animated",
         "description": "In-container kinetic text and motion"[:100],
         "default": current == "animated"},
        {"label": "Slideshow", "value": "slideshow",
         "description": "Plain narrated screenshot slideshow"[:100],
         "default": current == "slideshow"},
    ]
    return {"type": SELECT_MENU, "custom_id": f"{MODE_PREFIX}{job_id}",
            "placeholder": "Output format", "min_values": 1, "max_values": 1,
            "options": options}


def build_animation_select(job_id: str, current: str = "cursor_click") -> dict:
    options = [{
        "label": label, "value": key, "description": desc[:100],
        "default": key == current,
    } for key, label, desc in ANIMATIONS]
    return {"type": SELECT_MENU, "custom_id": f"{ANIMATION_PREFIX}{job_id}",
            "placeholder": "Animation style", "min_values": 1, "max_values": 1,
            "options": options}


def build_source_components(job_id: str) -> list[dict]:
    return [{"type": ACTION_ROW, "components": [
        _button("From a website", f"{SRC_URL_PREFIX}{job_id}", STYLE_PRIMARY),
        _button("From my screenshots", f"{SRC_SHOTS_PREFIX}{job_id}", STYLE_SECONDARY),
    ]}]


def build_upload_components(job_id: str) -> list[dict]:
    return [{"type": ACTION_ROW, "components": [
        _button("Continue", f"{SRC_SHOTS_CONTINUE_PREFIX}{job_id}", STYLE_SUCCESS)]}]


def build_describe_components(job_id: str) -> list[dict]:
    return [{"type": ACTION_ROW, "components": [
        _button("Add description", f"{DETAILS_PREFIX}{job_id}", STYLE_PRIMARY)]}]


def build_choice_components(job_id: str) -> list[dict]:
    return [{"type": ACTION_ROW, "components": [
        _button("Generate now", f"{GENNOW_PREFIX}{job_id}", STYLE_SUCCESS),
        _button("Add direction", f"{DETAILS_PREFIX}{job_id}", STYLE_SECONDARY)]}]


def build_generate_step_components(job_id: str) -> list[dict]:
    return [{"type": ACTION_ROW, "components": [
        _button("Generate video", f"{GENERATE_PREFIX}{job_id}", STYLE_SUCCESS),
        _button("Style & voice", f"{OPTIONS_PREFIX}{job_id}", STYLE_SECONDARY)]}]


def build_options_components(job_id: str, voices: list[dict],
                             current_style: str = "clean_product_demo",
                             current_voice: str = "amy",
                             current_mode: str = "remotion",
                             current_animation: str = "cursor_click") -> list[dict]:
    return [
        {"type": ACTION_ROW, "components": [build_style_select(job_id, current_style)]},
        {"type": ACTION_ROW, "components": [build_voice_select(job_id, voices, current_voice)]},
        {"type": ACTION_ROW, "components": [build_mode_select(job_id, current_mode)]},
        {"type": ACTION_ROW, "components": [build_animation_select(job_id, current_animation)]},
        {"type": ACTION_ROW, "components": [
            _button("Generate video", f"{GENERATE_PREFIX}{job_id}", STYLE_SUCCESS),
            _button("Back", f"{OPTIONS_BACK_PREFIX}{job_id}", STYLE_SECONDARY)]},
    ]


def build_done_components(job_id: str, versions: list[dict]) -> list[dict]:
    rows = [{"type": ACTION_ROW, "components": [
        _button("Refine", f"{REFINE_PREFIX}{job_id}", STYLE_PRIMARY)]}]
    opts = []
    for v in (versions or [])[:25]:
        n = v.get("version_no")
        if n is None:
            continue
        opts.append({"label": f"Version {n}" + (" (current)" if v.get("current") else ""),
                     "value": str(n)})
    if opts:
        rows.append({"type": ACTION_ROW, "components": [{
            "type": SELECT_MENU, "custom_id": f"{VERSION_PREFIX}{job_id}",
            "placeholder": "Revert to a version…", "min_values": 1, "max_values": 1,
            "options": opts}]})
    return rows


def build_proposal_components(job_id: str) -> list[dict]:
    return [{"type": ACTION_ROW, "components": [
        _button("Apply this change", f"{APPLY_PREFIX}{job_id}", STYLE_SUCCESS)]}]


# --- predicates / extractors ---
def is_vid_new(c: str) -> bool: return c == NEW_ID
def is_vid_list(c: str) -> bool: return c == LIST_ID
def is_vid_details(c: str) -> bool: return c.startswith(DETAILS_PREFIX)
def is_vid_details_modal(c: str) -> bool: return c.startswith(DETAILS_MODAL_PREFIX)
def is_vid_capture(c: str) -> bool: return c.startswith(CAPTURE_PREFIX)
def is_vid_capture_modal(c: str) -> bool: return c.startswith(CAPTURE_MODAL_PREFIX)
def is_vid_style(c: str) -> bool: return c.startswith(STYLE_PREFIX)
def is_vid_voice(c: str) -> bool: return c.startswith(VOICE_PREFIX)
def is_vid_mode(c: str) -> bool: return c.startswith(MODE_PREFIX)
def is_vid_animation(c: str) -> bool: return c.startswith(ANIMATION_PREFIX)
def is_vid_generate(c: str) -> bool: return c.startswith(GENERATE_PREFIX)
def is_vid_gennow(c: str) -> bool: return c.startswith(GENNOW_PREFIX)
def job_from_gennow(c: str) -> str: return _suffix_after(c, GENNOW_PREFIX)
def is_vid_refine(c: str) -> bool: return c.startswith(REFINE_PREFIX)
def is_vid_refine_modal(c: str) -> bool: return c.startswith(REFINE_MODAL_PREFIX)
def is_vid_apply(c: str) -> bool: return c.startswith(APPLY_PREFIX)
def is_vid_version(c: str) -> bool: return c.startswith(VERSION_PREFIX)

def job_from_style(c: str) -> str: return _suffix_after(c, STYLE_PREFIX)
def job_from_voice(c: str) -> str: return _suffix_after(c, VOICE_PREFIX)
def job_from_mode(c: str) -> str: return _suffix_after(c, MODE_PREFIX)
def job_from_animation(c: str) -> str: return _suffix_after(c, ANIMATION_PREFIX)
def job_from_generate(c: str) -> str: return _suffix_after(c, GENERATE_PREFIX)
def job_from_details(c: str) -> str: return _suffix_after(c, DETAILS_PREFIX)
def job_from_details_modal(c: str) -> str: return _suffix_after(c, DETAILS_MODAL_PREFIX)
def job_from_capture(c: str) -> str: return _suffix_after(c, CAPTURE_PREFIX)
def job_from_capture_modal(c: str) -> str: return _suffix_after(c, CAPTURE_MODAL_PREFIX)
def job_from_refine(c: str) -> str: return _suffix_after(c, REFINE_PREFIX)
def job_from_refine_modal(c: str) -> str: return _suffix_after(c, REFINE_MODAL_PREFIX)
def job_from_apply(c: str) -> str: return _suffix_after(c, APPLY_PREFIX)
def job_from_version(c: str) -> str: return _suffix_after(c, VERSION_PREFIX)

def is_vid_src_url(c: str) -> bool: return c.startswith(SRC_URL_PREFIX)
def is_vid_src_shots(c: str) -> bool: return c.startswith(SRC_SHOTS_PREFIX)
def is_vid_src_shots_continue(c: str) -> bool: return c.startswith(SRC_SHOTS_CONTINUE_PREFIX)
def is_vid_options(c: str) -> bool: return c.startswith(OPTIONS_PREFIX)
def is_vid_options_back(c: str) -> bool: return c.startswith(OPTIONS_BACK_PREFIX)

def job_from_src_url(c: str) -> str: return _suffix_after(c, SRC_URL_PREFIX)
def job_from_src_shots(c: str) -> str: return _suffix_after(c, SRC_SHOTS_PREFIX)
def job_from_src_shots_continue(c: str) -> str: return _suffix_after(c, SRC_SHOTS_CONTINUE_PREFIX)
def job_from_options(c: str) -> str: return _suffix_after(c, OPTIONS_PREFIX)
def job_from_options_back(c: str) -> str: return _suffix_after(c, OPTIONS_BACK_PREFIX)
