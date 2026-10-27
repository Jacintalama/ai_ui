"""An agent's face: the office robot, as a picture (2026-10-27).

The office draws every agent as a robot in a colour of its own
(static/office/js/agent.js: the hue comes from the name, the face from the
state). In the main chat the same agent answered under Open WebUI's grey
default avatar, so a person could not tell Ada's reply from Mia's at a
glance. This draws the same robot, head and shoulders, as an SVG data URI:
once for the model's profile picture (meta.profile_image_url, set when an
agent is made and backfilled for the ones that exist) and once, small, at
the top of a reply the Auto model routed to an agent.

Pure, deterministic and dependency free: the same name always gives the
same face, which is what makes the chat and the office agree.
"""
from __future__ import annotations

import base64
from xml.sax.saxutils import escape as _xml_escape


def hue_of(name: str) -> int:
    """agent.js nameHue, exactly: the string's chars folded into 0..359."""
    h = 0
    for ch in str(name or ""):
        h = (h * 31 + ord(ch)) % 360
    return h


def palette(name: str) -> dict:
    """agent.js ownPalette for this name."""
    h = hue_of(name)
    return {"accent": f"hsl({h}, 70%, 66%)", "body": f"hsl({h}, 45%, 32%)",
            "body2": f"hsl({h}, 45%, 24%)"}


def _face(a: dict) -> str:
    # The "ready" face: the one the office shows at a quiet desk.
    return (f'<path d="M50 72 Q58 63 66 72" stroke="{a["accent"]}" stroke-width="3.2" fill="none" stroke-linecap="round"/>'
            f'<path d="M74 72 Q82 63 90 72" stroke="{a["accent"]}" stroke-width="3.2" fill="none" stroke-linecap="round"/>'
            f'<path d="M58 83 Q70 93 82 83 Z" fill="{a["accent"]}" opacity=".9"/>')


def svg(agent_id: str, name: str, size: int | None = None) -> str:
    """The robot's head and shoulders, on a round backdrop, as SVG text.

    The drawing is agent.js robot() cut to the head (its viewBox 22 0 96 96
    of that figure's 4 0 132 182), so the chat avatar is the office face.
    `size` sets width and height on the root, which is the natural size an
    <img> takes; left out, the picture fills whatever frame it is in."""
    a = palette(name)
    uid = "g" + "".join(c for c in str(agent_id or "a") if c.isalnum())[:40]
    dims = f' width="{int(size)}" height="{int(size)}"' if size else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="22 0 96 96"{dims} role="img" aria-label="{_xml_escape(str(name or ""), {chr(34): "&quot;"})}">'
        f'<defs><linearGradient id="{uid}" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0%" stop-color="{a["body"]}"/><stop offset="100%" stop-color="{a["body2"]}"/></linearGradient></defs>'
        '<circle cx="70" cy="48" r="48" fill="#101a2e"/>'
        # Shoulders, so the head is not floating.
        f'<rect x="34" y="90" width="72" height="30" rx="18" fill="{a["body"]}"/>'
        # Neck and antenna.
        f'<rect x="62" y="14" width="16" height="34" rx="8" fill="url(#{uid})"/>'
        f'<line x1="70" y1="6" x2="70" y2="16" stroke="{a["accent"]}" stroke-width="3" stroke-linecap="round"/>'
        f'<circle cx="70" cy="6" r="5" fill="{a["accent"]}"/>'
        # The head, its screen and the face.
        f'<rect x="30" y="46" width="80" height="46" rx="16" fill="url(#{uid})"/>'
        '<rect x="42" y="58" width="56" height="24" rx="8" fill="#0c1220"/>'
        f'{_face(a)}'
        f'<rect x="44" y="15" width="10" height="24" rx="5" fill="{a["accent"]}" opacity=".8"/>'
        f'<rect x="86" y="15" width="10" height="24" rx="5" fill="{a["accent"]}" opacity=".8"/>'
        '</svg>'
    )


def data_uri(agent_id: str, name: str, size: int | None = None) -> str:
    """The picture as a data: URL, base64 so no character needs quoting."""
    raw = svg(agent_id, name, size).encode("utf-8")
    return "data:image/svg+xml;base64," + base64.b64encode(raw).decode("ascii")


#: The size of the robot at the top of a reply in the chat: a line's height.
REPLY_SIZE = 28


def reply_face(agent_id: str, name: str) -> str:
    """The markdown that opens a routed reply: the small robot and the name,
    on one line, so the person sees who answered before reading."""
    label = str(name or agent_id or "Agent")
    safe = label.replace("]", "").replace("[", "")
    return f"![{safe}]({data_uri(agent_id, label, REPLY_SIZE)}) **{label}**"
