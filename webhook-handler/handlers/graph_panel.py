"""#graph: the web Graph page as a pinned Discord panel.

Pure builders and custom_id predicates, mirroring cronjob_panel.py. The graph
is the per-user knowledge graph built from chats. A message can show a summary
and answer "what do you know about X"; drawing it belongs on the page. Replies
are rendered by CommandRouter._handle_graph, shared with `/aiui graph`.
"""

_PREFIX = "graph"

# custom_ids
MY = f"{_PREFIX}:my"
ASK = f"{_PREFIX}:ask"
ASK_MODAL = f"{_PREFIX}:askmodal"
TOPIC_INPUT = "topic"  # the modal's text input custom_id


def is_graph(custom_id: str) -> bool:
    return custom_id.split(":", 1)[0] == _PREFIX


def is_my(custom_id: str) -> bool:
    return custom_id == MY


def is_ask(custom_id: str) -> bool:
    return custom_id == ASK


def is_ask_modal(custom_id: str) -> bool:
    return custom_id == ASK_MODAL


def graph_url(base_url: str) -> str:
    """The standalone page, which serves 200 on its own outside the shell."""
    return f"{base_url.rstrip('/')}/tasks/graph"


def build_panel_payload(base_url: str) -> dict:
    return {
        "content": (
            "**Graph**\n"
            "Your personal knowledge graph, built from your chats.\n"
            "• **My graph** — what IO knows, by type\n"
            "• **Ask the graph** — what it knows about a topic\n"
            "• **Open the graph** — the full picture on the web"
        ),
        "components": [
            {
                "type": 1,
                "components": [
                    {"type": 2, "style": 1, "label": "My graph", "custom_id": MY},
                    {"type": 2, "style": 2, "label": "Ask the graph", "custom_id": ASK},
                    {"type": 2, "style": 5, "label": "Open the graph",
                     "url": graph_url(base_url)},
                ],
            }
        ],
    }


def build_ask_modal() -> dict:
    """One short text input. The submit is routed by ASK_MODAL."""
    return {
        "custom_id": ASK_MODAL,
        "title": "Ask your graph",
        "components": [
            {
                "type": 1,
                "components": [
                    {
                        "type": 4,
                        "custom_id": TOPIC_INPUT,
                        "style": 1,
                        "label": "Topic",
                        "min_length": 1,
                        "max_length": 200,
                        "placeholder": "e.g. my portfolio site",
                        "required": True,
                    }
                ],
            }
        ],
    }
