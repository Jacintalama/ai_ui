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
NEW_MODAL_ID = "aiuivid:newmodal"
STYLE_PREFIX = "aiuivid:style:"
VOICE_PREFIX = "aiuivid:voice:"
GENERATE_PREFIX = "aiuivid:generate:"
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


def _suffix_after(custom_id: str, prefix: str) -> str:
    if not custom_id.startswith(prefix):
        raise ValueError(f"not a {prefix!r} custom_id: {custom_id!r}")
    suffix = custom_id[len(prefix):]
    if not suffix:
        raise ValueError(f"{prefix!r} custom_id has no value: {custom_id!r}")
    return suffix


def build_video_embed() -> dict:
    return {
        "title": "AIUI · VIDEO STUDIO",
        "color": ROBOTIC_CYAN,
        "description": (
            "```\n"
            "> turn screenshots into a narrated walkthrough\n"
            "> New video -> name it, pick style + voice\n"
            "> drop your screenshots in the thread (or /video add)\n"
            "> Generate -> we render it in your private thread\n"
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


def build_video_modal() -> dict:
    return {
        "title": "New video"[:45],
        "custom_id": NEW_MODAL_ID,
        "components": [
            {"type": ACTION_ROW, "components": [{
                "type": TEXT_INPUT, "custom_id": TITLE_INPUT,
                "label": "Title", "style": TEXT_SHORT, "required": True,
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


def build_studio_components(job_id: str, voices: list[dict]) -> list[dict]:
    return [
        {"type": ACTION_ROW, "components": [build_style_select(job_id)]},
        {"type": ACTION_ROW, "components": [build_voice_select(job_id, voices)]},
        {"type": ACTION_ROW, "components": [
            _button("Generate video", f"{GENERATE_PREFIX}{job_id}", STYLE_SUCCESS)]},
    ]


def build_generate_row(job_id: str) -> list[dict]:
    return [{"type": ACTION_ROW, "components": [
        _button("Generate video", f"{GENERATE_PREFIX}{job_id}", STYLE_SUCCESS)]}]


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
def is_vid_new_modal(c: str) -> bool: return c == NEW_MODAL_ID
def is_vid_style(c: str) -> bool: return c.startswith(STYLE_PREFIX)
def is_vid_voice(c: str) -> bool: return c.startswith(VOICE_PREFIX)
def is_vid_generate(c: str) -> bool: return c.startswith(GENERATE_PREFIX)
def is_vid_refine(c: str) -> bool: return c.startswith(REFINE_PREFIX)
def is_vid_refine_modal(c: str) -> bool: return c.startswith(REFINE_MODAL_PREFIX)
def is_vid_apply(c: str) -> bool: return c.startswith(APPLY_PREFIX)
def is_vid_version(c: str) -> bool: return c.startswith(VERSION_PREFIX)

def job_from_style(c: str) -> str: return _suffix_after(c, STYLE_PREFIX)
def job_from_voice(c: str) -> str: return _suffix_after(c, VOICE_PREFIX)
def job_from_generate(c: str) -> str: return _suffix_after(c, GENERATE_PREFIX)
def job_from_refine(c: str) -> str: return _suffix_after(c, REFINE_PREFIX)
def job_from_refine_modal(c: str) -> str: return _suffix_after(c, REFINE_MODAL_PREFIX)
def job_from_apply(c: str) -> str: return _suffix_after(c, APPLY_PREFIX)
def job_from_version(c: str) -> str: return _suffix_after(c, VERSION_PREFIX)
