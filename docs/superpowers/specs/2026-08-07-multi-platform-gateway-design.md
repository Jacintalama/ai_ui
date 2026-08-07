# Multi-Platform Gateway, phase 1: Telegram and CLI

Date: 2026-08-07
Status: approved design, not yet implemented
Prior art: NousResearch/hermes-agent (MIT), read but not imported

## The problem

Everything valuable on the platform lives inside Open WebUI: per-user memory through
the Brain, the Gmail assistant, Documents export, "remember that...", thirteen models,
the free auto-router and Fusion. None of it is reachable unless you open a browser
and log in.

There is a second problem underneath. `webhook-handler` is 21,741 lines and contains a
Discord implementation and a near-duplicate Slack implementation of every feature:

| Feature | Discord | Slack | Total |
|---|---:|---:|---:|
| Commands and interactions | 6,749 | 1,962 | 8,711 |
| App Builder panel | 1,024 | 582 | 1,606 |
| Video panel | 388 | 497 | 885 |
| Schedule panel | 219 | 430 | 649 |
| Recruiting panel | 145 | 278 | 423 |
| Recruiting review | 118 | 238 | 356 |

Those pairs are not one flow with two transports. They are two different UI toolkits
(Discord components, Slack Block Kit) drawing the same flow. Adding three more
platforms the way we build today means writing every panel three more times.

## Goals

1. A person can message the IO agent from Telegram, including by voice memo, and get an
   answer built from their own Brain, with their own tools and models.
2. The same conversation can be continued from a terminal, and from the Open WebUI web
   app.
3. Adding platform number three is a small file, not a new copy of every feature.

## Non-goals

- **Panel unification is out of scope.** Discord and Slack panels keep working exactly
  as they are and are not touched. See "Why panels are excluded" below.
- Group chats are out of scope for phase 1. See decision 4.
- WhatsApp and Signal are out of scope for phase 1. See phases.
- Concurrent editing of one conversation from two surfaces at the same instant.
  Last write wins.

## What we learned from hermes-agent

Their `gateway/` module is 85,300 lines across more than twenty adapters. Three findings
shaped this design.

**The adapter surface is tiny, and that is the trick.** `BasePlatformAdapter` is 4,825
lines but declares only three abstract methods. Everything else has a working default in
the base. A new platform is a small file. We preserve that property.

**Their continuity claim oversells the code.** `build_session_key()` puts the platform
name directly in the key, so platforms are isolated by design. Continuity is an explicit
`/resume` that repoints a session at another transcript. That is correct, because
automatic merging would leak group context into private chats, but it means we build a
command, not magic.

**Buttons are not portable.** Searching their adapters for interactive elements returns
55 hits in Telegram and zero in both WhatsApp and Signal. Their answer is that text is
the universal substrate and buttons are a per-platform enhancement.

### Why panels are excluded

That third finding is the reason panel unification is a non-goal. Our panels are the
duplicated code, and they are duplicated because they are toolkit-specific. Signal has
no interactive elements at all and WhatsApp caps at three reply buttons, so porting
panels is not an adapter problem, it is a redesign of every flow into a text fallback.
Folding that into this project would have made it unshippable. It stays a separate
future decision.

## Decisions

| # | Question | Decision |
|---|---|---|
| 1 | What is the gateway for? | Talking to the AI from anywhere. Text first. Panels untouched. |
| 2 | Which backend answers? | Open WebUI, as the paired user. |
| 3 | Who can use it? | Everyone, through self-serve pairing. No admin in the loop. |
| 4 | Group chats? | Direct messages only. |
| 5 | Which platforms first? | Telegram and CLI. |

Decision 4 is a privacy decision, not a feature decision. The Brain is injected into
every model call. In a group, one person asking "what am I working on" would print their
private memory to the whole room with no warning and no way to know in advance. Refusing
non-DM chats outright means no code path exists for that to happen.

Decision 5 reflects real cost. Telegram and CLI have no external blocker. Discord and
Slack already have live connections to reroute. WhatsApp needs Meta business
verification and template approval, which is process rather than code. Signal needs a
JVM daemon of roughly 200 to 400MB on a box with about 1.2GB free.

## Architecture

The gateway is a package inside `webhook-handler`. No new container is deployed.

```
Telegram ──webhook──┐
                    ├──> gateway/ ──> MessageEvent ──> resolve identity (tasks)
CLI script ──HTTP───┘        │                              │
                             │                    unpaired ─┴──> issue code, reply
                             │                      paired
                             v                        │
                      [voice? POST OWUI                v
                       /audio/transcriptions]   tasks mints 60s OWUI token
                             │                        │
                             v                        │
                      OWUI /api/chat/completions <────┘
                             │
              Brain filter + Gmail/Documents/Remember tools
              all run as that user, unchanged
                             │
                             v
                      reply ──> adapter.send()
                             │
                      store OWUI chat id in gateway_sessions
```

The gateway owns four jobs and nothing else: normalize inbound, resolve identity,
transcribe audio, route to Open WebUI as that person. It owns no model logic, no tools,
no memory and no prompt, because all of those already exist and stay where they are.

The consequence is that anything added to Open WebUI later appears on every gateway
platform with no gateway change.

### Acting as the user

This is the hop the design turns on, and getting it wrong fails silently.

If the gateway called Open WebUI with the shared admin API key we already hold, Open
WebUI would resolve the caller as the admin, and the Brain filter would inject the
*admin's* memory into every answer for every user. During testing by an admin that looks
completely correct.

Verified inside the running production container on 2026-08-07:

- `open_webui/utils/auth.py` sets `ALGORITHM = 'HS256'` and
  `SESSION_SECRET = WEBUI_SECRET_KEY`.
- `create_token(data, expires_delta)` adds `jti`, `iat` and `exp`.
- `get_current_user` reads `data['id']` and calls `Users.get_user_by_id(data['id'])`.
- `is_valid_token` is a **revocation blocklist, not an allowlist**. It returns `True`
  unless the `jti` or the user has been explicitly revoked, so a freshly minted token
  with a random `jti` passes.

So a service holding `WEBUI_SECRET_KEY` can present a request as any user.

**The tasks service mints the token, not the gateway.** `WEBUI_SECRET_KEY` is added to
tasks only. The gateway receives a token already scoped to one user with a 60 second
expiry. Tokens are minted per request, never persisted and never logged.

### Continuity

`gateway_sessions` maps a conversation to a real Open WebUI chat id. The first message
creates a chat via `POST /api/v1/chats/new`; each turn appends via
`POST /api/v1/chats/{id}`. Both routes confirmed present in the running container, along
with `GET /api/v1/chats/{id}`.

Because the mapping is to a real chat, the Telegram conversation appears in the user's
Open WebUI sidebar, is searchable, and feeds the Brain like any other chat, since the
knowledge graph already reads chats as a source. Continuity is not a bespoke mechanism
we maintain. It is the chat id.

`/resume` lists the user's recent gateway chats, takes a pick, and repoints
`gateway_sessions` at that `owui_chat_id`.

## Components

```
webhook-handler/gateway/
  events.py      MessageEvent, SessionSource, MessageType
  base.py        BasePlatformAdapter
  registry.py    PlatformEntry, PlatformRegistry
  pairing.py     issue and redeem codes (calls tasks)
  sessions.py    conversation -> Open WebUI chat id (calls tasks)
  platforms/
    telegram.py
    cli.py
```

Estimated 1,500 to 2,000 lines. `webhook-handler` runs at 110MB of its 512MB cap, so
there is room.

### events.py

```python
class MessageType(Enum):
    TEXT = "text"
    VOICE = "voice"
    PHOTO = "photo"
    DOCUMENT = "document"

@dataclass
class SessionSource:
    platform: str            # "telegram" | "cli"
    chat_id: str
    chat_type: str = "dm"    # phase 1 refuses anything else
    user_id: str | None = None
    user_name: str | None = None

@dataclass
class MessageEvent:
    text: str
    source: SessionSource
    message_type: MessageType = MessageType.TEXT
    media_paths: list[str] = field(default_factory=list)   # already downloaded
    message_id: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)
```

hermes's `auto_skill`, `channel_prompt`, `channel_context` and `internal` fields are
dropped, because they serve their agent loop and we do not have one. `chat_type` is kept
even though phase 1 is DM only, because it is what we use to detect and refuse a group.

### base.py

hermes declares three abstract methods because their adapters are long-lived clients
with callbacks. Ours are webhook driven, so parsing the inbound payload is a real half
of the job and belongs in the contract. This is a deliberate deviation.

```python
class BasePlatformAdapter(ABC):
    @abstractmethod
    async def connect(self) -> bool: ...       # telegram: setWebhook.  cli: no-op
    @abstractmethod
    async def disconnect(self) -> None: ...    # telegram: deleteWebhook
    @abstractmethod
    def parse_inbound(self, payload, headers) -> MessageEvent | None: ...
    @abstractmethod
    async def send(self, chat_id: str, text: str) -> None: ...
```

Defaulted in the base, overridden only when a platform can do better:

- `send_typing(chat_id)` and `stop_typing(chat_id)`, no-ops by default
- `verify_webhook(payload, headers) -> bool`, returns True by default
- `download_media(ref) -> str`, raises `NotImplementedError` by default
- chunking, driven by `max_message_length` from the registry entry

### registry.py

```python
@dataclass
class PlatformEntry:
    name: str
    label: str
    adapter_factory: Callable[[], BasePlatformAdapter]
    required_env: list[str]
    max_message_length: int = 0     # telegram: 4096
    emoji: str = "🔌"
```

The registry refuses to enable a platform whose `required_env` is unset. This is the
same dormant-by-default pattern used for Google sign-in: the code ships, the platform
stays dark until someone supplies a token, and deploying changes nothing visible.

hermes's plugin system, `setup_fn` and `platform_hint` are skipped. All three are real
ideas and none earns its keep at two platforms.

## Data model

`webhook-handler` has no database access: no driver in `requirements.txt`, no
`DATABASE_URL`. It reaches data through the tasks service over HTTP. So state lives in
the `tasks` schema and the gateway calls tasks with the existing `X-Internal-Secret`
pattern.

```sql
CREATE TABLE tasks.gateway_links (
    id                BIGSERIAL PRIMARY KEY,
    platform          TEXT        NOT NULL,
    platform_user_id  TEXT        NOT NULL,
    owui_user_id      TEXT        NOT NULL,
    email             TEXT        NOT NULL,
    linked_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (platform, platform_user_id)
);

CREATE TABLE tasks.gateway_pairing_codes (
    id                BIGSERIAL PRIMARY KEY,
    code_hash         TEXT        NOT NULL,
    platform          TEXT        NOT NULL,
    platform_user_id  TEXT        NOT NULL,
    platform_user_name TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at        TIMESTAMPTZ NOT NULL,
    redeemed_at       TIMESTAMPTZ,
    attempts          INT         NOT NULL DEFAULT 0
);
CREATE INDEX ON tasks.gateway_pairing_codes (platform, platform_user_id);

CREATE TABLE tasks.gateway_sessions (
    id            BIGSERIAL PRIMARY KEY,
    platform      TEXT        NOT NULL,
    chat_id       TEXT        NOT NULL,
    owui_chat_id  TEXT        NOT NULL,
    owui_user_id  TEXT        NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (platform, chat_id)
);
```

Retention: `gateway_sessions` rows idle for more than 30 days are pruned. The Open WebUI
chat itself is never deleted, because it is the user's data and lives in their sidebar.

## New endpoints in tasks (routes_gateway.py)

Paths below are as the tasks service sees them. Externally they are prefixed with
`/tasks`, so `GET /gateway/link` is `https://ai-ui.coolestdomain.win/tasks/gateway/link`
in a browser.

Internal, authenticated with `X-Internal-Secret`:

- `POST /gateway/resolve` given `{platform, platform_user_id, platform_user_name}`,
  returns either `{linked: true, email, owui_user_id, owui_token}` with a 60 second
  token, or `{linked: false, code, expires_at}`.
  When an unexpired unredeemed code already exists for that platform user, it returns
  **that same code** rather than issuing another. Otherwise a user who messages twice
  gets two codes and the rate limit reads as an error to someone doing nothing wrong.
- `GET  /gateway/session` given `{platform, chat_id}`, returns `{owui_chat_id}` or null.
- `PUT  /gateway/session` upserts the mapping.
- `GET  /gateway/sessions/recent` lists a user's recent gateway chats, for `/resume`.

User-facing, authenticated with `X-User-Email` like every other tasks page:

- `GET  /gateway/link` the page where a signed-in user pastes their code.
- `POST /gateway/link` redeems a code, creating the `gateway_links` row.

Because the link page is authenticated as the signed-in user, redeeming a code is
inherently done as a known account. The gateway never learns a password and the user
never pastes a token.

## Flows

### Pairing

1. Unpaired user messages the bot.
2. Gateway calls `POST /gateway/resolve`, receives `linked: false` and a code.
3. Bot replies with the code and the link URL.
4. User opens `https://ai-ui.coolestdomain.win/tasks/gateway/link`, already signed into
   IO, and pastes the code.
5. tasks validates and writes `gateway_links`, keyed to the signed-in user.
6. Next message from that platform user resolves as linked.

Hardening, taken from hermes's `pairing.py` because they did the reading:

- Codes hashed at rest, so a database leak grants nothing.
- 8 characters from a 32-character alphabet excluding `0/O/1/I`.
- 1 hour expiry, single use.
- One code per platform user per 10 minutes.
- Lockout after 5 failed redemption attempts.
- Codes never written to logs.

### A text message

1. Telegram POSTs the update. The route verifies the secret header, returns **200
   immediately**, and schedules the work in the background.
2. Deduplicate on `update_id`.
3. `parse_inbound` produces a `MessageEvent`. Non-DM `chat_type` gets a polite refusal
   and stops.
4. Resolve identity. Unpaired stops at the pairing reply.
5. `send_typing`.
6. Look up `gateway_sessions`. If a mapping exists, `GET /api/v1/chats/{id}` supplies the
   prior messages. If not, create one with `POST /api/v1/chats/new` and store the
   mapping. The Open WebUI chat is the only transcript; the gateway keeps no copy.
7. `POST /api/chat/completions` with the 60 second token.
8. Append both messages to the Open WebUI chat.
9. Chunk the reply at `max_message_length` and send.

Returning 200 before doing the work is not an optimization. Telegram re-delivers any
update that does not get a fast 200, so a slow model call would otherwise cause the same
message to be processed several times.

### A voice memo

Between steps 3 and 4 above: resolve the `file_id` with `getFile`, download the Opus
clip to a temp path, and POST it to `POST /api/v1/audio/transcriptions` with the user's
token. `faster-whisper-base` is already cached inside the open-webui container and
`faster_whisper` imports cleanly, so this adds no dependency and no new memory.

The transcript reaches the model wrapped so the model knows it was spoken:

```
[The user sent a voice message. Here's what they said: "..."]
```

Limits: clips over **2 minutes or 10MB** are refused with an explanation. The temp file
is deleted in a `finally`.

### /resume

`GET /gateway/sessions/recent`, present the list, take a pick, `PUT /gateway/session`
to repoint. Available on both Telegram and the CLI.

## Error handling

The governing rule differs from the rest of this codebase. Build post-processing fails
open because nobody is watching. Here somebody is waiting for a reply, so **nothing may
fail silently**. Every failure produces a sentence.

| Failure | Behaviour |
|---|---|
| Bad webhook secret | Return 200, log, ignore. A non-200 makes Telegram retry forever. |
| Duplicate `update_id` | Drop silently. It is a retry, not a message. |
| Group or channel chat | "I only work in direct messages for now." |
| Unpaired user | The pairing code reply. |
| tasks unreachable | "I can't reach my memory right now, try again in a moment." |
| Open WebUI timeout or 5xx | Same shape, naming the model. |
| Transcription failed | Say so explicitly. Never drop a voice memo silently. |
| Clip too long | State the 2 minute limit. |
| Reply over 4096 chars | Chunk on paragraph boundaries. |

## Security

- `WEBUI_SECRET_KEY` is added to the tasks service only. It is the ability to act as any
  user, so it lives in exactly one place. The gateway only ever holds a 60 second token
  scoped to one person.
- Minted tokens are never persisted and never logged.
- Pairing codes are hashed at rest and never logged.
- The Telegram webhook uses a secret header, checked on every request.
- Group chats are refused, so personal memory has no path to a shared room.
- No new inbound port. Telegram arrives through the existing Caddy and api-gateway path.

## Testing

Following the repo's existing seam pattern, `_owui_call`, `_transcribe` and
`_tasks_client` are module-level seams so tests monkeypatch instead of hitting the
network or a browser.

Runs anywhere:

- `parse_inbound` against recorded Telegram payloads: text, voice, photo, group, edited.
- Pairing lifecycle: generate, redeem, expire, single use, rate limit, lockout.
- Chunking at 4096 on paragraph boundaries.
- Group refusal.
- Registry refuses a platform with unset `required_env`.
- Duplicate `update_id` is dropped.

Needs the container, per the existing DB tier rule:

- `gateway_links`, `gateway_pairing_codes` and `gateway_sessions` round trips.
- Token minting produces a token Open WebUI accepts.

### Acceptance check

No unit test can prove the premise the design rests on. The acceptance check is
empirical and must be run on the server:

1. Pair a real Telegram account to a non-admin IO user.
2. Send a real message.
3. Confirm in the tasks logs that the Brain context fetch fired with **that user's
   email**, not the admin's.
4. Send a real voice memo and confirm the transcript reaches the model.
5. Open Open WebUI in a browser and confirm the conversation is in that user's sidebar.

If step 3 shows the wrong address, the design is wrong. That check runs on day one, not
at the end.

## Phases

**Phase 1, this spec.** Adapter core and registry, self-serve pairing and link page,
Telegram adapter with voice memos, CLI script, sessions and `/resume`. Gated by nothing;
every dependency is verified and in place.

**Phase 2.** Route the existing Discord and Slack connections through the same core.
Panels stay exactly as they are. This is an in-place refactor inside the service that
already owns both, not a cross-service migration, which is the main reason the gateway
lives in `webhook-handler`. Gated by phase 1 landing.

**Phase 3.** WhatsApp and Signal. Gated by things that are not code: Meta business
verification and template approval for WhatsApp, memory headroom for Signal.

## Verified versus untested

Everything marked verified was checked against the running production container or the
real codebase on 2026-08-07, not inferred from documentation.

| Claim | State | Evidence |
|---|---|---|
| A minted token can act as any user | verified | HS256 against `WEBUI_SECRET_KEY`; `is_valid_token` is a blocklist |
| The Brain resolves per user | verified | Filter reads `__user__.email`, calls `/context` with it |
| Chats can be created and appended | verified | `POST /chats/new`, `GET|POST /chats/{id}` present |
| Transcription is already available | verified | Model cached in container, `faster_whisper` imports |
| webhook-handler cannot reach the DB | verified | No driver in requirements, no `DATABASE_URL` |
| Whisper fits under the open-webui cap | untested | 568MB of 1024MB used; clip cap is the mitigation |
| Telegram delivery is reliable behind Caddy | untested | No bot exists yet; first real check in phase 1 |
| Signal fits on this box | doubtful | JVM daemon 200 to 400MB against roughly 1.2GB free |

## Deployment notes

- `webhook-handler` is **not** covered by `deploy_orchestrator.sh`. Deploy it manually,
  one `scp` per changed file, then rebuild. `scp -r` silently skips files.
- The tasks service is covered by the orchestrator.
- New env: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET` on webhook-handler,
  `WEBUI_SECRET_KEY` on tasks. All three go in the server `.env`, which is never
  committed and never overwritten.
- Telegram's webhook is registered by `connect()` at startup, so the public URL must
  exist in Caddy before first boot.
