"""The wire rules for a user's own Slack app and Discord bot.

Both are held-open sockets rather than webhooks, so the mistakes available here
are different from anything the existing adapters can make: acking late,
answering a message three times, connecting with an intent the owner never
granted, or answering somebody the owner never allowed.
"""
import json

import pytest

from gateway.platforms.slack_socket import SlackSocket


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


def _socket(allow=lambda _uid: True, on_event=None):
    seen = []

    async def default(conn, event):
        seen.append(event)

    s = SlackSocket("k", "xoxb-not-real", "xapp-not-real",
                    on_event or default, allow=allow)
    s.seen = seen
    return s


def _envelope(user="U1", text="hi", envelope_id="e1", ev_type="message"):
    return json.dumps({
        "type": "events_api", "envelope_id": envelope_id,
        "payload": {"type": "event_callback",
                    "event": {"type": ev_type, "user": user, "text": text,
                              "channel": "D1", "channel_type": "im"}},
    })


# --- Slack --------------------------------------------------------------

async def test_hello_is_what_makes_it_connected():
    s = _socket()
    assert s.connected is False
    await s._on_frame(FakeWS(), json.dumps({"type": "hello"}))
    assert s.connected is True
    assert s.last_error == ""


async def test_an_event_is_acked_before_it_is_handled():
    """Slack retries an unacked envelope up to three times, so doing the work
    first means a slow message gets answered three times over."""
    order = []

    class Recorder(FakeWS):
        async def send(self, raw):
            order.append("ack")
            await super().send(raw)

    async def on_event(conn, event):
        order.append("work")

    s = _socket(on_event=on_event)
    ws = Recorder()
    await s._on_frame(ws, _envelope())
    assert order == ["ack", "work"]
    assert ws.sent == [{"envelope_id": "e1"}]


async def test_an_ignored_event_is_still_acked():
    """Not acking something we chose to ignore just makes Slack send it twice
    more before giving up."""
    s = _socket(allow=lambda _uid: False)
    ws = FakeWS()
    await s._on_frame(ws, _envelope())
    assert ws.sent == [{"envelope_id": "e1"}]
    assert s.seen == []


async def test_only_the_people_the_owner_allowed_are_answered():
    s = _socket(allow=lambda uid: uid == "U_ALLOWED")
    await s._on_frame(FakeWS(), _envelope(user="U_STRANGER"))
    assert s.seen == []
    await s._on_frame(FakeWS(), _envelope(user="U_ALLOWED"))
    assert len(s.seen) == 1


async def test_a_non_message_event_is_not_treated_as_one():
    s = _socket()
    await s._on_frame(FakeWS(), _envelope(ev_type="reaction_added"))
    assert s.seen == []


async def test_a_disconnect_ends_the_session_so_the_loop_redials():
    """Slack cycles these connections roughly hourly. It is routine, so it
    must not be recorded as an error or backed off."""
    s = _socket()
    with pytest.raises(ConnectionResetError):
        await s._on_frame(FakeWS(), json.dumps({"type": "disconnect",
                                                "reason": "refresh_requested"}))


async def test_junk_on_the_wire_is_ignored_rather_than_fatal():
    s = _socket()
    for raw in ("not json at all", json.dumps([1, 2, 3]), json.dumps({})):
        await s._on_frame(FakeWS(), raw)
    assert s.seen == []


async def test_an_event_without_an_envelope_is_still_processed():
    """Acking is best effort; refusing to handle the message because there was
    nothing to ack would drop it entirely."""
    s = _socket()
    frame = json.loads(_envelope())
    frame.pop("envelope_id")
    await s._on_frame(FakeWS(), json.dumps(frame))
    assert len(s.seen) == 1
