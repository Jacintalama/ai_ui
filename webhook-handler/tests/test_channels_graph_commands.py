"""`/aiui channels` and `/aiui graph` on Discord and Slack.

Two pages exist on the web that neither bot could reach: Channels (which chat
platforms this account has linked to IO, and how to link the rest) and Graph
(the per-user knowledge graph built from chats). Every other web feature the
bots expose (App Builder, cron, video) is a native command, not a link, so
these follow the same shape: one handler in CommandRouter, rendered as plain
text so the same code serves both platforms, with the web URL at the end for
the parts a chat message cannot show.

Both are read-only. Linking a channel involves a pairing step that belongs on
the web page; rebuilding a graph is a button there too. YAGNI.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from clients.tasks import TasksAPIError
from handlers.commands import CommandContext, CommandRouter, NATURAL


def _router():
    return CommandRouter(
        openwebui_client=MagicMock(),
        n8n_client=MagicMock(api_key=""),
        discord_user_email_map={},
        tasks_client=MagicMock(),
    )


def _ctx(subcommand, arguments="", platform="discord", captured=None):
    captured = captured if captured is not None else []

    async def respond(m):
        captured.append(m)
    return CommandContext(
        user_id="100", user_name="t", channel_id="c",
        raw_text=f"{subcommand} {arguments}".strip(),
        subcommand=subcommand, arguments=arguments, platform=platform,
        respond=respond, metadata={},
    ), captured


# ---------------------------------------------------------------------------
# Parsing: the words must be recognised, or they fall through to "ask"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("channels", ("channels", "")),
    ("graph", ("graph", "")),
    ("graph my portfolio site", ("graph", "my portfolio site")),
    ("Channels", ("channels", "")),
])
def test_the_words_parse_as_commands(text, expected):
    assert CommandRouter.parse_command(text) == expected


def test_unrelated_text_is_still_natural_language():
    assert CommandRouter.parse_command("what is a graph")[0] == NATURAL


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("sub,handler", [("channels", "_handle_channels"), ("graph", "_handle_graph")])
async def test_execute_routes_to_the_handler(sub, handler):
    r = _router()
    setattr(r, handler, AsyncMock())
    ctx, _ = _ctx(sub)
    await r.execute(ctx)
    getattr(r, handler).assert_called_once_with(ctx)


# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------

CONNECTIONS = {
    "telegram_bot": "@io_bot",
    "connections": [
        {"platform": "telegram", "label": "Telegram", "linked_at": "2026-08-30T10:00:00+00:00",
         "name": "jacint_t"},
        {"platform": "cli", "label": "Terminal", "linked_at": None, "name": ""},
        {"platform": "discord", "label": "Discord", "linked_at": "2026-06-01T00:00:00+00:00",
         "name": ""},
    ],
}


@pytest.mark.asyncio
async def test_channels_lists_linked_and_unlinked_with_the_web_link():
    r = _router()
    r._resolve_email_for_ctx = AsyncMock(return_value="me@example.com")
    r._tasks_client.get_channel_connections = AsyncMock(return_value=CONNECTIONS)
    ctx, out = _ctx("channels")
    await r._handle_channels(ctx)
    r._tasks_client.get_channel_connections.assert_awaited_once_with("me@example.com")
    text = "\n".join(out)
    assert "Telegram" in text and "jacint_t" in text
    assert "Terminal" in text and "not linked" in text
    assert "Discord" in text
    assert "https://ai-ui.coolestdomain.win/channel" in text


@pytest.mark.asyncio
async def test_channels_reads_the_same_on_slack():
    r = _router()
    r._resolve_email_for_ctx = AsyncMock(return_value="me@example.com")
    r._tasks_client.get_channel_connections = AsyncMock(return_value=CONNECTIONS)
    ctx, out = _ctx("channels", platform="slack")
    await r._handle_channels(ctx)
    assert "Telegram" in "\n".join(out)


@pytest.mark.asyncio
async def test_channels_without_an_email_uses_the_not_linked_flow():
    r = _router()
    r._resolve_email_for_ctx = AsyncMock(return_value=None)
    r._respond_not_linked = AsyncMock()
    r._tasks_client.get_channel_connections = AsyncMock()
    ctx, _ = _ctx("channels")
    await r._handle_channels(ctx)
    r._respond_not_linked.assert_awaited_once_with(ctx)
    r._tasks_client.get_channel_connections.assert_not_called()


@pytest.mark.asyncio
async def test_channels_api_failure_is_one_friendly_line():
    r = _router()
    r._resolve_email_for_ctx = AsyncMock(return_value="me@example.com")
    r._tasks_client.get_channel_connections = AsyncMock(
        side_effect=TasksAPIError(503, "tasks service unreachable"))
    ctx, out = _ctx("channels")
    await r._handle_channels(ctx)
    assert len(out) == 1
    assert "channels" in out[0].lower()
    assert "Traceback" not in out[0]


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

GRAPH = {"nodes": [], "links": [], "count": 42,
         "counts": {"person": 10, "project": 7, "topic": 25},
         "auto_refresh": False, "truncated": False}


@pytest.mark.asyncio
async def test_graph_with_no_topic_summarises_and_links():
    r = _router()
    r._resolve_email_for_ctx = AsyncMock(return_value="me@example.com")
    r._tasks_client.get_knowledge_graph = AsyncMock(return_value=GRAPH)
    ctx, out = _ctx("graph")
    await r._handle_graph(ctx)
    r._tasks_client.get_knowledge_graph.assert_awaited_once_with("me@example.com")
    text = "\n".join(out)
    assert "42" in text
    assert "person: 10" in text and "project: 7" in text and "topic: 25" in text
    assert "https://ai-ui.coolestdomain.win/tasks/graph" in text


@pytest.mark.asyncio
async def test_graph_that_is_empty_says_so_instead_of_zero_by_type():
    r = _router()
    r._resolve_email_for_ctx = AsyncMock(return_value="me@example.com")
    r._tasks_client.get_knowledge_graph = AsyncMock(
        return_value={"nodes": [], "links": [], "count": 0, "counts": {}})
    ctx, out = _ctx("graph")
    await r._handle_graph(ctx)
    text = "\n".join(out)
    assert "empty" in text.lower()
    assert "https://ai-ui.coolestdomain.win/tasks/graph" in text


@pytest.mark.asyncio
async def test_graph_with_a_topic_returns_the_context():
    r = _router()
    r._resolve_email_for_ctx = AsyncMock(return_value="me@example.com")
    r._tasks_client.get_graph_context = AsyncMock(
        return_value={"context": "Portfolio site: built 2026-08-24, uses Supabase.",
                      "count": 3, "used": True})
    ctx, out = _ctx("graph", "portfolio")
    await r._handle_graph(ctx)
    r._tasks_client.get_graph_context.assert_awaited_once_with("me@example.com", "portfolio")
    text = "\n".join(out)
    assert "Portfolio site: built 2026-08-24" in text
    assert "portfolio" in text


@pytest.mark.asyncio
async def test_graph_with_an_unknown_topic_says_nothing_yet():
    r = _router()
    r._resolve_email_for_ctx = AsyncMock(return_value="me@example.com")
    r._tasks_client.get_graph_context = AsyncMock(
        return_value={"context": "", "count": 0, "used": False})
    ctx, out = _ctx("graph", "quantum knitting")
    await r._handle_graph(ctx)
    text = "\n".join(out).lower()
    assert "quantum knitting" in text
    assert "nothing" in text or "no " in text


@pytest.mark.asyncio
async def test_graph_without_an_email_uses_the_not_linked_flow():
    r = _router()
    r._resolve_email_for_ctx = AsyncMock(return_value=None)
    r._respond_not_linked = AsyncMock()
    ctx, _ = _ctx("graph")
    await r._handle_graph(ctx)
    r._respond_not_linked.assert_awaited_once_with(ctx)


@pytest.mark.asyncio
async def test_graph_api_failure_is_one_friendly_line():
    r = _router()
    r._resolve_email_for_ctx = AsyncMock(return_value="me@example.com")
    r._tasks_client.get_knowledge_graph = AsyncMock(side_effect=TasksAPIError(500, "boom"))
    ctx, out = _ctx("graph")
    await r._handle_graph(ctx)
    assert len(out) == 1
    assert "graph" in out[0].lower()
    assert "Traceback" not in out[0]


# ---------------------------------------------------------------------------
# Discoverable
# ---------------------------------------------------------------------------

def test_help_mentions_both():
    text = CommandRouter._help_text()
    assert "/aiui channels" in text
    assert "/aiui graph" in text
