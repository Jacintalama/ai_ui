"""Mattermost: what counts as a message, and what must never be one.

The mistakes available here are the ones every socket channel offers, plus one
of Mattermost's own: the post arrives as a JSON STRING nested inside the event,
so a parser that reads `data.post.message` finds nothing and the channel is
silently deaf.
"""
import json

import pytest

from gateway.platforms.mattermost import (MattermostAdapter, MattermostSocket,
                                          ws_url)


def _event(text="hello", user="u1", channel="d1", ctype="D",
           post_type="", from_bot=False, sender="@ralph"):
    post = {"id": "p1", "user_id": user, "channel_id": channel,
            "message": text, "type": post_type,
            "props": {"from_bot": "true"} if from_bot else {}}
    return {"event": "posted",
            "data": {"channel_type": ctype, "sender_name": sender,
                     # Mattermost's own shape: a JSON string, not an object.
                     "post": json.dumps(post)}}


@pytest.fixture
def adapter():
    return MattermostAdapter(client=None)


def test_a_direct_message_is_understood(adapter):
    ev = adapter.parse_inbound(_event(), {})
    assert ev is not None
    assert ev.text == "hello"
    assert ev.source.platform == "mattermost"
    assert ev.source.chat_type == "dm"
    assert ev.source.user_id == "u1"
    assert ev.source.chat_id == "d1"
    assert ev.source.user_name == "ralph", "the @ should not reach the model"


def test_the_post_is_read_out_of_its_json_string(adapter):
    """Mattermost nests the post as a STRING. Reading it as an object finds
    nothing, and the channel is deaf without a single error anywhere."""
    ev = adapter.parse_inbound(_event(text="from inside the string"), {})
    assert ev.text == "from inside the string"


def test_a_team_channel_is_never_answered(adapter):
    """The Brain is injected into every model call, so answering in a team
    channel would print one person's private memory to the room."""
    for ctype in ("O", "P", "G"):
        assert adapter.parse_inbound(_event(ctype=ctype), {}) is None


def test_the_bots_own_post_is_ignored(adapter):
    """It arrives back on the bot's own socket. Without this the bot answers
    itself, forever."""
    assert adapter.parse_inbound(_event(from_bot=True), {}) is None


def test_a_system_post_is_ignored(adapter):
    """Joins, leaves, header changes: every system post carries a type."""
    assert adapter.parse_inbound(_event(post_type="system_join_channel"), {}) is None


def test_an_empty_message_is_not_a_message(adapter):
    assert adapter.parse_inbound(_event(text="   "), {}) is None


def test_junk_never_raises(adapter):
    for payload in (None, {}, {"event": "posted"}, {"event": "typing"},
                    {"event": "posted", "data": {"channel_type": "D",
                                                 "post": "not json"}}):
        assert adapter.parse_inbound(payload, {}) is None


@pytest.mark.parametrize("base,expected", [
    ("https://mm.example.com", "wss://mm.example.com/api/v4/websocket"),
    ("http://localhost:8065", "ws://localhost:8065/api/v4/websocket"),
    ("https://mm.example.com/", "wss://mm.example.com/api/v4/websocket"),
])
def test_the_socket_url_is_derived_from_the_users_server(base, expected):
    assert ws_url(base) == expected


# --- the socket ---------------------------------------------------------

def _socket(allow=lambda _u: True):
    seen = []

    async def on_event(conn, frame):
        seen.append(frame)

    s = MattermostSocket("k", "https://mm.example.com", "tok", on_event,
                         allow=allow)
    s.seen = seen
    return s


async def test_hello_is_what_makes_it_connected():
    s = _socket()
    assert s.connected is False
    await s._on_frame(json.dumps({"event": "hello"}))
    assert s.connected is True


async def test_a_rejected_token_is_raised_rather_than_ignored():
    """Mattermost answers a bad token with a normal reply carrying a status,
    not by refusing the upgrade, so without this a wrong token looks exactly
    like a socket that opened and then said nothing."""
    s = _socket()
    with pytest.raises(PermissionError):
        await s._on_frame(json.dumps({"status": "FAIL", "seq_reply": 1}))


async def test_only_the_people_the_owner_allowed_are_answered():
    s = _socket(allow=lambda u: u == "yes")
    await s._on_frame(json.dumps(_event(user="no")))
    assert s.seen == []
    await s._on_frame(json.dumps(_event(user="yes")))
    assert len(s.seen) == 1


async def test_a_frame_that_is_not_a_post_is_skipped():
    s = _socket()
    await s._on_frame(json.dumps({"event": "typing", "data": {}}))
    await s._on_frame("not json at all")
    assert s.seen == []
