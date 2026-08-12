# Bring Your Own Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each IO user save their own Telegram bot token on the Channels page, so their own bot talks to their own account and nobody else can see or configure it.

**Architecture:** The tasks service owns the secret. It stores a Fernet-encrypted bot token in a new `tasks.gateway_bots` table, validates the token against Telegram before storing, and registers a per-bot webhook at `/webhook/telegram/{bot_key}`. webhook-handler has no database, so on an inbound update it asks tasks for that bot's config over the existing internal-secret seam and caches the adapter per `bot_key`. The shared `@aiuiteam_bot` keeps working unchanged on the keyless `/webhook/telegram` route.

**Tech Stack:** FastAPI, SQLAlchemy async, Postgres, `cryptography.fernet`, httpx, pytest (`asyncio_mode = auto`), vanilla JS in `static/gateway-link.html`.

**Spec:** `docs/superpowers/specs/2026-08-12-bring-your-own-bot-design.md`

## Global Constraints

- Branch: `feat/multi-platform-gateway`. Do not create a new branch.
- **Never log a bot token and never put one in a URL path.** `bot_key` is the opaque path segment. This repeats an existing rule in `webhook-handler/main.py` and a real past bug fixed in `d7e67d9c7`.
- **Import `crypto_utils` inside functions, never at module scope.** It raises `RuntimeError` at import when `AIUI_FERNET_KEY` is unset, which would take the whole tasks service down instead of failing one save.
- **Do not modify the existing Discord or Slack integrations.** Not `handlers/`, not the Discord bot, not the Slack app.
- **`/webhook/telegram` with no key must keep serving the shared bot** on the `TELEGRAM_BOT_TOKEN` env path, unchanged.
- `mcp-servers/tasks/pytest.ini` sets `asyncio_mode = auto`, so async tests need no decorator.
- Running the tasks suite locally produces roughly 130 pre-existing `ERROR at setup` failures from `db_session` with no local Postgres. That is not your change. Tests marked "container tier" in this plan are expected to error locally.
- Tasks service needs `GATEWAY_PUBLIC_URL` in its environment (webhook-handler already has it). Task 11 adds it to `docker-compose.unified.yml`.
- Commit after every task. Do not squash tasks together.

## File Structure

| File | Responsibility |
|---|---|
| `mcp-servers/tasks/migrations/036_gateway_bots.sql` | create | The table. Idempotent, like every other migration. |
| `mcp-servers/tasks/models.py` | modify | `GatewayBot` model, next to `GatewayLink`. |
| `mcp-servers/tasks/gateway_bots.py` | create | Pure helpers: key generation, encryption wrapper, token masking, allowed-id parsing. No I/O, no DB. |
| `mcp-servers/tasks/telegram_api.py` | create | The only place that talks to api.telegram.org from tasks. Module-level seam so tests never make a network call. |
| `mcp-servers/tasks/routes_gateway.py` | modify | Browser CRUD on `page_router`, internal lookup and claim on `router`, catalogue grows to ten. |
| `mcp-servers/tasks/static/gateway-link.html` | modify | The inline configure form, Test, Edit, Remove, toggle, and the inert-control shape on every row. |
| `webhook-handler/clients/tasks.py` | modify | `gateway_bot_config` and `gateway_bot_claim`. |
| `webhook-handler/main.py` | modify | `/webhook/telegram/{bot_key}`, the adapter cache, the allow gate, and the dedupe key fix. |

Tests live beside the existing gateway tests in `mcp-servers/tasks/tests/` and `webhook-handler/tests/`.

---

### Task 1: The table and the model

**Files:**
- Create: `mcp-servers/tasks/migrations/036_gateway_bots.sql`
- Modify: `mcp-servers/tasks/models.py` (add after the `GatewayLink` class)
- Test: `mcp-servers/tasks/tests/test_gateway_bot_model.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `models.GatewayBot` with columns `id`, `bot_key`, `email`, `platform`, `token_encrypted`, `webhook_secret`, `bot_username`, `allowed_ids`, `owner_platform_user_id`, `enabled`, `created_at`, `last_error`.

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_gateway_bot_model.py`:

```python
"""The bots table is where a user's own bot token lives.

Column-level test on purpose: the encrypted token and the owner email are the
two fields whose absence would silently turn this into a plaintext store or a
shared one.
"""
from models import GatewayBot


def test_table_is_in_the_tasks_schema():
    assert GatewayBot.__tablename__ == "gateway_bots"
    assert GatewayBot.__table_args__["schema"] == "tasks"


def test_every_column_the_design_needs_exists():
    columns = set(GatewayBot.__table__.columns.keys())
    assert columns == {
        "id", "bot_key", "email", "platform", "token_encrypted",
        "webhook_secret", "bot_username", "allowed_ids",
        "owner_platform_user_id", "enabled", "created_at", "last_error",
    }


def test_the_token_column_is_named_for_being_encrypted():
    # A column called `token` would invite a plaintext write. The name is the
    # guardrail.
    assert "token" not in GatewayBot.__table__.columns
    assert "token_encrypted" in GatewayBot.__table__.columns


def test_a_bot_key_is_unique_across_users():
    # bot_key is the public path segment. Two rows sharing one would make an
    # inbound update ambiguous.
    assert GatewayBot.__table__.columns["bot_key"].unique is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd mcp-servers/tasks && python -m pytest tests/test_gateway_bot_model.py -q
```

Expected: FAIL with `ImportError: cannot import name 'GatewayBot' from 'models'`.

- [ ] **Step 3: Write the migration**

Create `mcp-servers/tasks/migrations/036_gateway_bots.sql`:

```sql
-- 036: a user's own chat bot.
--
-- Hermes configures one bot per server. IO has many accounts, so a bot belongs
-- to exactly one of them: their token, their data, invisible to everyone else.
--
-- The token is Fernet-encrypted by the application before it ever reaches this
-- table, so a dump of this database grants nobody the ability to send as
-- anyone's bot.
--
-- bot_key is NOT a secret. It is the opaque path segment in
-- /webhook/telegram/{bot_key}. Authentication is webhook_secret, which Telegram
-- echoes back in the x-telegram-bot-api-secret-token header.
--
-- Idempotent: db.py re-runs every migration on every startup.

CREATE TABLE IF NOT EXISTS tasks.gateway_bots (
    id                      BIGSERIAL PRIMARY KEY,
    bot_key                 TEXT        NOT NULL,
    email                   TEXT        NOT NULL,
    platform                TEXT        NOT NULL,
    token_encrypted         TEXT        NOT NULL,
    webhook_secret          TEXT        NOT NULL,
    bot_username            TEXT,
    -- Comma-separated platform user ids allowed to talk to this bot. Empty
    -- means owner only, enforced through owner_platform_user_id below.
    allowed_ids             TEXT        NOT NULL DEFAULT '',
    -- The platform account that claimed this bot by messaging it first. NULL
    -- until first contact. Claiming decides who the bot talks to; it does NOT
    -- link an IO account, which still requires a pairing code.
    owner_platform_user_id  TEXT,
    enabled                 BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error              TEXT
);

-- The inbound hot path: one lookup per update on a cold cache.
CREATE UNIQUE INDEX IF NOT EXISTS gateway_bots_key
    ON tasks.gateway_bots (bot_key);

-- The Channels page lists this account's bots.
CREATE INDEX IF NOT EXISTS gateway_bots_email
    ON tasks.gateway_bots (email);

-- One bot per platform per account. A second Telegram bot for the same user
-- would make "which bot does IO start a conversation on" ambiguous.
CREATE UNIQUE INDEX IF NOT EXISTS gateway_bots_email_platform
    ON tasks.gateway_bots (email, platform);
```

- [ ] **Step 4: Add the model**

In `mcp-servers/tasks/models.py`, directly after the `GatewayLink` class:

```python
class GatewayBot(Base):
    """A bot a user brought themselves, rather than the one IO operates.

    `token_encrypted` is Fernet ciphertext, never plaintext. `bot_key` is the
    opaque segment in /webhook/telegram/{bot_key} and is deliberately not a
    secret: authentication is `webhook_secret`, which Telegram echoes back in a
    header."""
    __tablename__ = "gateway_bots"
    __table_args__ = {"schema": "tasks"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    bot_key = Column(Text, nullable=False, unique=True)
    email = Column(Text, nullable=False)
    platform = Column(Text, nullable=False)
    token_encrypted = Column(Text, nullable=False)
    webhook_secret = Column(Text, nullable=False)
    bot_username = Column(Text)
    allowed_ids = Column(Text, nullable=False, default="")
    owner_platform_user_id = Column(Text)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False,
                        server_default=func.now())
    last_error = Column(Text)
```

If `Boolean` is not already imported in `models.py`, add it to the existing `from sqlalchemy import ...` line.

- [ ] **Step 5: Run test to verify it passes**

```bash
cd mcp-servers/tasks && python -m pytest tests/test_gateway_bot_model.py -q
```

Expected: PASS, 4 passed.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/migrations/036_gateway_bots.sql mcp-servers/tasks/models.py mcp-servers/tasks/tests/test_gateway_bot_model.py
git commit -m "feat(gateway): a table for a bot that belongs to one user"
```

---

### Task 2: Key generation, encryption, and masking

**Files:**
- Create: `mcp-servers/tasks/gateway_bots.py`
- Test: `mcp-servers/tasks/tests/test_gateway_bots_helpers.py`

**Interfaces:**
- Consumes: `crypto_utils.encrypt`, `crypto_utils.decrypt` (imported lazily inside functions).
- Produces:
  - `new_bot_key() -> str` (32 lowercase hex chars)
  - `new_webhook_secret() -> str` (32 lowercase hex chars)
  - `encrypt_token(token: str) -> str`
  - `decrypt_token(blob: str) -> str`
  - `mask_token(token: str) -> str`
  - `parse_allowed_ids(raw: str) -> str` (normalized comma-separated digits)
  - `is_allowed(allowed_ids: str, owner_platform_user_id: str | None, sender_id: str) -> bool`

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_gateway_bots_helpers.py`:

```python
"""Pure helpers around a user's own bot. No database, no network.

The masking and the allow gate are the two that carry real consequences: one
decides what leaves the server, the other decides who gets to talk to a bot.
"""
import os

os.environ.setdefault("AIUI_FERNET_KEY",
                      "hUZ3RkVvY0JmS3FnWlp4TXcyN0RkNTZWc1RCQzNKS1E=")

import gateway_bots as gb


def test_a_bot_key_is_long_random_hex():
    key = gb.new_bot_key()
    assert len(key) == 32
    assert all(c in "0123456789abcdef" for c in key)


def test_two_bot_keys_are_never_the_same():
    assert gb.new_bot_key() != gb.new_bot_key()


def test_a_webhook_secret_is_its_own_value():
    # Reusing bot_key as the secret would make the public path segment the
    # credential.
    assert gb.new_webhook_secret() != gb.new_bot_key()
    assert len(gb.new_webhook_secret()) == 32


def test_a_token_survives_a_round_trip():
    token = "123456:AAH1234567890abcdefghijklmnopqrs"
    assert gb.decrypt_token(gb.encrypt_token(token)) == token


def test_encrypting_does_not_leave_the_token_readable():
    token = "123456:AAH1234567890abcdefghijklmnopqrs"
    assert token not in gb.encrypt_token(token)


def test_a_masked_token_shows_only_the_last_four():
    assert gb.mask_token("123456:AAH1234567890abcdefghijklmnop4f2a") == "...4f2a"


def test_a_short_token_masks_to_nothing_readable():
    # Never fall back to showing the whole thing when it is short.
    assert gb.mask_token("abc") == "..."


def test_allowed_ids_are_normalized():
    assert gb.parse_allowed_ids(" 111, 222 ,333 ") == "111,222,333"


def test_allowed_ids_drop_anything_that_is_not_a_number():
    # A Telegram user id is numeric. Anything else is a typo or an injection
    # attempt, and silently keeping it would widen the gate.
    assert gb.parse_allowed_ids("111, @someone, 222") == "111,222"


def test_allowed_ids_of_nothing_is_empty():
    assert gb.parse_allowed_ids("  ,  , ") == ""


def test_an_unclaimed_bot_lets_the_first_sender_in():
    assert gb.is_allowed("", None, "999") is True


def test_a_claimed_bot_only_serves_its_claimer():
    assert gb.is_allowed("", "999", "999") is True
    assert gb.is_allowed("", "999", "1000") is False


def test_an_allow_list_overrides_the_claim():
    assert gb.is_allowed("111,222", "999", "222") is True
    assert gb.is_allowed("111,222", "999", "999") is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd mcp-servers/tasks && python -m pytest tests/test_gateway_bots_helpers.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gateway_bots'`.

- [ ] **Step 3: Write the implementation**

Create `mcp-servers/tasks/gateway_bots.py`:

```python
"""Pure helpers for a bot that belongs to one user.

No database and no network, so every rule here is testable without either.

crypto_utils is imported INSIDE the functions on purpose: it raises at import
time when AIUI_FERNET_KEY is unset, and importing it at module scope would take
the whole tasks service down at boot instead of failing one save with a message
the user can act on.
"""
import secrets


def new_bot_key() -> str:
    """The opaque path segment in /webhook/telegram/{bot_key}.

    Not a secret, but unguessable anyway: a guessable one would let anyone
    probe which bots exist."""
    return secrets.token_hex(16)


def new_webhook_secret() -> str:
    """What Telegram echoes back in x-telegram-bot-api-secret-token.

    Separate from bot_key so the public part of the URL is never the
    credential."""
    return secrets.token_hex(16)


def encrypt_token(token: str) -> str:
    from crypto_utils import encrypt
    return encrypt(token)


def decrypt_token(blob: str) -> str:
    from crypto_utils import decrypt
    return decrypt(blob)


def mask_token(token: str) -> str:
    """What the browser is allowed to see: enough to recognise, never enough
    to use."""
    if len(token) < 8:
        return "..."
    return "..." + token[-4:]


def parse_allowed_ids(raw: str) -> str:
    """Normalize the allow list to comma-separated digits.

    Anything non-numeric is dropped rather than kept: a Telegram user id is a
    number, so a stray @handle is a mistake, and keeping it would leave the
    owner believing they had restricted access when they had not."""
    out = [part.strip() for part in (raw or "").split(",")]
    return ",".join(p for p in out if p.isdigit())


def is_allowed(allowed_ids: str, owner_platform_user_id: str | None,
               sender_id: str) -> bool:
    """May this sender talk to this bot?

    An explicit allow list wins outright. With no list, the bot serves only the
    account that claimed it, and an unclaimed bot serves whoever arrives first
    so that the owner can claim their own bot by messaging it."""
    allowed = [p for p in (allowed_ids or "").split(",") if p]
    if allowed:
        return str(sender_id) in allowed
    if not owner_platform_user_id:
        return True
    return str(sender_id) == str(owner_platform_user_id)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd mcp-servers/tasks && python -m pytest tests/test_gateway_bots_helpers.py -q
```

Expected: PASS, 13 passed.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/gateway_bots.py mcp-servers/tasks/tests/test_gateway_bots_helpers.py
git commit -m "feat(gateway): key generation, token masking, and the allow gate"
```

---

### Task 3: The Telegram API seam

**Files:**
- Create: `mcp-servers/tasks/telegram_api.py`
- Test: `mcp-servers/tasks/tests/test_telegram_api.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `class TelegramError(Exception)` with attribute `description: str`
  - `async def get_me(token: str) -> dict` returning `{"id": int, "username": str}`
  - `async def set_webhook(token: str, url: str, secret: str) -> None`
  - `async def delete_webhook(token: str) -> None`
  - `async def send_message(token: str, chat_id: str, text: str) -> None`
  - `_client_factory` module-level seam, defaults to `httpx.AsyncClient`

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_telegram_api.py`:

```python
"""The only place tasks talks to api.telegram.org.

Tests drive the module-level _client_factory seam, the same pattern the app
post-processing modules use, so nothing here touches the network.
"""
import pytest

import telegram_api as tg


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FakeClient:
    """Records every call so a test can assert on the URL as well as the body."""

    def __init__(self, payload=None, raises=None):
        self.payload = payload or {"ok": True, "result": {}}
        self.raises = raises
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None):
        self.calls.append((url, json))
        if self.raises:
            raise self.raises
        return FakeResponse(self.payload)


@pytest.fixture
def fake(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(tg, "_client_factory", lambda **kw: client)
    return client


async def test_get_me_returns_the_bot_identity(fake):
    fake.payload = {"ok": True, "result": {"id": 42, "username": "ralphs_io_bot"}}
    assert await tg.get_me("123:AAH") == {"id": 42, "username": "ralphs_io_bot"}


async def test_get_me_raises_what_telegram_actually_said(fake):
    fake.payload = {"ok": False, "description": "Unauthorized"}
    with pytest.raises(tg.TelegramError) as err:
        await tg.get_me("123:AAH")
    assert err.value.description == "Unauthorized"


async def test_a_network_failure_is_also_a_telegram_error(fake):
    # The caller has one thing to catch, so a save cannot 500 on a timeout.
    fake.raises = RuntimeError("connect timeout")
    with pytest.raises(tg.TelegramError):
        await tg.get_me("123:AAH")


async def test_set_webhook_sends_the_url_and_the_secret(fake):
    await tg.set_webhook("123:AAH", "https://io.example/webhook/telegram/abc",
                         "s3cret")
    url, body = fake.calls[0]
    assert url.endswith("/setWebhook")
    assert body["url"] == "https://io.example/webhook/telegram/abc"
    assert body["secret_token"] == "s3cret"


async def test_the_token_is_in_the_url_telegram_requires_and_nowhere_else(fake):
    await tg.delete_webhook("123:AAH")
    url, body = fake.calls[0]
    assert url == "https://api.telegram.org/bot123:AAH/deleteWebhook"
    assert body == {}


async def test_send_message_carries_the_chat_and_the_text(fake):
    await tg.send_message("123:AAH", "555", "IO is connected.")
    url, body = fake.calls[0]
    assert url.endswith("/sendMessage")
    assert body["chat_id"] == "555"
    assert body["text"] == "IO is connected."


async def test_send_message_surfaces_a_rejection(fake):
    fake.payload = {"ok": False, "description": "chat not found"}
    with pytest.raises(tg.TelegramError) as err:
        await tg.send_message("123:AAH", "555", "hi")
    assert err.value.description == "chat not found"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd mcp-servers/tasks && python -m pytest tests/test_telegram_api.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'telegram_api'`.

- [ ] **Step 3: Write the implementation**

Create `mcp-servers/tasks/telegram_api.py`:

```python
"""The only place the tasks service calls api.telegram.org.

One module so there is exactly one place that handles a bot token, and one
seam (_client_factory) so no test ever opens a socket.

NEVER log `token`. The Telegram API puts it in the URL, which is why _api()
exists and why nothing here logs a URL.
"""
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10.0

#: Swapped by tests. Production always gets a real client.
_client_factory = httpx.AsyncClient


class TelegramError(Exception):
    """Anything that stopped a Telegram call from succeeding.

    One exception type for both a rejection and a timeout, so a caller has one
    thing to catch and a save can never 500 on a network blip."""

    def __init__(self, description: str):
        super().__init__(description)
        self.description = description


def _api(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


async def _call(token: str, method: str, **payload: Any) -> dict:
    try:
        async with _client_factory(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(_api(token, method), json=payload)
            body = resp.json()
    except TelegramError:
        raise
    except Exception as exc:  # noqa: BLE001
        # Deliberately not logging the exception's repr: httpx puts the full
        # URL, and therefore the token, into its error messages.
        log.warning("telegram: %s failed to complete", method)
        raise TelegramError(f"Could not reach Telegram: {type(exc).__name__}")

    if not body.get("ok"):
        raise TelegramError(str(body.get("description") or "Telegram refused the call"))
    return body.get("result") or {}


async def get_me(token: str) -> dict:
    """Proves a token works and yields the bot's identity."""
    result = await _call(token, "getMe")
    return {"id": result.get("id"), "username": result.get("username") or ""}


async def set_webhook(token: str, url: str, secret: str) -> None:
    await _call(token, "setWebhook", url=url, secret_token=secret)


async def delete_webhook(token: str) -> None:
    await _call(token, "deleteWebhook")


async def send_message(token: str, chat_id: str, text: str) -> None:
    await _call(token, "sendMessage", chat_id=chat_id, text=text)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd mcp-servers/tasks && python -m pytest tests/test_telegram_api.py -q
```

Expected: PASS, 7 passed.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/telegram_api.py mcp-servers/tasks/tests/test_telegram_api.py
git commit -m "feat(gateway): one seam for talking to Telegram, with no token in any log"
```

---

### Task 4: Saving, listing, testing and removing a bot

**Files:**
- Modify: `mcp-servers/tasks/routes_gateway.py` (add to `page_router`, after the existing `disconnect` route)
- Test: `mcp-servers/tasks/tests/test_gateway_bot_routes.py`
- Test (container tier): `mcp-servers/tasks/tests/test_gateway_bot_routes_db.py`

**Interfaces:**
- Consumes: `gateway_bots.new_bot_key`, `new_webhook_secret`, `encrypt_token`, `mask_token`, `parse_allowed_ids`; `telegram_api.get_me`, `set_webhook`, `delete_webhook`, `send_message`, `TelegramError`; `models.GatewayBot`.
- Produces these routes on `page_router` (prefix `/tasks/gateway`), all requiring `current_user`:
  - `POST /bots` body `{"platform": str, "token": str, "allowed_ids": str}` returns `{"bot_key", "bot_username", "token_hint", "enabled", "allowed_ids"}`
  - `GET /bots` returns `{"bots": [ ... same shape, plus "last_error" ... ]}`
  - `POST /bots/{bot_key}/test` returns `{"ok": bool, "detail": str}`
  - `PATCH /bots/{bot_key}` body `{"enabled": bool}` returns the bot shape
  - `DELETE /bots/{bot_key}` returns `{"status": "removed"}`
- Produces module-level seam `_public_url() -> str` reading `GATEWAY_PUBLIC_URL`.

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_gateway_bot_routes.py`:

```python
"""Saving a bot, without a database.

The DB-backed behaviour lives in test_gateway_bot_routes_db.py, which only runs
in the container. What is tested here is the part that must hold regardless of
storage: a token that Telegram rejects is never written, and a token never
comes back to the browser.
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("INTERNAL_CALLBACK_SECRET", "test-internal-secret")
os.environ.setdefault("AIUI_FERNET_KEY",
                      "hUZ3RkVvY0JmS3FnWlp4TXcyN0RkNTZWc1RCQzNKS1E=")
os.environ.setdefault("GATEWAY_PUBLIC_URL", "https://io.example")

import routes_gateway
import telegram_api
from auth import CurrentUser, current_user


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(routes_gateway.page_router)
    app.dependency_overrides[current_user] = lambda: CurrentUser(
        email="ralph@example.com")
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def telegram_rejects(monkeypatch):
    async def _get_me(token):
        raise telegram_api.TelegramError("Unauthorized")
    monkeypatch.setattr(routes_gateway.telegram_api, "get_me", _get_me)


@pytest.fixture
def no_writes(monkeypatch):
    """Fails loudly if the route reaches the database at all."""
    written = []

    class Boom:
        async def __aenter__(self):
            written.append("opened")
            raise AssertionError("the route opened a session it should not have")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(routes_gateway, "session", lambda: Boom())
    return written


def test_a_token_telegram_rejects_is_never_stored(client, telegram_rejects, no_writes):
    resp = client.post("/tasks/gateway/bots",
                       json={"platform": "telegram", "token": "123:bad",
                             "allowed_ids": ""})
    assert resp.status_code == 400
    assert no_writes == []


def test_the_rejection_says_what_telegram_said(client, telegram_rejects, no_writes):
    resp = client.post("/tasks/gateway/bots",
                       json={"platform": "telegram", "token": "123:bad",
                             "allowed_ids": ""})
    assert "Unauthorized" in resp.json()["detail"]


def test_an_unsupported_platform_is_refused_before_any_network_call(client, no_writes):
    # Discord and Slack rows exist on the page but cannot honour a save yet.
    resp = client.post("/tasks/gateway/bots",
                       json={"platform": "discord", "token": "x",
                             "allowed_ids": ""})
    assert resp.status_code == 400
    assert "not" in resp.json()["detail"].lower()


def test_an_empty_token_is_refused(client, no_writes):
    resp = client.post("/tasks/gateway/bots",
                       json={"platform": "telegram", "token": "   ",
                             "allowed_ids": ""})
    assert resp.status_code == 422 or resp.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd mcp-servers/tasks && python -m pytest tests/test_gateway_bot_routes.py -q
```

Expected: FAIL, all four with 404, because `POST /tasks/gateway/bots` does not exist.

- [ ] **Step 3: Write the implementation**

In `mcp-servers/tasks/routes_gateway.py`, add `telegram_api` and `gateway_bots` to the imports near `import gateway_pairing as gp`:

```python
import gateway_bots as gbots
import telegram_api
```

Add `GatewayBot` to the existing `from models import ...` line. Then append after the `disconnect` route:

```python
# --- A bot the user brought themselves ---------------------------------------
# Hermes configures one bot per server. Here a bot belongs to one account, so
# every read below filters on the session email and never on a path value.

#: Platforms that can actually honour a saved token today. Every other channel
#: shows the controls in an inert state, so the page never grows a button that
#: lies.
BOT_CAPABLE_PLATFORMS = {"telegram"}


def _public_url() -> str:
    """Where Telegram should deliver. Seam so tests need no env."""
    return os.environ.get("GATEWAY_PUBLIC_URL", "").rstrip("/")


class BotIn(BaseModel):
    platform: str = Field(min_length=1, max_length=32)
    token: str = Field(min_length=1, max_length=200)
    allowed_ids: str = Field(default="", max_length=500)


class BotToggleIn(BaseModel):
    enabled: bool


def _bot_view(row: GatewayBot) -> dict[str, Any]:
    """What the browser is allowed to know. Never the token.

    `token_hint` is empty here on purpose and is NOT derivable from a stored
    row: only the save response ever knows the plaintext, and only once."""
    return {
        "bot_key": row.bot_key,
        "platform": row.platform,
        "bot_username": row.bot_username or "",
        "token_hint": "",
        "enabled": bool(row.enabled),
        "allowed_ids": row.allowed_ids or "",
        "last_error": row.last_error or "",
    }


@page_router.post("/bots")
async def save_bot(body: BotIn,
                   user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    """Store a user's own bot token and point it at this server.

    getMe runs BEFORE anything is written, so a stored row always means a token
    that worked at least once. If setWebhook then fails the row survives but
    disabled, with the reason on it: a half-live bot that silently swallows
    messages is worse than one the page can tell you is broken."""
    platform = body.platform.strip().lower()
    if platform not in BOT_CAPABLE_PLATFORMS:
        raise HTTPException(
            status_code=400,
            detail=f"{platform} cannot take your own bot yet.")

    token = body.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Paste your bot token.")

    try:
        identity = await telegram_api.get_me(token)
    except telegram_api.TelegramError as exc:
        raise HTTPException(status_code=400,
                            detail=f"Telegram said: {exc.description}")

    bot_key = gbots.new_bot_key()
    secret = gbots.new_webhook_secret()

    try:
        encrypted = gbots.encrypt_token(token)
    except RuntimeError as exc:
        # AIUI_FERNET_KEY is missing. Refuse rather than store plaintext.
        log.error("gateway: cannot store a bot token: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="This server cannot store bot tokens securely right now.")

    async with session() as s:
        await s.execute(
            delete(GatewayBot).where(GatewayBot.email == user.email,
                                     GatewayBot.platform == platform))
        row = GatewayBot(
            bot_key=bot_key, email=user.email, platform=platform,
            token_encrypted=encrypted, webhook_secret=secret,
            bot_username=identity.get("username", ""),
            allowed_ids=gbots.parse_allowed_ids(body.allowed_ids),
            enabled=True, last_error=None,
        )
        s.add(row)
        await s.commit()

    hook_url = f"{_public_url()}/webhook/telegram/{bot_key}"
    try:
        await telegram_api.set_webhook(token, hook_url, secret)
    except telegram_api.TelegramError as exc:
        async with session() as s:
            await s.execute(
                update(GatewayBot).where(GatewayBot.bot_key == bot_key)
                .values(enabled=False, last_error=exc.description))
            await s.commit()
        log.warning("gateway: setWebhook failed for %s", user.email)
        return {"bot_key": bot_key, "platform": platform,
                "bot_username": identity.get("username", ""),
                "token_hint": gbots.mask_token(token),
                "enabled": False, "allowed_ids": gbots.parse_allowed_ids(body.allowed_ids),
                "last_error": exc.description}

    log.info("gateway: %s saved their own %s bot", user.email, platform)
    return {"bot_key": bot_key, "platform": platform,
            "bot_username": identity.get("username", ""),
            "token_hint": gbots.mask_token(token),
            "enabled": True,
            "allowed_ids": gbots.parse_allowed_ids(body.allowed_ids),
            "last_error": ""}


@page_router.get("/bots")
async def list_bots(user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    async with session() as s:
        rows = (await s.execute(
            select(GatewayBot).where(GatewayBot.email == user.email)
        )).scalars().all()
    return {"bots": [_bot_view(r) for r in rows]}


async def _owned_bot(s, email: str, bot_key: str) -> GatewayBot:
    """One bot, or a 404. Filtered on the session email, never on the path
    alone, so bot_key is a lookup handle and not an authorisation."""
    row = (await s.execute(
        select(GatewayBot).where(GatewayBot.bot_key == bot_key,
                                 GatewayBot.email == email)
    )).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="No such bot.")
    return row


@page_router.post("/bots/{bot_key}/test")
async def test_bot(bot_key: str,
                   user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    """Prove the bot works and say exactly what Telegram said.

    Two modes, because a bot saved thirty seconds ago has nobody to talk to
    yet: unpaired, getMe proves the credential; paired, a real message proves
    the whole path."""
    async with session() as s:
        row = await _owned_bot(s, user.email, bot_key)
        token = gbots.decrypt_token(row.token_encrypted)
        link = (await s.execute(
            select(GatewayLink).where(GatewayLink.email == user.email,
                                      GatewayLink.platform == row.platform)
        )).scalars().first()
        chat_id = row.owner_platform_user_id or (
            link.platform_user_id if link else "")

    try:
        if chat_id:
            await telegram_api.send_message(
                token, chat_id, "IO is connected. This message came from your own bot.")
            detail = "Sent. Check your Telegram."
        else:
            identity = await telegram_api.get_me(token)
            detail = (f"Your bot @{identity.get('username','')} is alive. "
                      "Now message it and send your code.")
    except telegram_api.TelegramError as exc:
        async with session() as s:
            await s.execute(
                update(GatewayBot).where(GatewayBot.bot_key == bot_key)
                .values(last_error=exc.description))
            await s.commit()
        return {"ok": False, "detail": f"Telegram said: {exc.description}"}

    async with session() as s:
        await s.execute(update(GatewayBot)
                        .where(GatewayBot.bot_key == bot_key)
                        .values(last_error=None))
        await s.commit()
    return {"ok": True, "detail": detail}


@page_router.patch("/bots/{bot_key}")
async def toggle_bot(bot_key: str, body: BotToggleIn,
                     user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    """Off deletes the webhook, so Telegram stops delivering at source rather
    than us dropping updates we keep receiving."""
    async with session() as s:
        row = await _owned_bot(s, user.email, bot_key)
        token = gbots.decrypt_token(row.token_encrypted)
        secret = row.webhook_secret

    error = ""
    try:
        if body.enabled:
            await telegram_api.set_webhook(
                token, f"{_public_url()}/webhook/telegram/{bot_key}", secret)
        else:
            await telegram_api.delete_webhook(token)
    except telegram_api.TelegramError as exc:
        error = exc.description

    async with session() as s:
        await s.execute(
            update(GatewayBot).where(GatewayBot.bot_key == bot_key)
            .values(enabled=bool(body.enabled) and not error,
                    last_error=error or None))
        await s.commit()
        row = await _owned_bot(s, user.email, bot_key)
        return _bot_view(row)


@page_router.delete("/bots/{bot_key}")
async def remove_bot(bot_key: str,
                     user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    """Remove the row even if Telegram will not let go of the webhook.

    An orphaned webhook points at a bot_key that no longer resolves, which
    404s, so it is inert. Keeping the row because a remote call failed would
    leave the user unable to get rid of their own token."""
    async with session() as s:
        row = await _owned_bot(s, user.email, bot_key)
        token = gbots.decrypt_token(row.token_encrypted)

    try:
        await telegram_api.delete_webhook(token)
    except telegram_api.TelegramError:
        log.warning("gateway: could not clear the webhook while removing a bot")

    async with session() as s:
        await s.execute(delete(GatewayBot).where(
            GatewayBot.bot_key == bot_key, GatewayBot.email == user.email))
        await s.commit()
    log.info("gateway: %s removed their own bot", user.email)
    return {"status": "removed"}
```

Add `update` to the existing `from sqlalchemy import delete, select` line so it reads `from sqlalchemy import delete, select, update`.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd mcp-servers/tasks && python -m pytest tests/test_gateway_bot_routes.py -q
```

Expected: PASS, 4 passed.

- [ ] **Step 5: Write the container-tier isolation test**

Create `mcp-servers/tasks/tests/test_gateway_bot_routes_db.py`:

```python
"""One account must not be able to touch another's bot.

Runs in the container, where there is a real database:
  ssh root@46.224.193.25 "docker exec tasks sh -lc \\
    'cd /app && python -m pytest tests/test_gateway_bot_routes_db.py -q'"

Locally every test here ERRORs at setup with no Postgres, which is expected.
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("AIUI_FERNET_KEY",
                      "hUZ3RkVvY0JmS3FnWlp4TXcyN0RkNTZWc1RCQzNKS1E=")
os.environ.setdefault("GATEWAY_PUBLIC_URL", "https://io.example")

import routes_gateway
from auth import CurrentUser, current_user
from models import GatewayBot

OWNER = "owner-byob@example.com"
STRANGER = "stranger-byob@example.com"


@pytest.fixture
def app_for(monkeypatch):
    async def _get_me(token):
        return {"id": 1, "username": "someones_bot"}

    async def _noop(*a, **kw):
        return None

    monkeypatch.setattr(routes_gateway.telegram_api, "get_me", _get_me)
    monkeypatch.setattr(routes_gateway.telegram_api, "set_webhook", _noop)
    monkeypatch.setattr(routes_gateway.telegram_api, "delete_webhook", _noop)

    def _build(email):
        app = FastAPI()
        app.include_router(routes_gateway.page_router)
        app.dependency_overrides[current_user] = lambda: CurrentUser(email=email)
        return TestClient(app, raise_server_exceptions=False)

    return _build


@pytest.fixture
async def owner_bot(db_session, app_for):
    client = app_for(OWNER)
    resp = client.post("/tasks/gateway/bots",
                       json={"platform": "telegram",
                             "token": "111:AAHownertokenvalue",
                             "allowed_ids": ""})
    assert resp.status_code == 200
    key = resp.json()["bot_key"]
    yield key
    await db_session.execute(
        GatewayBot.__table__.delete().where(GatewayBot.email.in_([OWNER, STRANGER])))
    await db_session.commit()


async def test_the_owner_sees_their_own_bot(owner_bot, app_for):
    body = app_for(OWNER).get("/tasks/gateway/bots").json()
    assert [b["bot_key"] for b in body["bots"]] == [owner_bot]


async def test_a_stranger_sees_nothing(owner_bot, app_for):
    assert app_for(STRANGER).get("/tasks/gateway/bots").json()["bots"] == []


async def test_a_stranger_cannot_toggle_it(owner_bot, app_for):
    resp = app_for(STRANGER).patch(f"/tasks/gateway/bots/{owner_bot}",
                                   json={"enabled": False})
    assert resp.status_code == 404


async def test_a_stranger_cannot_test_it(owner_bot, app_for):
    resp = app_for(STRANGER).post(f"/tasks/gateway/bots/{owner_bot}/test")
    assert resp.status_code == 404


async def test_a_stranger_cannot_delete_it(owner_bot, app_for):
    resp = app_for(STRANGER).delete(f"/tasks/gateway/bots/{owner_bot}")
    assert resp.status_code == 404


async def test_the_token_never_comes_back_in_a_listing(owner_bot, app_for):
    body = app_for(OWNER).get("/tasks/gateway/bots").json()
    assert "111:AAHownertokenvalue" not in str(body)


async def test_saving_twice_replaces_rather_than_duplicates(owner_bot, app_for):
    client = app_for(OWNER)
    client.post("/tasks/gateway/bots",
                json={"platform": "telegram", "token": "222:AAHsecondtoken",
                      "allowed_ids": ""})
    assert len(client.get("/tasks/gateway/bots").json()["bots"]) == 1
```

- [ ] **Step 6: Run the non-DB suite to confirm nothing regressed**

```bash
cd mcp-servers/tasks && python -m pytest tests/ -q -k "gateway and not db"
```

Expected: PASS. The `_db` files error at setup locally, which is why they are excluded here.

- [ ] **Step 7: Commit**

```bash
git add mcp-servers/tasks/routes_gateway.py mcp-servers/tasks/tests/test_gateway_bot_routes.py mcp-servers/tasks/tests/test_gateway_bot_routes_db.py
git commit -m "feat(gateway): save, test, toggle and remove your own bot"
```

---

### Task 5: The internal lookup and claim endpoints

**Files:**
- Modify: `mcp-servers/tasks/routes_gateway.py` (add to `router`, the internal one)
- Modify: `mcp-servers/tasks/tests/test_gateway_routes_auth.py` (extend `CALLS`)
- Test: `mcp-servers/tasks/tests/test_gateway_bot_internal.py`

**Interfaces:**
- Consumes: `models.GatewayBot`, `gateway_bots.decrypt_token`.
- Produces on `router` (prefix `/gateway`, `X-Internal-Secret` required):
  - `GET /bots/{bot_key}` returns `{"platform", "owner_email", "token", "webhook_secret", "allowed_ids", "owner_platform_user_id", "enabled"}` or 404
  - `POST /bots/{bot_key}/claim` body `{"platform_user_id": str}` returns `{"claimed": bool}`

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_gateway_bot_internal.py`:

```python
"""The lookup webhook-handler makes on a cold cache.

This endpoint hands out a decrypted bot token, so the only thing standing
between it and the internet is the internal secret and the fact that it is
mounted bare. Both are asserted here.
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("INTERNAL_CALLBACK_SECRET", "test-internal-secret")
os.environ.setdefault("AIUI_FERNET_KEY",
                      "hUZ3RkVvY0JmS3FnWlp4TXcyN0RkNTZWc1RCQzNKS1E=")

import routes_gateway

HEADERS = {"X-Internal-Secret": "test-internal-secret"}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes_gateway.router)
    return TestClient(app, raise_server_exceptions=False)


def test_lookup_without_the_secret_is_403(client):
    assert client.get("/gateway/bots/abc").status_code == 403


def test_claim_without_the_secret_is_403(client):
    resp = client.post("/gateway/bots/abc/claim", json={"platform_user_id": "1"})
    assert resp.status_code == 403


def test_the_lookup_is_not_on_the_browser_router(client):
    # page_router carries X-User-Email from a browser session. A bot token
    # endpoint must never be reachable that way.
    app = FastAPI()
    app.include_router(routes_gateway.page_router)
    browser = TestClient(app, raise_server_exceptions=False)
    assert browser.get("/tasks/gateway/bots/abc").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd mcp-servers/tasks && python -m pytest tests/test_gateway_bot_internal.py -q
```

Expected: FAIL. The first two return 404 instead of 403, because the routes do not exist.

- [ ] **Step 3: Write the implementation**

In `mcp-servers/tasks/routes_gateway.py`, append at the end of the file:

```python
# --- What webhook-handler needs to serve an inbound update --------------------
# Internal only. This hands back a DECRYPTED token, so it lives on `router`,
# which is mounted bare at http://tasks:8210 and is unreachable from a browser.


class BotClaimIn(BaseModel):
    platform_user_id: str = Field(min_length=1, max_length=64)


@router.get("/bots/{bot_key}")
async def bot_config(bot_key: str,
                     x_internal_secret: str = Header(default="")) -> dict[str, Any]:
    """Everything needed to answer one inbound update on this bot."""
    _require_internal(x_internal_secret)
    async with session() as s:
        row = (await s.execute(
            select(GatewayBot).where(GatewayBot.bot_key == bot_key)
        )).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="unknown bot")
    return {
        "platform": row.platform,
        "owner_email": row.email,
        "token": gbots.decrypt_token(row.token_encrypted),
        "webhook_secret": row.webhook_secret,
        "allowed_ids": row.allowed_ids or "",
        "owner_platform_user_id": row.owner_platform_user_id or "",
        "enabled": bool(row.enabled),
    }


@router.post("/bots/{bot_key}/claim")
async def bot_claim(bot_key: str, body: BotClaimIn,
                    x_internal_secret: str = Header(default="")) -> dict[str, bool]:
    """The first account to message a bot becomes the one it serves.

    Conditional on the column still being NULL, so two updates arriving
    together cannot race one another into overwriting the claim. Claiming does
    NOT link an IO account: that still needs a pairing code."""
    _require_internal(x_internal_secret)
    async with session() as s:
        result = await s.execute(
            update(GatewayBot)
            .where(GatewayBot.bot_key == bot_key,
                   GatewayBot.owner_platform_user_id.is_(None))
            .values(owner_platform_user_id=body.platform_user_id))
        await s.commit()
    return {"claimed": bool(result.rowcount)}
```

- [ ] **Step 4: Extend the existing fail-closed test**

In `mcp-servers/tasks/tests/test_gateway_routes_auth.py`, add two entries to `CALLS`:

```python
    ("get", "/gateway/bots/abc", None),
    ("post", "/gateway/bots/abc/claim", {"platform_user_id": "1"}),
```

- [ ] **Step 5: Run both tests to verify they pass**

```bash
cd mcp-servers/tasks && python -m pytest tests/test_gateway_bot_internal.py tests/test_gateway_routes_auth.py -q
```

Expected: PASS, 3 passed plus 12 passed.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/routes_gateway.py mcp-servers/tasks/tests/test_gateway_bot_internal.py mcp-servers/tasks/tests/test_gateway_routes_auth.py
git commit -m "feat(gateway): the internal lookup that lets webhook-handler serve a user's bot"
```

---

### Task 6: The client method on webhook-handler

**Files:**
- Modify: `webhook-handler/clients/tasks.py` (add to the multi-platform gateway section, after `gateway_recent_sessions`)
- Test: `webhook-handler/tests/test_gateway_bot_client.py`

**Interfaces:**
- Consumes: the routes from Task 5.
- Produces:
  - `async def gateway_bot_config(self, bot_key: str) -> dict | None` (None on 404)
  - `async def gateway_bot_claim(self, bot_key: str, platform_user_id: str) -> bool`

- [ ] **Step 1: Write the failing test**

Create `webhook-handler/tests/test_gateway_bot_client.py`:

```python
"""Fetching a user's bot config over the internal seam.

An unknown key must come back as None rather than raising, because an inbound
update on a deleted bot is normal and must not page anyone.
"""
import pytest

from clients.tasks import TasksAPIError, TasksClient


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


@pytest.fixture
def client(monkeypatch):
    c = TasksClient("http://tasks:8210", internal_secret="s")
    return c


async def test_a_known_key_returns_the_config(client, monkeypatch):
    async def _req(method, path, **kw):
        assert method == "GET"
        assert path == "/gateway/bots/abc123"
        return FakeResponse(200, {"owner_email": "ralph@example.com",
                                  "token": "111:AAH", "enabled": True})
    monkeypatch.setattr(client, "_internal_request", _req)
    config = await client.gateway_bot_config("abc123")
    assert config["owner_email"] == "ralph@example.com"


async def test_an_unknown_key_is_none_not_an_error(client, monkeypatch):
    async def _req(method, path, **kw):
        raise TasksAPIError(404, "unknown bot")
    monkeypatch.setattr(client, "_internal_request", _req)
    assert await client.gateway_bot_config("nope") is None


async def test_tasks_being_down_still_raises(client, monkeypatch):
    # The caller must be able to tell "no such bot" from "I could not ask",
    # because the second one has to become a 503 so Telegram redelivers.
    async def _req(method, path, **kw):
        raise TasksAPIError(503, "down")
    monkeypatch.setattr(client, "_internal_request", _req)
    with pytest.raises(TasksAPIError):
        await client.gateway_bot_config("abc123")


async def test_claiming_reports_whether_it_took(client, monkeypatch):
    async def _req(method, path, **kw):
        assert path == "/gateway/bots/abc123/claim"
        assert kw["json"] == {"platform_user_id": "999"}
        return FakeResponse(200, {"claimed": True})
    monkeypatch.setattr(client, "_internal_request", _req)
    assert await client.gateway_bot_claim("abc123", "999") is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd webhook-handler && python -m pytest tests/test_gateway_bot_client.py -q
```

Expected: FAIL with `AttributeError: 'TasksClient' object has no attribute 'gateway_bot_config'`.

- [ ] **Step 3: Write the implementation**

In `webhook-handler/clients/tasks.py`, after `gateway_recent_sessions`:

```python
    async def gateway_bot_config(self, bot_key: str) -> dict | None:
        """Everything needed to serve one inbound update on a user's own bot.

        Returns None when the key is unknown, which is normal: a removed bot
        can still have a webhook pointing here for a while. Any other failure
        raises, because the caller must be able to tell "no such bot" from "I
        could not ask", and only the second one may return a 503.

        The `token` in the response is plaintext. Do not log this dict.
        """
        try:
            resp = await self._internal_request("GET", f"/gateway/bots/{bot_key}")
        except TasksAPIError as exc:
            if exc.status == 404:
                return None
            raise
        return resp.json()

    async def gateway_bot_claim(self, bot_key: str, platform_user_id: str) -> bool:
        """First contact decides who an unclaimed bot serves."""
        resp = await self._internal_request(
            "POST", f"/gateway/bots/{bot_key}/claim",
            json={"platform_user_id": platform_user_id})
        return bool(resp.json().get("claimed"))
```

`TasksAPIError` is defined at `webhook-handler/clients/tasks.py:17` and stores the code as `.status`, where `0` means a network-level failure. A `0` must NOT be treated as a 404: it is exactly the case that has to raise so the route can answer 503.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd webhook-handler && python -m pytest tests/test_gateway_bot_client.py -q
```

Expected: PASS, 4 passed.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/clients/tasks.py webhook-handler/tests/test_gateway_bot_client.py
git commit -m "feat(gateway): ask tasks which user a bot belongs to"
```

---

### Task 7: The per-bot webhook route and adapter cache

**Files:**
- Modify: `webhook-handler/main.py` (add after the existing `telegram_webhook` route)
- Test: `webhook-handler/tests/test_gateway_bot_route.py`

**Interfaces:**
- Consumes: `gateway_bot_config`, `gateway_bot_claim` from Task 6; the existing `TelegramAdapter`, `gateway_pipeline.handle_event`, `_spawn_gateway`.
- Produces:
  - route `POST /webhook/telegram/{bot_key}`
  - `_bot_adapters: dict[str, tuple]` module-level cache
  - `async def _bot_adapter(bot_key: str) -> tuple | None` returning `(adapter, config)`
  - `def _forget_bot(bot_key: str) -> None`

- [ ] **Step 1: Write the failing test**

Create `webhook-handler/tests/test_gateway_bot_route.py`:

```python
"""Inbound updates on a user's own bot.

Every assertion here is about a failure mode that would be invisible in
production: a silently dropped message, a 200 on an update we never handled, or
a bot serving someone it should not.
"""
import pytest
from fastapi.testclient import TestClient

import main
from clients.tasks import TasksAPIError

# Mirror the TestClient construction in tests/test_gateway_telegram_route.py
# exactly. That file already solves how to exercise a route on main.app without
# running the whole application lifespan; do not invent a second way.

CONFIG = {
    "platform": "telegram",
    "owner_email": "ralph@example.com",
    "token": "111:AAHtoken",
    "webhook_secret": "s3cret",
    "allowed_ids": "",
    "owner_platform_user_id": "",
    "enabled": True,
}

UPDATE = {
    "update_id": 1,
    "message": {"message_id": 5, "text": "hello",
                "chat": {"id": 999, "type": "private"},
                "from": {"id": 999, "username": "ralph"}},
}


@pytest.fixture
def client(monkeypatch):
    main._bot_adapters.clear()
    main._gateway_seen_updates.clear()
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture
def spawned(monkeypatch):
    """Capture what would have been scheduled, and close it so pytest does not
    warn about a coroutine that was never awaited."""
    calls = []

    def _fake_spawn(coro):
        calls.append(coro)
        coro.close()
        return None

    monkeypatch.setattr(main, "_spawn_gateway", _fake_spawn)
    return calls


class FakeTasks:
    """Stands in for the module-level gateway_tasks client."""

    def __init__(self, config, claimed=True, error=None):
        self.config = config
        self.claimed = claimed
        self.error = error
        self.config_calls = []

    async def gateway_bot_config(self, bot_key):
        self.config_calls.append(bot_key)
        if self.error:
            raise self.error
        return self.config

    async def gateway_bot_claim(self, bot_key, platform_user_id):
        return self.claimed


@pytest.fixture
def tasks_says(monkeypatch):
    def _set(config, claimed=True, error=None):
        fake = FakeTasks(config, claimed=claimed, error=error)
        monkeypatch.setattr(main, "gateway_tasks", fake)
        return fake
    return _set


def test_an_unknown_bot_key_is_404(client, tasks_says, spawned):
    tasks_says(None)
    resp = client.post("/webhook/telegram/nosuchkey", json=UPDATE,
                       headers={"x-telegram-bot-api-secret-token": "s3cret"})
    assert resp.status_code == 404
    assert spawned == []


def test_tasks_being_down_is_503_so_telegram_redelivers(client, tasks_says, spawned):
    tasks_says(None, error=TasksAPIError(0, "connect failed"))
    resp = client.post("/webhook/telegram/abc", json=UPDATE,
                       headers={"x-telegram-bot-api-secret-token": "s3cret"})
    assert resp.status_code == 503


def test_a_wrong_secret_is_rejected(client, tasks_says, spawned):
    tasks_says(CONFIG)
    resp = client.post("/webhook/telegram/abc", json=UPDATE,
                       headers={"x-telegram-bot-api-secret-token": "wrong"})
    assert resp.status_code == 200
    assert spawned == []


def test_a_disabled_bot_is_accepted_and_ignored(client, tasks_says, spawned):
    tasks_says({**CONFIG, "enabled": False})
    resp = client.post("/webhook/telegram/abc", json=UPDATE,
                       headers={"x-telegram-bot-api-secret-token": "s3cret"})
    assert resp.status_code == 200
    assert spawned == []


def test_a_sender_outside_the_allow_list_is_ignored(client, tasks_says, spawned):
    tasks_says({**CONFIG, "allowed_ids": "111,222"})
    client.post("/webhook/telegram/abc", json=UPDATE,
                headers={"x-telegram-bot-api-secret-token": "s3cret"})
    assert spawned == []


def test_a_claimed_bot_ignores_everyone_else(client, tasks_says, spawned):
    tasks_says({**CONFIG, "owner_platform_user_id": "1000"})
    client.post("/webhook/telegram/abc", json=UPDATE,
                headers={"x-telegram-bot-api-secret-token": "s3cret"})
    assert spawned == []


def test_a_good_update_reaches_the_pipeline(client, tasks_says, spawned):
    tasks_says(CONFIG)
    resp = client.post("/webhook/telegram/abc", json=UPDATE,
                       headers={"x-telegram-bot-api-secret-token": "s3cret"})
    assert resp.status_code == 200
    assert len(spawned) == 1


def test_the_config_is_fetched_once_and_then_cached(client, tasks_says, spawned):
    fake = tasks_says(CONFIG)
    for update_id in (1, 2):
        client.post("/webhook/telegram/abc",
                    json={**UPDATE, "update_id": update_id},
                    headers={"x-telegram-bot-api-secret-token": "s3cret"})
    assert fake.config_calls == ["abc"]


def test_the_shared_route_is_untouched_by_all_of_this(client, tasks_says, spawned):
    # The keyless route must keep serving @aiuiteam_bot on the env-var path.
    # It is registered from TELEGRAM_BOT_TOKEN, which is unset in tests, so a
    # 503 here proves the route still exists and still answers from the
    # registry rather than from a user's bot config.
    tasks_says(CONFIG)
    resp = client.post("/webhook/telegram", json=UPDATE,
                       headers={"x-telegram-bot-api-secret-token": "s3cret"})
    assert resp.status_code == 503
    assert spawned == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd webhook-handler && python -m pytest tests/test_gateway_bot_route.py -q
```

Expected: FAIL with `AttributeError: module 'main' has no attribute '_bot_adapters'`.

- [ ] **Step 3: Write the implementation**

In `webhook-handler/main.py`, after the `_gateway_seen_updates` declaration around line 123:

```python
# A user's own bot, one adapter per bot_key, built on first contact.
# Bounded because a cold entry costs one internal call, not because it is a log.
# Nothing invalidates this on a change made in the browser: the cost of a stale
# entry is bounded by _BOT_CACHE_MAX evictions, and a removed bot 404s on
# lookup, which is what clears it.
_bot_adapters: dict[str, tuple] = {}
_BOT_CACHE_MAX = 200

#: The gateway's tasks client, set at startup. A module-level name because the
#: per-bot route needs it and reaching into gateway_pipeline._tasks would be
#: touching a private attribute of another module.
gateway_tasks = None
```

Then bind it where the pipeline is already configured, at `webhook-handler/main.py:223`. Replace:

```python
    gateway_pipeline.configure(TasksClient(
        settings.tasks_url,
        internal_secret=settings.internal_callback_secret,
    ))
```

with:

```python
    global gateway_tasks
    gateway_tasks = TasksClient(
        settings.tasks_url,
        internal_secret=settings.internal_callback_secret,
    )
    gateway_pipeline.configure(gateway_tasks)
```

If that block is not already inside a function, drop the `global` line and assign directly.

Then, after the existing `telegram_webhook` route:

```python
def _forget_bot(bot_key: str) -> None:
    _bot_adapters.pop(bot_key, None)


async def _bot_adapter(bot_key: str):
    """(adapter, config) for a user's own bot, or None if there is no such bot.

    Raises TasksAPIError when tasks cannot be reached, which the caller turns
    into a 503 so Telegram redelivers rather than losing the message."""
    cached = _bot_adapters.get(bot_key)
    if cached is not None:
        return cached

    if gateway_tasks is None:
        raise RuntimeError("gateway tasks client is not configured yet")

    config = await gateway_tasks.gateway_bot_config(bot_key)
    if config is None:
        return None

    adapter = TelegramAdapter(
        token=config["token"],
        webhook_secret=config["webhook_secret"],
    )
    adapter.name = "telegram"
    adapter.max_message_length = TELEGRAM_MAX_MESSAGE

    if len(_bot_adapters) >= _BOT_CACHE_MAX:
        _bot_adapters.clear()
    _bot_adapters[bot_key] = (adapter, config)
    return _bot_adapters[bot_key]


@app.post("/webhook/telegram/{bot_key}")
async def telegram_webhook_for_bot(bot_key: str, request: Request):
    """Inbound updates on a bot that belongs to one user.

    Same 200-before-the-work contract as the shared route, with two
    deliberate exceptions: an unknown key is a 404 so a stale webhook stops
    costing us a lookup, and tasks being unreachable is a 503 so Telegram
    redelivers instead of us silently eating the message.
    """
    try:
        entry = await _bot_adapter(bot_key)
    except Exception:  # noqa: BLE001
        logger.warning("gateway: could not load bot config, asking for a retry")
        return JSONResponse(content={"ok": False}, status_code=503)

    if entry is None:
        return JSONResponse(content={"ok": False}, status_code=404)

    adapter, config = entry

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(content={"ok": True}, status_code=200)

    headers = dict(request.headers)
    if not adapter.verify_webhook(payload, headers):
        logger.warning("gateway: rejected an update with a bad secret")
        return JSONResponse(content={"ok": True}, status_code=200)

    if not config.get("enabled"):
        # The user switched their bot off. deleteWebhook stops this at source;
        # anything already in flight lands here.
        return JSONResponse(content={"ok": True}, status_code=200)

    update_id = payload.get("update_id")
    if isinstance(update_id, int):
        seen_key = (bot_key, update_id)
        if seen_key in _gateway_seen_updates:
            return JSONResponse(content={"ok": True}, status_code=200)
        if len(_gateway_seen_updates) >= _GATEWAY_SEEN_MAX:
            _gateway_seen_updates.clear()
        _gateway_seen_updates.add(seen_key)

    try:
        event = adapter.parse_inbound(payload, headers)
    except Exception:  # noqa: BLE001
        logger.exception("gateway: parse failed on a user bot, dropping the update")
        return JSONResponse(content={"ok": True}, status_code=200)
    if event is None:
        return JSONResponse(content={"ok": True}, status_code=200)

    # MessageEvent carries the person on event.source.user_id, NOT on the event
    # itself: source.chat_id is the conversation and source.user_id is the
    # human. On a Telegram DM they happen to be the same number, which is
    # exactly why reading the wrong one would pass every test and be wrong in a
    # group.
    sender_id = str(event.source.user_id or "")
    if not _bot_sender_allowed(config, sender_id):
        logger.info("gateway: a user bot ignored a sender it does not serve")
        return JSONResponse(content={"ok": True}, status_code=200)

    if not config.get("owner_platform_user_id") and sender_id:
        try:
            if await gateway_tasks.gateway_bot_claim(bot_key, sender_id):
                config["owner_platform_user_id"] = sender_id
        except Exception:  # noqa: BLE001
            # A failed claim leaves the bot unclaimed and still serving. It is
            # a narrowing step, so failing open here loses nothing that was not
            # already open.
            logger.warning("gateway: could not record a bot claim")

    _spawn_gateway(gateway_pipeline.handle_event(event, adapter))
    return JSONResponse(content={"ok": True}, status_code=200)
```

Add the allow gate as a module-level function just above `_bot_adapter`:

```python
def _bot_sender_allowed(config: dict, sender_id: str) -> bool:
    """An explicit allow list wins. With none, the bot serves only the account
    that claimed it, and an unclaimed bot serves whoever arrives first so the
    owner can claim their own bot by messaging it."""
    allowed = [p for p in (config.get("allowed_ids") or "").split(",") if p]
    if allowed:
        return sender_id in allowed
    claimed = config.get("owner_platform_user_id") or ""
    if not claimed:
        return True
    return sender_id == str(claimed)
```

`MessageEvent` and `SessionSource` are defined in `webhook-handler/gateway/events.py`, not `base.py`. `user_id` lives on `event.source`, is typed `str | None`, and is already imported into `main.py` through the adapter.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd webhook-handler && python -m pytest tests/test_gateway_bot_route.py -q
```

Expected: PASS, 9 passed.

- [ ] **Step 5: Run the whole gateway suite to prove the shared bot still works**

```bash
cd webhook-handler && python -m pytest tests/ -q -k gateway
```

Expected: PASS, including the pre-existing `test_gateway_telegram_route.py`.

- [ ] **Step 6: Commit**

```bash
git add webhook-handler/main.py webhook-handler/tests/test_gateway_bot_route.py
git commit -m "feat(gateway): serve inbound updates on a user's own bot"
```

---

### Task 8: The dedupe collision fix

**Files:**
- Modify: `webhook-handler/main.py:122` and the shared `telegram_webhook` route
- Test: `webhook-handler/tests/test_gateway_dedupe_key.py`

**Interfaces:**
- Consumes: `_gateway_seen_updates` from Task 7.
- Produces: `SHARED_BOT_KEY = "shared"`; `_gateway_seen_updates` holds `tuple[str, int]`.

- [ ] **Step 1: Write the failing test**

Create `webhook-handler/tests/test_gateway_dedupe_key.py`:

```python
"""update_id is a per-bot counter, not a global one.

Before this fix two users' bots collided on the same integer and one person's
message vanished as a duplicate. Nothing would have surfaced that: the drop
path returns 200 and logs nothing.
"""
import main


def test_the_dedupe_key_is_scoped_to_a_bot():
    main._gateway_seen_updates.clear()
    main._gateway_seen_updates.add(("botA", 1))
    assert ("botB", 1) not in main._gateway_seen_updates


def test_the_shared_bot_has_a_key_of_its_own():
    assert main.SHARED_BOT_KEY
    assert isinstance(main.SHARED_BOT_KEY, str)


def test_the_same_update_on_the_same_bot_is_still_a_duplicate():
    main._gateway_seen_updates.clear()
    main._gateway_seen_updates.add(("botA", 7))
    assert ("botA", 7) in main._gateway_seen_updates
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd webhook-handler && python -m pytest tests/test_gateway_dedupe_key.py -q
```

Expected: FAIL with `AttributeError: module 'main' has no attribute 'SHARED_BOT_KEY'`.

- [ ] **Step 3: Write the implementation**

Replace the declaration at `webhook-handler/main.py:120-123`:

```python
# Telegram re-delivers an update until it sees a 200, and we answer before the
# work is done, so the same update_id can arrive several times. Bounded: this
# is a dedupe window, not a log.
#
# Keyed on (bot_key, update_id), NOT update_id alone. update_id is a per-bot
# counter, so once users bring their own bots a bare integer collides across
# them and silently swallows one person's message. The shared bot uses a fixed
# key so it shares the same window without colliding with anyone.
SHARED_BOT_KEY = "shared"
_gateway_seen_updates: set[tuple[str, int]] = set()
_GATEWAY_SEEN_MAX = 2000
```

In the existing `telegram_webhook` route, replace the dedupe block:

```python
    update_id = payload.get("update_id")
    if isinstance(update_id, int):
        seen_key = (SHARED_BOT_KEY, update_id)
        if seen_key in _gateway_seen_updates:
            return JSONResponse(content={"ok": True}, status_code=200)
        if len(_gateway_seen_updates) >= _GATEWAY_SEEN_MAX:
            _gateway_seen_updates.clear()
        _gateway_seen_updates.add(seen_key)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd webhook-handler && python -m pytest tests/test_gateway_dedupe_key.py tests/test_gateway_telegram_route.py -q
```

Expected: PASS. If `test_gateway_telegram_route.py` asserts on the old set contents, update those assertions to the tuple form.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/main.py webhook-handler/tests/test_gateway_dedupe_key.py
git commit -m "fix(gateway): scope update dedupe to a bot, since update_id is per bot"
```

---

### Task 9: The catalogue and the control shape on every row

**Files:**
- Modify: `mcp-servers/tasks/routes_gateway.py` (`CHANNEL_CATALOGUE` and `_channel_status`)
- Test: `mcp-servers/tasks/tests/test_gateway_catalogue.py`

**Interfaces:**
- Consumes: `BOT_CAPABLE_PLATFORMS` from Task 4.
- Produces: each connection dict gains `"can_bring_bot": bool` and `"bot": dict | None`.

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_gateway_catalogue.py`:

```python
"""Every channel row carries the same controls, and says why an inert one is
inert.

Matching Hermes' shape is the point: the same toggle, Test and Configure on
every row. Honesty is the constraint: a control that cannot work must be
visibly inert with a reason, never a button that silently does nothing.
"""
import os

os.environ.setdefault("AIUI_FERNET_KEY",
                      "hUZ3RkVvY0JmS3FnWlp4TXcyN0RkNTZWc1RCQzNKS1E=")

import routes_gateway as rg


def test_the_catalogue_matches_the_hermes_list():
    names = [c["platform"] for c in rg.CHANNEL_CATALOGUE]
    assert names == ["telegram", "cli", "slack", "discord", "mattermost",
                     "matrix", "whatsapp", "signal", "email", "teams"]


def test_every_channel_says_what_it_is():
    for entry in rg.CHANNEL_CATALOGUE:
        assert entry["blurb"].strip()
        assert entry["label"].strip()
        assert entry["icon"].strip()


def test_every_channel_that_is_not_ready_says_why():
    for entry in rg.CHANNEL_CATALOGUE:
        row = rg._channel_status(entry, {})
        if row["status"] in ("planned", "off"):
            assert row["note"].strip(), f"{row['platform']} is silent about why"


def test_only_telegram_can_take_your_own_bot_today():
    for entry in rg.CHANNEL_CATALOGUE:
        row = rg._channel_status(entry, {})
        assert row["can_bring_bot"] is (entry["platform"] == "telegram")


def test_a_row_carries_a_bot_slot_even_when_empty():
    # The page renders the same shape for every row, so the field must always
    # be present rather than appearing only when a bot exists.
    for entry in rg.CHANNEL_CATALOGUE:
        assert "bot" in rg._channel_status(entry, {})


def test_mattermost_and_matrix_are_honest_about_being_unbuilt():
    rows = {c["platform"]: rg._channel_status(c, {})
            for c in rg.CHANNEL_CATALOGUE}
    assert rows["mattermost"]["status"] == "planned"
    assert rows["matrix"]["status"] == "planned"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd mcp-servers/tasks && python -m pytest tests/test_gateway_catalogue.py -q
```

Expected: FAIL on the catalogue ordering test, because Mattermost and Matrix are missing.

- [ ] **Step 3: Write the implementation**

In `CHANNEL_CATALOGUE`, insert after the Discord entry:

```python
    {"platform": "mattermost", "label": "Mattermost", "icon": "💠",
     "blurb": "Use IO from Mattermost channels and direct messages.",
     "planned": "Not started. Needs a bot account and a webhook route."},
    {"platform": "matrix", "label": "Matrix", "icon": "🔷",
     "blurb": "Use IO from Matrix rooms and direct messages.",
     "planned": "Not started. Needs a homeserver login this box does not hold."},
```

In `_channel_status`, add `can_bring_bot` and `bot` to the base `row` dict:

```python
    row = {"platform": platform, "label": entry["label"], "icon": entry["icon"],
           "blurb": entry.get("blurb", ""), "name": "", "linked_at": None,
           "note": "",
           # The page draws the same three controls on every row. These two say
           # which of them can actually do anything here.
           "can_bring_bot": platform in BOT_CAPABLE_PLATFORMS,
           "bot": None}
```

Then update `list_connections` to attach each user's bot to its row:

```python
@page_router.get("/connections")
async def list_connections(
        user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    """Every channel, with this account's status for each."""
    async with session() as s:
        rows = (await s.execute(
            select(GatewayLink).where(GatewayLink.email == user.email)
            .order_by(GatewayLink.linked_at.desc())
        )).scalars().all()
        bots = (await s.execute(
            select(GatewayBot).where(GatewayBot.email == user.email)
        )).scalars().all()

    linked = {
        r.platform: {
            "name": r.platform_user_name or "",
            "linked_at": r.linked_at.isoformat() if r.linked_at else None,
        }
        for r in rows
    }
    by_platform = {b.platform: _bot_view(b) for b in bots}

    connections = []
    for entry in CHANNEL_CATALOGUE:
        row = _channel_status(entry, linked)
        row["bot"] = by_platform.get(row["platform"])
        connections.append(row)

    return {
        "telegram_bot": os.environ.get("GATEWAY_TELEGRAM_BOT", ""),
        "connections": connections,
    }
```

`BOT_CAPABLE_PLATFORMS` and `_bot_view` are defined later in the file than `_channel_status`. Move both above `CHANNEL_CATALOGUE` so they are bound at call time regardless of import order.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd mcp-servers/tasks && python -m pytest tests/test_gateway_catalogue.py -q
```

Expected: PASS, 6 passed.

- [ ] **Step 5: Run the existing channel-row test to prove it still holds**

```bash
cd mcp-servers/tasks && python -m pytest tests/ -q -k "gateway and not db"
```

Expected: PASS. The test added in `ca07f1524` covers the two new rows automatically.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/routes_gateway.py mcp-servers/tasks/tests/test_gateway_catalogue.py
git commit -m "feat(gateway): ten channels, and every row says whether it can take your bot"
```

---

### Task 10: The Channels page

**Files:**
- Modify: `mcp-servers/tasks/static/gateway-link.html`
- Test: `mcp-servers/tasks/tests/test_gateway_page_bot_copy.py`

**Interfaces:**
- Consumes: `GET /tasks/gateway/connections` (now carrying `can_bring_bot` and `bot`), and the four bot routes from Task 4.
- Produces: no Python interface. The page is the deliverable.

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_gateway_page_bot_copy.py`:

```python
"""The page has to be honest about what a token does before anyone pastes one.

Following the pattern in ca07f1524: assert on the copy, because this is the
only place a user is told that IO can now send as their bot.
"""
from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / "static" / "gateway-link.html"
HTML = PAGE.read_text(encoding="utf-8")


def test_the_page_offers_a_way_to_bring_your_own_bot():
    assert "Use my own bot" in HTML


def test_the_page_names_botfather_so_a_user_knows_where_to_get_a_token():
    assert "BotFather" in HTML


def test_the_page_says_the_bot_is_private_to_the_user():
    assert "Nobody else can" in HTML


def test_the_page_offers_all_three_hermes_controls():
    for control in ("Test", "Edit", "Remove bot"):
        assert control in HTML


def test_the_page_never_ships_a_hardcoded_token():
    # A pasted example token would be a live credential in a public file.
    assert "AAH" not in HTML


def test_the_quick_connect_path_is_still_offered():
    assert "Quick connect" in HTML
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd mcp-servers/tasks && python -m pytest tests/test_gateway_page_bot_copy.py -q
```

Expected: FAIL on `Use my own bot`.

- [ ] **Step 3: Add the bot section to the page**

In `mcp-servers/tasks/static/gateway-link.html`, inside the per-row rendering, after the existing pairing panel is built, add a bot section. Insert this function above the row loop:

```javascript
// A bot the user brought themselves. Rendered on every row so the page keeps
// one shape; inert with a reason on a channel that cannot honour it yet.
function botSection(c, refresh) {
  const box = document.createElement("div");
  box.className = "botbox";

  const head = document.createElement("div");
  head.className = "botheadline";
  head.textContent = "Use my own bot";
  box.appendChild(head);

  if (!c.can_bring_bot) {
    const why = document.createElement("p");
    why.className = "why";
    why.textContent = c.note || (c.label + " cannot take your own bot yet.");
    box.appendChild(why);
    return box;
  }

  if (c.bot) {
    const who = document.createElement("div");
    who.className = "who";
    who.textContent = c.bot.bot_username
      ? "Your bot @" + c.bot.bot_username
      : "Your bot is saved.";
    box.appendChild(who);

    if (c.bot.last_error) {
      const bad = document.createElement("p");
      bad.className = "why";
      bad.textContent = "Telegram said: " + c.bot.last_error;
      box.appendChild(bad);
    }

    const msg = document.createElement("p");
    msg.className = "msg";

    const row = document.createElement("div");
    row.className = "botactions";

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.textContent = c.bot.enabled ? "Turn off" : "Turn on";
    toggle.onclick = async () => {
      toggle.disabled = true;
      const res = await fetch("/tasks/gateway/bots/" + encodeURIComponent(c.bot.bot_key), {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({enabled: !c.bot.enabled}),
      });
      toggle.disabled = false;
      if (res.ok) refresh();
      else setMsg(msg, "That did not take. Try again.");
    };

    const test = document.createElement("button");
    test.type = "button";
    test.textContent = "Test";
    test.onclick = async () => {
      test.disabled = true;
      setMsg(msg, "Asking Telegram...");
      const res = await fetch("/tasks/gateway/bots/" + encodeURIComponent(c.bot.bot_key) + "/test",
                              {method: "POST"});
      const body = await res.json().catch(() => ({}));
      test.disabled = false;
      setMsg(msg, body.detail || "Could not reach the server.");
    };

    const edit = document.createElement("button");
    edit.type = "button";
    edit.textContent = "Edit";
    edit.onclick = () => { box.replaceChildren(head, botForm(c, refresh)); };

    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove bot";
    remove.onclick = async () => {
      remove.disabled = true;
      const res = await fetch("/tasks/gateway/bots/" + encodeURIComponent(c.bot.bot_key),
                              {method: "DELETE"});
      remove.disabled = false;
      if (res.ok) refresh();
      else setMsg(msg, "Could not remove it. Try again.");
    };

    row.append(toggle, test, edit, remove);
    box.append(row, msg);
    return box;
  }

  box.appendChild(botForm(c, refresh));
  return box;
}

function botForm(c, refresh) {
  const form = document.createElement("div");

  const pitch = document.createElement("p");
  pitch.className = "why";
  pitch.textContent =
    "Your bot, your token, your data. Nobody else can see it or configure it. " +
    "Saving it lets IO send messages as that bot.";
  form.appendChild(pitch);

  const tokenLabel = document.createElement("div");
  tokenLabel.className = "fieldlabel";
  tokenLabel.textContent = "BOT TOKEN";
  const token = document.createElement("input");
  token.type = "password";
  token.placeholder = "paste the token";
  const tokenHelp = document.createElement("p");
  tokenHelp.className = "why";
  tokenHelp.textContent = "Get one from BotFather on Telegram.";

  const idsLabel = document.createElement("div");
  idsLabel.className = "fieldlabel";
  idsLabel.textContent = "ALLOWED TELEGRAM USER IDS";
  const ids = document.createElement("input");
  ids.type = "text";
  ids.placeholder = "leave empty for just you";

  const msg = document.createElement("p");
  msg.className = "msg";

  const save = document.createElement("button");
  save.type = "button";
  save.className = "primary";
  save.textContent = "SAVE & ENABLE";
  save.onclick = async () => {
    const value = token.value.trim();
    if (!value) { setMsg(msg, "Paste your bot token first."); return; }
    save.disabled = true;
    setMsg(msg, "Checking it with Telegram...");
    const res = await fetch("/tasks/gateway/bots", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({platform: c.platform, token: value,
                            allowed_ids: ids.value}),
    });
    const body = await res.json().catch(() => ({}));
    save.disabled = false;
    token.value = "";
    if (!res.ok) { setMsg(msg, body.detail || "That did not work."); return; }
    refresh();
  };

  form.append(tokenLabel, token, tokenHelp, idsLabel, ids, save, msg);
  return form;
}
```

Then, in the row loop, label the existing pairing panel and append the bot section. Where the panel is currently appended, add before it:

```javascript
    const quick = document.createElement("div");
    quick.className = "botheadline";
    quick.textContent = "Quick connect";
    panel.prepend(quick);
```

and after the panel is appended to the row:

```javascript
    row.appendChild(botSection(c, load));
```

Rename the existing top-level loader to `load` if it is not already, so `refresh` has something to call.

Add styles next to the existing `button` rule:

```css
  .botbox { margin-top: 14px; padding-top: 12px; border-top: 1px solid #1e2b36; }
  .botheadline { font-weight: 600; letter-spacing: .04em; margin-bottom: 6px; }
  .fieldlabel { font-size: 11px; letter-spacing: .08em; margin-top: 10px; opacity: .8; }
  .botbox input { width: 100%; box-sizing: border-box; margin-top: 4px; }
  .botactions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd mcp-servers/tasks && python -m pytest tests/test_gateway_page_bot_copy.py -q
```

Expected: PASS, 6 passed.

- [ ] **Step 5: Run the whole non-DB gateway suite**

```bash
cd mcp-servers/tasks && python -m pytest tests/ -q -k "gateway and not db"
```

Expected: PASS, including the row-copy test from `ca07f1524`.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/static/gateway-link.html mcp-servers/tasks/tests/test_gateway_page_bot_copy.py
git commit -m "feat(gateway): bring your own bot from the Channels page"
```

---

### Task 11: Deploy and verify on prod

**Files:**
- Modify: `docker-compose.unified.yml` (add `GATEWAY_PUBLIC_URL` to the tasks service environment)

**Interfaces:**
- Consumes: everything above.
- Produces: a working feature on `https://ai-ui.coolestdomain.win`.

- [ ] **Step 1: Add the env var the tasks service now needs**

In `docker-compose.unified.yml`, under the `tasks` service `environment:` block, add:

```yaml
      # Where a user's own bot should deliver. Same value webhook-handler uses;
      # tasks needs it to build the setWebhook URL at save time.
      - GATEWAY_PUBLIC_URL=${GATEWAY_PUBLIC_URL}
```

Confirm `AIUI_FERNET_KEY` is already in that block. If it is not, add it the same way. Do not touch `.env` on the server.

- [ ] **Step 2: Run the full local suite**

```bash
cd mcp-servers/tasks && python -m pytest tests/ -q 2>&1 | tail -5
cd ../../webhook-handler && python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: tasks shows roughly 130 pre-existing `ERROR at setup` from `db_session` and no new failures. webhook-handler shows all passing.

- [ ] **Step 3: Commit, because the deploy script refuses a dirty tree**

```bash
git add docker-compose.unified.yml
git commit -m "chore(gateway): give tasks the public URL it needs to register a webhook"
```

- [ ] **Step 4: Deploy tasks**

```bash
ORCH_HOST=46.224.193.25 ./scripts/deploy_orchestrator.sh
```

If `rsync` is unavailable, fall back to one `scp` per changed file, then rebuild `tasks`, then update `.deploy-state` by hand as JSON.

- [ ] **Step 5: Deploy webhook-handler by hand**

The orchestrator does not watch it. One `scp` per changed file, never `scp -r`:

```bash
scp webhook-handler/main.py root@46.224.193.25:/root/proxy-server/webhook-handler/main.py
scp webhook-handler/clients/tasks.py root@46.224.193.25:/root/proxy-server/webhook-handler/clients/tasks.py
ssh root@46.224.193.25 "cd /root/proxy-server && sed -i 's/\r$//' webhook-handler/main.py webhook-handler/clients/tasks.py && docker compose -f docker-compose.unified.yml up -d --build webhook-handler"
```

- [ ] **Step 6: Confirm the migration ran and nothing regressed**

```bash
curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz
ssh root@46.224.193.25 "docker exec tasks sh -lc 'cd /app && python -m pytest tests/test_gateway_bot_routes_db.py -q'"
```

Expected: healthz returns OK, and the container-tier isolation tests pass against the real database.

- [ ] **Step 7: Verify with a real bot**

This is the step that catches wiring a unit test cannot, per the CLAUDE.md note that `_run_execution`-style wiring is only provable end to end.

1. Create a throwaway bot in BotFather and copy the token.
2. Open Channels, expand Telegram, paste the token, Save & Enable. The card must come back showing your bot's username.
3. Press Test. It should say the bot is alive and to send your code.
4. Message the bot on Telegram, send the pairing code from the page, then ask it something. It must answer.
5. Press Test again. It should now send you a real message.
6. Turn the bot off. Message it again. It must stay silent.
7. Turn it back on, confirm it answers, then Remove bot.
8. Confirm `@aiuiteam_bot` still answers throughout, and that the Discord bot still responds in its channel.

- [ ] **Step 8: Record the result**

```bash
git commit --allow-empty -m "chore(gateway): verified bring-your-own-bot end to end on prod"
```

---

## What this plan does not do

- Make Discord, Slack, Mattermost, Matrix, WhatsApp, Signal, Email or Teams configurable. Their rows show the controls in an inert state with a reason.
- Touch the existing Discord or Slack integrations in any way.
- Cache invalidation across the browser and webhook-handler. A bot edited in the browser can be served from a stale cache entry until it is evicted. The failure is bounded and self-correcting; a push-invalidate is a follow-up if it ever bites.
- **Outbound-initiated messages preferring a user's own bot.** The spec says that where IO starts the conversation, such as cron results, the user's own bot wins. Nothing in webhook-handler sends an unsolicited Telegram message today: every `adapter.send` in `gateway/pipeline.py` is a reply to an inbound event, which already goes back on the bot it arrived on. There is no code path to change, so this becomes real only when Telegram delivery is added to the scheduler.
