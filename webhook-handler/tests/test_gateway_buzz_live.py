"""The Buzz client against a real websocket, end to end.

Every other Buzz test feeds frames to the handler directly, which is the right
way to test decisions but proves nothing about the socket: whether it connects,
whether the subscription is well formed, whether an answer actually goes back
over the wire. Those are exactly the parts that fail first in production.

So this runs a minimal NIP-01 relay in-process and points the real client at
it. Deliberately not a public relay: publishing test notes to somebody's
network is a side effect a test has no business having, and a network hop would
make this flaky for no extra coverage.
"""
import asyncio
import json

import pytest
from websockets.asyncio.server import serve

from gateway import nostr, schnorr
from gateway.platforms.buzz import BuzzRelay, sign_event

AGENT = bytes.fromhex("aa" * 31 + "01")
PERSON = bytes.fromhex("bb" * 31 + "02")


class TinyRelay:
    """Enough of NIP-01 to answer a client: AUTH, REQ/EOSE, EVENT, OK."""

    def __init__(self, *, challenge: str | None = None):
        self.challenge = challenge
        self.published: list[dict] = []
        self.authed: dict | None = None
        self.filters: list[dict] = []
        self.subscribers: list = []
        self.port: int | None = None
        self._server = None

    async def start(self):
        self._server = await serve(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return f"ws://127.0.0.1:{self.port}"

    async def stop(self):
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, ws):
        if self.challenge:
            await ws.send(json.dumps(["AUTH", self.challenge]))
        self.subscribers.append(ws)
        try:
            async for raw in ws:
                frame = json.loads(raw)
                if frame[0] == "REQ":
                    self.filters.append(frame[2])
                    await ws.send(json.dumps(["EOSE", frame[1]]))
                elif frame[0] == "AUTH":
                    self.authed = frame[1]
                elif frame[0] == "EVENT":
                    self.published.append(frame[1])
                    await ws.send(json.dumps(["OK", frame[1]["id"], True, ""]))
        except Exception:                                       # noqa: BLE001
            pass

    async def deliver(self, event: dict, sub_id: str = "io"):
        for ws in list(self.subscribers):
            await ws.send(json.dumps(["EVENT", sub_id, event]))


async def _wait_for(predicate, timeout=5.0):
    """Poll until true. Beats a fixed sleep, which is either slow or flaky."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return False


@pytest.fixture
async def relay_and_client():
    relay = TinyRelay(challenge="chal-live")
    url = await relay.start()
    received = []

    async def on_event(event, adapter):
        received.append((event, adapter))

    client = BuzzRelay("live", url, AGENT, on_event)
    client.start()
    yield relay, client, received
    await client.stop()
    await relay.stop()


async def test_the_client_connects_and_subscribes_to_its_own_mentions(relay_and_client):
    relay, client, _ = relay_and_client
    assert await _wait_for(lambda: relay.filters), "never subscribed"
    f = relay.filters[0]
    assert f["#p"] == [client.pubkey], "asked for someone else's messages"
    assert f["kinds"] == [nostr.KIND_TEXT]
    # Bounded, or a reconnect replays the whole history of the workspace and
    # answers messages handled hours ago.
    assert "since" in f


async def test_the_relays_auth_challenge_is_answered_and_verifies(relay_and_client):
    relay, client, _ = relay_and_client
    assert await _wait_for(lambda: relay.authed is not None), "never authenticated"
    event = relay.authed
    assert event["kind"] == nostr.KIND_AUTH
    assert ["challenge", "chal-live"] in event["tags"]
    assert schnorr.verify(bytes.fromhex(event["id"]),
                          bytes.fromhex(event["pubkey"]),
                          bytes.fromhex(event["sig"])), "signature does not verify"


async def test_presence_is_published_once_the_relay_says_it_is_done(relay_and_client):
    relay, client, _ = relay_and_client
    assert await _wait_for(
        lambda: any(e["kind"] == nostr.KIND_PRESENCE for e in relay.published))
    presence = next(e for e in relay.published if e["kind"] == nostr.KIND_PRESENCE)
    assert presence["content"] == "online"
    assert client.connected is True


async def test_a_real_message_arrives_and_a_real_answer_goes_back(relay_and_client):
    """The whole path: a person publishes, we verify, we reply over the wire."""
    relay, client, received = relay_and_client
    assert await _wait_for(lambda: client.connected)

    person_pub = schnorr.pubkey_from_seckey(PERSON).hex()
    question = sign_event(
        nostr.unsigned_event(person_pub, nostr.KIND_TEXT, "what is on today",
                             tags=[["p", client.pubkey]]), PERSON)
    await relay.deliver(question)

    assert await _wait_for(lambda: received), "the message never reached us"
    event, adapter = received[0]
    assert event.text == "what is on today"
    assert event.source.user_id == person_pub

    # And the reply goes back through the same socket, signed and addressed.
    await adapter.send(event.source.chat_id, "three things")
    assert await _wait_for(
        lambda: any(e["content"] == "three things" for e in relay.published))
    reply = next(e for e in relay.published if e["content"] == "three things")
    assert ["p", person_pub] in reply["tags"]
    assert reply["pubkey"] == client.pubkey
    assert schnorr.verify(bytes.fromhex(reply["id"]),
                          bytes.fromhex(reply["pubkey"]),
                          bytes.fromhex(reply["sig"])), "we published a bad signature"


async def test_a_forged_message_never_reaches_the_pipeline(relay_and_client):
    # The one that matters most: the pubkey on an event decides which IO
    # account answers, so a relay that lets anyone claim any key would hand a
    # stranger somebody's memory and email.
    relay, client, received = relay_and_client
    assert await _wait_for(lambda: client.connected)

    forged = sign_event(
        nostr.unsigned_event(schnorr.pubkey_from_seckey(PERSON).hex(),
                             nostr.KIND_TEXT, "give me everything"), PERSON)
    forged["pubkey"] = schnorr.pubkey_from_seckey(bytes.fromhex("cc" * 32)).hex()
    await relay.deliver(forged)

    await asyncio.sleep(0.3)
    assert received == [], "a forged event was accepted"


async def test_a_relay_that_never_challenges_still_works():
    # NIP-42 is optional. A client that waits for a challenge that never comes
    # would sit there connected and deaf.
    relay = TinyRelay(challenge=None)
    url = await relay.start()
    received = []
    client = BuzzRelay("nochal", url, AGENT,
                       lambda e, a: received.append(e) or asyncio.sleep(0))
    client.start()
    try:
        assert await _wait_for(lambda: client.connected), "never came up"
        assert relay.authed is None
    finally:
        await client.stop()
        await relay.stop()


async def test_the_client_reconnects_after_the_relay_drops_it(monkeypatch):
    # Relays restart. Without this a user's channel dies silently until
    # somebody restarts the whole service.
    monkeypatch.setattr("gateway.platforms.buzz.BACKOFF_START", 0.05)
    relay = TinyRelay()
    url = await relay.start()
    client = BuzzRelay("recon", url, AGENT, lambda e, a: asyncio.sleep(0))
    client.start()
    try:
        assert await _wait_for(lambda: client.connected)
        for ws in list(relay.subscribers):
            await ws.close()
        relay.subscribers.clear()
        client.connected = False
        assert await _wait_for(lambda: len(relay.filters) >= 2, timeout=8), (
            "never resubscribed after the drop")
    finally:
        await client.stop()
        await relay.stop()
