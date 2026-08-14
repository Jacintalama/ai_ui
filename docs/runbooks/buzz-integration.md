# Connecting Buzz to IO

**Status: live.** Each user connects their own Buzz workspace from the Channels
page. There is no server-wide Buzz credential and there should never be one.

An earlier version of this file described a webhook contract that IO would
serve and Buzz would call. That was wrong about how Buzz works and the code
implementing it was removed. If you find a `/webhook/gateway/buzz` endpoint
anywhere, it is a leftover.

## What Buzz is, and why that changes everything

Buzz is a Nostr workspace, not a chat product with an API. There is no endpoint
to call and no bot to register. A relay is reached over a websocket, every
message is a signed event, and identity is a secp256k1 keypair. Buzz's own
documentation puts it plainly: the relay treats external services identically
to agents, by keypair, not by permission flags.

So IO is never *called* by Buzz. IO **joins a workspace as an agent** and holds
a connection open, which inverts what every other channel here assumes:

| Every other channel | Buzz |
|---|---|
| The platform calls us when a user speaks | We hold a websocket and receive events |
| A shared secret authenticates the platform | A keypair authenticates *us*, per workspace |
| One integration serves every workspace | One connection per workspace, each with its own key |
| Idle costs nothing | Every connected user costs an open socket |

That last row is why there is a cap.

## What a user does

Three steps, all on the Channels page, no admin and no deploy:

1. In their Buzz workspace, create an agent identity for IO and copy its
   private key (`nsec1...`).
2. Copy the relay URL their own Buzz app connects to (`wss://...`).
3. Paste both into the Buzz row and save. IO joins as that agent. They then
   message it from Buzz and it replies with a pairing code, which they paste
   back on the same page.

The key is encrypted per account with Fernet and is visible to nobody else. The
relay URL is not a secret and prefills on edit.

**Do not build a way for one user to enter another's code.** A code links
whichever IO account asked for it, and it hands the holder that account's
memory, email assistant and files.

## How it is built

| File | What it does |
|---|---|
| `webhook-handler/gateway/schnorr.py` | BIP-340 signing and verification |
| `webhook-handler/gateway/nip19.py` | `nsec`/`npub` bech32 |
| `webhook-handler/gateway/nostr.py` | NIP-01 ids, NIP-42 auth, NIP-OA, frames |
| `webhook-handler/gateway/platforms/buzz.py` | One relay connection and its adapter |
| `webhook-handler/gateway/buzz_manager.py` | Which connections are open, and the cap |
| `mcp-servers/tasks/nostr_{schnorr,nip19}.py` | Byte-identical mirrors, for validating a pasted key in the browser |

### Signing is pure Python, on purpose

`coincurve` is the obvious choice. It is not installed in either container and
its wheel does not build on Windows, so it would have been a signing layer
nobody could exercise outside production. Both paths exist, `schnorr.sign`
prefers coincurve when importable, and a test asserts the two agree wherever
both are present.

The pure path is **not constant time**. Scalar multiplication branches on the
bits of the nonce. Observing that timing requires already executing code on the
box that holds the key, at which point the key is readable directly.

Correctness is checked against BIP-340's own published vectors rather than by
round-tripping against itself: an implementation can be self-consistently wrong
and every event it signs is then rejected by a relay with no error saying why.

### Keys are accepted as `nsec1...`, never hex

bech32 is checksummed. A mistyped key is refused in the browser with a reason,
instead of connecting as an identity nobody owns and failing later as a silent
authentication refusal.

### Every inbound event is verified twice

The id must be the sha256 of the canonical body, and the signature must be the
claimed author's. Relays are **not** trusted to have checked. The author's
pubkey is exactly what decides which IO account answers, so without this anyone
who can reach the relay could speak as anyone else.

A relay is also a shared workspace, so the same allow rule a personal Telegram
bot uses applies here: an explicit allow list wins, otherwise the account that
claimed the connection, otherwise whoever arrives first so the owner can claim
it by messaging their own agent. Without it, every colleague of the owner would
reach the owner's IO account.

### The cap, and why there is no idle-drop

`MAX_CONNECTIONS = 25` in `buzz_manager.py`. Each connection is an open socket
on a 3.8GB box.

Idle-drop is deliberately **not** implemented, even though it is the obvious
companion to a cap. The socket IS how a message reaches us, so dropping an idle
connection means silently not receiving. The demand signal is whether the user
has the channel switched on; turning it off frees the slot. A user over the cap
is recorded in `skipped` with a reason rather than dropped silently.

### Reconciled by polling, not by a push

webhook-handler asks tasks every 30 seconds which connections should be open
(`GET /gateway/bots?platform=buzz`, internal secret) and makes reality match.
Polling is self-healing: a relay that died, either service restarting, or a
credential edited in another window all converge within one interval.

It reports back through `POST /gateway/bots/{bot_key}/state`, which is the only
reason the page can say whether a connection is actually up rather than merely
saved.

## Switching it off

`BUZZ_ENABLED` is read by **both** services. webhook-handler runs the
connections; tasks renders the row. Blank it on both, or the channel is live
while the page calls it off, which is how the Terminal channel once shipped.

## Checking it end to end

`webhook-handler/tests/test_gateway_buzz_live.py` runs a minimal NIP-01 relay
in-process and drives the real client against it: connect, answer the auth
challenge, subscribe, receive a signed message, publish a signed reply, refuse a
forged one, reconnect after a drop. It runs on a developer machine and in the
container, and it publishes nothing to any public network.

For a full production check, run the same shape against the deployed services:
serve a relay on `127.0.0.1` inside the webhook-handler container, save a row
through the real `POST /tasks/gateway/bots` route with that URL, wait for the
manager to dial in, deliver a signed event, and confirm a signed pairing offer
comes back. Delete exactly the row you created afterwards.

## What is deliberately not handled

- **Encrypted direct messages** (NIP-04, NIP-17). We subscribe to kind 1 events
  tagged with our pubkey, which is how an agent is addressed in the open. An
  encrypted DM arrives as a kind we do not request, so it is invisible rather
  than mishandled. If Buzz users DM agents encrypted by default, this is the
  first thing to add.
- **Attachments and voice.** Text only. Telegram carries voice through the same
  pipeline, so adding it later is work in the adapter, not a protocol change.
- **Push from IO.** IO only answers. Nothing arrives in a workspace unprompted
  beyond presence.
