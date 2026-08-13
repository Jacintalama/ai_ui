"""The Nostr protocol layer Buzz speaks.

Pure functions on purpose, so all of this runs on a developer machine. The
signing primitive needs coincurve, which has no Windows wheel, and this
repository already has one tier of tests that never ran anywhere because it
was coupled to something the machine could not provide.

The event-id vector below is not invented: it is the worked example from
block/buzz docs/nips/NIP-OA.md, so a change to the serialization fails
against Buzz's own published output rather than against our reading of it.
"""
import json
import time

import pytest

from gateway import nostr

# From block/buzz docs/nips/NIP-OA.md.
SPEC_EVENT = {
    "id": "d892a65e7677e0554ebb70ee16deeb6a0727dba46450fb4bc001291d7bff971b",
    "pubkey": "c6047f9441ed7d6d3045406e95c07cd85c778e4b8cef3ca7abac09b95c709ee5",
    "created_at": 1713956400,
    "kind": 1,
    "tags": [["auth",
              "79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798",
              "kind=1&created_at<1713957000",
              "8b7df2575caf0a108374f8471722b233c53f9ff827a8b0f91861966c3b9dd5cb"
              "2e189eae9f49d72187674c2f5bd244145e10ff86c9f257ffe65a1ee5f108b369"]],
    "content": "owner-attested agent event",
}


def test_the_event_id_matches_buzz_s_own_published_example():
    got = nostr.event_id(SPEC_EVENT["pubkey"], SPEC_EVENT["created_at"],
                         SPEC_EVENT["kind"], SPEC_EVENT["tags"],
                         SPEC_EVENT["content"])
    assert got == SPEC_EVENT["id"]


def test_the_serialization_carries_no_whitespace():
    # The id is a hash of these bytes. One stray space and every relay rejects
    # the event, with no error that says why.
    raw = nostr.canonical("ab" * 32, 1, 1, [], "hi")
    assert b", " not in raw and b": " not in raw
    assert raw.startswith(b'[0,"')


def test_non_ascii_content_is_not_escaped_away():
    # ensure_ascii would rewrite these as \\uXXXX, changing the hash, so a
    # message with an emoji or an accent would be silently unpublishable.
    raw = nostr.canonical("ab" * 32, 1, 1, [], "café 🐝")
    assert "café 🐝".encode("utf-8") in raw


def test_the_same_content_always_hashes_the_same():
    a = nostr.event_id("ab" * 32, 100, 1, [["p", "cd" * 32]], "hello")
    b = nostr.event_id("ab" * 32, 100, 1, [["p", "cd" * 32]], "hello")
    assert a == b


def test_changing_anything_changes_the_id():
    base = dict(pubkey="ab" * 32, created_at=100, kind=1, tags=[], content="x")
    original = nostr.event_id(**base)
    for field, value in [("created_at", 101), ("kind", 2), ("content", "y"),
                         ("tags", [["p", "cd" * 32]])]:
        assert nostr.event_id(**{**base, field: value}) != original


def test_an_unsigned_event_carries_its_own_id_and_no_signature():
    ev = nostr.unsigned_event("ab" * 32, 1, "hello")
    assert ev["id"] == nostr.event_id(ev["pubkey"], ev["created_at"],
                                      ev["kind"], ev["tags"], ev["content"])
    assert "sig" not in ev, "signing belongs to the caller, not this module"


# --- NIP-OA, the owner's attestation ----------------------------------------

def test_the_attestation_preimage_is_exactly_what_the_spec_says():
    got = nostr.attestation_preimage("agentpub", "kind=1")
    assert got == b"nostr:agent-auth:agentpub:kind=1"


def test_the_preimage_binds_the_agent_so_it_cannot_be_reused():
    # Without the agent pubkey in the preimage, one owner signature would
    # vouch for any agent that copied it.
    a = nostr.attestation_preimage("agent-one", "kind=1")
    b = nostr.attestation_preimage("agent-two", "kind=1")
    assert a != b


def test_the_auth_tag_has_the_four_elements_the_spec_requires():
    tag = nostr.auth_tag("owner" * 1, "kind=1", "sig")
    assert tag == ["auth", "owner", "kind=1", "sig"]


@pytest.mark.parametrize("conditions,kind,created_at,ok", [
    ("", 1, 500, True),                                   # no clauses
    ("kind=1", 1, 500, True),
    ("kind=1", 2, 500, False),
    ("created_at<1000", 1, 500, True),
    ("created_at<1000", 1, 1000, False),                  # strict
    ("created_at>100", 1, 500, True),
    ("created_at>100", 1, 100, False),                    # strict
    ("kind=1&created_at<1000", 1, 500, True),
    ("kind=1&created_at<1000", 1, 1500, False),
    ("kind=1&created_at<1000", 2, 500, False),
])
def test_conditions_are_enforced_as_written(conditions, kind, created_at, ok):
    assert nostr.conditions_hold(conditions, kind, created_at) is ok


def test_an_unknown_clause_is_refused_rather_than_ignored():
    # Skipping a clause we do not understand would silently widen whatever the
    # owner meant to narrow, which is the wrong way for this to fail.
    assert nostr.conditions_hold("kind=1&something_new=7", 1, 500) is False


# --- NIP-42, answering the relay's challenge --------------------------------

def test_the_auth_event_carries_the_challenge_and_the_relay():
    ev = nostr.auth_event("ab" * 32, "wss://buzz.example/relay", "chal-123")
    assert ev["kind"] == nostr.KIND_AUTH == 22242
    assert ["challenge", "chal-123"] in ev["tags"]
    assert ["relay", "wss://buzz.example/relay"] in ev["tags"]


def test_the_auth_event_names_the_relay_so_it_cannot_be_replayed_elsewhere():
    a = nostr.auth_event("ab" * 32, "wss://one.example/relay", "same", created_at=1)
    b = nostr.auth_event("ab" * 32, "wss://two.example/relay", "same", created_at=1)
    assert a["id"] != b["id"]


def test_a_fresh_challenge_produces_a_fresh_event():
    a = nostr.auth_event("ab" * 32, "wss://r", "one", created_at=1)
    b = nostr.auth_event("ab" * 32, "wss://r", "two", created_at=1)
    assert a["id"] != b["id"]


# --- presence and frames ----------------------------------------------------

def test_presence_uses_the_ephemeral_kind_buzz_watches():
    ev = nostr.presence_event("ab" * 32, "online")
    assert ev["kind"] == nostr.KIND_PRESENCE == 20001
    assert ev["content"] == "online"


def test_an_invented_presence_state_is_refused():
    with pytest.raises(ValueError):
        nostr.presence_event("ab" * 32, "busy")


def test_a_subscription_frame_is_a_req():
    frame = json.loads(nostr.req_frame("sub1", {"kinds": [1]}))
    assert frame[0] == "REQ" and frame[1] == "sub1"
    assert frame[2] == {"kinds": [1]}


def test_publishing_frame_is_an_event():
    ev = nostr.unsigned_event("ab" * 32, 1, "hi")
    assert json.loads(nostr.event_frame(ev))[0] == "EVENT"


def test_the_mentions_filter_asks_only_for_messages_addressed_to_us():
    f = nostr.mentions_filter("ab" * 32)
    assert f["#p"] == ["ab" * 32]
    assert f["kinds"] == [nostr.KIND_TEXT]


def test_a_reconnect_can_bound_how_far_back_it_replays():
    # Without `since`, reconnecting would replay the whole history of the
    # community and answer messages that were handled hours ago.
    since = int(time.time()) - 60
    assert nostr.mentions_filter("ab" * 32, since=since)["since"] == since
