"""Slack #graph panel. Block Kit analog of graph_panel.py (Discord).

Pure builders. "My graph" and the modal's submit are answered ephemerally by
CommandRouter._handle_graph; the link button opens the drawn graph on the web.
The origin channel rides in the modal's private_metadata so the submit
handler knows where the ephemeral reply goes, the same trick the App Builder
modal uses.
"""

MY_ACTION_ID = "graph_my"
ASK_ACTION_ID = "graph_ask"
OPEN_ACTION_ID = "graph_open"  # url button; the posted action no-ops
ASK_MODAL_ID = "graph_ask_modal"
TOPIC_BLOCK_ID = "graph_topic"
TOPIC_INPUT_ID = "topic"

_BUTTON_TEXT_MAX = 75
_TITLE_MAX = 24


def graph_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/tasks/graph"


def _button(text: str, action_id: str, *, primary: bool = False) -> dict:
    btn = {
        "type": "button",
        "text": {"type": "plain_text", "text": text[:_BUTTON_TEXT_MAX]},
        "action_id": action_id,
    }
    if primary:
        btn["style"] = "primary"
    return btn


def _link_button(text: str, action_id: str, url: str) -> dict:
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": text[:_BUTTON_TEXT_MAX]},
        "action_id": action_id,
        "url": url,
    }


def build_graph_blocks(base_url: str) -> list[dict]:
    return [
        {"type": "header", "text": {"type": "plain_text", "text": "Graph"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": (
            "Your personal knowledge graph, built from your chats.\n"
            "• *My graph* — what IO knows, by type\n"
            "• *Ask the graph* — what it knows about a topic\n"
            "• *Open the graph* — the full picture on the web")}},
        {"type": "actions", "elements": [
            _button("My graph", MY_ACTION_ID, primary=True),
            _button("Ask the graph", ASK_ACTION_ID),
            _link_button("Open the graph", OPEN_ACTION_ID, graph_url(base_url)),
        ]},
    ]


def build_ask_modal(origin_channel: str) -> dict:
    return {
        "type": "modal",
        "callback_id": ASK_MODAL_ID,
        "private_metadata": origin_channel or "",
        "title": {"type": "plain_text", "text": "Ask your graph"[:_TITLE_MAX]},
        "submit": {"type": "plain_text", "text": "Ask"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": TOPIC_BLOCK_ID,
                "label": {"type": "plain_text", "text": "Topic"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": TOPIC_INPUT_ID,
                    "max_length": 200,
                    "placeholder": {"type": "plain_text", "text": "e.g. my portfolio site"},
                },
            }
        ],
    }


def topic_from_view(view: dict) -> str:
    values = (view.get("state") or {}).get("values") or {}
    block = values.get(TOPIC_BLOCK_ID) or {}
    return ((block.get(TOPIC_INPUT_ID) or {}).get("value") or "").strip()
