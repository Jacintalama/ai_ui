# Connecting Buzz to IO

**Status: not live.** The protocol layer is built and tested. The signing
primitive, the websocket client and the connection manager are not. Nothing on
the Channels page accepts a Buzz credential yet, and the row says so.

Read this before touching the Buzz row. An earlier version of this file
described a webhook contract that IO would serve and Buzz would call. That was
wrong about how Buzz works and the code implementing it has been removed. If
you find a `/webhook/gateway/buzz` endpoint anywhere, it is a leftover.

## What Buzz actually is

Buzz is a Nostr workspace, not a chat product with an API. There is no endpoint
to call and no bot to register. A relay is reached over a websocket, every
message is a signed event, and identity is a secp256k1 keypair. Buzz's own
documentation puts it plainly: the relay treats external services identically
to agents, by keypair, not by permission flags.

So IO is never *called* by Buzz. IO **joins a workspace as an agent** and holds
a connection open, which inverts everything the old design assumed:

| The old design assumed | What is actually true |
|---|---|
| Buzz calls us when a user speaks | We hold a websocket and receive events |
| A shared secret authenticates Buzz | A keypair authenticates *us*, per workspace |
| One integration serves every workspace | One connection per workspace, each with its own key |
| Idle costs nothing | Every connected user costs an open socket |

That last row is why the cap below exists.

## What a workspace owner has to provide

Two things, and only the owner of that workspace can produce them:

1. **An agent identity for IO.** They create it in their Buzz workspace and
   copy its private key, which starts with `nsec1`.
2. **The relay URL.** The `wss://` address their own Buzz app connects to.

Both are entered by the user on IO's Channels page, encrypted per account, and
visible to nobody else. This is the same shape as bringing your own Telegram
bot: your workspace, your key, your data.

**Each user connects their own workspace.** There is no server-wide Buzz
credential and there should never be one. A single shared identity would put
every user's traffic through one keypair, and one workspace owner's key would
reach another's people.

## What is built

`webhook-handler/gateway/nostr.py`, with `tests/test_gateway_nostr.py` beside
it. Pure functions, no crypto primitive and no I/O, which is the whole point of
the split: it runs on a developer machine. The signing primitive needs
`coincurve`, which has no Windows wheel, and this repository already carries one
tier of tests that never ran anywhere because it was coupled to something the
machine could not provide.

It covers NIP-01 event ids and canonical serialization, NIP-42 auth events,
NIP-OA owner attestation, presence, and the REQ/EVENT/CLOSE frames.

The event-id test asserts against the worked example published in block/buzz
`docs/nips/NIP-OA.md`, so a change to the serialization fails against Buzz's
own output rather than against our reading of their prose.

## What is not built

- **Signing.** `unsigned_event` deliberately stops short of a signature.
  Schnorr signing needs `coincurve`, confirmed working on the production Linux
  box and unavailable on Windows, so it belongs behind a seam that the pure
  layer never imports.
- **The websocket client.** Connect, answer the NIP-42 challenge, subscribe to
  mentions, publish replies, reconnect with a bounded `since` so a reconnect
  does not replay and re-answer hours of history.
- **The connection manager.** Per user, **cap 25**, connect on demand, drop on
  idle, and refuse politely past the cap. Every live connection is an open
  socket on a 3.8GB box.
- **Storage for the relay URL.** `gateway_bots` has no `endpoint` column yet.

## Why the page does not take the key yet

The Channels row shows the two fields, disabled, with the reason printed under
them. Accepting a private key that nothing can use would mean taking custody of
a live secret in exchange for nothing: all of the risk of holding it, none of
the benefit of using it. The fields are drawn from the same `connect_form` the
live channels use, so the preview cannot drift from what is eventually
accepted.

## Switching it on, when it exists

`BUZZ_ENABLED` is read by **both** services on purpose. webhook-handler runs
the agent connection; tasks only renders the row. Setting it on one of them is
exactly how the Terminal channel once ended up live while the page called it
switched off.

It must stay unset until the transport exists. Flipping it early is what put
*"Message IO from Buzz and it will reply with a code"* on the row, an
instruction no Buzz user could carry out, because IO was not in their workspace
to be messaged.

Once IO is an agent there, that sentence becomes true and pairing works like
every other channel: first message returns a code, the user pastes it into the
Channels page while signed in, and every later message is answered as that
account.

**Do not build a way for one user to enter another's code.** A code links
whichever IO account asked for it, and it hands the holder that account's
memory, email assistant and files.
