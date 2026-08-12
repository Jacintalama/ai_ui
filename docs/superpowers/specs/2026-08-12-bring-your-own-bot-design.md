# Bring your own bot: per-user channel configuration

Date: 2026-08-12
Branch: `feat/multi-platform-gateway`
Status: designed, not implemented

## The problem

The Channels page lists every channel and its status, but it has no button that
switches anything on. Whether a channel exists at all is decided by environment
variables read at webhook-handler startup (`TELEGRAM_BOT_TOKEN`,
`GATEWAY_CLI_ENABLED`), so turning one on means editing `.env` on the VPS and
rebuilding. The page has nothing it is permitted to change, which is why it has
no controls.

Hermes solves this with a per-channel toggle, a Test button and a CONFIGURE
modal that takes a bot token. Hermes is single tenant: one operator, one token,
one instance that now speaks Discord. IO is multi tenant, so the same buttons
cannot mean the same thing.

## Decisions taken

1. **Per user, not per server.** A bot belongs to one account. Nobody else can
   see it, test it, or configure it. This matches how the platform already
   handles connect-your-own-Vercel and connect-your-own-Gmail, and it is the
   first slice of a larger direction: every tool a user connects is theirs, and
   later their agent acts across everything they connected.
2. **The shared bot stays.** `@aiuiteam_bot` remains the ten second on-ramp so
   nobody is locked out for lacking a developer account. Bringing your own bot
   is the upgrade, shown as the primary action.
3. **Telegram first.** It is the channel already routed through Channels, and
   its webhook model costs nothing per user.
4. **The current Discord and Slack bots are not touched.** They keep serving
   App Builder panels and cron exactly as they do today.
5. **Hermes' shape, one channel at a time.** Every row carries the same three
   controls in the same positions. On a channel that is not built, the control
   is visibly inert and the row says why. No button that pretends to work.

## Scope

In scope: per-user Telegram bots, end to end, with the storage and isolation
pattern that the remaining channels will reuse.

Out of scope: making Discord, Slack, Mattermost, Matrix or any other channel
functional; refactoring the existing Discord and Slack integrations; the
agent-over-all-connections layer.

## Architecture

### Where the token lives

Tasks holds the secret. webhook-handler asks for it on demand and caches it.

webhook-handler has no database and no encryption key. It asks tasks for
everything over an internal-secret HTTP call, and that seam is what this design
follows. The two alternatives were rejected:

- Pushing config to webhook-handler on save creates two copies of the truth and
  needs a full-sync step on restart. Every bug becomes a stale-cache bug.
- Giving webhook-handler the database and the Fernet key puts the encryption
  key and schema knowledge in a second service for no gain on the read path.

The chosen design self-heals: restart webhook-handler and it repopulates on the
next message, with no sync to get wrong.

### Data model

New table `tasks.gateway_bots`, migration `036_gateway_bots.sql`:

| Column | Purpose |
|---|---|
| `id` | surrogate key |
| `bot_key` | 32 random hex, public, appears in the webhook URL |
| `email` | owner, the only account that can see this row |
| `platform` | `telegram` for now |
| `token_encrypted` | Fernet, via the existing `crypto_utils` helper |
| `webhook_secret` | per bot, sent to Telegram as `secret_token` |
| `bot_username` | from `getMe`, shown on the card |
| `allowed_ids` | comma-separated numeric Telegram user IDs that may pair through this bot, empty means owner only |
| `enabled` | the toggle |
| `created_at`, `last_error` | for the Needs attention state |

`bot_key` is deliberately not a secret. It is an opaque lookup handle.
Authentication is the `x-telegram-bot-api-secret-token` header, compared with
`hmac.compare_digest`, which `TelegramAdapter.verify_webhook` already does.

`TelegramAdapter` already takes `token`, `webhook_secret` and `public_url` as
constructor arguments, so per-user bots need instances, not a rewrite.

### Saving a bot

1. The user expands the Telegram row, clicks Use my own bot, pastes a BotFather
   token.
2. Tasks calls `getMe` first. If Telegram rejects it, nothing is stored and the
   form shows the exact error. A stored row always means a token that worked at
   least once.
3. Tasks encrypts the token, generates `bot_key` and `webhook_secret`, inserts
   the row, then calls
   `setWebhook(url=.../webhook/telegram/{bot_key}, secret_token=...)`.
4. The card returns showing `Connected as @your_bot`, plus a pairing code.

### Receiving a message

```
Telegram -> POST /webhook/telegram/{bot_key}      (webhook-handler)
              | cache miss
            GET /gateway/bots/{bot_key}            (tasks, internal secret)
              | owner, token, secret, allowed_ids, enabled
            verify x-telegram-bot-api-secret-token
              |
            existing gateway pipeline, unchanged
```

The adapter is cached per `bot_key`. A restart costs one extra hop on the next
message and nothing else.

`/webhook/telegram` with no key keeps serving the shared bot on the env-var
path, so `@aiuiteam_bot` is untouched.

### Pairing

Pairing stays code-based. Telegram bot usernames are public and searchable, so
trust-on-first-use would be an account takeover: a stranger could find
`@ralphs_io_bot`, message it first, and be linked to Ralph's IO account. The bot
answers an unknown sender with "send me the code from your Channels page,"
which is the flow that already exists.

`allowed_ids` defaults to owner only. Adding IDs lets named people pair through
your bot, each to their own IO account, never to yours.

### Both bots coexist

A reply always goes back on whichever bot the message arrived on. Where IO
starts the conversation, such as cron results and notifications, the user's own
bot wins if they have one.

## UI

Channels lives in the narrow right pane and rows already expand in place, so
the Hermes modal becomes an inline expansion. Same fields, same buttons.

Available, no bot yet:

```
 Telegram   Available
   Chat with IO from Telegram DMs, including voice memos.

   Quick connect
   Message @aiuiteam_bot and send this code:
      4 8 2 1                      expires in 9:41

   Use my own bot                        Setup guide
   Your bot, your token, your data. Nobody else can
   see it or configure it.

   BOT TOKEN *
   [ 123456:AA...                                  ]
   Get one from @BotFather on Telegram.

   ALLOWED TELEGRAM USER IDS
   [ leave empty for just you                      ]

                          [ Cancel ]  [ SAVE & ENABLE ]
```

Connected through your own bot. The toggle is the user's, not the server's.
Off calls `deleteWebhook`, so the bot goes quiet without being deleted:

```
 Telegram   Connected                            [ ON  o ]
   Your bot @ralphs_io_bot, linked as @ralph, 2 days ago

   [ Test ]   [ Edit ]   [ Remove bot ]
```

Test reports what Telegram actually said, success or failure, in place under
the buttons. It has two modes, because a freshly saved bot has nobody to talk
to yet:

- not paired yet: Test calls `getMe` and confirms the token still works,
  answering "Your bot is alive. Now message it and send your code."
- paired: Test calls `sendMessage` to the owner's linked chat, so a pass means
  the whole path works, not just the credential.

A broken bot says so rather than going silent:

```
 Telegram   Needs attention
   Your bot stopped responding 2 hours ago.
   Telegram said: 401 Unauthorized. The token may have
   been revoked in BotFather.            [ Test ]  [ Edit ]
```

`CHANNEL_CATALOGUE` grows from eight to ten with Mattermost and Matrix, to
match the Hermes list. Every row renders the three controls; on a channel that
is not built the controls are inert and the existing reason copy explains why.

## Security

- The token is encrypted at rest, so a database dump alone leaks nothing.
- It never appears in a URL, never in a log line, and never returns to the
  browser. The API returns a masked hint such as `...AA4f` so the card can show
  which token is stored.
- Every browser-facing read of `gateway_bots` filters on the email from the
  session, never on a value from the request. `bot_key` resolves only through
  the internal-secret endpoint, which a browser cannot reach.
- Test is rate limited per user, since it spends an outbound Telegram call.
- Saving a token means IO can send as that bot. The card says so plainly.

## Failure handling

| What breaks | What happens |
|---|---|
| `getMe` rejects the token | Nothing stored. Exact Telegram error in the form. |
| `setWebhook` fails after insert | Row saved `enabled=false` with `last_error`. Card shows Needs attention with Retry. |
| Tasks down during a lookup | Return 503 so Telegram redelivers. Never 200-and-drop. |
| Unknown `bot_key` | 404 immediately, no row written, no work done. |
| Toggle off, update still arrives | 200 and ignore. `deleteWebhook` stops it at source. |
| `deleteWebhook` fails on removal | Row still deleted. The orphan hits an unknown key and 404s, so it is inert. |
| Fernet key missing at boot | Save refuses with a clear error. Never falls back to plaintext. |

### A bug this surfaces

`_gateway_seen_updates` in `webhook-handler/main.py` holds bare `update_id`
values, but `update_id` is a per-bot counter. Two users' bots will collide on
the same integer and one person's message will silently vanish as a duplicate.
The key becomes `(bot_key, update_id)`, with the shared bot using a fixed key.
Fixing this is part of the work.

## Testing

Following the module-level seam pattern already used in this branch, so no test
calls Telegram for real.

Tasks:
- a bad token stores no row at all
- `setWebhook` failing leaves `enabled=false` with `last_error`
- the save response carries only a masked token
- user B cannot read, test, toggle or delete user A's bot, extending the
  isolation test from `1cfba5e4d`
- Fernet round-trips

webhook-handler:
- a cache miss makes exactly one internal call, a hit makes none
- unknown `bot_key` 404s without touching the database
- a wrong secret header is rejected
- tasks being down returns 503
- two different bots emitting the same `update_id` are both processed. This
  test fails against today's code, which is the point of writing it.

Page, extending `ca07f1524`:
- every row renders all three controls
- any inert control carries a reason next to it

The `gateway_bots` CRUD tests need the `db_session` fixture, so they run in the
container per CLAUDE.md, not locally.

## Rollout

Migration `036_gateway_bots.sql`. Two services ship: tasks through
`deploy_orchestrator.sh`, and webhook-handler by hand, one `scp` per file with
the CRLF `sed` after, since the script does not watch it.

It lands dormant. No user has a bot, the table is empty, `/webhook/telegram`
keeps serving `@aiuiteam_bot`, and the deploy changes nothing visible.

Prod verification is a real BotFather bot: save it, Test it, message it, get a
reply, toggle it off, confirm it goes quiet.

## Follow-ups, deliberately not in this spec

- Making a second channel live, reusing this pattern. Slack is the cheapest
  next one, because the Events API over HTTPS needs no persistent connection.
- Discord per-user bots. DM chat needs an open websocket per bot, which caps
  how many users can have it on a 3.8 GB box. Slash commands avoid the cap
  entirely. That trade-off is its own decision.
- The agent-over-all-connections layer.
