"""The Nostr protocol Buzz speaks, with no crypto primitive and no I/O.

Split deliberately. Everything here is pure and runs anywhere, so it is
testable on a developer machine; the signing primitive needs coincurve, which
has no Windows wheel. Without that split the whole transport would only be
testable inside the container, and this repository already has one tier of
tests that never ran anywhere for exactly that reason.

Buzz is a Nostr workspace: a relay reached over WebSocket where every message
is a signed event, identity is a secp256k1 keypair, and the relay "treats
external services identically to agents, by keypair, not by permission flags".
So IO joins as an agent rather than being called by a webhook.

References, all from block/buzz:
  NIP-01  event id and canonical serialization
  NIP-42  the auth challenge a relay issues
  NIP-OA  the owner attestation an agent carries (docs/nips/NIP-OA.md)
"""
import hashlib
import json
import time

#: NIP-42. The event a client signs to answer a relay's auth challenge.
KIND_AUTH = 22242

#: Ephemeral presence. Buzz calls relay presence "the sole status signal" for
#: a remote agent, since there is no other management channel.
KIND_PRESENCE = 20001

#: NIP-01 short text note, which is what an ordinary message is.
KIND_TEXT = 1


def canonical(pubkey: str, created_at: int, kind: int, tags: list,
              content: str) -> bytes:
    """The exact bytes NIP-01 hashes to produce an event id.

    Compact separators and no ASCII escaping, because the id is a hash: a
    stray space or an escaped non-ASCII character changes it, and the event is
    then rejected by every relay with no useful error.

    Verified against the worked example in block/buzz docs/nips/NIP-OA.md,
    which is an authoritative vector rather than our own reading of the prose.
    """
    return json.dumps([0, pubkey, created_at, kind, tags, content],
                      separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def event_id(pubkey: str, created_at: int, kind: int, tags: list,
             content: str) -> str:
    """The event id: sha256 of the canonical serialization, lowercase hex."""
    return hashlib.sha256(
        canonical(pubkey, created_at, kind, tags, content)).hexdigest()


def unsigned_event(pubkey: str, kind: int, content: str,
                   tags: list | None = None, created_at: int | None = None) -> dict:
    """An event with everything but the signature.

    The caller signs `id` with the agent key and drops the result in `sig`.
    Keeping signing out of this module is what lets every rule here be tested
    without a native dependency.
    """
    tags = tags or []
    created_at = int(time.time()) if created_at is None else created_at
    return {
        "pubkey": pubkey,
        "created_at": created_at,
        "kind": kind,
        "tags": tags,
        "content": content,
        "id": event_id(pubkey, created_at, kind, tags, content),
    }


def attestation_preimage(agent_pubkey: str, conditions: str) -> bytes:
    """What the OWNER signs to vouch for an agent, per NIP-OA.

    The owner signs sha256 of this; the agent then carries the resulting
    signature in an `auth` tag on its own events. The agent key stays the sole
    author, so this proves permission without handing the agent the owner's
    identity.
    """
    return f"nostr:agent-auth:{agent_pubkey}:{conditions}".encode("utf-8")


def auth_tag(owner_pubkey: str, conditions: str, sig: str) -> list:
    """The NIP-OA tag an attested agent puts on its events."""
    return ["auth", owner_pubkey, conditions, sig]


def conditions_hold(conditions: str, kind: int, created_at: int) -> bool:
    """Does an event satisfy the conditions the owner attested to?

    Clauses are joined by `&`: kind=N, created_at<T, created_at>T. Relays do
    not enforce these, clients do, so IO checks them on anything it is asked
    to trust rather than assuming the far end did.

    An unrecognised clause is refused rather than ignored. Skipping one would
    silently widen whatever the owner meant to narrow.
    """
    for clause in (c.strip() for c in (conditions or "").split("&")):
        if not clause:
            continue
        if clause.startswith("kind="):
            if str(kind) != clause[len("kind="):]:
                return False
        elif clause.startswith("created_at<"):
            if not created_at < int(clause[len("created_at<"):]):
                return False
        elif clause.startswith("created_at>"):
            if not created_at > int(clause[len("created_at>"):]):
                return False
        else:
            return False
    return True


def auth_event(pubkey: str, relay_url: str, challenge: str,
               created_at: int | None = None) -> dict:
    """NIP-42. The unsigned answer to a relay's auth challenge.

    Both tags are load bearing. The relay checks the challenge is the one it
    issued and that the url is itself, which is what stops a signed answer
    being replayed at a different relay.
    """
    return unsigned_event(
        pubkey, KIND_AUTH, "",
        tags=[["relay", relay_url], ["challenge", challenge]],
        created_at=created_at)


def presence_event(pubkey: str, state: str,
                   created_at: int | None = None) -> dict:
    """Ephemeral presence, the only status signal a remote agent has."""
    if state not in ("online", "away", "offline"):
        raise ValueError(f"unknown presence state: {state!r}")
    return unsigned_event(pubkey, KIND_PRESENCE, state, created_at=created_at)


def req_frame(sub_id: str, *filters: dict) -> str:
    """A subscription. Relay answers with EVENTs, then EOSE."""
    return json.dumps(["REQ", sub_id, *filters], separators=(",", ":"))


def event_frame(event: dict) -> str:
    """Publish a signed event."""
    return json.dumps(["EVENT", event], separators=(",", ":"))


def close_frame(sub_id: str) -> str:
    return json.dumps(["CLOSE", sub_id], separators=(",", ":"))


def mentions_filter(pubkey: str, since: int | None = None) -> dict:
    """Everything addressed to us.

    `#p` is the tag a message carries to name its recipient, so this is how an
    agent is reached whether the message is a direct one or a mention in a
    room. Bounded by `since` so a reconnect replays recent traffic rather than
    the entire history of the community.
    """
    f: dict = {"kinds": [KIND_TEXT], "#p": [pubkey]}
    if since is not None:
        f["since"] = since
    return f
