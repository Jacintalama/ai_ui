"""The Buzz relay's read loop, and how many of them may exist.

Everything here runs without a websocket: frames are fed to the handler
directly. That is deliberate. The parts worth testing are the decisions made
about a frame, and a real socket would only make those decisions harder to
reach.
"""
import json

import pytest

from gateway import buzz_manager as bm
from gateway import nostr, schnorr
from gateway.platforms.buzz import BuzzAdapter, BuzzRelay, sign_event

SECKEY = bytes.fromhex("11" * 32)
OTHER = bytes.fromhex("22" * 32)


def _signed(seckey, content="hello", kind=nostr.KIND_TEXT, tags=None):
    pub = schnorr.pubkey_from_seckey(seckey).hex()
    return sign_event(nostr.unsigned_event(pub, kind, content, tags=tags or []),
                      seckey)


class FakeSocket:
    def __init__(self):
        self.sent = []

    async def send(self, text):
        self.sent.append(text)


def _relay(allow=None):
    seen = []

    async def on_event(event, adapter):
        seen.append(event)

    relay = BuzzRelay("botkey", "wss://relay.example/x", SECKEY, on_event,
                      allow=allow)
    relay._ws = FakeSocket()
    relay.received = seen
    return relay


# --- signing -----------------------------------------------------------------

def test_a_signed_event_verifies_against_its_own_id():
    event = _signed(SECKEY)
    assert schnorr.verify(bytes.fromhex(event["id"]),
                          bytes.fromhex(event["pubkey"]),
                          bytes.fromhex(event["sig"]))


def test_signing_does_not_disturb_the_event():
    unsigned = nostr.unsigned_event(
        schnorr.pubkey_from_seckey(SECKEY).hex(), 1, "hi")
    signed = sign_event(unsigned, SECKEY)
    assert {k: v for k, v in signed.items() if k != "sig"} == unsigned


# --- what counts as a message ------------------------------------------------

@pytest.mark.parametrize("event", [
    {"kind": 7, "pubkey": "ab" * 32, "content": "x"},        # a reaction
    {"kind": 1, "pubkey": "short", "content": "x"},          # not a pubkey
    {"kind": 1, "pubkey": "ab" * 32, "content": "   "},      # nothing said
    {"kind": 1, "pubkey": "ab" * 32, "content": 5},          # not text
    {"kind": 1, "pubkey": "ab" * 32},                        # no content
    "not even a dict",
])
def test_anything_we_do_not_handle_is_ignored_rather_than_guessed(event):
    assert BuzzAdapter(None).parse_inbound(event, {}) is None


def test_a_text_note_becomes_a_message_from_its_author():
    event = _signed(OTHER, "what is on today")
    parsed = BuzzAdapter(None).parse_inbound(event, {})
    assert parsed.text == "what is on today"
    assert parsed.source.platform == "buzz"
    # The person IS the conversation: a reply goes to their pubkey.
    assert parsed.source.user_id == parsed.source.chat_id == event["pubkey"]
    assert parsed.source.chat_type == "dm"


# --- the frames --------------------------------------------------------------

async def test_an_auth_challenge_is_answered_with_a_signed_event():
    relay = _relay()
    await relay._on_frame(json.dumps(["AUTH", "chal-42"]))
    frame = json.loads(relay._ws.sent[-1])
    assert frame[0] == "AUTH"
    event = frame[1]
    assert event["kind"] == nostr.KIND_AUTH
    assert ["challenge", "chal-42"] in event["tags"]
    # The relay's own url is signed too, so the answer cannot be replayed at a
    # different relay by anyone who saw it go past.
    assert ["relay", "wss://relay.example/x"] in event["tags"]
    assert schnorr.verify(bytes.fromhex(event["id"]),
                          bytes.fromhex(event["pubkey"]),
                          bytes.fromhex(event["sig"]))


async def test_presence_goes_out_once_the_backlog_has_been_delivered():
    relay = _relay()
    await relay._on_frame(json.dumps(["EOSE", "io"]))
    published = json.loads(relay._ws.sent[-1])[1]
    assert published["kind"] == nostr.KIND_PRESENCE
    assert published["content"] == "online"
    assert relay.connected is True


async def test_a_message_addressed_to_us_reaches_the_pipeline():
    relay = _relay()
    await relay._on_frame(json.dumps(["EVENT", "io", _signed(OTHER, "hi")]))
    assert [e.text for e in relay.received] == ["hi"]


async def test_the_same_message_twice_is_answered_once():
    # Relays redeliver on reconnect. Answering twice is worse than missing it:
    # the second answer costs the user tokens for a question already handled.
    relay = _relay()
    event = _signed(OTHER, "hi")
    for _ in range(3):
        await relay._on_frame(json.dumps(["EVENT", "io", event]))
    assert len(relay.received) == 1


async def test_an_event_whose_id_does_not_match_its_body_is_dropped():
    # The id is a hash of the content. A mismatch means the content was
    # changed after signing, so the signature vouches for something else.
    relay = _relay()
    event = _signed(OTHER, "hi")
    event["content"] = "transfer everything"
    await relay._on_frame(json.dumps(["EVENT", "io", event]))
    assert relay.received == []


async def test_an_event_with_a_bad_signature_is_dropped():
    # Relays are not trusted to have checked. Without this, anyone who can
    # reach the relay could speak as anyone else, and the pubkey is exactly
    # what decides which IO account answers.
    relay = _relay()
    event = _signed(OTHER, "hi")
    event["sig"] = "00" * 64
    await relay._on_frame(json.dumps(["EVENT", "io", event]))
    assert relay.received == []


async def test_an_event_claiming_someone_elses_key_is_dropped():
    relay = _relay()
    event = _signed(OTHER, "hi")
    event["pubkey"] = schnorr.pubkey_from_seckey(bytes.fromhex("33" * 32)).hex()
    await relay._on_frame(json.dumps(["EVENT", "io", event]))
    assert relay.received == []


async def test_our_own_reply_echoed_back_is_not_treated_as_a_question():
    # We subscribe by tag, and our replies carry tags too. Without this the
    # agent would answer itself, forever.
    relay = _relay()
    await relay._on_frame(json.dumps(["EVENT", "io", _signed(SECKEY, "my reply")]))
    assert relay.received == []


async def test_a_sender_who_is_not_allowed_is_ignored():
    # A relay is a shared workspace. Without this, every colleague of the
    # owner would reach the owner's IO account, memory and email included.
    relay = _relay(allow=lambda pubkey: False)
    await relay._on_frame(json.dumps(["EVENT", "io", _signed(OTHER, "hi")]))
    assert relay.received == []


async def test_a_refusal_from_the_relay_is_recorded_rather_than_swallowed():
    # A refused publish looks exactly like a delivered one from here.
    relay = _relay()
    await relay._on_frame(json.dumps(["OK", "abc", False, "rate-limited"]))
    assert "rate-limited" in relay.last_error


@pytest.mark.parametrize("frame", [
    "not json", "{}", "[]", '["EVENT"]', '["EVENT","io",null]',
    '["AUTH"]', '"a string"', "123",
])
async def test_a_malformed_frame_does_not_break_the_read_loop(frame):
    # One bad frame from a relay must not drop a connection that is otherwise
    # carrying somebody's conversation.
    relay = _relay()
    await relay._on_frame(frame)
    assert relay.received == []


async def test_a_reply_is_addressed_to_the_person_who_asked():
    relay = _relay()
    await relay.publish_reply("cd" * 32, "here you go")
    published = json.loads(relay._ws.sent[-1])[1]
    assert published["content"] == "here you go"
    assert ["p", "cd" * 32] in published["tags"]
    assert published["kind"] == nostr.KIND_TEXT


# --- the cap -----------------------------------------------------------------

class FakeTasks:
    def __init__(self, bots):
        self.bots = bots
        self.states = []

    async def gateway_bots_for_platform(self, platform):
        return self.bots

    async def gateway_bot_state(self, bot_key, connected, error=""):
        self.states.append((bot_key, connected, error))


def _bot(i, endpoint="wss://relay.example/x"):
    from gateway import nip19
    return {"bot_key": f"bot{i}", "endpoint": endpoint,
            "token": nip19.encode(bytes([i or 1]) * 32, "nsec"),
            "allowed_ids": "", "owner_platform_user_id": ""}


def _manager(bots):
    from gateway import nip19
    return bm.BuzzManager(
        FakeTasks(bots), lambda e, a: None,
        decode_key=lambda nsec: nip19.decode(nsec, "nsec"),
        allow_factory=lambda config: (lambda pubkey: True))


async def test_every_enabled_connection_is_opened(monkeypatch):
    monkeypatch.setattr(BuzzRelay, "start", lambda self: None)
    manager = _manager([_bot(1), _bot(2)])
    await manager.reconcile()
    assert manager.status()["open"] == 2


async def test_a_connection_that_is_switched_off_is_dropped(monkeypatch):
    monkeypatch.setattr(BuzzRelay, "start", lambda self: None)

    async def _stop(self):
        return None
    monkeypatch.setattr(BuzzRelay, "stop", _stop)

    manager = _manager([_bot(1), _bot(2)])
    await manager.reconcile()
    manager._tasks.bots = [_bot(1)]
    await manager.reconcile()
    assert manager.status()["open"] == 1


async def test_the_cap_holds_and_says_who_was_left_out(monkeypatch):
    # Every open relay is a socket on a 3.8GB box, so this is a real limit and
    # not a formality. Silently dropping the extras would leave a user with the
    # channel switched on and nothing happening, forever, with no way to tell.
    monkeypatch.setattr(BuzzRelay, "start", lambda self: None)
    monkeypatch.setattr(bm, "MAX_CONNECTIONS", 3)
    manager = _manager([_bot(i) for i in range(1, 8)])
    await manager.reconcile()
    status = manager.status()
    assert status["open"] == 3
    assert len(status["skipped"]) == 4
    assert all("slot" in why for why in status["skipped"].values())


async def test_a_relay_url_that_is_not_a_websocket_is_refused(monkeypatch):
    monkeypatch.setattr(BuzzRelay, "start", lambda self: None)
    manager = _manager([_bot(1, endpoint="https://relay.example")])
    await manager.reconcile()
    assert manager.status()["open"] == 0
    assert "websocket" in manager.skipped["bot1"]


async def test_an_unreadable_key_skips_only_that_user(monkeypatch):
    monkeypatch.setattr(BuzzRelay, "start", lambda self: None)
    broken = {**_bot(1), "token": "nsec1nonsense"}
    manager = _manager([broken, _bot(2)])
    await manager.reconcile()
    assert manager.status()["open"] == 1
    assert "bot1" in manager.skipped


async def test_the_state_of_each_connection_is_reported_once(monkeypatch):
    monkeypatch.setattr(BuzzRelay, "start", lambda self: None)
    manager = _manager([_bot(1)])
    await manager.reconcile()
    await manager.report()
    await manager.report()
    assert manager._tasks.states == [("bot1", False, "")]


async def test_a_change_in_state_is_reported(monkeypatch):
    monkeypatch.setattr(BuzzRelay, "start", lambda self: None)
    manager = _manager([_bot(1)])
    await manager.reconcile()
    await manager.report()
    manager._relays["bot1"].connected = True
    await manager.report()
    assert manager._tasks.states[-1] == ("bot1", True, "")


def test_the_status_never_leaks_a_relay_url_or_a_key(monkeypatch):
    # A relay URL identifies somebody's workspace, and this is read by an
    # operator endpoint rather than by its owner.
    monkeypatch.setattr(BuzzRelay, "start", lambda self: None)
    manager = _manager([_bot(1)])
    blob = json.dumps(manager.status())
    assert "wss://" not in blob and "nsec" not in blob
