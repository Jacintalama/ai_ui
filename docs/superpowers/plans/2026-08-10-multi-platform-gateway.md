# Multi-Platform Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a person message the IO agent from Telegram (text or voice memo) or a terminal, get an answer built from their own Brain with their own tools and models, and continue the same conversation in the Open WebUI web app.

**Architecture:** A `gateway/` package inside the existing `webhook-handler` service normalizes inbound messages from any platform into one `MessageEvent`, resolves the sender to an IO account through the `tasks` service, and calls Open WebUI's own chat API **as that user** using a 60 second token that `tasks` mints. No new container. The gateway owns no model logic, no tools, no memory and no prompt, so anything added to Open WebUI later appears on every gateway platform with no gateway change.

**Tech Stack:** Python 3.11, FastAPI, httpx, asyncpg + SQLAlchemy (tasks only), pytest with `asyncio_mode = auto`, respx for HTTP mocking. No new third-party dependency in either service.

**Source spec:** `docs/superpowers/specs/2026-08-07-multi-platform-gateway-design.md`

## Global Constraints

- **No new dependency in either service.** `webhook-handler/requirements.txt` and `mcp-servers/tasks/requirements.txt` are unchanged by this plan. HS256 token minting is hand-rolled with `hmac`/`hashlib`/`base64`, matching the existing `mcp-servers/tasks/edit_capability.py`.
- **Migrations re-run on every startup.** `mcp-servers/tasks/db.py::_run_migrations` applies every `migrations/*.sql` in sorted order at each boot, so all DDL must be `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`.
- **Never use the `db_session` fixture for gateway tests.** It `TRUNCATE`s eight `tasks.*` tables. Its guard refuses on production, but the correct pattern here is a raw asyncpg connection that deletes only rows it created, matched by a unique id.
- **No em-dashes or en-dashes anywhere.** Every bot reply in this plan is copy a real person reads. Use a period, a comma, or "and"/"so".
- **No AI attribution in commits.** No `Co-Authored-By`, no "Generated with" line. Author is Ralph Benitez.
- **Never touch, overwrite, or commit `.env`.** The server's `.env` is the only copy of the production secrets. Env additions are appended by hand at deploy time (Task 16).
- **Dormant by default.** With `TELEGRAM_BOT_TOKEN` unset the platform never registers, the route returns 503, and deploying changes nothing visible. Same pattern as the Google sign-in wiring.
- **`WEBUI_SECRET_KEY` goes on the `tasks` service only.** It is the ability to act as any user. The gateway only ever holds a token already scoped to one person for 60 seconds. Tokens are never persisted and never logged.
- **Pairing codes and minted tokens are never written to logs**, at any level, including DEBUG.
- **Module-level seams for tests.** Network and subprocess boundaries are module-level names (`_tasks`, `_owui`, `_transcribe`) that tests monkeypatch. Follow `mcp-servers/tasks/tests/test_autofix_loop.py`.
- **Everything after "the model answered" fails loudly, not open.** The rest of this codebase fails open in post-processing because nobody is watching. Here somebody is waiting for a reply, so every failure produces a sentence.

## Routing facts this plan depends on (verified 2026-08-10)

These were checked against the live box, not inferred. They remove two open questions from the spec.

- **`/webhook/*` already reaches webhook-handler.** `/etc/caddy/Caddyfile` line 39 has `handle /webhook/* { reverse_proxy localhost:8086 }`. `https://ai-ui.coolestdomain.win/webhook/telegram` is live the moment the code deploys. **No Caddy change is needed and there is no deploy-ordering problem.** The spec's closing note about registering the webhook before first boot is obsolete; Task 16 fixes the spec text.
- **`/gateway/*` is already taken.** Caddy sends it to `localhost:8085`, the api-gateway. Never expose any part of this feature at a bare public `/gateway/...` path. The tasks endpoints are safe because they are only reachable in-network (`http://tasks:8210/gateway/...`) or under the `/tasks/` prefix.
- **`X-User-Email` is injected for `/tasks/*` too.** `api-gateway/main.py:423` builds `gateway_headers` once from the caller's Open WebUI session cookie and forwards them to every backend, including the `/tasks/*` branch at line 532. So `https://ai-ui.coolestdomain.win/tasks/gateway/link` arrives at the tasks service already carrying the signed-in user's email.
- **Voice transcription is not gated.** `chat.stt` defaults to `True` for non-admins (`config.py:1868`). `AUDIO_STT_ALLOWED_EXTENSIONS` defaults to a list containing `ogg`. `AUDIO_STT_SUPPORTED_CONTENT_TYPES` defaults to empty, and `utils/misc.py:1092` turns empty into `['audio/*', 'video/webm']`, so `audio/ogg` matches. **Telegram voice files must be saved with a `.ogg` extension, not Telegram's native `.oga`**, or the upload is rejected on extension before it reaches the model.
- **The default model is `auto_router.auto`.** The `auto_router` pipe function is active on prod and its `pipes()` returns `{"id": "auto", "name": "Auto (Free)"}`, giving the composite id `auto_router.auto` in the same shape as the existing `webhook_automation.webhook-automation`. It is free, so a runaway loop costs nothing.

## File structure

**tasks service** (`mcp-servers/tasks/`)

| File | Responsibility |
|---|---|
| `owui_token.py` (new) | Mint one short-lived Open WebUI session token for one user id. Nothing else. |
| `gateway_pairing.py` (new) | Pairing code alphabet, generation, hashing, comparison. Pure functions, no DB. |
| `migrations/033_gateway.sql` (new) | The three gateway tables. |
| `models.py` (modify) | `GatewayLink`, `GatewayPairingCode`, `GatewaySession`. |
| `routes_gateway.py` (new) | Two routers: internal (`X-Internal-Secret`) and user-facing (`X-User-Email`). |
| `static/gateway-link.html` (new) | The page where a signed-in user pastes a code. |
| `main.py` (modify) | Include both routers and the page route. |

**webhook-handler** (`webhook-handler/`)

| File | Responsibility |
|---|---|
| `gateway/events.py` (new) | `MessageType`, `SessionSource`, `MessageEvent`. Data only. |
| `gateway/base.py` (new) | `BasePlatformAdapter` and `chunk_text`. |
| `gateway/registry.py` (new) | `PlatformEntry`, `PlatformRegistry`. Dormant-by-default enablement. |
| `gateway/owui.py` (new) | `OWUIUserClient`: Open WebUI calls carrying a per-user token. |
| `gateway/pairing.py` (new) | The pairing reply copy. Policy, not transport. |
| `gateway/sessions.py` (new) | Get-or-create the Open WebUI chat, append a turn, list chats for `/resume`. |
| `gateway/pipeline.py` (new) | The one flow: `MessageEvent` in, reply sent. Holds the seams. |
| `gateway/platforms/telegram.py` (new) | Telegram parse, send, media download, webhook registration. |
| `gateway/platforms/cli.py` (new) | The CLI adapter. Parse a JSON body, return the reply inline. |
| `clients/tasks.py` (modify) | Four gateway HTTP methods. All tasks transport lives here already. |
| `config.py` (modify) | Telegram settings, gateway model, gateway public URL. |
| `main.py` (modify) | Two routes plus registry startup. |
| `scripts/io.py` (new) | The single-file CLI. |

`gateway/owui.py` and `gateway/pipeline.py` are additions to the spec's component list. The spec described the flow without naming a file for it, and the existing `clients/openwebui.py` is bound to the shared admin key, which is exactly the thing this design must not use.

---

### Task 1: Mint an Open WebUI token, and prove the premise

The whole design rests on one claim: a service holding `WEBUI_SECRET_KEY` can present a request to Open WebUI as any user. This task builds that and then checks it against the running server, before anything else is written. If the server check fails, stop and re-plan.

**Files:**
- Create: `mcp-servers/tasks/owui_token.py`
- Test: `mcp-servers/tasks/tests/test_owui_token.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `mint_owui_token(user_id: str, ttl_seconds: int = 60) -> str`, and the module constant `DEFAULT_TTL_SECONDS = 60`. Raises `RuntimeError` when `WEBUI_SECRET_KEY` is unset, `ValueError` on an empty `user_id`.

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_owui_token.py`:

```python
"""mint_owui_token must produce a token Open WebUI's own decoder accepts.

Open WebUI signs session JWTs HS256 over WEBUI_SECRET_KEY and its
is_valid_token is a revocation blocklist, so a fresh token with a random jti
passes. These tests pin the wire format; the real proof that Open WebUI
accepts it is the server check in step 6, which no unit test can replace.
"""
import base64
import hashlib
import hmac
import json

import pytest

import owui_token


def _decode(token: str) -> tuple[dict, dict, bytes, bytes]:
    header_b64, payload_b64, sig_b64 = token.split(".")

    def unb64(s: str) -> bytes:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

    signing_input = f"{header_b64}.{payload_b64}".encode()
    return (
        json.loads(unb64(header_b64)),
        json.loads(unb64(payload_b64)),
        unb64(sig_b64),
        signing_input,
    )


def test_mint_produces_three_part_hs256_token(monkeypatch):
    monkeypatch.setenv("WEBUI_SECRET_KEY", "test-secret")
    token = owui_token.mint_owui_token("user-abc")

    header, payload, sig, signing_input = _decode(token)
    assert header == {"alg": "HS256", "typ": "JWT"}
    assert payload["id"] == "user-abc"
    assert payload["exp"] - payload["iat"] == 60
    assert payload["jti"]

    expected = hmac.new(b"test-secret", signing_input, hashlib.sha256).digest()
    assert hmac.compare_digest(sig, expected)


def test_each_mint_has_a_distinct_jti(monkeypatch):
    monkeypatch.setenv("WEBUI_SECRET_KEY", "test-secret")
    a = _decode(owui_token.mint_owui_token("user-abc"))[1]
    b = _decode(owui_token.mint_owui_token("user-abc"))[1]
    assert a["jti"] != b["jti"]


def test_ttl_is_honoured(monkeypatch):
    monkeypatch.setenv("WEBUI_SECRET_KEY", "test-secret")
    payload = _decode(owui_token.mint_owui_token("user-abc", ttl_seconds=5))[1]
    assert payload["exp"] - payload["iat"] == 5


def test_fails_closed_without_a_secret(monkeypatch):
    monkeypatch.setenv("WEBUI_SECRET_KEY", "")
    with pytest.raises(RuntimeError):
        owui_token.mint_owui_token("user-abc")


def test_rejects_an_empty_user_id(monkeypatch):
    monkeypatch.setenv("WEBUI_SECRET_KEY", "test-secret")
    with pytest.raises(ValueError):
        owui_token.mint_owui_token("")
```

- [ ] **Step 2: Run the test to verify it fails**

Run from `mcp-servers/tasks/`:

```bash
python -m pytest tests/test_owui_token.py -q
```

Expected: collection error, `ModuleNotFoundError: No module named 'owui_token'`.

- [ ] **Step 3: Write the implementation**

Create `mcp-servers/tasks/owui_token.py`:

```python
"""Mint a short-lived Open WebUI session token for one user.

Open WebUI signs its session JWTs HS256 over WEBUI_SECRET_KEY
(open_webui/utils/auth.py: SESSION_SECRET = WEBUI_SECRET_KEY, ALGORITHM =
'HS256'), get_current_user resolves the caller from the token's `id` claim,
and is_valid_token is a revocation BLOCKLIST rather than an allowlist, so a
freshly minted token with a random jti is accepted. This module can therefore
present a request to Open WebUI as ANY user.

That is why it lives here and only here. WEBUI_SECRET_KEY is set on the tasks
service alone; callers get back a token already scoped to one user with a 60
second life. Never persist a minted token and never log one.

Hand-rolled rather than added as a PyJWT dependency: the output is a plain
HS256 JWS and the same primitives already appear in edit_capability.py.
"""
import base64
import hashlib
import hmac
import json
import os
import time
import uuid

ALGORITHM = "HS256"
DEFAULT_TTL_SECONDS = 60


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _json_segment(obj: dict) -> str:
    return _b64(json.dumps(obj, separators=(",", ":"), sort_keys=True).encode())


def mint_owui_token(user_id: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> str:
    """Return an Open WebUI session token that resolves as `user_id`.

    Fails closed: a missing secret raises rather than returning something that
    would be silently rejected downstream and read as a model outage.
    """
    secret = os.environ.get("WEBUI_SECRET_KEY", "").encode()
    if not secret:
        raise RuntimeError("WEBUI_SECRET_KEY not set")
    if not user_id:
        raise ValueError("user_id required")

    now = int(time.time())
    signing_input = (
        _json_segment({"alg": ALGORITHM, "typ": "JWT"})
        + "."
        + _json_segment({
            "id": user_id,
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + ttl_seconds,
        })
    )
    sig = hmac.new(secret, signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(sig)}"
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
python -m pytest tests/test_owui_token.py -q
```

Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/owui_token.py mcp-servers/tasks/tests/test_owui_token.py
git commit -m "feat(gateway): mint short-lived Open WebUI tokens scoped to one user"
```

- [ ] **Step 6: Prove Open WebUI accepts the token, on the server**

This is the acceptance check the spec says runs on day one. It needs no `.env` change and no deploy: the secret is read out of the running open-webui container's own environment and the token is minted in a throwaway interpreter.

Pick a **non-admin** user id first:

```bash
ssh root@46.224.193.25 "docker exec -e PGPASSWORD=\$POSTGRES_PASSWORD postgres sh -lc 'psql -U \$POSTGRES_USER -d openwebui -t -c \"SELECT id, email, role FROM public.\\\"user\\\" WHERE role <> '\''admin'\'' LIMIT 3;\"'"
```

Then mint against that id and call Open WebUI with it:

```bash
ssh root@46.224.193.25 'UID_TO_TEST=<paste-a-non-admin-id>; \
SECRET=$(docker exec open-webui printenv WEBUI_SECRET_KEY); \
TOKEN=$(docker exec -e S="$SECRET" -e U="$UID_TO_TEST" open-webui python -c "
import base64,hashlib,hmac,json,os,time,uuid
b=lambda r: base64.urlsafe_b64encode(r).decode().rstrip(chr(61))
seg=lambda o: b(json.dumps(o,separators=(chr(44),chr(58)),sort_keys=True).encode())
n=int(time.time())
si=seg({chr(97)+chr(108)+chr(103):chr(72)+chr(83)+chr(50)+chr(53)+chr(54),chr(116)+chr(121)+chr(112):chr(74)+chr(87)+chr(84)})+chr(46)+seg({chr(105)+chr(100):os.environ[chr(85)],chr(106)+chr(116)+chr(105):str(uuid.uuid4()),chr(105)+chr(97)+chr(116):n,chr(101)+chr(120)+chr(112):n+60})
print(si+chr(46)+b(hmac.new(os.environ[chr(83)].encode(),si.encode(),hashlib.sha256).digest()))
"); \
docker exec open-webui curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/auths/; \
docker exec open-webui curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/auths/'
```

Expected: `200`, then a JSON body whose `email` is **the non-admin user you picked**, not an admin address.

If the email comes back as an admin, or the status is 401, **stop and report**. The design's central hop does not work and the remaining tasks are built on it. Do not proceed on the assumption that it will be fixed later.

The `chr(...)` spelling in that snippet exists only because the command travels through PowerShell, ssh and `sh -lc`, each of which eats a different set of quotes. Nothing in the repo is written that way.

---

### Task 2: Pairing code primitives

**Files:**
- Create: `mcp-servers/tasks/gateway_pairing.py`
- Test: `mcp-servers/tasks/tests/test_gateway_pairing.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `CODE_ALPHABET`, `CODE_LENGTH = 8`, `CODE_TTL_SECONDS = 3600`, `RESEND_COOLDOWN_SECONDS = 600`, `MAX_REDEEM_ATTEMPTS = 5`, `generate_code() -> str`, `normalize_code(raw: str) -> str`, `hash_code(code: str) -> str`, `codes_match(code: str, code_hash: str) -> bool`.

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_gateway_pairing.py`:

```python
"""Pairing code primitives.

Codes are hashed at rest so a database leak grants nothing, and the alphabet
excludes 0/O/1/I because these get read off a phone screen and typed into a
browser by hand.
"""
import gateway_pairing as gp


def test_code_shape():
    code = gp.generate_code()
    assert len(code) == gp.CODE_LENGTH == 8
    assert set(code) <= set(gp.CODE_ALPHABET)


def test_alphabet_excludes_confusable_characters():
    for ch in "01OI":
        assert ch not in gp.CODE_ALPHABET


def test_codes_are_not_repeated_across_many_draws():
    codes = {gp.generate_code() for _ in range(500)}
    assert len(codes) > 490          # 32**8 space; collisions here mean a bad RNG


def test_hash_is_not_the_code():
    code = gp.generate_code()
    digest = gp.hash_code(code)
    assert code not in digest
    assert len(digest) == 64


def test_matching_is_case_and_whitespace_insensitive():
    code = gp.generate_code()
    digest = gp.hash_code(code)
    assert gp.codes_match(code.lower(), digest)
    assert gp.codes_match(f"  {code[:4]} {code[4:]}  ", digest)


def test_a_wrong_code_does_not_match():
    digest = gp.hash_code("ABCD2345")
    assert not gp.codes_match("ABCD2346", digest)


def test_matching_against_an_empty_hash_is_false():
    assert not gp.codes_match("ABCD2345", "")


def test_normalize_strips_junk_but_keeps_order():
    assert gp.normalize_code(" ab-cd 2345 ") == "ABCD2345"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_gateway_pairing.py -q
```

Expected: `ModuleNotFoundError: No module named 'gateway_pairing'`.

- [ ] **Step 3: Write the implementation**

Create `mcp-servers/tasks/gateway_pairing.py`:

```python
"""Pairing code primitives for the multi-platform gateway.

Hardening lifted from NousResearch/hermes-agent's pairing.py, which had already
done the reading: hash at rest, a confusable-free alphabet, short expiry, single
use, a resend cooldown and a redemption lockout.

Pure functions only. The rows live in routes_gateway.py so this module stays
testable without a database.
"""
import hashlib
import hmac
import secrets

# 32 characters, no 0/O/1/I. A code is read off a phone and typed into a browser.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
CODE_TTL_SECONDS = 3600
RESEND_COOLDOWN_SECONDS = 600
MAX_REDEEM_ATTEMPTS = 5

# Domain separator, so a gateway code hash can never be confused with any other
# sha256 digest this codebase stores.
_DOMAIN = "gateway_pair:"


def generate_code() -> str:
    """A fresh code. `secrets`, not `random`: this is an auth credential."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(raw: str) -> str:
    """Upper-case and drop anything outside the alphabet.

    People paste codes with spaces, dashes and the wrong case. Rejecting those
    would read as "the code is wrong" when the code is fine.
    """
    return "".join(ch for ch in (raw or "").upper() if ch in CODE_ALPHABET)


def hash_code(code: str) -> str:
    return hashlib.sha256((_DOMAIN + normalize_code(code)).encode()).hexdigest()


def codes_match(code: str, code_hash: str) -> bool:
    """Constant-time compare, so timing does not leak a prefix."""
    return hmac.compare_digest(hash_code(code), code_hash or "")
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
python -m pytest tests/test_gateway_pairing.py -q
```

Expected: `8 passed`.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/gateway_pairing.py mcp-servers/tasks/tests/test_gateway_pairing.py
git commit -m "feat(gateway): pairing code generation, hashing and comparison"
```

---

### Task 3: Gateway schema and models

**Files:**
- Create: `mcp-servers/tasks/migrations/033_gateway.sql`
- Modify: `mcp-servers/tasks/models.py` (append three classes at the end)
- Test: `mcp-servers/tasks/tests/test_gateway_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces: tables `tasks.gateway_links`, `tasks.gateway_pairing_codes`, `tasks.gateway_sessions`, and the SQLAlchemy models `GatewayLink`, `GatewayPairingCode`, `GatewaySession` importable from `models`.

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_gateway_models.py`:

```python
"""The gateway models must match the migration, and the migration must be
re-runnable: db.py applies every migrations/*.sql on every single startup.
"""
import pathlib
import re

from models import GatewayLink, GatewayPairingCode, GatewaySession

MIGRATION = (
    pathlib.Path(__file__).parent.parent / "migrations" / "033_gateway.sql"
).read_text(encoding="utf-8")


def _sql_columns(table: str) -> set[str]:
    """Column names declared inside one CREATE TABLE block of the migration.

    Parsed rather than hand-listed. Two hand-maintained lists agreeing with each
    other proves nothing about the SQL that actually builds the table.
    """
    block = re.search(
        rf"CREATE TABLE IF NOT EXISTS tasks\.{table}\s*\((.*?)\n\);",
        MIGRATION, re.IGNORECASE | re.DOTALL)
    assert block, f"no CREATE TABLE block found for tasks.{table}"

    # Table-level constraints start with a keyword rather than a column name.
    keywords = {"primary", "unique", "foreign", "constraint", "check", "exclude"}
    names = set()
    for line in block.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("--"):
            continue
        first = line.split()[0]
        if first.lower() in keywords:
            continue
        names.add(first)
    return names


def test_every_create_is_idempotent():
    creates = re.findall(r"CREATE\s+(TABLE|INDEX|UNIQUE INDEX)\s+(?!IF NOT EXISTS)",
                         MIGRATION, re.IGNORECASE)
    assert creates == [], f"non-idempotent DDL would fail on the second boot: {creates}"


def test_all_three_tables_are_created():
    for table in ("gateway_links", "gateway_pairing_codes", "gateway_sessions"):
        assert f"tasks.{table}" in MIGRATION


def test_models_point_at_the_tasks_schema():
    for model in (GatewayLink, GatewayPairingCode, GatewaySession):
        assert model.__table_args__["schema"] == "tasks"


def test_model_columns_match_the_migration():
    # Parsed from the SQL, not hand-listed, so a column renamed in one place and
    # not the other fails here instead of at runtime against a real database.
    for model, table in ((GatewayLink, "gateway_links"),
                         (GatewayPairingCode, "gateway_pairing_codes"),
                         (GatewaySession, "gateway_sessions")):
        assert {c.name for c in model.__table__.columns} == _sql_columns(table)


def test_the_column_parser_actually_finds_columns():
    # Guards the test above: a parser that silently returned an empty set would
    # make it pass for any model at all.
    assert _sql_columns("gateway_links") == {
        "id", "platform", "platform_user_id", "owui_user_id", "email", "linked_at"}
    assert len(_sql_columns("gateway_pairing_codes")) == 9
    assert len(_sql_columns("gateway_sessions")) == 6


def test_one_link_per_platform_user():
    # Two rows for the same Telegram account would make identity ambiguous and
    # the winner would depend on row order.
    assert "gateway_links_platform_user" in MIGRATION
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_gateway_models.py -q
```

Expected: `FileNotFoundError` for `033_gateway.sql`, or `ImportError: cannot import name 'GatewayLink'`.

- [ ] **Step 3: Write the migration**

Create `mcp-servers/tasks/migrations/033_gateway.sql`:

```sql
-- 033: multi-platform gateway. Three tables:
--   gateway_links          a platform account paired to an IO account
--   gateway_pairing_codes  short-lived codes that create those links
--   gateway_sessions       a platform conversation -> a real Open WebUI chat
--
-- webhook-handler has no database driver, so it reaches all three over HTTP
-- through routes_gateway.py. Nothing else reads them.
--
-- Idempotent: db.py re-runs every migration on every startup.

CREATE TABLE IF NOT EXISTS tasks.gateway_links (
    id                BIGSERIAL PRIMARY KEY,
    platform          TEXT        NOT NULL,
    platform_user_id  TEXT        NOT NULL,
    owui_user_id      TEXT        NOT NULL,
    email             TEXT        NOT NULL,
    linked_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One IO account per platform account. Without this, identity is ambiguous and
-- which one wins depends on row order.
CREATE UNIQUE INDEX IF NOT EXISTS gateway_links_platform_user
    ON tasks.gateway_links (platform, platform_user_id);

CREATE TABLE IF NOT EXISTS tasks.gateway_pairing_codes (
    id                 BIGSERIAL PRIMARY KEY,
    -- sha256 of the code, never the code. A dump of this table grants nothing.
    code_hash          TEXT        NOT NULL,
    platform           TEXT        NOT NULL,
    platform_user_id   TEXT        NOT NULL,
    platform_user_name TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at         TIMESTAMPTZ NOT NULL,
    redeemed_at        TIMESTAMPTZ,
    attempts           INT         NOT NULL DEFAULT 0
);

-- Both hot paths: "does this platform user already have a live code" on every
-- unpaired message, and "find the row for this code" on redeem.
CREATE INDEX IF NOT EXISTS gateway_pairing_codes_platform_user
    ON tasks.gateway_pairing_codes (platform, platform_user_id);
CREATE INDEX IF NOT EXISTS gateway_pairing_codes_hash
    ON tasks.gateway_pairing_codes (code_hash);

CREATE TABLE IF NOT EXISTS tasks.gateway_sessions (
    id            BIGSERIAL PRIMARY KEY,
    platform      TEXT        NOT NULL,
    chat_id       TEXT        NOT NULL,
    -- The Open WebUI chat is the ONLY transcript. The gateway keeps no copy,
    -- so there is nothing that can drift out of sync with the user's sidebar.
    owui_chat_id  TEXT        NOT NULL,
    owui_user_id  TEXT        NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS gateway_sessions_platform_chat
    ON tasks.gateway_sessions (platform, chat_id);

-- /resume lists a user's recent gateway chats, newest first.
CREATE INDEX IF NOT EXISTS gateway_sessions_user_updated
    ON tasks.gateway_sessions (owui_user_id, updated_at DESC);
```

- [ ] **Step 4: Add the models**

Append to `mcp-servers/tasks/models.py`:

```python
class GatewayLink(Base):
    """A platform account (Telegram, CLI) paired to an IO account.

    `owui_user_id` is the Open WebUI user id, which is what a minted token
    carries; `email` is stored alongside it for logging and for the tasks
    endpoints that key on email like every other route here."""
    __tablename__ = "gateway_links"
    __table_args__ = {"schema": "tasks"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    platform = Column(Text, nullable=False)
    platform_user_id = Column(Text, nullable=False)
    owui_user_id = Column(Text, nullable=False)
    email = Column(Text, nullable=False)
    linked_at = Column(DateTime(timezone=True), server_default=func.now())


class GatewayPairingCode(Base):
    """A short-lived, single-use code that turns into a GatewayLink.

    `code_hash` is a sha256, never the code itself."""
    __tablename__ = "gateway_pairing_codes"
    __table_args__ = {"schema": "tasks"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code_hash = Column(Text, nullable=False)
    platform = Column(Text, nullable=False)
    platform_user_id = Column(Text, nullable=False)
    platform_user_name = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    redeemed_at = Column(DateTime(timezone=True), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)


class GatewaySession(Base):
    """One platform conversation mapped to one real Open WebUI chat.

    Because the target is a real chat, the conversation shows up in the user's
    sidebar, is searchable, and feeds the Brain, with no sync mechanism of our
    own to maintain."""
    __tablename__ = "gateway_sessions"
    __table_args__ = {"schema": "tasks"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    platform = Column(Text, nullable=False)
    chat_id = Column(Text, nullable=False)
    owui_chat_id = Column(Text, nullable=False)
    owui_user_id = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())
```

Check the import line at the top of `models.py` before running: it must already bring in `BigInteger`, `Integer`, `Text`, `DateTime` and `func` from `sqlalchemy`. Add only the names that are missing, to the existing import.

- [ ] **Step 5: Run the test to verify it passes**

```bash
python -m pytest tests/test_gateway_models.py -q
```

Expected: `6 passed`.

- [ ] **Step 6: Confirm nothing else broke**

```bash
python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: the same pre-existing failure count as before this task. Roughly 130 `ERROR at setup` from `db_session` with no local Postgres is normal and is not your change.

- [ ] **Step 7: Commit**

```bash
git add mcp-servers/tasks/migrations/033_gateway.sql mcp-servers/tasks/models.py mcp-servers/tasks/tests/test_gateway_models.py
git commit -m "feat(gateway): add gateway_links, pairing_codes and sessions tables"
```

---

### Task 4: Internal gateway endpoints in tasks

The endpoints webhook-handler calls. Authenticated with `X-Internal-Secret`, the same header the schedule-result callback and `/discord-links/*` already use. Mounted bare, so they are reachable only inside the docker network.

**Files:**
- Create: `mcp-servers/tasks/routes_gateway.py`
- Modify: `mcp-servers/tasks/main.py` (one import, one include)
- Test: `mcp-servers/tasks/tests/test_gateway_routes_auth.py` (runs anywhere)
- Test: `mcp-servers/tasks/tests/test_gateway_routes_db.py` (container tier)

**Interfaces:**
- Consumes: `owui_token.mint_owui_token` (Task 1), `gateway_pairing` (Task 2), `models.GatewayLink|GatewayPairingCode|GatewaySession` (Task 3).
- Produces: `router` (an `APIRouter(prefix="/gateway")`) with `POST /resolve`, `GET /session`, `PUT /session`, `GET /sessions/recent`. Response shapes are pinned in the code below and Task 8 consumes them verbatim.

- [ ] **Step 1: Write the failing auth test**

Create `mcp-servers/tasks/tests/test_gateway_routes_auth.py`:

```python
"""Every internal gateway endpoint must fail closed without the secret.

These endpoints mint tokens that act as any user, so an unset or mismatched
INTERNAL_CALLBACK_SECRET must be a 403, never an open door.
"""
import os

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

os.environ.setdefault("INTERNAL_CALLBACK_SECRET", "test-internal-secret")

import routes_gateway


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes_gateway.router)
    return TestClient(app, raise_server_exceptions=False)


CALLS = [
    ("post", "/gateway/resolve", {"platform": "telegram", "platform_user_id": "1"}),
    ("get", "/gateway/session?platform=telegram&chat_id=1", None),
    ("put", "/gateway/session", {"platform": "telegram", "chat_id": "1",
                                 "owui_chat_id": "c", "owui_user_id": "u"}),
    ("get", "/gateway/sessions/recent?owui_user_id=u", None),
]


@pytest.mark.parametrize("method,path,body", CALLS)
def test_missing_secret_is_403(client, method, path, body):
    resp = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)
    assert resp.status_code == 403


@pytest.mark.parametrize("method,path,body", CALLS)
def test_wrong_secret_is_403(client, method, path, body):
    headers = {"X-Internal-Secret": "not-the-secret"}
    resp = (getattr(client, method)(path, json=body, headers=headers) if body
            else getattr(client, method)(path, headers=headers))
    assert resp.status_code == 403


def test_an_unset_server_secret_still_refuses(client, monkeypatch):
    # An empty expected secret must not mean "everything matches".
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", "")
    resp = client.post("/gateway/resolve", json={"platform": "telegram",
                                                 "platform_user_id": "1"},
                       headers={"X-Internal-Secret": ""})
    assert resp.status_code == 403


def test_resolve_refuses_a_blank_platform_user(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", "test-internal-secret")
    resp = client.post("/gateway/resolve", json={"platform": "telegram",
                                                 "platform_user_id": ""},
                       headers={"X-Internal-Secret": "test-internal-secret"})
    assert resp.status_code == 422
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/test_gateway_routes_auth.py -q
```

Expected: `ModuleNotFoundError: No module named 'routes_gateway'`.

- [ ] **Step 3: Write the router**

Create `mcp-servers/tasks/routes_gateway.py`:

```python
"""Multi-platform gateway state, and the user-token mint.

webhook-handler has no database driver and no DATABASE_URL, so every piece of
gateway state is reached through this module over HTTP.

Two routers, deliberately separate:

  router       prefix /gateway       X-Internal-Secret. Mounted BARE only, so
                                     it is reachable at http://tasks:8210 from
                                     inside the docker network and from nowhere
                                     else. Do not mount it under /tasks.
  page_router  prefix /tasks/gateway X-User-Email, injected by api-gateway from
                                     the browser's Open WebUI session cookie.

Never log a pairing code and never log a minted token.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update

import gateway_pairing as gp
from db import session
from models import GatewayLink, GatewayPairingCode, GatewaySession
from owui_token import mint_owui_token

log = logging.getLogger(__name__)

router = APIRouter(prefix="/gateway")

# Sessions idle longer than this are pruned on write. The Open WebUI chat they
# point at is never deleted: it is the user's data and lives in their sidebar.
SESSION_RETENTION_DAYS = 30


def _require_internal(secret: str) -> None:
    expected = os.environ.get("INTERNAL_CALLBACK_SECRET", "")
    if not expected or secret != expected:
        raise HTTPException(status_code=403, detail="invalid internal secret")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ResolveIn(BaseModel):
    platform: str = Field(min_length=1)
    platform_user_id: str = Field(min_length=1)
    platform_user_name: str = ""


class SessionIn(BaseModel):
    platform: str = Field(min_length=1)
    chat_id: str = Field(min_length=1)
    owui_chat_id: str = Field(min_length=1)
    owui_user_id: str = Field(min_length=1)


@router.post("/resolve")
async def resolve(body: ResolveIn,
                  x_internal_secret: str = Header(default="")) -> dict[str, Any]:
    """Who is this platform user, and if we do not know, how do they tell us?

    Linked   -> {linked: true, email, owui_user_id, owui_token}
    Unlinked -> {linked: false, code, expires_at}

    A repeat call while a code is still live returns THAT SAME CODE rather than
    issuing another. Otherwise someone who messages twice gets two codes, only
    one works, and the resend cooldown reads as an error to a person who did
    nothing wrong.
    """
    _require_internal(x_internal_secret)
    async with session() as s:
        link = (await s.execute(
            select(GatewayLink).where(
                GatewayLink.platform == body.platform,
                GatewayLink.platform_user_id == body.platform_user_id,
            )
        )).scalar_one_or_none()

        if link:
            return {
                "linked": True,
                "email": link.email,
                "owui_user_id": link.owui_user_id,
                "owui_token": mint_owui_token(link.owui_user_id),
            }

        now = _now()
        live = (await s.execute(
            select(GatewayPairingCode).where(
                GatewayPairingCode.platform == body.platform,
                GatewayPairingCode.platform_user_id == body.platform_user_id,
                GatewayPairingCode.redeemed_at.is_(None),
                GatewayPairingCode.expires_at > now,
                GatewayPairingCode.attempts < gp.MAX_REDEEM_ATTEMPTS,
            ).order_by(GatewayPairingCode.created_at.desc()).limit(1)
        )).scalar_one_or_none()
        if live:
            # The code itself is not recoverable from the hash, so a resend has
            # to re-mint. Reuse the ROW and overwrite its hash, which keeps the
            # one-live-code-per-user property intact.
            code = gp.generate_code()
            live.code_hash = gp.hash_code(code)
            live.expires_at = now + timedelta(seconds=gp.CODE_TTL_SECONDS)
            live.platform_user_name = body.platform_user_name or live.platform_user_name
            expires_at = live.expires_at
            await s.commit()
            return {"linked": False, "code": code,
                    "expires_at": expires_at.isoformat()}

        code = gp.generate_code()
        row = GatewayPairingCode(
            code_hash=gp.hash_code(code),
            platform=body.platform,
            platform_user_id=body.platform_user_id,
            platform_user_name=body.platform_user_name or None,
            expires_at=now + timedelta(seconds=gp.CODE_TTL_SECONDS),
        )
        s.add(row)
        await s.commit()
        log.info("gateway: issued a pairing code for %s user %s",
                 body.platform, body.platform_user_id)   # never the code
        return {"linked": False, "code": code,
                "expires_at": row.expires_at.isoformat()}


@router.get("/session")
async def get_session(platform: str, chat_id: str,
                      x_internal_secret: str = Header(default="")) -> dict[str, Any]:
    _require_internal(x_internal_secret)
    async with session() as s:
        row = (await s.execute(
            select(GatewaySession).where(
                GatewaySession.platform == platform,
                GatewaySession.chat_id == chat_id,
            )
        )).scalar_one_or_none()
    if not row:
        return {"owui_chat_id": None}
    return {"owui_chat_id": row.owui_chat_id, "owui_user_id": row.owui_user_id}


@router.put("/session")
async def put_session(body: SessionIn,
                      x_internal_secret: str = Header(default="")) -> dict[str, str]:
    """Upsert the conversation -> Open WebUI chat mapping, and prune old rows."""
    _require_internal(x_internal_secret)
    now = _now()
    async with session() as s:
        row = (await s.execute(
            select(GatewaySession).where(
                GatewaySession.platform == body.platform,
                GatewaySession.chat_id == body.chat_id,
            )
        )).scalar_one_or_none()
        if row:
            row.owui_chat_id = body.owui_chat_id
            row.owui_user_id = body.owui_user_id
            row.updated_at = now
        else:
            s.add(GatewaySession(
                platform=body.platform,
                chat_id=body.chat_id,
                owui_chat_id=body.owui_chat_id,
                owui_user_id=body.owui_user_id,
                updated_at=now,
            ))
        await s.execute(delete(GatewaySession).where(
            GatewaySession.updated_at < now - timedelta(days=SESSION_RETENTION_DAYS)
        ))
        await s.commit()
    return {"status": "ok"}


@router.get("/sessions/recent")
async def recent_sessions(owui_user_id: str, limit: int = 10,
                          x_internal_secret: str = Header(default="")) -> dict[str, Any]:
    """Backs /resume. Newest first, capped."""
    _require_internal(x_internal_secret)
    limit = max(1, min(limit, 25))
    async with session() as s:
        rows = (await s.execute(
            select(GatewaySession)
            .where(GatewaySession.owui_user_id == owui_user_id)
            .order_by(GatewaySession.updated_at.desc())
            .limit(limit)
        )).scalars().all()
    return {"sessions": [
        {"platform": r.platform, "chat_id": r.chat_id,
         "owui_chat_id": r.owui_chat_id,
         "updated_at": r.updated_at.isoformat() if r.updated_at else None}
        for r in rows
    ]}
```

- [ ] **Step 4: Run the auth test to verify it passes**

```bash
python -m pytest tests/test_gateway_routes_auth.py -q
```

Expected: `10 passed`.

- [ ] **Step 5: Wire the router into the app**

In `mcp-servers/tasks/main.py`, add to the block of `from routes_* import router as *_router` lines (keep them alphabetical, so after `from routes_fusion_page import ...`):

```python
from routes_gateway import router as gateway_router
```

And beside the other `app.include_router(...)` calls:

```python
app.include_router(gateway_router)  # /gateway, internal only (X-Internal-Secret).
                                    # Deliberately NOT mounted under /tasks: these
                                    # endpoints mint tokens that act as any user.
```

- [ ] **Step 6: Verify the app still imports and the routes exist**

From `mcp-servers/tasks/`:

```bash
python -c "
import os
os.environ.setdefault('DATABASE_URL', 'postgresql://nobody@nowhere/nobody')
os.environ.setdefault('AIUI_FERNET_KEY', 'YWl1aS10ZXN0LWtleS1ub3QtYS1yZWFsLXNlY3JldCE=')
from main import app
paths = sorted(r.path for r in app.routes if '/gateway' in r.path)
print(paths)
"
```

Expected exactly:

```
['/gateway/resolve', '/gateway/session', '/gateway/session', '/gateway/sessions/recent']
```

Two `/gateway/session` entries is correct: GET and PUT are separate routes. If any path starts with `/tasks/gateway`, you mounted the internal router twice. Remove the second include.

- [ ] **Step 7: Write the container-tier test**

Create `mcp-servers/tasks/tests/test_gateway_routes_db.py`:

```python
"""Round trips against a real database. Container tier.

Deliberately does NOT use the db_session fixture: that fixture TRUNCATEs eight
tasks.* tables, and on 2026-04-27 a careless run of exactly this kind wiped 9
production projects and all chat history. Everything here is namespaced under a
unique platform value and deleted in a finally.
"""
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    "test" not in os.environ.get("DATABASE_URL", "")
    and not os.environ.get("AIUI_CONTAINER_DB"),
    reason="needs a real database; run inside the tasks container",
)

import asyncpg
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import routes_gateway

SECRET = os.environ.get("INTERNAL_CALLBACK_SECRET", "")
HEADERS = {"X-Internal-Secret": SECRET}


@pytest.fixture
def platform():
    """A platform name no real row will ever use, so cleanup is exact."""
    return f"pytest-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def fresh_db_engine():
    """db.py caches an engine bound to whichever event loop first used it.

    pytest-asyncio hands every test a fresh loop, so a maker left over from the
    previous test poisons this one with "another operation is in progress".
    Abandon it rather than closing it, because closing would touch the dead
    loop. Same reset tests/conftest.py does, for the same reason, but without
    its db_session fixture, which TRUNCATEs eight tasks.* tables.
    """
    import db

    db._engine = None
    db._session_maker = None
    yield
    db._engine = None
    db._session_maker = None


@pytest.fixture
async def client():
    app = FastAPI()
    app.include_router(routes_gateway.router)
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://t") as c:
        yield c


async def _cleanup(platform: str) -> None:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        for table in ("gateway_links", "gateway_pairing_codes", "gateway_sessions"):
            await conn.execute(
                f"DELETE FROM tasks.{table} WHERE platform = $1", platform)
    finally:
        await conn.close()


async def test_unlinked_user_gets_a_code_then_the_same_one_again(client, platform):
    try:
        first = await client.post("/gateway/resolve", headers=HEADERS, json={
            "platform": platform, "platform_user_id": "u1"})
        assert first.status_code == 200
        assert first.json()["linked"] is False
        assert len(first.json()["code"]) == 8

        second = await client.post("/gateway/resolve", headers=HEADERS, json={
            "platform": platform, "platform_user_id": "u1"})
        assert second.json()["linked"] is False

        conn = await asyncpg.connect(os.environ["DATABASE_URL"])
        try:
            rows = await conn.fetchval(
                "SELECT count(*) FROM tasks.gateway_pairing_codes "
                "WHERE platform = $1 AND platform_user_id = $2", platform, "u1")
        finally:
            await conn.close()
        assert rows == 1, "a second message must not create a second code row"
    finally:
        await _cleanup(platform)


async def test_a_linked_user_gets_a_token(client, platform):
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        await conn.execute(
            "INSERT INTO tasks.gateway_links "
            "(platform, platform_user_id, owui_user_id, email) "
            "VALUES ($1, $2, $3, $4)",
            platform, "u2", "owui-user-2", "someone@example.com")
    finally:
        await conn.close()
    try:
        resp = await client.post("/gateway/resolve", headers=HEADERS, json={
            "platform": platform, "platform_user_id": "u2"})
        body = resp.json()
        assert body["linked"] is True
        assert body["email"] == "someone@example.com"
        assert body["owui_token"].count(".") == 2
        assert "code" not in body
    finally:
        await _cleanup(platform)


async def test_session_upsert_is_idempotent_and_readable(client, platform):
    try:
        payload = {"platform": platform, "chat_id": "c1",
                   "owui_chat_id": "owui-chat-1", "owui_user_id": "owui-user-1"}
        assert (await client.put("/gateway/session", headers=HEADERS,
                                 json=payload)).status_code == 200
        payload["owui_chat_id"] = "owui-chat-2"
        assert (await client.put("/gateway/session", headers=HEADERS,
                                 json=payload)).status_code == 200

        got = await client.get("/gateway/session", headers=HEADERS,
                               params={"platform": platform, "chat_id": "c1"})
        assert got.json()["owui_chat_id"] == "owui-chat-2"

        recent = await client.get("/gateway/sessions/recent", headers=HEADERS,
                                  params={"owui_user_id": "owui-user-1"})
        mine = [s for s in recent.json()["sessions"] if s["platform"] == platform]
        assert len(mine) == 1
    finally:
        await _cleanup(platform)


async def test_an_unknown_session_reads_as_null(client, platform):
    got = await client.get("/gateway/session", headers=HEADERS,
                           params={"platform": platform, "chat_id": "nope"})
    assert got.json()["owui_chat_id"] is None
```

- [ ] **Step 8: Run the container-tier test on the server**

The tasks app runs from the baked `/app`, not a bind mount, so copy the three files in before running. This is a temporary dev loop and the copies vanish on the next rebuild.

```bash
scp mcp-servers/tasks/owui_token.py mcp-servers/tasks/gateway_pairing.py mcp-servers/tasks/routes_gateway.py mcp-servers/tasks/models.py root@46.224.193.25:/tmp/
scp mcp-servers/tasks/migrations/033_gateway.sql root@46.224.193.25:/tmp/
scp mcp-servers/tasks/tests/test_gateway_routes_db.py root@46.224.193.25:/tmp/
ssh root@46.224.193.25 "
  for f in owui_token.py gateway_pairing.py routes_gateway.py models.py; do
    sed -i 's/\r\$//' /tmp/\$f && docker cp /tmp/\$f tasks:/app/\$f
  done
  sed -i 's/\r\$//' /tmp/033_gateway.sql && docker cp /tmp/033_gateway.sql tasks:/app/migrations/033_gateway.sql
  sed -i 's/\r\$//' /tmp/test_gateway_routes_db.py && docker cp /tmp/test_gateway_routes_db.py tasks:/app/tests/test_gateway_routes_db.py
  docker exec tasks sh -lc 'cd /app && python -c \"import asyncio, db; asyncio.run(db._run_migrations())\" && AIUI_CONTAINER_DB=1 python -m pytest tests/test_gateway_routes_db.py -q'
"
```

Expected: `4 passed`. The `sed` calls are not optional: this repo checks out CRLF on Windows and a stray `\r` inside the SQL breaks the migration.

- [ ] **Step 9: Commit**

```bash
git add mcp-servers/tasks/routes_gateway.py mcp-servers/tasks/main.py mcp-servers/tasks/tests/test_gateway_routes_auth.py mcp-servers/tasks/tests/test_gateway_routes_db.py
git commit -m "feat(gateway): internal resolve, session and recent-sessions endpoints"
```

---

### Task 5: The link page and code redemption

Where a signed-in user pastes their code. Authenticated by `X-User-Email`, which api-gateway injects from the browser's Open WebUI session cookie, so redeeming is inherently done as a known account. The gateway never learns a password and the user never pastes a token.

**Files:**
- Modify: `mcp-servers/tasks/routes_gateway.py` (add `page_router` at the end)
- Create: `mcp-servers/tasks/static/gateway-link.html`
- Modify: `mcp-servers/tasks/main.py` (include `page_router`)
- Test: `mcp-servers/tasks/tests/test_gateway_link.py` (runs anywhere)
- Test: `mcp-servers/tasks/tests/test_gateway_link_db.py` (container tier)

**Interfaces:**
- Consumes: everything from Task 4, plus `gateway_pairing.MAX_REDEEM_ATTEMPTS`.
- Produces: `page_router` with `GET /tasks/gateway/link` (the HTML page) and `POST /tasks/gateway/link` (redeem, body `{"code": "..."}`), returning `{"status": "linked", "platform": "...", "platform_user_name": "..."}` on success.

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_gateway_link.py`:

```python
"""The link page must require a signed-in user and must never accept a code
without one. The redeem path is the only way a gateway_links row is created,
so an unauthenticated redeem would let anyone claim any pending code.
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("INTERNAL_CALLBACK_SECRET", "test-internal-secret")

import routes_gateway


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes_gateway.page_router)
    return TestClient(app, raise_server_exceptions=False)


def test_redeem_without_a_signed_in_user_is_401(client):
    resp = client.post("/tasks/gateway/link", json={"code": "ABCD2345"})
    assert resp.status_code == 401


def test_redeem_with_a_blank_code_is_422(client):
    resp = client.post("/tasks/gateway/link", json={"code": ""},
                       headers={"X-User-Email": "someone@example.com"})
    assert resp.status_code == 422


def test_the_page_route_needs_no_auth(client):
    # The HTML itself is inert. Everything it can do requires the header.
    resp = client.get("/tasks/gateway/link")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_the_page_posts_to_the_same_path():
    page = (
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "static", "gateway-link.html")
    )
    with open(page, encoding="utf-8") as fh:
        html = fh.read()
    assert "/tasks/gateway/link" in html
    # Same-origin fetch, so the browser sends the Open WebUI session cookie and
    # api-gateway can turn it into X-User-Email. An absolute URL would break that.
    assert "https://" not in html.split("fetch(")[1].split(")")[0]
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/test_gateway_link.py -q
```

Expected: `AttributeError: module 'routes_gateway' has no attribute 'page_router'`.

- [ ] **Step 3: Add the page router**

Append to `mcp-servers/tasks/routes_gateway.py`:

```python
# ---------------------------------------------------------------------------
# User-facing. X-User-Email is injected by api-gateway from the caller's Open
# WebUI session cookie (api-gateway/main.py builds gateway_headers for every
# backend, including the /tasks/* branch), so reaching these endpoints already
# proves who you are.
# ---------------------------------------------------------------------------
from fastapi import Depends                               # noqa: E402
from fastapi.responses import FileResponse                # noqa: E402

from auth import CurrentUser, current_user                # noqa: E402

page_router = APIRouter(prefix="/tasks/gateway")


class RedeemIn(BaseModel):
    code: str = Field(min_length=1)


@page_router.get("/link", include_in_schema=False)
def link_page() -> FileResponse:
    """Inert HTML. Every action it offers goes back through POST /link."""
    return FileResponse("static/gateway-link.html", media_type="text/html")


async def _owui_user_id_for(email: str) -> str | None:
    """The Open WebUI user id behind an email.

    A minted token carries the id, not the address, so pairing has to resolve
    it once here. Raw asyncpg because public."user" is Open WebUI's table and
    has no model in this service; same approach as routes_knowledge_graph.py.
    """
    import asyncpg
    conn = await asyncpg.connect(os.environ.get("DATABASE_URL", ""))
    try:
        row = await conn.fetchrow(
            'SELECT id FROM public."user" WHERE lower(email) = lower($1) LIMIT 1',
            email)
    finally:
        await conn.close()
    return row["id"] if row else None


@page_router.post("/link")
async def redeem(body: RedeemIn,
                 user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    """Turn a pairing code into a link, as the signed-in user.

    Wrong codes burn an attempt on every live code belonging to the same
    platform user, which is what makes MAX_REDEEM_ATTEMPTS a real lockout
    rather than something you retry past.
    """
    code = gp.normalize_code(body.code)
    if len(code) != gp.CODE_LENGTH:
        raise HTTPException(status_code=400, detail="That code does not look right.")

    now = _now()
    code_hash = gp.hash_code(code)
    async with session() as s:
        row = (await s.execute(
            select(GatewayPairingCode).where(
                GatewayPairingCode.code_hash == code_hash,
                GatewayPairingCode.redeemed_at.is_(None),
            ).limit(1)
        )).scalar_one_or_none()

        if row is None:
            raise HTTPException(status_code=404,
                                detail="That code is not valid. Ask for a new one.")
        if row.expires_at <= now:
            raise HTTPException(status_code=410,
                                detail="That code has expired. Ask for a new one.")
        if row.attempts >= gp.MAX_REDEEM_ATTEMPTS:
            raise HTTPException(status_code=429,
                                detail="Too many attempts. Ask for a new code.")

        owui_user_id = await _owui_user_id_for(user.email)
        if not owui_user_id:
            raise HTTPException(status_code=404, detail="No IO account for that address.")

        existing = (await s.execute(
            select(GatewayLink).where(
                GatewayLink.platform == row.platform,
                GatewayLink.platform_user_id == row.platform_user_id,
            )
        )).scalar_one_or_none()
        if existing:
            existing.owui_user_id = owui_user_id
            existing.email = user.email
            existing.linked_at = now
        else:
            s.add(GatewayLink(
                platform=row.platform,
                platform_user_id=row.platform_user_id,
                owui_user_id=owui_user_id,
                email=user.email,
            ))
        row.redeemed_at = now
        platform, name = row.platform, row.platform_user_name or ""
        await s.commit()

    log.info("gateway: linked %s account to %s", platform, user.email)
    return {"status": "linked", "platform": platform, "platform_user_name": name}
```

`page_router` carries these two routes and nothing else. Anything that needs the internal secret belongs on `router`.

Now the attempt bookkeeping. A wrong code never finds a row, so the counter cannot be incremented through `row`. Add this helper above `redeem`:

```python
async def _burn_attempt(s) -> None:
    """A wrong code matches no row, so there is nothing to increment directly.

    Increment every live code instead. That bounds guessing against the whole
    pool rather than per-code, which is the property MAX_REDEEM_ATTEMPTS needs.
    """
    await s.execute(
        update(GatewayPairingCode)
        .where(GatewayPairingCode.redeemed_at.is_(None),
               GatewayPairingCode.expires_at > _now())
        .values(attempts=GatewayPairingCode.attempts + 1)
    )
    await s.commit()
```

and in `redeem`, change the `row is None` branch to:

```python
        if row is None:
            await _burn_attempt(s)
            raise HTTPException(status_code=404,
                                detail="That code is not valid. Ask for a new one.")
```

- [ ] **Step 4: Write the page**

Create `mcp-servers/tasks/static/gateway-link.html`:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connect a chat app</title>
<style>
  :root { color-scheme: light dark; }
  body {
    font: 16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
    max-width: 34rem; margin: 4rem auto; padding: 0 1.25rem;
  }
  h1 { font-size: 1.35rem; margin-bottom: .25rem; }
  p.sub { opacity: .7; margin-top: 0; }
  input {
    font: inherit; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    letter-spacing: .18em; text-transform: uppercase;
    width: 100%; padding: .7rem .85rem; box-sizing: border-box;
    border: 1px solid rgba(128,128,128,.45); border-radius: .4rem;
    background: transparent; color: inherit;
  }
  button {
    font: inherit; margin-top: .75rem; padding: .6rem 1.1rem;
    border: 0; border-radius: .4rem; cursor: pointer;
    background: #2f6fe4; color: #fff;
  }
  button[disabled] { opacity: .55; cursor: default; }
  #msg { margin-top: 1rem; min-height: 1.5rem; }
  .ok { color: #1a7f43; }
  .bad { color: #c0392b; }
</style>
</head>
<body>
  <h1>Connect a chat app</h1>
  <p class="sub">Paste the code the bot sent you. It works once and expires in an hour.</p>

  <form id="f" autocomplete="off">
    <input id="code" name="code" maxlength="14" placeholder="ABCD2345"
           aria-label="Pairing code" required>
    <button id="go" type="submit">Connect</button>
  </form>
  <p id="msg" role="status" aria-live="polite"></p>

<script>
const form = document.getElementById('f');
const msg  = document.getElementById('msg');
const go   = document.getElementById('go');

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  go.disabled = true;
  msg.className = '';
  msg.textContent = 'Checking...';
  try {
    // Same-origin on purpose: the browser sends the Open WebUI session cookie
    // and api-gateway turns it into X-User-Email. An absolute URL would not.
    const res = await fetch('/tasks/gateway/link', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: document.getElementById('code').value }),
    });
    const body = await res.json().catch(() => ({}));
    if (res.ok) {
      msg.className = 'ok';
      msg.textContent = 'Connected. Go back to ' + (body.platform || 'your chat app')
                      + ' and send a message.';
      form.hidden = true;
      return;
    }
    if (res.status === 401) {
      msg.className = 'bad';
      msg.textContent = 'Sign in to IO first, then reload this page.';
    } else {
      msg.className = 'bad';
      msg.textContent = body.detail || 'That did not work. Ask the bot for a new code.';
    }
  } catch (err) {
    msg.className = 'bad';
    msg.textContent = 'Could not reach the server. Try again in a moment.';
  }
  go.disabled = false;
});
</script>
</body>
</html>
```

- [ ] **Step 5: Wire it up**

In `mcp-servers/tasks/main.py`, change the import added in Task 4 to bring in both routers, and add the second include:

```python
from routes_gateway import page_router as gateway_page_router, router as gateway_router
```

```python
app.include_router(gateway_page_router)  # /tasks/gateway/link, signed-in user
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
python -m pytest tests/test_gateway_link.py -q
```

Expected: `4 passed`.

- [ ] **Step 7: Write and run the container-tier redemption test**

Create `mcp-servers/tasks/tests/test_gateway_link_db.py`:

```python
"""The redemption lifecycle against a real database. Container tier.

Same safety rule as test_gateway_routes_db.py: unique platform namespace,
delete only our own rows, never the db_session fixture.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(
    "test" not in os.environ.get("DATABASE_URL", "")
    and not os.environ.get("AIUI_CONTAINER_DB"),
    reason="needs a real database; run inside the tasks container",
)

import asyncpg
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import gateway_pairing as gp
import routes_gateway

SECRET = os.environ.get("INTERNAL_CALLBACK_SECRET", "")


@pytest.fixture
def platform():
    return f"pytest-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def fresh_db_engine():
    """Rebind db.py's cached engine per test.

    pytest-asyncio gives every test a fresh event loop and db.py's engine stays
    bound to the first one that used it, so without this the second test onward
    fails with "another operation is in progress". Abandon rather than close:
    closing would touch the dead loop. Proven necessary on the real container
    during Task 4, where 3 of 4 tests failed exactly this way.
    """
    import db

    db._engine = None
    db._session_maker = None
    yield
    db._engine = None
    db._session_maker = None


@pytest.fixture
async def client():
    app = FastAPI()
    app.include_router(routes_gateway.router)
    app.include_router(routes_gateway.page_router)
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://t") as c:
        yield c


async def _a_real_email() -> str:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        return await conn.fetchval(
            'SELECT email FROM public."user" WHERE email IS NOT NULL LIMIT 1')
    finally:
        await conn.close()


async def _cleanup(platform: str) -> None:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        for table in ("gateway_links", "gateway_pairing_codes"):
            await conn.execute(
                f"DELETE FROM tasks.{table} WHERE platform = $1", platform)
    finally:
        await conn.close()


async def test_redeem_creates_a_link_and_burns_the_code(client, platform):
    email = await _a_real_email()
    try:
        issued = await client.post(
            "/gateway/resolve", headers={"X-Internal-Secret": SECRET},
            json={"platform": platform, "platform_user_id": "u1",
                  "platform_user_name": "Ralph"})
        code = issued.json()["code"]

        ok = await client.post("/tasks/gateway/link", json={"code": code},
                               headers={"X-User-Email": email})
        assert ok.status_code == 200, ok.text
        assert ok.json()["platform"] == platform

        again = await client.post("/tasks/gateway/link", json={"code": code},
                                  headers={"X-User-Email": email})
        assert again.status_code == 404, "a code must work exactly once"

        now_linked = await client.post(
            "/gateway/resolve", headers={"X-Internal-Secret": SECRET},
            json={"platform": platform, "platform_user_id": "u1"})
        assert now_linked.json()["linked"] is True
        assert now_linked.json()["email"] == email
    finally:
        await _cleanup(platform)


async def test_an_expired_code_is_refused(client, platform):
    email = await _a_real_email()
    code = gp.generate_code()
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        await conn.execute(
            "INSERT INTO tasks.gateway_pairing_codes "
            "(code_hash, platform, platform_user_id, expires_at) "
            "VALUES ($1, $2, $3, $4)",
            gp.hash_code(code), platform, "u2",
            datetime.now(timezone.utc) - timedelta(minutes=1))
    finally:
        await conn.close()
    try:
        resp = await client.post("/tasks/gateway/link", json={"code": code},
                                 headers={"X-User-Email": email})
        assert resp.status_code == 410
    finally:
        await _cleanup(platform)


async def test_a_wrong_code_burns_an_attempt(client, platform):
    email = await _a_real_email()
    try:
        await client.post("/gateway/resolve",
                          headers={"X-Internal-Secret": SECRET},
                          json={"platform": platform, "platform_user_id": "u3"})
        for _ in range(gp.MAX_REDEEM_ATTEMPTS):
            await client.post("/tasks/gateway/link",
                              json={"code": "ZZZZZZZZ"},
                              headers={"X-User-Email": email})
        conn = await asyncpg.connect(os.environ["DATABASE_URL"])
        try:
            attempts = await conn.fetchval(
                "SELECT attempts FROM tasks.gateway_pairing_codes "
                "WHERE platform = $1 AND platform_user_id = $2", platform, "u3")
        finally:
            await conn.close()
        assert attempts >= gp.MAX_REDEEM_ATTEMPTS
    finally:
        await _cleanup(platform)
```

Copy and run it the same way as Task 4 step 8, adding `static/gateway-link.html`:

```bash
scp mcp-servers/tasks/routes_gateway.py root@46.224.193.25:/tmp/
scp mcp-servers/tasks/tests/test_gateway_link_db.py root@46.224.193.25:/tmp/
ssh root@46.224.193.25 "
  sed -i 's/\r\$//' /tmp/routes_gateway.py && docker cp /tmp/routes_gateway.py tasks:/app/routes_gateway.py
  sed -i 's/\r\$//' /tmp/test_gateway_link_db.py && docker cp /tmp/test_gateway_link_db.py tasks:/app/tests/test_gateway_link_db.py
  docker exec tasks sh -lc 'cd /app && AIUI_CONTAINER_DB=1 python -m pytest tests/test_gateway_link_db.py -q'
"
```

Expected: `3 passed`.

- [ ] **Step 8: Commit**

```bash
git add mcp-servers/tasks/routes_gateway.py mcp-servers/tasks/static/gateway-link.html mcp-servers/tasks/main.py mcp-servers/tasks/tests/test_gateway_link.py mcp-servers/tasks/tests/test_gateway_link_db.py
git commit -m "feat(gateway): self-serve pairing page and code redemption"
```

---

### Task 6: Gateway events and the adapter contract

The tasks service side is done. Everything from here lives in `webhook-handler`.

**Files:**
- Create: `webhook-handler/gateway/__init__.py`
- Create: `webhook-handler/gateway/events.py`
- Create: `webhook-handler/gateway/base.py`
- Test: `webhook-handler/tests/test_gateway_events.py`
- Test: `webhook-handler/tests/test_gateway_chunking.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `MessageType` (`TEXT`, `VOICE`, `PHOTO`, `DOCUMENT`), `SessionSource(platform, chat_id, chat_type="dm", user_id=None, user_name=None)`, `MessageEvent(text, source, message_type=MessageType.TEXT, media_ref=None, media_duration=None, media_paths=[], message_id=None, timestamp=...)`, `BasePlatformAdapter` with abstract `connect`, `disconnect`, `parse_inbound`, `send` and defaulted `send_typing`, `stop_typing`, `verify_webhook`, `download_media`, and the free function `chunk_text(text, limit) -> list[str]`.

`media_ref` and `media_duration` are additions to the spec's dataclass. Telegram gives a `file_id` that has to be exchanged for a download URL, and the parse step must not do network calls, so the reference travels on the event and the download happens later. The duration travels with it because refusing a long clip is only useful before it is downloaded, and the byte count is not known until it already has been.

- [ ] **Step 1: Write the failing tests**

Create `webhook-handler/tests/test_gateway_events.py`:

```python
"""The normalized inbound contract.

Every adapter produces one of these and the pipeline reads nothing else, so a
new platform is a parse function rather than a new branch downstream.
"""
from datetime import datetime

from gateway.events import MessageEvent, MessageType, SessionSource


def test_a_text_event_needs_only_text_and_a_source():
    event = MessageEvent(text="hello", source=SessionSource(
        platform="telegram", chat_id="42"))
    assert event.message_type is MessageType.TEXT
    assert event.media_paths == []
    assert event.media_ref is None
    assert event.media_duration is None
    assert isinstance(event.timestamp, datetime)


def test_chat_type_defaults_to_dm():
    assert SessionSource(platform="cli", chat_id="1").chat_type == "dm"


def test_media_paths_are_not_shared_between_events():
    a = MessageEvent(text="", source=SessionSource(platform="t", chat_id="1"))
    b = MessageEvent(text="", source=SessionSource(platform="t", chat_id="2"))
    a.media_paths.append("/tmp/x.ogg")
    assert b.media_paths == [], "a mutable default would leak across events"


def test_the_message_types_we_actually_handle():
    assert {t.value for t in MessageType} == {"text", "voice", "photo", "document"}
```

Create `webhook-handler/tests/test_gateway_chunking.py`:

```python
"""Replies are chunked on paragraph boundaries.

Telegram hard-caps a message at 4096 characters. A model answer that goes over
must arrive as several readable messages, not one truncated one and not a
mid-word split when a paragraph break was available.
"""
import pytest

from gateway.base import chunk_text


def test_short_text_is_one_chunk():
    assert chunk_text("hello", 4096) == ["hello"]


def test_empty_text_produces_nothing():
    assert chunk_text("", 4096) == []


def test_text_at_exactly_the_limit_is_not_split():
    text = "a" * 4096
    assert chunk_text(text, 4096) == [text]


def test_paragraphs_are_the_preferred_seam():
    para = "x" * 3000
    chunks = chunk_text(f"{para}\n\n{para}", 4096)
    assert chunks == [para, para]


def test_a_single_oversized_paragraph_is_hard_split():
    chunks = chunk_text("y" * 10000, 4096)
    assert len(chunks) == 3
    assert all(len(c) <= 4096 for c in chunks)


@pytest.mark.parametrize("limit", [50, 500, 4096])
def test_no_content_is_lost_and_no_chunk_is_oversized(limit):
    text = "\n\n".join(f"paragraph {i} " + "z" * (i * 37) for i in range(20))
    chunks = chunk_text(text, limit)
    assert all(0 < len(c) <= limit for c in chunks)
    strip = lambda s: s.replace("\n", "")
    assert "".join(strip(c) for c in chunks) == strip(text)


def test_a_zero_limit_means_no_chunking():
    # A platform that declares max_message_length = 0 has no cap.
    assert chunk_text("a" * 9000, 0) == ["a" * 9000]
```

- [ ] **Step 2: Run them to verify they fail**

From `webhook-handler/`:

```bash
python -m pytest tests/test_gateway_events.py tests/test_gateway_chunking.py -q
```

Expected: `ModuleNotFoundError: No module named 'gateway'`.

- [ ] **Step 3: Write events.py**

Create `webhook-handler/gateway/__init__.py` as an empty file, then `webhook-handler/gateway/events.py`:

```python
"""The normalized inbound contract every platform adapter produces.

Modelled on hermes-agent's MessageEvent, minus the fields that only make sense
for their agent loop (auto_skill, channel_prompt, channel_context, internal).
We route to Open WebUI, which already owns the prompt and the tools.

chat_type is kept even though phase 1 is direct messages only. It is precisely
what the pipeline reads to detect and refuse a group, and the Brain is injected
into every model call, so answering in a group would print one person's private
memory to the whole room.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class MessageType(Enum):
    TEXT = "text"
    VOICE = "voice"
    PHOTO = "photo"
    DOCUMENT = "document"


@dataclass
class SessionSource:
    """Where a message came from, in platform-neutral terms.

    chat_id is the CONVERSATION, user_id is the PERSON. On a Telegram direct
    message they happen to be the same number; do not rely on that.
    """
    platform: str                       # "telegram" | "cli"
    chat_id: str
    chat_type: str = "dm"               # anything other than "dm" is refused
    user_id: str | None = None
    user_name: str | None = None


@dataclass
class MessageEvent:
    text: str
    source: SessionSource
    message_type: MessageType = MessageType.TEXT
    # An opaque, platform-specific handle to media that has NOT been fetched
    # yet (Telegram's file_id). Parsing must stay free of network calls, so the
    # download happens later, in the pipeline.
    media_ref: str | None = None
    # Seconds, when the platform tells us up front. The pipeline refuses a long
    # clip on this, BEFORE downloading it: the duration is in the inbound
    # payload and the byte count is not known until the file is already fetched.
    media_duration: int | None = None
    # Filled in after download. Temp paths; the pipeline deletes them.
    media_paths: list[str] = field(default_factory=list)
    message_id: str | None = None
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 4: Write base.py**

Create `webhook-handler/gateway/base.py`:

```python
"""The adapter contract, and the one piece of shared behaviour worth sharing.

hermes-agent declares three abstract methods because their adapters are
long-lived clients with callbacks. Ours are webhook driven, so parsing the
inbound payload is a real half of the job and belongs in the contract. That is
the one deliberate deviation.

Everything else has a working default here, which is what keeps a new platform
a small file rather than a copy of the whole flow.
"""
import logging
from abc import ABC, abstractmethod
from typing import Any

log = logging.getLogger(__name__)


def chunk_text(text: str, limit: int) -> list[str]:
    """Split `text` into pieces no longer than `limit`.

    Prefers paragraph breaks, falls back to line breaks, and hard-slices only
    when a single line is genuinely longer than the limit. `limit <= 0` means
    the platform has no cap.
    """
    text = text or ""
    if not text:
        return []
    if limit <= 0 or len(text) <= limit:
        return [text]

    chunks: list[str] = []
    buf = ""
    for para in text.split("\n\n"):
        joined = f"{buf}\n\n{para}" if buf else para
        if len(joined) <= limit:
            buf = joined
            continue
        if buf:
            chunks.append(buf)
            buf = ""
        if len(para) <= limit:
            buf = para
            continue
        for line in _hard_lines(para, limit):
            if buf and len(buf) + 1 + len(line) <= limit:
                buf = f"{buf}\n{line}"
            else:
                if buf:
                    chunks.append(buf)
                buf = line
    if buf:
        chunks.append(buf)
    return [c for c in chunks if c]


def _hard_lines(para: str, limit: int) -> list[str]:
    out: list[str] = []
    for line in para.split("\n"):
        while len(line) > limit:
            out.append(line[:limit])
            line = line[limit:]
        out.append(line)
    return out


class BasePlatformAdapter(ABC):
    """One platform's transport. No conversation logic lives here."""

    #: Set by the registry from the PlatformEntry, so chunking needs no subclass.
    max_message_length: int = 0
    name: str = ""

    @abstractmethod
    async def connect(self) -> bool:
        """Make the platform able to reach us. Telegram: setWebhook. CLI: no-op.

        Returns False rather than raising when the platform is misconfigured,
        so one broken adapter cannot stop the service from starting.
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """Undo connect(). Telegram: deleteWebhook."""

    @abstractmethod
    def parse_inbound(self, payload: dict, headers: dict) -> "Any | None":
        """Payload -> MessageEvent, or None for anything we do not handle.

        Must be pure and synchronous: no network, no disk. Returning None is
        the normal way to ignore edits, reactions and other update kinds.
        """

    @abstractmethod
    async def send(self, chat_id: str, text: str) -> None:
        """Deliver one message. Chunking is handled by send_chunked."""

    # --- defaulted below: override only when a platform can do better --------

    async def send_chunked(self, chat_id: str, text: str) -> None:
        for piece in chunk_text(text, self.max_message_length):
            await self.send(chat_id, piece)

    async def send_typing(self, chat_id: str) -> None:
        """A visible "working on it". Silent no-op where the platform has none."""

    async def stop_typing(self, chat_id: str) -> None:
        """Most platforms expire the indicator on their own."""

    def verify_webhook(self, payload: dict, headers: dict) -> bool:
        """True by default. A platform with a signature or secret overrides."""
        return True

    async def download_media(self, ref: str) -> str:
        """Fetch `ref` to a temp path. Platforms without media do not implement it."""
        raise NotImplementedError(f"{self.name} cannot download media")
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
python -m pytest tests/test_gateway_events.py tests/test_gateway_chunking.py -q
```

Expected: `13 passed`.

- [ ] **Step 6: Commit**

```bash
git add webhook-handler/gateway/__init__.py webhook-handler/gateway/events.py webhook-handler/gateway/base.py webhook-handler/tests/test_gateway_events.py webhook-handler/tests/test_gateway_chunking.py
git commit -m "feat(gateway): normalized message events and the adapter contract"
```

---

### Task 7: The platform registry

**Files:**
- Create: `webhook-handler/gateway/registry.py`
- Test: `webhook-handler/tests/test_gateway_registry.py`

**Interfaces:**
- Consumes: `gateway.base.BasePlatformAdapter`.
- Produces: `PlatformEntry(name, label, adapter_factory, required_env, max_message_length=0, emoji="🔌")` and `PlatformRegistry` with `register(entry)`, `is_enabled(name) -> bool`, `enabled() -> list[PlatformEntry]`, `adapter(name) -> BasePlatformAdapter | None`, `all_names() -> list[str]`. `adapter()` returns the same instance on repeated calls and `None` when the platform is not enabled.

- [ ] **Step 1: Write the failing test**

Create `webhook-handler/tests/test_gateway_registry.py`:

```python
"""A platform stays dark until its environment is supplied.

Same dormant-by-default shape as the Google sign-in wiring: the code ships,
nothing appears, and deploying changes nothing visible until someone sets a
token. That is what makes it safe to merge this before a bot exists.
"""
from gateway.base import BasePlatformAdapter
from gateway.registry import PlatformEntry, PlatformRegistry


class FakeAdapter(BasePlatformAdapter):
    name = "fake"

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        pass

    def parse_inbound(self, payload, headers):
        return None

    async def send(self, chat_id: str, text: str) -> None:
        pass


def _entry(**over) -> PlatformEntry:
    base = dict(name="fake", label="Fake", adapter_factory=FakeAdapter,
                required_env=["FAKE_TOKEN"], max_message_length=100)
    base.update(over)
    return PlatformEntry(**base)


def test_a_platform_with_unset_env_is_not_enabled(monkeypatch):
    monkeypatch.delenv("FAKE_TOKEN", raising=False)
    reg = PlatformRegistry()
    reg.register(_entry())
    assert reg.is_enabled("fake") is False
    assert reg.enabled() == []
    assert reg.adapter("fake") is None


def test_a_blank_env_value_does_not_count_as_set(monkeypatch):
    monkeypatch.setenv("FAKE_TOKEN", "   ")
    reg = PlatformRegistry()
    reg.register(_entry())
    assert reg.is_enabled("fake") is False


def test_every_required_var_must_be_present(monkeypatch):
    monkeypatch.setenv("FAKE_TOKEN", "t")
    monkeypatch.delenv("FAKE_SECRET", raising=False)
    reg = PlatformRegistry()
    reg.register(_entry(required_env=["FAKE_TOKEN", "FAKE_SECRET"]))
    assert reg.is_enabled("fake") is False


def test_an_enabled_platform_yields_one_cached_adapter(monkeypatch):
    monkeypatch.setenv("FAKE_TOKEN", "t")
    reg = PlatformRegistry()
    reg.register(_entry())
    first = reg.adapter("fake")
    assert isinstance(first, FakeAdapter)
    assert reg.adapter("fake") is first, "a new client per message would leak sockets"


def test_the_adapter_is_told_its_message_limit(monkeypatch):
    monkeypatch.setenv("FAKE_TOKEN", "t")
    reg = PlatformRegistry()
    reg.register(_entry())
    assert reg.adapter("fake").max_message_length == 100


def test_a_platform_with_no_required_env_is_always_enabled():
    reg = PlatformRegistry()
    reg.register(_entry(name="cli", required_env=[]))
    assert reg.is_enabled("cli") is True


def test_an_unknown_platform_is_not_enabled_and_has_no_adapter():
    reg = PlatformRegistry()
    assert reg.is_enabled("nope") is False
    assert reg.adapter("nope") is None


def test_registering_twice_replaces_rather_than_duplicates(monkeypatch):
    monkeypatch.setenv("FAKE_TOKEN", "t")
    reg = PlatformRegistry()
    reg.register(_entry())
    reg.register(_entry(label="Fake 2"))
    assert reg.all_names() == ["fake"]
    assert reg.enabled()[0].label == "Fake 2"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/test_gateway_registry.py -q
```

Expected: `ModuleNotFoundError: No module named 'gateway.registry'`.

- [ ] **Step 3: Write the implementation**

Create `webhook-handler/gateway/registry.py`:

```python
"""Which platforms exist, and which of them are actually usable right now.

hermes-agent's registry carries a plugin system, a setup_fn and a platform_hint.
All three are real ideas and none earns its keep at two platforms, so they are
left out until a third one asks for them.
"""
import logging
import os
from dataclasses import dataclass, field
from typing import Callable

from gateway.base import BasePlatformAdapter

log = logging.getLogger(__name__)


@dataclass
class PlatformEntry:
    name: str
    label: str
    adapter_factory: Callable[[], BasePlatformAdapter]
    required_env: list[str] = field(default_factory=list)
    max_message_length: int = 0          # telegram: 4096.  0 means no cap.
    emoji: str = "🔌"


class PlatformRegistry:
    """Dormant by default: a platform whose required_env is unset never wakes up.

    So this whole feature can ship to production before any bot token exists,
    and deploying it changes nothing visible.
    """

    def __init__(self) -> None:
        self._entries: dict[str, PlatformEntry] = {}
        self._adapters: dict[str, BasePlatformAdapter] = {}

    def register(self, entry: PlatformEntry) -> None:
        self._entries[entry.name] = entry
        # Drop any cached adapter so a re-register cannot hand out a stale one.
        self._adapters.pop(entry.name, None)

    def all_names(self) -> list[str]:
        return list(self._entries)

    def is_enabled(self, name: str) -> bool:
        entry = self._entries.get(name)
        if entry is None:
            return False
        return all(os.environ.get(var, "").strip() for var in entry.required_env)

    def enabled(self) -> list[PlatformEntry]:
        return [e for n, e in self._entries.items() if self.is_enabled(n)]

    def adapter(self, name: str) -> BasePlatformAdapter | None:
        """One long-lived adapter per platform, built on first use.

        Cached deliberately: a fresh client per inbound message would open a new
        connection pool every time on a box with 3.8GB of RAM.
        """
        if not self.is_enabled(name):
            return None
        if name not in self._adapters:
            entry = self._entries[name]
            adapter = entry.adapter_factory()
            adapter.name = entry.name
            adapter.max_message_length = entry.max_message_length
            self._adapters[name] = adapter
            log.info("gateway: %s adapter ready", name)
        return self._adapters[name]


#: The process-wide registry. main.py registers into this at import time.
registry = PlatformRegistry()
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
python -m pytest tests/test_gateway_registry.py -q
```

Expected: `8 passed`.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/gateway/registry.py webhook-handler/tests/test_gateway_registry.py
git commit -m "feat(gateway): platform registry, dormant until its env is set"
```

---

### Task 8: Gateway methods on the tasks client

All tasks transport already lives in `clients/tasks.py`, including an
`_internal_request` helper for `X-Internal-Secret` endpoints. Extend it rather
than opening a second path to the same service.

**Files:**
- Modify: `webhook-handler/clients/tasks.py` (append four methods to `TasksClient`)
- Test: `webhook-handler/tests/test_gateway_tasks_client.py`

**Interfaces:**
- Consumes: the tasks endpoints from Task 4.
- Produces, on `TasksClient`:
  - `gateway_resolve(platform, platform_user_id, platform_user_name="") -> dict` returning either `{"linked": True, "email", "owui_user_id", "owui_token"}` or `{"linked": False, "code", "expires_at"}`
  - `gateway_get_session(platform, chat_id) -> str | None`
  - `gateway_put_session(platform, chat_id, owui_chat_id, owui_user_id) -> None`
  - `gateway_recent_sessions(owui_user_id, limit=10) -> list[dict]`
  - All raise `TasksAPIError` on failure, which is the existing exception the callers already know.

- [ ] **Step 1: Write the failing test**

Create `webhook-handler/tests/test_gateway_tasks_client.py`:

```python
"""The gateway's half of the tasks client.

These endpoints hand back a token that acts as a specific user, so the tests
pin the header, the path and the returned shape. A silent shape change here
would surface as "the model answered as the wrong person".
"""
import httpx
import pytest
import respx

from clients.tasks import TasksAPIError, TasksClient

BASE = "http://tasks-test:8210"


def _client() -> TasksClient:
    return TasksClient(BASE, internal_secret="s3cr3t")


@respx.mock
async def test_resolve_sends_the_internal_secret_and_no_user_email():
    route = respx.post(f"{BASE}/gateway/resolve").mock(
        return_value=httpx.Response(200, json={
            "linked": True, "email": "a@b.c",
            "owui_user_id": "u1", "owui_token": "tok"}))
    out = await _client().gateway_resolve("telegram", "111", "Ralph")

    assert out["linked"] is True
    assert out["owui_token"] == "tok"
    sent = route.calls[0].request
    assert sent.headers["X-Internal-Secret"] == "s3cr3t"
    assert "X-User-Email" not in sent.headers


@respx.mock
async def test_resolve_passes_the_platform_user_through():
    route = respx.post(f"{BASE}/gateway/resolve").mock(
        return_value=httpx.Response(200, json={
            "linked": False, "code": "ABCD2345", "expires_at": "2026-08-10T12:00:00Z"}))
    out = await _client().gateway_resolve("telegram", "111", "Ralph")

    assert out["code"] == "ABCD2345"
    import json
    body = json.loads(route.calls[0].request.content)
    assert body == {"platform": "telegram", "platform_user_id": "111",
                    "platform_user_name": "Ralph"}


@respx.mock
async def test_get_session_returns_the_chat_id():
    respx.get(f"{BASE}/gateway/session").mock(
        return_value=httpx.Response(200, json={"owui_chat_id": "chat-1"}))
    assert await _client().gateway_get_session("telegram", "42") == "chat-1"


@respx.mock
async def test_get_session_returns_none_when_unmapped():
    respx.get(f"{BASE}/gateway/session").mock(
        return_value=httpx.Response(200, json={"owui_chat_id": None}))
    assert await _client().gateway_get_session("telegram", "42") is None


@respx.mock
async def test_put_session_sends_all_four_fields():
    route = respx.put(f"{BASE}/gateway/session").mock(
        return_value=httpx.Response(200, json={"status": "ok"}))
    await _client().gateway_put_session("telegram", "42", "chat-1", "u1")

    import json
    assert json.loads(route.calls[0].request.content) == {
        "platform": "telegram", "chat_id": "42",
        "owui_chat_id": "chat-1", "owui_user_id": "u1"}


@respx.mock
async def test_recent_sessions_returns_the_list():
    respx.get(f"{BASE}/gateway/sessions/recent").mock(
        return_value=httpx.Response(200, json={"sessions": [
            {"platform": "telegram", "chat_id": "42",
             "owui_chat_id": "chat-1", "updated_at": "2026-08-10T10:00:00Z"}]}))
    out = await _client().gateway_recent_sessions("u1")
    assert len(out) == 1 and out[0]["owui_chat_id"] == "chat-1"


@respx.mock
async def test_a_server_error_raises_tasks_api_error():
    respx.post(f"{BASE}/gateway/resolve").mock(
        return_value=httpx.Response(500, json={"detail": "boom"}))
    with pytest.raises(TasksAPIError):
        await _client().gateway_resolve("telegram", "111")


@respx.mock
async def test_an_unreachable_service_raises_with_status_zero():
    respx.post(f"{BASE}/gateway/resolve").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(TasksAPIError) as exc:
        await _client().gateway_resolve("telegram", "111")
    assert exc.value.status == 0
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/test_gateway_tasks_client.py -q
```

Expected: `AttributeError: 'TasksClient' object has no attribute 'gateway_resolve'`.

- [ ] **Step 3: Write the implementation**

Append to the `TasksClient` class in `webhook-handler/clients/tasks.py`:

```python
    # --- Multi-platform gateway ---------------------------------------------
    # These use _internal_request (X-Internal-Secret), never _request: there is
    # no user email yet at resolve time, and resolving IS how we learn it.

    async def gateway_resolve(
        self, platform: str, platform_user_id: str, platform_user_name: str = "",
    ) -> dict:
        """Who is this platform user?

        Linked   -> {"linked": True, "email", "owui_user_id", "owui_token"}
        Unlinked -> {"linked": False, "code", "expires_at"}

        The token is scoped to one user for 60 seconds. Do not store it, do not
        log it, and do not reuse it across requests.
        """
        resp = await self._internal_request("POST", "/gateway/resolve", json={
            "platform": platform,
            "platform_user_id": platform_user_id,
            "platform_user_name": platform_user_name,
        })
        return resp.json()

    async def gateway_get_session(self, platform: str, chat_id: str) -> str | None:
        """The Open WebUI chat this conversation maps to, or None if it is new."""
        resp = await self._internal_request(
            "GET", "/gateway/session",
            params={"platform": platform, "chat_id": chat_id})
        return resp.json().get("owui_chat_id")

    async def gateway_put_session(
        self, platform: str, chat_id: str, owui_chat_id: str, owui_user_id: str,
    ) -> None:
        await self._internal_request("PUT", "/gateway/session", json={
            "platform": platform,
            "chat_id": chat_id,
            "owui_chat_id": owui_chat_id,
            "owui_user_id": owui_user_id,
        })

    async def gateway_recent_sessions(
        self, owui_user_id: str, limit: int = 10,
    ) -> list[dict]:
        """Backs /resume. Newest first."""
        resp = await self._internal_request(
            "GET", "/gateway/sessions/recent",
            params={"owui_user_id": owui_user_id, "limit": limit})
        return resp.json().get("sessions", [])
```

Check `_internal_request` before running: it must forward `params` as well as `json`. It already takes `**kwargs` and passes them to `client.request`, so no change is needed. If it does not, add `**kwargs` rather than adding a `params` special case.

- [ ] **Step 4: Run the test to verify it passes**

```bash
python -m pytest tests/test_gateway_tasks_client.py -q
```

Expected: `8 passed`.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/clients/tasks.py webhook-handler/tests/test_gateway_tasks_client.py
git commit -m "feat(gateway): tasks client methods for resolve and session mapping"
```

---

### Task 9: The per-user Open WebUI client

`clients/openwebui.py` exists but is bound to the shared admin API key, which is
exactly the thing this design must not use: the Brain filter would inject the
admin's memory into every user's answer, and it would look completely correct
when an admin tested it. This client carries a caller-supplied token instead.

**Files:**
- Create: `webhook-handler/gateway/owui.py`
- Test: `webhook-handler/tests/test_gateway_owui.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `OWUIUserClient(base_url, token, timeout=120.0)` with:
  - `chat_completion(messages: list[dict], model: str, chat_id: str | None = None) -> str`
  - `create_chat(title: str, model: str) -> str` returning the new chat id
  - `get_chat(chat_id: str) -> dict` returning the inner chat object
  - `update_chat(chat_id: str, chat: dict) -> None`
  - `transcribe(path: str) -> str`
  - and the exception `OWUIError(status: int, message: str)`.

- [ ] **Step 1: Write the failing test**

Create `webhook-handler/tests/test_gateway_owui.py`:

```python
"""Open WebUI calls that carry a per-user token.

The single most important assertion in this file is that the Authorization
header is the token we were handed. If it were ever the shared admin key, every
user's answers would be built from the admin's Brain and an admin testing it
would see nothing wrong.
"""
import httpx
import pytest
import respx

from gateway.owui import OWUIError, OWUIUserClient

BASE = "http://open-webui:8080"


def _client(token: str = "user-token") -> OWUIUserClient:
    return OWUIUserClient(BASE, token)


@respx.mock
async def test_completion_carries_the_user_token_and_returns_the_text():
    route = respx.post(f"{BASE}/api/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "hi there"}}]}))

    out = await _client().chat_completion(
        [{"role": "user", "content": "hi"}], "auto_router.auto")

    assert out == "hi there"
    assert route.calls[0].request.headers["Authorization"] == "Bearer user-token"


@respx.mock
async def test_completion_passes_chat_id_when_given():
    import json
    route = respx.post(f"{BASE}/api/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}}]}))

    await _client().chat_completion([{"role": "user", "content": "hi"}],
                                    "auto_router.auto", chat_id="chat-1")

    body = json.loads(route.calls[0].request.content)
    assert body["chat_id"] == "chat-1"
    assert body["stream"] is False


@respx.mock
async def test_an_empty_choices_list_raises_rather_than_returning_blank():
    respx.post(f"{BASE}/api/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": []}))
    with pytest.raises(OWUIError):
        await _client().chat_completion([{"role": "user", "content": "hi"}], "m")


@respx.mock
async def test_a_5xx_raises_with_its_status():
    respx.post(f"{BASE}/api/chat/completions").mock(
        return_value=httpx.Response(503, text="unavailable"))
    with pytest.raises(OWUIError) as exc:
        await _client().chat_completion([{"role": "user", "content": "hi"}], "m")
    assert exc.value.status == 503


@respx.mock
async def test_a_timeout_raises_with_status_zero():
    respx.post(f"{BASE}/api/chat/completions").mock(
        side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(OWUIError) as exc:
        await _client().chat_completion([{"role": "user", "content": "hi"}], "m")
    assert exc.value.status == 0


@respx.mock
async def test_create_chat_returns_the_new_id():
    import json
    route = respx.post(f"{BASE}/api/v1/chats/new").mock(
        return_value=httpx.Response(200, json={"id": "chat-9", "title": "Hello"}))

    chat_id = await _client().create_chat("Hello", "auto_router.auto")

    assert chat_id == "chat-9"
    body = json.loads(route.calls[0].request.content)
    # ChatForm is {chat: dict}; anything else is a 422.
    assert set(body) == {"chat"}
    assert body["chat"]["title"] == "Hello"
    assert body["chat"]["models"] == ["auto_router.auto"]


@respx.mock
async def test_get_chat_unwraps_the_inner_chat_object():
    respx.get(f"{BASE}/api/v1/chats/chat-9").mock(
        return_value=httpx.Response(200, json={
            "id": "chat-9", "title": "Hello",
            "chat": {"title": "Hello", "messages": [{"role": "user",
                                                     "content": "hi"}]}}))
    chat = await _client().get_chat("chat-9")
    assert chat["messages"][0]["content"] == "hi"


@respx.mock
async def test_update_chat_wraps_the_object_again():
    import json
    route = respx.post(f"{BASE}/api/v1/chats/chat-9").mock(
        return_value=httpx.Response(200, json={"id": "chat-9"}))

    await _client().update_chat("chat-9", {"title": "Hello", "messages": []})

    assert json.loads(route.calls[0].request.content) == {
        "chat": {"title": "Hello", "messages": []}}


@respx.mock
async def test_transcribe_uploads_the_file_and_returns_the_text(tmp_path):
    clip = tmp_path / "memo.ogg"
    clip.write_bytes(b"not really opus")
    route = respx.post(f"{BASE}/api/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "hello from a voice memo"}))

    out = await _client().transcribe(str(clip))

    assert out == "hello from a voice memo"
    sent = route.calls[0].request
    assert sent.headers["Authorization"] == "Bearer user-token"
    assert b"memo.ogg" in sent.content
    # audio/ogg matches Open WebUI's default audio/* allowlist; .ogg (not .oga)
    # is what its extension check accepts.
    assert b"audio/ogg" in sent.content


@respx.mock
async def test_transcribe_raises_when_the_response_has_no_text(tmp_path):
    clip = tmp_path / "memo.ogg"
    clip.write_bytes(b"x")
    respx.post(f"{BASE}/api/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={}))
    with pytest.raises(OWUIError):
        await _client().transcribe(str(clip))
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/test_gateway_owui.py -q
```

Expected: `ModuleNotFoundError: No module named 'gateway.owui'`.

- [ ] **Step 3: Write the implementation**

Create `webhook-handler/gateway/owui.py`:

```python
"""Open WebUI calls made AS a specific user.

clients/openwebui.py already talks to Open WebUI, but with the shared admin API
key. Using that here would resolve every caller as the admin, so the Brain
filter would inject the ADMIN's memory into every user's answer. An admin
testing it would see a perfectly correct-looking result. That silent failure is
the reason this second client exists.

The token comes from the tasks service, is scoped to one user, and lives 60
seconds. Never persist it and never log it.
"""
import json
import logging
import mimetypes
import os
import time
import uuid

import httpx

log = logging.getLogger(__name__)


class OWUIError(Exception):
    """status = 0 means a network-level failure (timeout, connection refused)."""

    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(f"open-webui error {status}: {message}")


class OWUIUserClient:
    def __init__(self, base_url: str, token: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.request(
                    method, url, headers=self._headers(), **kwargs)
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise OWUIError(0, f"open-webui unreachable: {e}") from e
        if resp.status_code >= 400:
            # resp.text, not the JSON detail: a 502 from the proxy is HTML.
            raise OWUIError(resp.status_code, resp.text[:400])
        return resp

    async def chat_completion(
        self, messages: list[dict], model: str, chat_id: str | None = None,
    ) -> str:
        payload: dict = {"model": model, "messages": messages, "stream": False}
        if chat_id:
            # Lets Open WebUI's own filters associate the turn with the chat.
            payload["chat_id"] = chat_id
        resp = await self._request("POST", "/api/chat/completions", json=payload)
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise OWUIError(502, f"no choices in response: {json.dumps(data)[:300]}")
        content = (choices[0].get("message") or {}).get("content") or ""
        if not content.strip():
            raise OWUIError(502, "the model returned an empty answer")
        return content

    async def create_chat(self, title: str, model: str) -> str:
        """Create a real Open WebUI chat and return its id.

        Real, not synthetic, on purpose: it puts the conversation in the user's
        sidebar, makes it searchable, and feeds the Brain, with no sync
        mechanism of our own to keep correct.
        """
        chat = {
            "id": "",
            "title": title[:120] or "New chat",
            "models": [model],
            "params": {},
            "messages": [],
            "history": {"messages": {}, "currentId": None},
            "tags": [],
            "timestamp": int(time.time() * 1000),
            "files": [],
        }
        resp = await self._request("POST", "/api/v1/chats/new", json={"chat": chat})
        chat_id = resp.json().get("id")
        if not chat_id:
            raise OWUIError(502, "chat creation returned no id")
        return chat_id

    async def get_chat(self, chat_id: str) -> dict:
        """The inner chat object, which is what update_chat expects back."""
        resp = await self._request("GET", f"/api/v1/chats/{chat_id}")
        return resp.json().get("chat") or {}

    async def update_chat(self, chat_id: str, chat: dict) -> None:
        await self._request("POST", f"/api/v1/chats/{chat_id}", json={"chat": chat})

    async def transcribe(self, path: str) -> str:
        """Speech to text through Open WebUI's own endpoint.

        Deliberately not a direct faster-whisper call: going through Open WebUI
        means the model, the cache and the engine setting stay in one place, and
        the container already has faster-whisper-base warm.

        The filename matters. Open WebUI checks the extension against
        AUDIO_STT_ALLOWED_EXTENSIONS, whose default list contains "ogg" and not
        Telegram's native "oga", so callers must hand us a .ogg path.
        """
        mime = mimetypes.guess_type(path)[0] or "audio/ogg"
        with open(path, "rb") as fh:
            files = {"file": (os.path.basename(path), fh.read(), mime)}
        resp = await self._request(
            "POST", "/api/v1/audio/transcriptions", files=files)
        text = (resp.json() or {}).get("text")
        if not text:
            raise OWUIError(502, "transcription returned no text")
        return text
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
python -m pytest tests/test_gateway_owui.py -q
```

Expected: `10 passed`. If `test_transcribe_uploads_the_file_and_returns_the_text` fails on the `audio/ogg` assertion, `mimetypes` on this machine does not know `.ogg`; the fallback in the code covers it, so check that the test wrote a `.ogg` name.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/gateway/owui.py webhook-handler/tests/test_gateway_owui.py
git commit -m "feat(gateway): Open WebUI client that acts as the paired user"
```

---

### Task 10: Pairing copy and session policy

Two small policy modules. Transport is already done; this is what we say and
which chat we say it in.

**Files:**
- Create: `webhook-handler/gateway/pairing.py`
- Create: `webhook-handler/gateway/sessions.py`
- Modify: `webhook-handler/config.py` (three settings)
- Test: `webhook-handler/tests/test_gateway_pairing_copy.py`
- Test: `webhook-handler/tests/test_gateway_sessions.py`

**Interfaces:**
- Consumes: `gateway.owui.OWUIUserClient` (Task 9), `clients.tasks.TasksClient` gateway methods (Task 8).
- Produces:
  - `gateway.pairing.pairing_message(code: str, link_url: str) -> str`
  - `gateway.sessions.get_or_create_chat(tasks, owui, platform, chat_id, owui_user_id, first_text, model) -> tuple[str, dict]` returning `(owui_chat_id, chat_object)`
  - `gateway.sessions.history_messages(chat: dict, limit: int = 20) -> list[dict]`
  - `gateway.sessions.append_turn(chat: dict, user_text: str, assistant_text: str, model: str) -> dict`
  - `gateway.sessions.title_from(text: str) -> str`
- New settings on `Settings`: `gateway_model` (default `"auto_router.auto"`, alias `GATEWAY_MODEL`), `gateway_public_url` (default `"https://ai-ui.coolestdomain.win"`), `gateway_history_turns` (default `20`).

- [ ] **Step 1: Write the failing tests**

Create `webhook-handler/tests/test_gateway_pairing_copy.py`:

```python
"""The pairing reply is the first thing a new user ever reads from us.

It has to say who we are, what to do, and where, in a message that survives
being read on a phone.
"""
from gateway.pairing import pairing_message

URL = "https://ai-ui.coolestdomain.win/tasks/gateway/link"


def test_the_code_and_the_link_are_both_present():
    msg = pairing_message("ABCD2345", URL)
    assert "ABCD2345" in msg
    assert URL in msg


def test_it_says_the_code_expires():
    assert "hour" in pairing_message("ABCD2345", URL).lower()


def test_no_em_dashes_or_en_dashes():
    # Global writing rule: these are an AI tell and this is copy a person reads.
    msg = pairing_message("ABCD2345", URL)
    assert "—" not in msg and "–" not in msg


def test_it_fits_in_a_single_telegram_message():
    assert len(pairing_message("ABCD2345", URL)) < 900
```

Create `webhook-handler/tests/test_gateway_sessions.py`:

```python
"""Session policy: which Open WebUI chat a conversation writes to, and how a
turn is appended so the sidebar renders it.

Open WebUI's frontend keeps BOTH a flat `messages` list and a `history` map
keyed by message id with `currentId` on the newest leaf. Writing only one of
them produces a chat that exists but shows nothing.
"""
from unittest.mock import AsyncMock

import pytest

from gateway.sessions import (append_turn, get_or_create_chat, history_messages,
                              title_from)


def test_title_is_a_short_single_line():
    assert title_from("hello there") == "hello there"
    long = "word " * 40
    assert len(title_from(long)) <= 60
    assert "\n" not in title_from("first line\nsecond line")


def test_title_falls_back_when_there_is_no_text():
    assert title_from("") == "New chat"
    assert title_from("   ") == "New chat"


def test_history_messages_keeps_only_role_and_content():
    chat = {"messages": [
        {"role": "user", "content": "hi", "id": "1", "timestamp": 1},
        {"role": "assistant", "content": "hello", "id": "2", "done": True},
    ]}
    assert history_messages(chat) == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_history_messages_is_capped_to_the_most_recent():
    chat = {"messages": [{"role": "user", "content": str(i)} for i in range(50)]}
    out = history_messages(chat, limit=6)
    assert len(out) == 6
    assert out[-1]["content"] == "49"


def test_history_messages_skips_empty_and_malformed_entries():
    chat = {"messages": [
        {"role": "user", "content": ""},
        {"role": "user"},
        "not a dict",
        {"role": "assistant", "content": "kept"},
    ]}
    assert history_messages(chat) == [{"role": "assistant", "content": "kept"}]


def test_append_turn_writes_both_messages_and_history():
    chat = {"title": "t", "messages": [], "history": {"messages": {}, "currentId": None}}
    out = append_turn(chat, "hi", "hello", "auto_router.auto")

    assert [m["role"] for m in out["messages"]] == ["user", "assistant"]
    assert len(out["history"]["messages"]) == 2
    newest = out["history"]["currentId"]
    assert out["history"]["messages"][newest]["role"] == "assistant"


def test_append_turn_links_the_new_turn_to_the_previous_one():
    chat = {"title": "t", "messages": [], "history": {"messages": {}, "currentId": None}}
    first = append_turn(chat, "one", "1", "m")
    second = append_turn(first, "two", "2", "m")

    prev_leaf = first["history"]["currentId"]
    new_user = second["messages"][2]
    assert new_user["parentId"] == prev_leaf
    assert new_user["id"] in second["history"]["messages"][prev_leaf]["childrenIds"]


def test_append_turn_does_not_mutate_the_input():
    chat = {"title": "t", "messages": [], "history": {"messages": {}, "currentId": None}}
    append_turn(chat, "hi", "hello", "m")
    assert chat["messages"] == []


async def test_get_or_create_reuses_an_existing_mapping():
    tasks = AsyncMock()
    tasks.gateway_get_session.return_value = "chat-1"
    owui = AsyncMock()
    owui.get_chat.return_value = {"title": "old", "messages": [{"role": "user",
                                                                "content": "hi"}]}

    chat_id, chat = await get_or_create_chat(
        tasks, owui, "telegram", "42", "u1", "next message", "m")

    assert chat_id == "chat-1"
    assert chat["messages"]
    owui.create_chat.assert_not_called()
    tasks.gateway_put_session.assert_not_called()


async def test_get_or_create_makes_a_chat_and_stores_the_mapping():
    tasks = AsyncMock()
    tasks.gateway_get_session.return_value = None
    owui = AsyncMock()
    owui.create_chat.return_value = "chat-new"
    owui.get_chat.return_value = {"title": "Hello", "messages": []}

    chat_id, chat = await get_or_create_chat(
        tasks, owui, "telegram", "42", "u1", "Hello there", "m")

    assert chat_id == "chat-new"
    owui.create_chat.assert_awaited_once()
    tasks.gateway_put_session.assert_awaited_once_with(
        "telegram", "42", "chat-new", "u1")


async def test_a_mapping_pointing_at_a_deleted_chat_recovers():
    # The user deleted the chat in the browser. The next message must not 404
    # forever; it must make a new one and re-point the mapping.
    from gateway.owui import OWUIError

    tasks = AsyncMock()
    tasks.gateway_get_session.return_value = "chat-gone"
    owui = AsyncMock()
    owui.get_chat.side_effect = [OWUIError(404, "not found"), {"title": "t",
                                                               "messages": []}]
    owui.create_chat.return_value = "chat-fresh"

    chat_id, _ = await get_or_create_chat(
        tasks, owui, "telegram", "42", "u1", "hi", "m")

    assert chat_id == "chat-fresh"
    tasks.gateway_put_session.assert_awaited_once_with(
        "telegram", "42", "chat-fresh", "u1")
```

- [ ] **Step 2: Run them to verify they fail**

```bash
python -m pytest tests/test_gateway_pairing_copy.py tests/test_gateway_sessions.py -q
```

Expected: `ModuleNotFoundError: No module named 'gateway.pairing'`.

- [ ] **Step 3: Write pairing.py**

Create `webhook-handler/gateway/pairing.py`:

```python
"""What we say to someone we do not recognize yet.

Policy, not transport. The code itself comes from the tasks service; this
module only decides how it reads.
"""


def pairing_message(code: str, link_url: str) -> str:
    """The reply an unpaired user gets.

    Deliberately short. It is read on a phone, and the only thing that matters
    is the code and where to put it.
    """
    return (
        "Hi. I don't know who you are yet, so I can't reach your IO account.\n\n"
        f"Open {link_url} while signed in to IO, and paste this code:\n\n"
        f"{code}\n\n"
        "It works once and expires in an hour. Send me anything after that and "
        "we're connected."
    )
```

- [ ] **Step 4: Write sessions.py**

Create `webhook-handler/gateway/sessions.py`:

```python
"""Which Open WebUI chat a platform conversation writes to.

Continuity is not a mechanism we maintain, it is the chat id. Because the
mapping points at a REAL Open WebUI chat, the conversation shows up in the
user's sidebar, is searchable, and feeds the Brain like any other chat, with
nothing of ours that can drift out of sync.
"""
import logging
import time
import uuid

from gateway.owui import OWUIError

log = logging.getLogger(__name__)


def title_from(text: str) -> str:
    """A chat title from the opening message. Sidebar-sized, one line."""
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return "New chat"
    return cleaned[:60]


def history_messages(chat: dict, limit: int = 20) -> list[dict]:
    """The prior turns, reduced to what a completion call needs.

    Capped because the whole transcript grows without bound and the model call
    pays for every token of it. The full history stays in Open WebUI.
    """
    out: list[dict] = []
    for msg in (chat.get("messages") or []):
        if not isinstance(msg, dict):
            continue
        role, content = msg.get("role"), msg.get("content")
        if not role or not isinstance(content, str) or not content.strip():
            continue
        out.append({"role": role, "content": content})
    return out[-limit:] if limit > 0 else out


def append_turn(chat: dict, user_text: str, assistant_text: str,
                model: str) -> dict:
    """Return a copy of `chat` with one user and one assistant message added.

    Writes BOTH representations Open WebUI keeps: the flat `messages` list and
    the `history` map keyed by id with `currentId` on the newest leaf. Writing
    only one produces a chat that exists in the sidebar and renders empty.
    """
    history = dict(chat.get("history") or {})
    hist_msgs = dict(history.get("messages") or {})
    parent_id = history.get("currentId")
    stamp = int(time.time())

    user_id, asst_id = str(uuid.uuid4()), str(uuid.uuid4())
    user_msg = {
        "id": user_id, "parentId": parent_id, "childrenIds": [asst_id],
        "role": "user", "content": user_text, "timestamp": stamp,
    }
    asst_msg = {
        "id": asst_id, "parentId": user_id, "childrenIds": [],
        "role": "assistant", "content": assistant_text, "timestamp": stamp,
        "model": model, "modelName": model, "modelIdx": 0, "done": True,
    }
    if parent_id and parent_id in hist_msgs:
        prev = dict(hist_msgs[parent_id])
        prev["childrenIds"] = list(prev.get("childrenIds") or []) + [user_id]
        hist_msgs[parent_id] = prev
    hist_msgs[user_id] = user_msg
    hist_msgs[asst_id] = asst_msg

    out = dict(chat)
    out["messages"] = list(chat.get("messages") or []) + [user_msg, asst_msg]
    out["history"] = {"messages": hist_msgs, "currentId": asst_id}
    if not out.get("models"):
        out["models"] = [model]
    return out


async def get_or_create_chat(tasks, owui, platform: str, chat_id: str,
                             owui_user_id: str, first_text: str,
                             model: str) -> tuple[str, dict]:
    """Resolve this conversation to an Open WebUI chat, creating one if needed.

    Recovers when the mapping points at a chat the user has since deleted in the
    browser. Without that, one deletion would wedge the conversation on a 404
    forever and the only fix would be a database edit.
    """
    owui_chat_id = await tasks.gateway_get_session(platform, chat_id)

    if owui_chat_id:
        try:
            return owui_chat_id, await owui.get_chat(owui_chat_id)
        except OWUIError as e:
            if e.status != 404:
                raise
            log.info("gateway: mapped chat %s is gone, starting a new one",
                     owui_chat_id)

    new_id = await owui.create_chat(title_from(first_text), model)
    await tasks.gateway_put_session(platform, chat_id, new_id, owui_user_id)
    return new_id, await owui.get_chat(new_id)
```

- [ ] **Step 5: Add the settings**

In `webhook-handler/config.py`, add to `Settings` just below the Tasks service block:

```python
    # Multi-platform gateway. The model every gateway conversation uses.
    # auto_router.auto is the "Auto (Free)" pipe: active on prod, free, so a
    # runaway loop costs nothing.
    gateway_model: str = Field(default="auto_router.auto", alias="GATEWAY_MODEL")
    # Browser-visible base for the pairing link. Not tasks_public_url, so the
    # two can diverge without silently breaking pairing.
    gateway_public_url: str = "https://ai-ui.coolestdomain.win"
    # Prior turns replayed into each completion. The full transcript stays in
    # Open WebUI; this only bounds what each call pays for.
    gateway_history_turns: int = 20
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
python -m pytest tests/test_gateway_pairing_copy.py tests/test_gateway_sessions.py -q
```

Expected: `15 passed`.

- [ ] **Step 7: Commit**

```bash
git add webhook-handler/gateway/pairing.py webhook-handler/gateway/sessions.py webhook-handler/config.py webhook-handler/tests/test_gateway_pairing_copy.py webhook-handler/tests/test_gateway_sessions.py
git commit -m "feat(gateway): pairing copy and Open WebUI chat session policy"
```

---

### Task 11: The message pipeline

One flow, shared by every platform. This is the file that decides what happens
to a `MessageEvent`, and the only place the error copy lives.

**Files:**
- Create: `webhook-handler/gateway/pipeline.py`
- Test: `webhook-handler/tests/test_gateway_pipeline.py`

**Interfaces:**
- Consumes: everything from Tasks 6 through 10.
- Produces:
  - `configure(tasks_client) -> None`, called once at startup
  - `handle_event(event: MessageEvent, adapter: BasePlatformAdapter) -> str` returning the text that was sent, so a synchronous caller like the CLI can return it inline
  - the seams `_tasks` (the `TasksClient`) and `_owui_factory(token) -> OWUIUserClient`, which tests replace
  - the copy constants `GROUP_REFUSAL`, `TASKS_DOWN`, `MODEL_DOWN`, `UNEXPECTED`, `UNSUPPORTED_TYPE`

- [ ] **Step 1: Write the failing test**

Create `webhook-handler/tests/test_gateway_pipeline.py`:

```python
"""The one flow every platform runs.

The load-bearing assertion is that the Open WebUI client is built from the
token that resolve returned for THIS user. If the pipeline ever fell back to a
shared key, every answer would be built from the wrong person's Brain and it
would look completely correct to an admin testing it.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from clients.tasks import TasksAPIError
from gateway import pipeline
from gateway.events import MessageEvent, MessageType, SessionSource
from gateway.owui import OWUIError


@pytest.fixture
def adapter():
    a = AsyncMock()
    a.name = "telegram"
    a.max_message_length = 4096
    return a


@pytest.fixture
def owui():
    client = AsyncMock()
    client.get_chat.return_value = {"title": "t", "messages": [],
                                    "history": {"messages": {}, "currentId": None}}
    client.create_chat.return_value = "chat-1"
    client.chat_completion.return_value = "the answer"
    return client


@pytest.fixture(autouse=True)
def wired(monkeypatch, owui):
    """Replace both network seams. Nothing in this file touches a socket."""
    tasks = AsyncMock()
    tasks.gateway_resolve.return_value = {
        "linked": True, "email": "user@example.com",
        "owui_user_id": "owui-1", "owui_token": "tok-for-user-1"}
    tasks.gateway_get_session.return_value = None

    seen_tokens = []

    def factory(token: str):
        seen_tokens.append(token)
        return owui

    monkeypatch.setattr(pipeline, "_tasks", tasks)
    monkeypatch.setattr(pipeline, "_owui_factory", factory)
    return MagicMock(tasks=tasks, owui=owui, tokens=seen_tokens)


def _event(text="hello", chat_type="dm", message_type=MessageType.TEXT):
    return MessageEvent(
        text=text, message_type=message_type,
        source=SessionSource(platform="telegram", chat_id="42",
                             chat_type=chat_type, user_id="111",
                             user_name="Ralph"))


async def test_a_group_message_is_refused_without_calling_anything(adapter, wired):
    out = await pipeline.handle_event(_event(chat_type="group"), adapter)

    assert out == pipeline.GROUP_REFUSAL
    wired.tasks.gateway_resolve.assert_not_called()
    adapter.send_chunked.assert_awaited_once_with("42", pipeline.GROUP_REFUSAL)


async def test_an_unpaired_user_gets_a_code_and_no_model_call(adapter, wired):
    wired.tasks.gateway_resolve.return_value = {
        "linked": False, "code": "ABCD2345", "expires_at": "2026-08-10T12:00:00Z"}

    out = await pipeline.handle_event(_event(), adapter)

    assert "ABCD2345" in out
    assert "/tasks/gateway/link" in out
    wired.owui.chat_completion.assert_not_called()


async def test_the_model_is_called_with_this_users_token(adapter, wired):
    await pipeline.handle_event(_event(), adapter)
    assert wired.tokens == ["tok-for-user-1"]


async def test_the_answer_is_sent_back_chunked(adapter, wired):
    out = await pipeline.handle_event(_event(), adapter)

    assert out == "the answer"
    adapter.send_chunked.assert_awaited_once_with("42", "the answer")
    adapter.send_typing.assert_awaited_once_with("42")
    adapter.stop_typing.assert_awaited_once_with("42")


async def test_the_user_message_is_appended_to_the_completion_call(adapter, wired):
    wired.owui.get_chat.return_value = {
        "title": "t",
        "messages": [{"role": "user", "content": "earlier"},
                     {"role": "assistant", "content": "earlier answer"}],
        "history": {"messages": {}, "currentId": None}}
    wired.tasks.gateway_get_session.return_value = "chat-1"

    await pipeline.handle_event(_event("what about now"), adapter)

    messages = wired.owui.chat_completion.await_args.args[0]
    assert messages[-1] == {"role": "user", "content": "what about now"}
    assert messages[0]["content"] == "earlier"


async def test_the_turn_is_written_back_to_the_open_webui_chat(adapter, wired):
    await pipeline.handle_event(_event(), adapter)

    wired.owui.update_chat.assert_awaited_once()
    _, chat = wired.owui.update_chat.await_args.args
    assert [m["role"] for m in chat["messages"]] == ["user", "assistant"]


async def test_a_failed_transcript_write_still_delivers_the_answer(adapter, wired,
                                                                   caplog):
    wired.owui.update_chat.side_effect = OWUIError(500, "nope")

    out = await pipeline.handle_event(_event(), adapter)

    assert out == "the answer"
    adapter.send_chunked.assert_awaited_once_with("42", "the answer")
    assert "transcript" in caplog.text.lower()


async def test_tasks_being_down_produces_a_sentence_not_silence(adapter, wired):
    wired.tasks.gateway_resolve.side_effect = TasksAPIError(0, "unreachable")

    out = await pipeline.handle_event(_event(), adapter)

    assert out == pipeline.TASKS_DOWN
    adapter.send_chunked.assert_awaited_once_with("42", pipeline.TASKS_DOWN)


async def test_a_model_failure_produces_a_sentence(adapter, wired):
    wired.owui.chat_completion.side_effect = OWUIError(503, "unavailable")

    out = await pipeline.handle_event(_event(), adapter)

    assert out == pipeline.MODEL_DOWN


async def test_an_unexpected_error_still_answers_the_waiting_person(adapter, wired):
    wired.owui.chat_completion.side_effect = RuntimeError("something odd")

    out = await pipeline.handle_event(_event(), adapter)

    assert out == pipeline.UNEXPECTED
    adapter.stop_typing.assert_awaited_once_with("42")


async def test_an_unhandled_message_type_says_so(adapter, wired):
    out = await pipeline.handle_event(
        _event(text="", message_type=MessageType.PHOTO), adapter)
    assert out == pipeline.UNSUPPORTED_TYPE


async def test_an_empty_text_message_is_ignored_quietly(adapter, wired):
    out = await pipeline.handle_event(_event(text="   "), adapter)
    assert out == ""
    adapter.send_chunked.assert_not_called()


def test_no_copy_constant_uses_a_dash_character():
    for name in ("GROUP_REFUSAL", "TASKS_DOWN", "MODEL_DOWN", "UNEXPECTED",
                 "UNSUPPORTED_TYPE"):
        value = getattr(pipeline, name)
        assert "—" not in value and "–" not in value, name
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/test_gateway_pipeline.py -q
```

Expected: `ModuleNotFoundError: No module named 'gateway.pipeline'`.

- [ ] **Step 3: Write the implementation**

Create `webhook-handler/gateway/pipeline.py`:

```python
"""MessageEvent in, reply sent. The only flow, shared by every platform.

The governing rule here is the opposite of the rest of this codebase. Build
post-processing fails open because nobody is watching. Here somebody is staring
at a chat window waiting, so NOTHING may fail silently: every path ends in a
sentence the person can read.
"""
import logging

from clients.tasks import TasksAPIError
from config import settings
from gateway.base import BasePlatformAdapter
from gateway.events import MessageEvent, MessageType
from gateway.owui import OWUIError, OWUIUserClient
from gateway.pairing import pairing_message
from gateway.sessions import append_turn, get_or_create_chat, history_messages

log = logging.getLogger(__name__)

GROUP_REFUSAL = (
    "I only work in direct messages for now. Message me privately and I'll "
    "answer there."
)
TASKS_DOWN = "I can't reach my memory right now. Try again in a moment."
MODEL_DOWN = "The model didn't answer just now. Try again in a moment."
UNEXPECTED = "Something went wrong on my side. Try again in a moment."
UNSUPPORTED_TYPE = "I can only read text and voice messages right now."

#: Seams. main.py sets _tasks at startup; tests replace both.
_tasks = None


def _owui_factory(token: str) -> OWUIUserClient:
    return OWUIUserClient(settings.openwebui_url, token)


def configure(tasks_client) -> None:
    """Hand the pipeline its tasks client. Called once, from the app lifespan."""
    global _tasks
    _tasks = tasks_client


def link_url() -> str:
    return f"{settings.gateway_public_url.rstrip('/')}/tasks/gateway/link"


async def handle_event(event: MessageEvent, adapter: BasePlatformAdapter) -> str:
    """Run one inbound message end to end and return what was sent.

    Returning the text as well as sending it lets a synchronous caller (the CLI)
    answer inline without a second delivery mechanism.
    """
    src = event.source

    # Refused before anything else runs. The Brain is injected into every model
    # call, so answering in a group would print one person's private memory to
    # the whole room, with no warning and no way to know in advance.
    if src.chat_type != "dm":
        return await _say(adapter, src.chat_id, GROUP_REFUSAL)

    try:
        identity = await _tasks.gateway_resolve(
            src.platform, src.user_id or src.chat_id, src.user_name or "")
    except TasksAPIError as e:
        log.warning("gateway: resolve failed (%s): %s", e.status, e.message)
        return await _say(adapter, src.chat_id, TASKS_DOWN)

    if not identity.get("linked"):
        # Never log the code.
        return await _say(adapter, src.chat_id,
                          pairing_message(identity["code"], link_url()))

    owui = _owui_factory(identity["owui_token"])

    text = await _resolve_text(event, owui, adapter)
    if text is None:
        return await _say(adapter, src.chat_id, UNSUPPORTED_TYPE)
    if not text.strip():
        # A sticker, an empty edit, a stray keystroke. Answering would be noise.
        return ""

    await adapter.send_typing(src.chat_id)
    try:
        chat_id, chat = await get_or_create_chat(
            _tasks, owui, src.platform, src.chat_id,
            identity["owui_user_id"], text, settings.gateway_model)

        messages = history_messages(chat, settings.gateway_history_turns)
        messages.append({"role": "user", "content": text})
        answer = await owui.chat_completion(
            messages, settings.gateway_model, chat_id=chat_id)

        # Persist before delivering, but never let a persist failure swallow a
        # good answer: the person is waiting and the answer already exists.
        try:
            await owui.update_chat(
                chat_id, append_turn(chat, text, answer, settings.gateway_model))
        except Exception:                              # noqa: BLE001
            log.exception("gateway: could not write the transcript to chat %s; "
                          "delivering the answer anyway", chat_id)

        return await _say(adapter, src.chat_id, answer)

    except TasksAPIError as e:
        log.warning("gateway: tasks failed mid-flow (%s): %s", e.status, e.message)
        return await _say(adapter, src.chat_id, TASKS_DOWN)
    except OWUIError as e:
        log.warning("gateway: open-webui failed (%s): %s", e.status, e.message)
        return await _say(adapter, src.chat_id, MODEL_DOWN)
    except Exception:                                  # noqa: BLE001
        log.exception("gateway: unexpected failure handling a %s message",
                      src.platform)
        return await _say(adapter, src.chat_id, UNEXPECTED)
    finally:
        await adapter.stop_typing(src.chat_id)


async def _resolve_text(event: MessageEvent, owui: OWUIUserClient,
                        adapter: BasePlatformAdapter) -> str | None:
    """The text to send the model, or None for a type we do not handle.

    Voice is filled in by the transcription task; everything except TEXT falls
    through to None until then.
    """
    if event.message_type is MessageType.TEXT:
        return event.text
    return None


async def _say(adapter: BasePlatformAdapter, chat_id: str, text: str) -> str:
    await adapter.send_chunked(chat_id, text)
    return text
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
python -m pytest tests/test_gateway_pipeline.py -q
```

Expected: `13 passed`.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/gateway/pipeline.py webhook-handler/tests/test_gateway_pipeline.py
git commit -m "feat(gateway): the shared message pipeline, with no silent failures"
```

---

### Task 12: The Telegram adapter and its webhook route

**Files:**
- Create: `webhook-handler/gateway/platforms/__init__.py`
- Create: `webhook-handler/gateway/platforms/telegram.py`
- Modify: `webhook-handler/config.py` (two settings)
- Modify: `webhook-handler/main.py` (registry wiring, lifespan, one route)
- Test: `webhook-handler/tests/test_gateway_telegram.py`
- Test: `webhook-handler/tests/test_gateway_telegram_route.py`

**Interfaces:**
- Consumes: Tasks 6, 7, 11.
- Produces: `TelegramAdapter` implementing the full contract, the module constant `TELEGRAM_MAX_MESSAGE = 4096`, and `POST /webhook/telegram` on the app. New settings: `telegram_bot_token` (alias `TELEGRAM_BOT_TOKEN`), `telegram_webhook_secret` (alias `TELEGRAM_WEBHOOK_SECRET`).

Caddy already routes `/webhook/*` to this service, so the public URL exists the moment this deploys. Do not add a route under `/gateway/`: Caddy sends that to the api-gateway on port 8085.

- [ ] **Step 1: Write the failing adapter test**

Create `webhook-handler/tests/test_gateway_telegram.py`:

```python
"""Parsing real Telegram update payloads.

parse_inbound must be pure and synchronous: no network, no disk. A voice memo
carries a file_id that has to be exchanged for a download URL, so the reference
travels on the event and the fetch happens later, in the pipeline.
"""
import httpx
import pytest
import respx

from gateway.events import MessageType
from gateway.platforms.telegram import TELEGRAM_MAX_MESSAGE, TelegramAdapter

API = "https://api.telegram.org/botTEST-TOKEN"


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TEST-TOKEN")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "hook-secret")
    a = TelegramAdapter(token="TEST-TOKEN", webhook_secret="hook-secret")
    a.max_message_length = TELEGRAM_MAX_MESSAGE
    a.name = "telegram"
    return a


def _dm(**over) -> dict:
    message = {
        "message_id": 5,
        "from": {"id": 111, "first_name": "Ralph", "username": "ralph"},
        "chat": {"id": 111, "type": "private"},
        "date": 1754870000,
        "text": "hello",
    }
    message.update(over)
    return {"update_id": 900, "message": message}


def test_a_direct_text_message_parses(adapter):
    event = adapter.parse_inbound(_dm(), {})
    assert event.text == "hello"
    assert event.message_type is MessageType.TEXT
    assert event.source.platform == "telegram"
    assert event.source.chat_id == "111"
    assert event.source.user_id == "111"
    assert event.source.chat_type == "dm"
    assert event.source.user_name == "Ralph"
    assert event.message_id == "5"


def test_a_group_message_keeps_its_real_chat_type(adapter):
    # The pipeline refuses on this value, so it must not be normalized to "dm".
    payload = _dm(chat={"id": -100, "type": "supergroup"})
    assert adapter.parse_inbound(payload, {}).source.chat_type == "supergroup"


def test_a_voice_memo_carries_a_file_id_a_duration_and_no_text(adapter):
    payload = _dm(text=None, voice={"file_id": "AwACAgQ", "duration": 7,
                                    "mime_type": "audio/ogg", "file_size": 8000})
    event = adapter.parse_inbound(payload, {})
    assert event.message_type is MessageType.VOICE
    assert event.media_ref == "AwACAgQ"
    assert event.media_duration == 7
    assert event.text == ""


def test_a_voice_memo_without_a_duration_does_not_invent_one(adapter):
    payload = _dm(text=None, voice={"file_id": "AwACAgQ"})
    assert adapter.parse_inbound(payload, {}).media_duration is None


def test_a_photo_is_typed_but_not_fetched(adapter):
    payload = _dm(text=None, photo=[{"file_id": "small"}, {"file_id": "large"}],
                  caption="look")
    event = adapter.parse_inbound(payload, {})
    assert event.message_type is MessageType.PHOTO
    assert event.media_ref == "large"          # Telegram sends sizes ascending
    assert event.text == "look"


@pytest.mark.parametrize("payload", [
    {"update_id": 1},                                       # nothing we handle
    {"update_id": 1, "edited_message": {"text": "x"}},      # an edit
    {"update_id": 1, "callback_query": {"id": "q"}},        # a button press
    {"update_id": 1, "channel_post": {"text": "x"}},        # a channel
])
def test_updates_we_do_not_handle_parse_to_none(adapter, payload):
    assert adapter.parse_inbound(payload, {}) is None


def test_a_malformed_payload_parses_to_none_rather_than_raising(adapter):
    assert adapter.parse_inbound({"message": "not a dict"}, {}) is None


def test_the_webhook_secret_is_checked(adapter):
    assert adapter.verify_webhook({}, {"x-telegram-bot-api-secret-token": "hook-secret"})
    assert not adapter.verify_webhook({}, {"x-telegram-bot-api-secret-token": "wrong"})
    assert not adapter.verify_webhook({}, {})


def test_header_matching_is_case_insensitive(adapter):
    assert adapter.verify_webhook({}, {"X-Telegram-Bot-Api-Secret-Token": "hook-secret"})


@respx.mock
async def test_send_posts_to_send_message(adapter):
    import json
    route = respx.post(f"{API}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True}))

    await adapter.send("111", "hi")

    body = json.loads(route.calls[0].request.content)
    assert body["chat_id"] == "111"
    assert body["text"] == "hi"


@respx.mock
async def test_a_send_failure_is_logged_and_not_raised(adapter, caplog):
    respx.post(f"{API}/sendMessage").mock(
        return_value=httpx.Response(400, json={"ok": False,
                                               "description": "chat not found"}))
    await adapter.send("111", "hi")          # must not raise
    assert "chat not found" in caplog.text


@respx.mock
async def test_connect_registers_the_webhook_with_its_secret(adapter):
    import json
    route = respx.post(f"{API}/setWebhook").mock(
        return_value=httpx.Response(200, json={"ok": True}))

    assert await adapter.connect() is True

    body = json.loads(route.calls[0].request.content)
    assert body["url"].endswith("/webhook/telegram")
    assert body["secret_token"] == "hook-secret"
    assert "message" in body["allowed_updates"]


@respx.mock
async def test_connect_returns_false_instead_of_raising(adapter):
    # One misconfigured platform must not stop the service from starting.
    respx.post(f"{API}/setWebhook").mock(side_effect=httpx.ConnectError("down"))
    assert await adapter.connect() is False


@respx.mock
async def test_disconnect_deletes_the_webhook(adapter):
    route = respx.post(f"{API}/deleteWebhook").mock(
        return_value=httpx.Response(200, json={"ok": True}))
    await adapter.disconnect()
    assert route.called
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/test_gateway_telegram.py -q
```

Expected: `ModuleNotFoundError: No module named 'gateway.platforms'`.

- [ ] **Step 3: Write the adapter**

Create `webhook-handler/gateway/platforms/__init__.py` as an empty file, then `webhook-handler/gateway/platforms/telegram.py`:

```python
"""Telegram, over webhooks rather than long polling.

Long polling would need a permanently running task holding an open connection.
Caddy already routes /webhook/* to this service, so a webhook costs nothing and
survives a restart.
"""
import logging
import os
import tempfile

import httpx

from config import settings
from gateway.base import BasePlatformAdapter
from gateway.events import MessageEvent, MessageType, SessionSource

log = logging.getLogger(__name__)

TELEGRAM_MAX_MESSAGE = 4096
SECRET_HEADER = "x-telegram-bot-api-secret-token"

# The second half of the clip guard. The duration cap lives in the pipeline,
# because it can be applied before anything is downloaded; this one cannot,
# since getFile is what tells us the size.
MAX_VOICE_BYTES = 10 * 1024 * 1024


class TelegramAdapter(BasePlatformAdapter):
    def __init__(self, token: str = "", webhook_secret: str = "",
                 public_url: str = ""):
        self._token = token or settings.telegram_bot_token
        self._secret = webhook_secret or settings.telegram_webhook_secret
        self._public_url = (public_url or settings.gateway_public_url).rstrip("/")

    @property
    def _api(self) -> str:
        return f"https://api.telegram.org/bot{self._token}"

    async def _call(self, method: str, **payload) -> dict:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(f"{self._api}/{method}", json=payload)
        if resp.status_code >= 400:
            raise httpx.HTTPStatusError(resp.text, request=resp.request,
                                        response=resp)
        return resp.json()

    # --- contract ------------------------------------------------------------

    async def connect(self) -> bool:
        """Point Telegram at our webhook.

        Returns False rather than raising: one unreachable platform must not
        stop the service from starting.
        """
        try:
            await self._call(
                "setWebhook",
                url=f"{self._public_url}/webhook/telegram",
                secret_token=self._secret,
                allowed_updates=["message"],
                drop_pending_updates=True,
            )
        except Exception as e:                          # noqa: BLE001
            log.error("gateway: could not register the Telegram webhook: %r", e)
            return False
        log.info("gateway: Telegram webhook registered")
        return True

    async def disconnect(self) -> None:
        try:
            await self._call("deleteWebhook")
        except Exception as e:                          # noqa: BLE001
            log.warning("gateway: could not remove the Telegram webhook: %r", e)

    def verify_webhook(self, payload: dict, headers: dict) -> bool:
        """Telegram echoes the secret we set in setWebhook on every delivery."""
        got = {k.lower(): v for k, v in (headers or {}).items()}.get(SECRET_HEADER)
        return bool(self._secret) and got == self._secret

    def parse_inbound(self, payload: dict, headers: dict) -> MessageEvent | None:
        """One Telegram update to a MessageEvent, or None if we do not handle it.

        Only `message` is handled. Edits, button presses and channel posts parse
        to None, which is how they get ignored without a branch downstream.
        """
        message = (payload or {}).get("message")
        if not isinstance(message, dict):
            return None
        chat = message.get("chat")
        sender = message.get("from") or {}
        if not isinstance(chat, dict) or not chat.get("id"):
            return None

        raw_type = chat.get("type") or ""
        source = SessionSource(
            platform="telegram",
            chat_id=str(chat["id"]),
            # "private" is the only thing that becomes "dm". Everything else
            # keeps its real name so the pipeline refuses it.
            chat_type="dm" if raw_type == "private" else (raw_type or "unknown"),
            user_id=str(sender.get("id") or chat["id"]),
            user_name=sender.get("first_name") or sender.get("username") or "",
        )
        common = {"source": source, "message_id": str(message.get("message_id") or "")}

        voice = message.get("voice") or message.get("audio")
        if isinstance(voice, dict) and voice.get("file_id"):
            duration = voice.get("duration")
            return MessageEvent(
                text="", message_type=MessageType.VOICE,
                media_ref=voice["file_id"],
                media_duration=duration if isinstance(duration, int) else None,
                **common)

        photo = message.get("photo")
        if isinstance(photo, list) and photo:
            # Telegram sends sizes smallest first; the last is the largest.
            return MessageEvent(text=message.get("caption") or "",
                                message_type=MessageType.PHOTO,
                                media_ref=(photo[-1] or {}).get("file_id"),
                                **common)

        document = message.get("document")
        if isinstance(document, dict) and document.get("file_id"):
            return MessageEvent(text=message.get("caption") or "",
                                message_type=MessageType.DOCUMENT,
                                media_ref=document["file_id"], **common)

        return MessageEvent(text=message.get("text") or "",
                            message_type=MessageType.TEXT, **common)

    async def send(self, chat_id: str, text: str) -> None:
        """Deliver one chunk. Never raises: the caller is already replying."""
        try:
            await self._call("sendMessage", chat_id=chat_id, text=text,
                             disable_web_page_preview=True)
        except Exception as e:                          # noqa: BLE001
            log.error("gateway: Telegram sendMessage failed: %r", e)

    async def send_typing(self, chat_id: str) -> None:
        try:
            await self._call("sendChatAction", chat_id=chat_id, action="typing")
        except Exception:                               # noqa: BLE001
            pass        # Cosmetic. Never let it cost a reply.

    async def download_media(self, ref: str) -> str:
        """Exchange a file_id for bytes on disk. Caller deletes the path.

        Saved as .ogg, never Telegram's native .oga: Open WebUI checks the
        extension against a list that contains "ogg" and not "oga", so the
        wrong suffix is rejected before the audio is ever looked at.
        """
        info = await self._call("getFile", file_id=ref)
        result = (info or {}).get("result") or {}
        file_path = result.get("file_path")
        if not file_path:
            raise RuntimeError("Telegram getFile returned no path")
        size = result.get("file_size") or 0
        if size > MAX_VOICE_BYTES:
            raise ValueError("file too large")

        url = f"https://api.telegram.org/file/bot{self._token}/{file_path}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.content

        fd, path = tempfile.mkstemp(suffix=".ogg", prefix="gateway-voice-")
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        return path
```

- [ ] **Step 4: Add the settings**

In `webhook-handler/config.py`, beside the Slack and Discord blocks:

```python
    # Telegram (multi-platform gateway). Both unset by default, which keeps the
    # platform dormant: the registry refuses to enable it and the route 503s.
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_webhook_secret: str = Field(default="", alias="TELEGRAM_WEBHOOK_SECRET")
```

- [ ] **Step 5: Run the adapter test to verify it passes**

```bash
python -m pytest tests/test_gateway_telegram.py -q
```

Expected: `17 passed`.

- [ ] **Step 6: Write the failing route test**

Create `webhook-handler/tests/test_gateway_telegram_route.py`:

```python
"""The inbound route.

Telegram re-delivers any update that does not get a fast 200, so returning 200
before doing the work is correctness, not an optimization. A slow model call
would otherwise have the same message processed several times.
"""
import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import main
from gateway.events import MessageEvent, MessageType, SessionSource

GOOD = {"x-telegram-bot-api-secret-token": "hook-secret"}


def _update(update_id: int = 900) -> dict:
    return {"update_id": update_id, "message": {
        "message_id": 5,
        "from": {"id": 111, "first_name": "Ralph"},
        "chat": {"id": 111, "type": "private"},
        "date": 1754870000, "text": "hello"}}


@pytest.fixture
def adapter():
    a = AsyncMock()
    a.name = "telegram"
    a.max_message_length = 4096
    a.verify_webhook.return_value = True
    a.parse_inbound.return_value = MessageEvent(
        text="hello", message_type=MessageType.TEXT,
        source=SessionSource(platform="telegram", chat_id="111",
                             user_id="111", chat_type="dm"))
    return a


@pytest.fixture
def client(monkeypatch, adapter):
    monkeypatch.setattr(main.gateway_registry, "adapter",
                        lambda name: adapter if name == "telegram" else None)
    monkeypatch.setattr(main, "_gateway_seen_updates", set())
    return TestClient(main.app)


def test_a_valid_update_is_accepted_immediately(client, adapter, monkeypatch):
    handled = asyncio.Event()

    async def fake_handle(event, adapter_):
        handled.set()
        return "ok"

    monkeypatch.setattr(main.gateway_pipeline, "handle_event", fake_handle)

    resp = client.post("/webhook/telegram", json=_update(), headers=GOOD)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_a_bad_secret_is_200_and_ignored(client, adapter, monkeypatch):
    # A non-200 would make Telegram retry this forever.
    adapter.verify_webhook.return_value = False
    called = []
    monkeypatch.setattr(main.gateway_pipeline, "handle_event",
                        AsyncMock(side_effect=lambda *a: called.append(1)))

    resp = client.post("/webhook/telegram", json=_update(),
                       headers={"x-telegram-bot-api-secret-token": "wrong"})

    assert resp.status_code == 200
    assert called == []


def test_a_duplicate_update_id_is_dropped(client, adapter, monkeypatch):
    seen = []

    async def fake_handle(event, adapter_):
        seen.append(1)
        return "ok"

    monkeypatch.setattr(main.gateway_pipeline, "handle_event", fake_handle)

    client.post("/webhook/telegram", json=_update(77), headers=GOOD)
    client.post("/webhook/telegram", json=_update(77), headers=GOOD)

    assert len(seen) == 1


def test_the_route_503s_when_telegram_is_not_configured(monkeypatch):
    monkeypatch.setattr(main.gateway_registry, "adapter", lambda name: None)
    resp = TestClient(main.app).post("/webhook/telegram", json=_update(),
                                     headers=GOOD)
    assert resp.status_code == 503


def test_an_unparseable_update_is_200_and_does_nothing(client, adapter, monkeypatch):
    adapter.parse_inbound.return_value = None
    called = []
    monkeypatch.setattr(main.gateway_pipeline, "handle_event",
                        AsyncMock(side_effect=lambda *a: called.append(1)))

    resp = client.post("/webhook/telegram", json={"update_id": 5}, headers=GOOD)

    assert resp.status_code == 200
    assert called == []
```

- [ ] **Step 7: Wire the route and the registry into main.py**

Add to the imports in `webhook-handler/main.py`:

```python
from gateway import pipeline as gateway_pipeline
from gateway.platforms.telegram import TELEGRAM_MAX_MESSAGE, TelegramAdapter
from gateway.registry import PlatformEntry, registry as gateway_registry
```

Below the global client declarations, register the platforms and the dedupe set:

```python
# --- Multi-platform gateway --------------------------------------------------
# Registered at import time; each entry stays dormant until its required_env is
# present, so this changes nothing visible until a token exists.
gateway_registry.register(PlatformEntry(
    name="telegram",
    label="Telegram",
    adapter_factory=TelegramAdapter,
    required_env=["TELEGRAM_BOT_TOKEN", "TELEGRAM_WEBHOOK_SECRET"],
    max_message_length=TELEGRAM_MAX_MESSAGE,
    emoji="✈️",
))

# Telegram re-delivers an update until it sees a 200, and we answer before the
# work is done, so the same update_id can arrive several times. Bounded: this
# is a dedupe window, not a log.
_gateway_seen_updates: set[int] = set()
_GATEWAY_SEEN_MAX = 2000
```

In the `lifespan` startup block, after the tasks client is created, add:

```python
    # Hand the gateway its tasks client, then register every enabled webhook.
    gateway_pipeline.configure(tasks_client)
    for entry in gateway_registry.enabled():
        adapter = gateway_registry.adapter(entry.name)
        if adapter and not await adapter.connect():
            logger.error("gateway: %s did not connect; its route will 503",
                         entry.name)
```

Use whatever the existing local variable for the `TasksClient` is called in `lifespan`; do not construct a second one.

Then add the route, next to the other `/webhook/*` routes:

```python
@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """Inbound Telegram updates.

    Returns 200 before the work happens. Telegram re-delivers anything that does
    not get a fast 200, so a slow model call would otherwise cause the same
    message to be answered several times. Every failure path is also a 200 for
    the same reason: a 4xx or 5xx would make Telegram retry it forever.
    """
    adapter = gateway_registry.adapter("telegram")
    if adapter is None:
        raise HTTPException(status_code=503, detail="Telegram is not configured")

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(content={"ok": True}, status_code=200)

    headers = dict(request.headers)
    if not adapter.verify_webhook(payload, headers):
        logger.warning("gateway: rejected a Telegram update with a bad secret")
        return JSONResponse(content={"ok": True}, status_code=200)

    update_id = payload.get("update_id")
    if isinstance(update_id, int):
        if update_id in _gateway_seen_updates:
            return JSONResponse(content={"ok": True}, status_code=200)
        if len(_gateway_seen_updates) >= _GATEWAY_SEEN_MAX:
            _gateway_seen_updates.clear()
        _gateway_seen_updates.add(update_id)

    event = adapter.parse_inbound(payload, headers)
    if event is None:
        return JSONResponse(content={"ok": True}, status_code=200)

    _spawn_gateway(gateway_pipeline.handle_event(event, adapter))
    return JSONResponse(content={"ok": True}, status_code=200)
```

And the task holder, using the same shape as `DiscordCommandHandler._spawn`, which exists because roughly 21 fire-and-forget `create_task` calls were being garbage collected mid-flight and swallowing their exceptions:

```python
_gateway_tasks: set = set()


def _spawn_gateway(coro) -> "asyncio.Task":
    """Run background work with a strong reference and a logged exception.

    An unreferenced task can be collected mid-flight (CPython docs) and a raise
    inside one is swallowed unless somebody retrieves it. Both have bitten this
    service before.
    """
    task = asyncio.create_task(coro)
    _gateway_tasks.add(task)

    def _done(t: "asyncio.Task") -> None:
        _gateway_tasks.discard(t)
        if not t.cancelled() and t.exception() is not None:
            logger.error("gateway: background handler failed: %r", t.exception(),
                         exc_info=t.exception())

    task.add_done_callback(_done)
    return task
```

- [ ] **Step 8: Run the route test to verify it passes**

```bash
python -m pytest tests/test_gateway_telegram_route.py -q
```

Expected: `5 passed`.

- [ ] **Step 9: Confirm the rest of the service still works**

```bash
python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: no new failures compared with before this task.

- [ ] **Step 10: Commit**

```bash
git add webhook-handler/gateway/platforms/ webhook-handler/config.py webhook-handler/main.py webhook-handler/tests/test_gateway_telegram.py webhook-handler/tests/test_gateway_telegram_route.py
git commit -m "feat(gateway): Telegram adapter and webhook route, dormant without a token"
```

---

### Task 13: Voice memos

Transcription goes through Open WebUI's own `/api/v1/audio/transcriptions`
rather than calling faster-whisper directly, so the model, the cache and the
engine setting stay in one place. Verified on the box: `faster-whisper-base` is
already cached in the open-webui container, `chat.stt` defaults to `True` for
non-admins, and the default content-type allowlist resolves to `audio/*`. So
this adds no dependency and no new memory.

**Files:**
- Modify: `webhook-handler/gateway/pipeline.py` (complete `_resolve_text`, add copy)
- Test: `webhook-handler/tests/test_gateway_voice.py`

**Interfaces:**
- Consumes: `adapter.download_media` (Task 12), `owui.transcribe` (Task 9).
- Produces: new copy constants `TRANSCRIBE_FAILED`, `CLIP_TOO_LONG`, the limit `MAX_VOICE_SECONDS = 120`, and the wrapper `voice_prompt(transcript: str) -> str`.

- [ ] **Step 1: Write the failing test**

Create `webhook-handler/tests/test_gateway_voice.py`:

```python
"""Voice memos.

A dropped voice memo is the worst failure this feature can have: the sender has
no idea whether it arrived, and re-recording is more effort than retyping. So
every voice path ends in a sentence, and the temp file is always removed.
"""
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway import pipeline
from gateway.events import MessageEvent, MessageType, SessionSource
from gateway.owui import OWUIError


@pytest.fixture
def adapter(tmp_path):
    a = AsyncMock()
    a.name = "telegram"
    a.max_message_length = 4096
    clip = tmp_path / "memo.ogg"
    clip.write_bytes(b"opus")
    a.download_media.return_value = str(clip)
    a.clip_path = str(clip)
    return a


@pytest.fixture
def owui():
    client = AsyncMock()
    client.get_chat.return_value = {"title": "t", "messages": [],
                                    "history": {"messages": {}, "currentId": None}}
    client.create_chat.return_value = "chat-1"
    client.chat_completion.return_value = "the answer"
    client.transcribe.return_value = "buy milk on the way home"
    return client


@pytest.fixture(autouse=True)
def wired(monkeypatch, owui):
    tasks = AsyncMock()
    tasks.gateway_resolve.return_value = {
        "linked": True, "email": "user@example.com",
        "owui_user_id": "owui-1", "owui_token": "tok"}
    tasks.gateway_get_session.return_value = None
    monkeypatch.setattr(pipeline, "_tasks", tasks)
    monkeypatch.setattr(pipeline, "_owui_factory", lambda token: owui)
    return MagicMock(tasks=tasks, owui=owui)


def _voice(ref="AwACAgQ", duration=7):
    return MessageEvent(
        text="", message_type=MessageType.VOICE, media_ref=ref,
        media_duration=duration,
        source=SessionSource(platform="telegram", chat_id="42",
                             user_id="111", chat_type="dm"))


async def test_the_transcript_reaches_the_model_marked_as_speech(adapter, wired):
    await pipeline.handle_event(_voice(), adapter)

    messages = wired.owui.chat_completion.await_args.args[0]
    sent = messages[-1]["content"]
    assert "buy milk on the way home" in sent
    assert "voice message" in sent.lower()


async def test_the_temp_file_is_deleted_after_a_successful_turn(adapter, wired):
    await pipeline.handle_event(_voice(), adapter)
    assert not os.path.exists(adapter.clip_path)


async def test_the_temp_file_is_deleted_when_transcription_fails(adapter, wired):
    wired.owui.transcribe.side_effect = OWUIError(500, "whisper died")

    out = await pipeline.handle_event(_voice(), adapter)

    assert out == pipeline.TRANSCRIBE_FAILED
    assert not os.path.exists(adapter.clip_path)


async def test_a_failed_transcription_never_passes_silently(adapter, wired):
    wired.owui.transcribe.side_effect = OWUIError(500, "whisper died")
    await pipeline.handle_event(_voice(), adapter)
    wired.owui.chat_completion.assert_not_called()


async def test_a_long_clip_is_refused_before_it_is_downloaded(adapter, wired):
    out = await pipeline.handle_event(
        _voice(duration=pipeline.MAX_VOICE_SECONDS + 1), adapter)

    assert out == pipeline.CLIP_TOO_LONG
    assert "2 minute" in out
    adapter.download_media.assert_not_called()


async def test_a_clip_exactly_at_the_limit_is_accepted(adapter, wired):
    await pipeline.handle_event(
        _voice(duration=pipeline.MAX_VOICE_SECONDS), adapter)
    adapter.download_media.assert_awaited_once()


async def test_an_oversized_file_states_the_limit_too(adapter, wired):
    # The adapter's byte guard, which only fires once getFile reports a size.
    adapter.download_media.side_effect = ValueError("file too large")

    out = await pipeline.handle_event(_voice(), adapter)

    assert out == pipeline.CLIP_TOO_LONG


async def test_a_download_failure_says_so(adapter, wired):
    adapter.download_media.side_effect = RuntimeError("getFile returned no path")
    out = await pipeline.handle_event(_voice(), adapter)
    assert out == pipeline.TRANSCRIBE_FAILED


async def test_an_empty_transcript_is_reported_not_sent_as_blank(adapter, wired):
    wired.owui.transcribe.return_value = "   "
    out = await pipeline.handle_event(_voice(), adapter)
    assert out == pipeline.TRANSCRIBE_FAILED


async def test_a_voice_event_with_no_media_reference_is_reported(adapter, wired):
    out = await pipeline.handle_event(_voice(ref=None), adapter)
    assert out == pipeline.TRANSCRIBE_FAILED
    adapter.download_media.assert_not_called()


def test_the_voice_wrapper_reads_as_speech():
    wrapped = pipeline.voice_prompt("hello there")
    assert "hello there" in wrapped
    assert "—" not in wrapped and "–" not in wrapped


def test_the_voice_copy_uses_no_dash_characters():
    for name in ("TRANSCRIBE_FAILED", "CLIP_TOO_LONG"):
        value = getattr(pipeline, name)
        assert "—" not in value and "–" not in value, name
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/test_gateway_voice.py -q
```

Expected: `AttributeError: module 'gateway.pipeline' has no attribute 'TRANSCRIBE_FAILED'`.

- [ ] **Step 3: Add the copy and the wrapper**

In `webhook-handler/gateway/pipeline.py`, add beside the other copy constants:

```python
TRANSCRIBE_FAILED = (
    "I couldn't make out that voice message. Could you send it again or type it?"
)
CLIP_TOO_LONG = (
    "That voice message is too long for me. I can handle up to 2 minutes."
)

# Whisper on this box is CPU only, so a long clip would hold a worker for
# minutes while the sender stares at nothing. Keep this in step with the
# sentence in CLIP_TOO_LONG.
MAX_VOICE_SECONDS = 120
```

and beside the other helpers:

```python
def voice_prompt(transcript: str) -> str:
    """Mark a transcript as speech so the model answers like it was spoken.

    Without this the model reads a transcription artifact as if it were typed,
    and hedges about the odd punctuation instead of just answering.
    """
    return f'[The user sent a voice message. Here is what they said: "{transcript}"]'
```

- [ ] **Step 4: Fill in the voice branch**

Replace `_resolve_text` in `webhook-handler/gateway/pipeline.py` with:

```python
async def _resolve_text(event: MessageEvent, owui: OWUIUserClient,
                        adapter: BasePlatformAdapter) -> str | None:
    """The text to send the model, or None for a type we do not handle.

    Returns the sentinel _FAILED when the type IS handled but this particular
    message could not be turned into text. That distinction matters: an
    unhandled type and a broken voice memo need different sentences.
    """
    if event.message_type is MessageType.TEXT:
        return event.text
    if event.message_type is MessageType.VOICE:
        return await _transcribe_voice(event, owui, adapter)
    return None


async def _transcribe_voice(event: MessageEvent, owui: OWUIUserClient,
                            adapter: BasePlatformAdapter) -> str:
    """Download the clip, transcribe it, and always remove the temp file."""
    if not event.media_ref:
        log.warning("gateway: a voice event arrived with no media reference")
        return _FAILED

    # Refused before the download, not after. The duration arrives in the
    # inbound payload, so a ten minute clip costs us nothing to reject; waiting
    # for the byte count would mean fetching the whole thing first.
    if event.media_duration and event.media_duration > MAX_VOICE_SECONDS:
        return _TOO_LONG

    # Transcription is the slow part of a voice turn, so the indicator goes up
    # here rather than after it.
    await adapter.send_typing(event.source.chat_id)

    path = None
    try:
        path = await adapter.download_media(event.media_ref)
        transcript = await owui.transcribe(path)
    except ValueError:
        # The adapter's own size guard. A distinct sentence, because "too long"
        # is something the sender can act on and "it broke" is not.
        return _TOO_LONG
    except Exception as e:                              # noqa: BLE001
        log.warning("gateway: transcription failed: %r", e)
        return _FAILED
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                log.warning("gateway: could not remove the temp clip %s", path)

    if not transcript.strip():
        return _FAILED
    return voice_prompt(transcript)
```

Add `import os` at the top of the module, and the two sentinels beside the copy constants:

```python
# Distinguishable from any real message text, so a person cannot type them.
_FAILED = "\x00gateway-transcribe-failed"
_TOO_LONG = "\x00gateway-clip-too-long"
```

Then, in `handle_event`, replace the block that follows `text = await _resolve_text(...)` with:

```python
    text = await _resolve_text(event, owui, adapter)
    if text is None:
        return await _say(adapter, src.chat_id, UNSUPPORTED_TYPE)
    if text == _FAILED:
        return await _say(adapter, src.chat_id, TRANSCRIBE_FAILED)
    if text == _TOO_LONG:
        return await _say(adapter, src.chat_id, CLIP_TOO_LONG)
    if not text.strip():
        return ""
```

Also change `UNSUPPORTED_TYPE` now that voice works:

```python
UNSUPPORTED_TYPE = (
    "I can read text and voice messages. I can't do anything with that one yet."
)
```

- [ ] **Step 5: Run both pipeline suites to verify they pass**

```bash
python -m pytest tests/test_gateway_voice.py tests/test_gateway_pipeline.py -q
```

Expected: `25 passed`. The earlier pipeline tests still pass because the TEXT branch is unchanged.

- [ ] **Step 6: Commit**

```bash
git add webhook-handler/gateway/pipeline.py webhook-handler/tests/test_gateway_voice.py
git commit -m "feat(gateway): transcribe voice memos through Open WebUI"
```

---

### Task 14: /resume

Continuity is not automatic and should not be. hermes-agent puts the platform
name directly in its session key for the same reason: silently merging a
conversation from one surface into another would move context a person did not
ask to move. So it is a command.

**Files:**
- Create: `webhook-handler/gateway/commands.py`
- Modify: `webhook-handler/gateway/pipeline.py` (dispatch commands before the model)
- Test: `webhook-handler/tests/test_gateway_commands.py`

**Interfaces:**
- Consumes: `tasks.gateway_recent_sessions`, `tasks.gateway_put_session` (Task 8).
- Produces: `gateway.commands.is_command(text) -> bool`, `gateway.commands.handle(text, tasks, source, owui_user_id) -> str | None` returning the reply for a command or `None` when the text is not one.

- [ ] **Step 1: Write the failing test**

Create `webhook-handler/tests/test_gateway_commands.py`:

```python
"""Slash commands, which are the only way continuity crosses a surface.

/resume repoints this conversation at another chat. It never merges anything
and never moves context on its own.
"""
from unittest.mock import AsyncMock

import pytest

from gateway import commands
from gateway.events import SessionSource

SOURCE = SessionSource(platform="telegram", chat_id="42", user_id="111")


@pytest.fixture
def tasks():
    client = AsyncMock()
    client.gateway_recent_sessions.return_value = [
        {"platform": "telegram", "chat_id": "42", "owui_chat_id": "chat-a",
         "updated_at": "2026-08-10T10:00:00+00:00"},
        {"platform": "cli", "chat_id": "dev-box", "owui_chat_id": "chat-b",
         "updated_at": "2026-08-09T09:00:00+00:00"},
    ]
    return client


@pytest.mark.parametrize("text,expected", [
    ("/resume", True), ("/RESUME", True), ("  /resume 2 ", True),
    ("/help", True), ("/start", True),
    ("resume", False), ("what is /resume", False), ("", False),
])
def test_command_detection(text, expected):
    assert commands.is_command(text) is expected


async def test_resume_with_no_argument_lists_the_options(tasks):
    out = await commands.handle("/resume", tasks, SOURCE, "u1")

    assert "1" in out and "2" in out
    assert "cli" in out.lower()
    tasks.gateway_put_session.assert_not_called()


async def test_resume_with_a_number_repoints_the_session(tasks):
    out = await commands.handle("/resume 2", tasks, SOURCE, "u1")

    tasks.gateway_put_session.assert_awaited_once_with(
        "telegram", "42", "chat-b", "u1")
    assert "picked up" in out.lower() or "resumed" in out.lower()


async def test_an_out_of_range_pick_is_refused_without_a_write(tasks):
    out = await commands.handle("/resume 9", tasks, SOURCE, "u1")

    tasks.gateway_put_session.assert_not_called()
    assert "1" in out and "2" in out


async def test_a_non_numeric_argument_is_refused_without_a_write(tasks):
    out = await commands.handle("/resume banana", tasks, SOURCE, "u1")
    tasks.gateway_put_session.assert_not_called()
    assert out


async def test_resume_with_no_history_says_so(tasks):
    tasks.gateway_recent_sessions.return_value = []
    out = await commands.handle("/resume", tasks, SOURCE, "u1")
    assert "nothing" in out.lower() or "no " in out.lower()
    tasks.gateway_put_session.assert_not_called()


async def test_help_lists_what_exists(tasks):
    out = await commands.handle("/help", tasks, SOURCE, "u1")
    assert "/resume" in out


async def test_start_is_a_welcome_not_an_error(tasks):
    out = await commands.handle("/start", tasks, SOURCE, "u1")
    assert out and "/resume" in out


async def test_an_unknown_command_points_at_help(tasks):
    out = await commands.handle("/nonsense", tasks, SOURCE, "u1")
    assert "/help" in out


async def test_plain_text_is_not_a_command(tasks):
    assert await commands.handle("hello there", tasks, SOURCE, "u1") is None


async def test_no_command_reply_uses_a_dash_character(tasks):
    for text in ("/help", "/start", "/resume", "/resume 9", "/nonsense"):
        out = await commands.handle(text, tasks, SOURCE, "u1")
        assert "—" not in out and "–" not in out, text
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/test_gateway_commands.py -q
```

Expected: `ModuleNotFoundError: No module named 'gateway.commands'`.

- [ ] **Step 3: Write the implementation**

Create `webhook-handler/gateway/commands.py`:

```python
"""The few slash commands the gateway understands.

Kept deliberately small. Everything a person actually wants to do is a sentence
to the model; commands exist only for things the model cannot do to itself,
which right now is exactly one thing: point this conversation at a different
transcript.
"""
import logging

from gateway.events import SessionSource

log = logging.getLogger(__name__)

KNOWN = ("/resume", "/help", "/start")


def is_command(text: str) -> bool:
    return (text or "").strip().startswith("/")


async def handle(text: str, tasks, source: SessionSource,
                 owui_user_id: str) -> str | None:
    """Run a command and return its reply, or None if `text` is not a command."""
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return None

    parts = raw.split()
    verb = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if verb in ("/help", "/start"):
        return _help()
    if verb == "/resume":
        return await _resume(tasks, source, owui_user_id, arg)
    return f"I don't know {verb}. Try /help."


def _help() -> str:
    return (
        "Just talk to me and I'll answer with your own IO account: your memory, "
        "your tools, your models.\n\n"
        "/resume  see your recent conversations and pick one up here\n"
        "/help    this message"
    )


async def _resume(tasks, source: SessionSource, owui_user_id: str,
                  arg: str) -> str:
    sessions = await tasks.gateway_recent_sessions(owui_user_id, limit=10)
    if not sessions:
        return "You have nothing to resume yet. Send me a message and we'll start one."

    if not arg:
        return _listing(sessions)

    if not arg.isdigit():
        return f"Pick a number.\n\n{_listing(sessions)}"
    pick = int(arg)
    if not 1 <= pick <= len(sessions):
        return f"There's no {pick}.\n\n{_listing(sessions)}"

    chosen = sessions[pick - 1]
    await tasks.gateway_put_session(
        source.platform, source.chat_id, chosen["owui_chat_id"], owui_user_id)
    return (
        f"Picked up your {chosen['platform']} conversation. "
        "Carry on from where you left off."
    )


def _listing(sessions: list[dict]) -> str:
    lines = ["Your recent conversations. Reply /resume <number> to continue one:"]
    for i, s in enumerate(sessions, start=1):
        when = (s.get("updated_at") or "")[:10]
        lines.append(f"{i}. {s.get('platform', 'unknown')}  {when}")
    return "\n".join(lines)
```

- [ ] **Step 4: Dispatch commands from the pipeline**

In `webhook-handler/gateway/pipeline.py`, add the import:

```python
from gateway import commands as gateway_commands
```

and insert this immediately after the empty-text guard in `handle_event`, before `send_typing`:

```python
    # Commands run before the model, so /resume works even when the model is
    # down. A command never reaches Open WebUI and never appears in the chat.
    if gateway_commands.is_command(text):
        try:
            reply = await gateway_commands.handle(
                text, _tasks, src, identity["owui_user_id"])
        except TasksAPIError as e:
            log.warning("gateway: command failed (%s): %s", e.status, e.message)
            return await _say(adapter, src.chat_id, TASKS_DOWN)
        if reply is not None:
            return await _say(adapter, src.chat_id, reply)
```

- [ ] **Step 5: Add the pipeline test for command dispatch**

Append to `webhook-handler/tests/test_gateway_pipeline.py`:

```python
async def test_a_command_is_answered_without_calling_the_model(adapter, wired):
    wired.tasks.gateway_recent_sessions.return_value = []

    out = await pipeline.handle_event(_event("/resume"), adapter)

    assert "resume" in out.lower()
    wired.owui.chat_completion.assert_not_called()
    wired.owui.create_chat.assert_not_called()


async def test_a_command_still_works_when_the_model_is_down(adapter, wired):
    wired.owui.chat_completion.side_effect = OWUIError(503, "unavailable")
    wired.tasks.gateway_recent_sessions.return_value = []

    out = await pipeline.handle_event(_event("/help"), adapter)

    assert "/resume" in out
```

- [ ] **Step 6: Run both suites to verify they pass**

```bash
python -m pytest tests/test_gateway_commands.py tests/test_gateway_pipeline.py -q
```

Expected: `33 passed`.

- [ ] **Step 7: Commit**

```bash
git add webhook-handler/gateway/commands.py webhook-handler/gateway/pipeline.py webhook-handler/tests/test_gateway_commands.py webhook-handler/tests/test_gateway_pipeline.py
git commit -m "feat(gateway): /resume, /help and command dispatch ahead of the model"
```

---

### Task 15: The CLI

The second platform, and the real test of whether the adapter surface is small
enough. If this file is long, the abstraction failed.

The CLI is request and response rather than push, so `handle_event`'s return
value is the reply and `send()` is a genuine no-op. That is also why the return
value exists: a buffer on the adapter would be shared across concurrent
requests, because the registry caches one adapter per platform.

**Files:**
- Create: `webhook-handler/gateway/platforms/cli.py`
- Modify: `webhook-handler/main.py` (register the platform, add one route)
- Create: `scripts/io.py`
- Test: `webhook-handler/tests/test_gateway_cli.py`

**Interfaces:**
- Consumes: Tasks 6, 7, 11, 14.
- Produces: `CliAdapter`, `DEVICE_ID_PATTERN`, and `POST /webhook/gateway/cli` returning `{"reply": "..."}`.

**Security note.** This route is reachable from the internet through Caddy's
`/webhook/*` rule and carries no signature, so the device id **is** the
credential: 32 hex characters of `secrets.token_hex(16)`, sent in a header,
never in a URL, never logged. An unrecognized device gets a pairing code and
nothing else. The strict format check exists so that garbage cannot mint
unbounded pairing rows.

- [ ] **Step 1: Write the failing test**

Create `webhook-handler/tests/test_gateway_cli.py`:

```python
"""The CLI adapter and its route.

The device id is the only credential on this path, so the format check and the
"unknown device gets a code, nothing else" behaviour are both load-bearing.
"""
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import main
from gateway.events import MessageType
from gateway.platforms.cli import CliAdapter

DEVICE = "a" * 32


@pytest.fixture
def adapter():
    a = CliAdapter()
    a.name = "cli"
    a.max_message_length = 0
    return a


def test_a_valid_body_parses_to_a_dm_event(adapter):
    event = adapter.parse_inbound(
        {"device_id": DEVICE, "device_name": "dev-box", "text": "hello"}, {})

    assert event.text == "hello"
    assert event.message_type is MessageType.TEXT
    assert event.source.platform == "cli"
    assert event.source.chat_id == DEVICE
    assert event.source.user_id == DEVICE
    assert event.source.chat_type == "dm"
    assert event.source.user_name == "dev-box"


@pytest.mark.parametrize("device_id", [
    "", "short", "z" * 32, "A" * 31, "a" * 33, None, 12345,
])
def test_a_malformed_device_id_parses_to_none(adapter, device_id):
    assert adapter.parse_inbound({"device_id": device_id, "text": "hi"}, {}) is None


def test_a_missing_text_parses_to_none(adapter):
    assert adapter.parse_inbound({"device_id": DEVICE}, {}) is None


async def test_send_is_a_no_op(adapter):
    # The route returns the reply, so send must do nothing and say nothing.
    assert await adapter.send(DEVICE, "anything") is None


async def test_connect_needs_nothing(adapter):
    assert await adapter.connect() is True
    assert await adapter.disconnect() is None


@pytest.fixture
def client(monkeypatch, adapter):
    monkeypatch.setattr(main.gateway_registry, "adapter",
                        lambda name: adapter if name == "cli" else None)
    return TestClient(main.app)


def test_the_route_returns_the_reply_inline(client, monkeypatch):
    async def fake_handle(event, adapter_):
        return f"you said: {event.text}"

    monkeypatch.setattr(main.gateway_pipeline, "handle_event", fake_handle)

    resp = client.post("/webhook/gateway/cli",
                       json={"device_id": DEVICE, "device_name": "dev-box",
                             "text": "hello"})

    assert resp.status_code == 200
    assert resp.json() == {"reply": "you said: hello"}


def test_a_bad_device_id_is_400_and_never_reaches_the_pipeline(client, monkeypatch):
    called = []
    monkeypatch.setattr(main.gateway_pipeline, "handle_event",
                        AsyncMock(side_effect=lambda *a: called.append(1)))

    resp = client.post("/webhook/gateway/cli",
                       json={"device_id": "nope", "text": "hello"})

    assert resp.status_code == 400
    assert called == []


def test_the_route_is_synchronous_unlike_telegram(client, monkeypatch):
    # No 200-then-work here: there is no re-delivery to defend against and the
    # caller is blocked on the answer.
    async def fake_handle(event, adapter_):
        return "done"

    monkeypatch.setattr(main.gateway_pipeline, "handle_event", fake_handle)
    assert client.post("/webhook/gateway/cli",
                       json={"device_id": DEVICE, "text": "x"}).json()["reply"] == "done"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/test_gateway_cli.py -q
```

Expected: `ModuleNotFoundError: No module named 'gateway.platforms.cli'`.

- [ ] **Step 3: Write the adapter**

Create `webhook-handler/gateway/platforms/cli.py`:

```python
"""A terminal, over plain HTTP.

Request and response rather than push, so send() is a real no-op and the route
returns handle_event's value. A buffer on the adapter would be wrong: the
registry caches one adapter per platform, so two concurrent requests would read
each other's replies.

Second platform, and the point of the exercise: if this file were long, the
adapter surface would be the wrong shape.
"""
import logging
import re

from gateway.base import BasePlatformAdapter
from gateway.events import MessageEvent, MessageType, SessionSource

log = logging.getLogger(__name__)

#: secrets.token_hex(16). The device id IS the credential on this path, so the
#: format is checked strictly: garbage must not be able to mint pairing rows.
DEVICE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class CliAdapter(BasePlatformAdapter):
    async def connect(self) -> bool:
        return True         # Nothing to register. The route is always there.

    async def disconnect(self) -> None:
        return None

    def parse_inbound(self, payload: dict, headers: dict) -> MessageEvent | None:
        device_id = (payload or {}).get("device_id")
        if not isinstance(device_id, str) or not DEVICE_ID_PATTERN.match(device_id):
            return None
        text = (payload or {}).get("text")
        if not isinstance(text, str) or not text.strip():
            return None

        name = (payload or {}).get("device_name")
        return MessageEvent(
            text=text,
            message_type=MessageType.TEXT,
            source=SessionSource(
                platform="cli",
                # One conversation per device. A second terminal is a second
                # conversation, and /resume is how you join them.
                chat_id=device_id,
                chat_type="dm",
                user_id=device_id,
                user_name=name if isinstance(name, str) else "",
            ),
        )

    async def send(self, chat_id: str, text: str) -> None:
        """No-op. The route returns the reply in its response body."""
        return None
```

- [ ] **Step 4: Register the platform and add the route**

In `webhook-handler/main.py`, beside the Telegram registration:

```python
from gateway.platforms.cli import CliAdapter
```

```python
gateway_registry.register(PlatformEntry(
    name="cli",
    label="Terminal",
    adapter_factory=CliAdapter,
    required_env=[],        # nothing to configure, so it is always enabled
    max_message_length=0,   # a terminal has no message cap
    emoji="⌨️",
))
```

and the route, beside the Telegram one:

```python
@app.post("/webhook/gateway/cli")
async def gateway_cli(request: Request):
    """The terminal client. Synchronous: the caller is blocked on the answer.

    Unlike Telegram there is no re-delivery to defend against, so there is no
    reason to answer before the work is done.
    """
    adapter = gateway_registry.adapter("cli")
    if adapter is None:
        raise HTTPException(status_code=503, detail="CLI gateway is not available")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    event = adapter.parse_inbound(payload, dict(request.headers))
    if event is None:
        raise HTTPException(status_code=400,
                            detail="A 32 character hex device_id and a non-empty "
                                   "text are both required")

    reply = await gateway_pipeline.handle_event(event, adapter)
    return JSONResponse(content={"reply": reply}, status_code=200)
```

- [ ] **Step 5: Write the client script**

Create `scripts/io.py`:

```python
#!/usr/bin/env python3
"""Talk to IO from a terminal.

    python scripts/io.py                 interactive
    python scripts/io.py "what's on today"    one shot
    echo "summarise this" | python scripts/io.py

Standard library only, so it runs anywhere Python does with nothing installed.

First run writes a random device id to ~/.io/device. That file IS your
credential: anyone holding it can talk to IO as you. It is created 0600. Delete
it to unpair, then pair again from the link page.
"""
import argparse
import json
import os
import pathlib
import secrets
import sys
import urllib.error
import urllib.request

DEFAULT_URL = os.environ.get("IO_URL", "https://ai-ui.coolestdomain.win")
DEVICE_FILE = pathlib.Path(os.environ.get("IO_HOME", pathlib.Path.home() / ".io")) / "device"


def device_id() -> str:
    """Read the device id, creating one on first run."""
    if DEVICE_FILE.exists():
        existing = DEVICE_FILE.read_text(encoding="utf-8").strip()
        if len(existing) == 32:
            return existing
    DEVICE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fresh = secrets.token_hex(16)
    # 0600 before anything is written, not after: a credential must never exist
    # world-readable, not even for one syscall.
    fd = os.open(DEVICE_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(fresh)
    return fresh


def ask(base_url: str, text: str) -> str:
    body = json.dumps({
        "device_id": device_id(),
        "device_name": os.environ.get("HOSTNAME") or pathlib.Path.home().name,
        "text": text,
    }).encode()
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/webhook/gateway/cli",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as resp:
            return json.loads(resp.read()).get("reply", "")
    except urllib.error.HTTPError as e:
        return f"[{e.code}] {e.read().decode(errors='replace')[:400]}"
    except urllib.error.URLError as e:
        return f"Could not reach {base_url}: {e.reason}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Talk to IO from a terminal.")
    parser.add_argument("message", nargs="*", help="send one message and exit")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"default {DEFAULT_URL}")
    args = parser.parse_args()

    if args.message:
        print(ask(args.url, " ".join(args.message)))
        return 0
    if not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            print(ask(args.url, piped))
        return 0

    print("Talking to IO. Ctrl-C to stop, /help for commands.")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in ("exit", "quit"):
            return 0
        print(ask(args.url, line))
        print()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
python -m pytest tests/test_gateway_cli.py -q
```

Expected: `14 passed`.

- [ ] **Step 7: Check the script parses and its help works**

From the repo root:

```bash
python scripts/io.py --help
```

Expected: the argparse usage block, no traceback.

- [ ] **Step 8: Run the whole webhook-handler suite**

```bash
cd webhook-handler && python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: no new failures compared with before this feature started.

- [ ] **Step 9: Commit**

```bash
git add webhook-handler/gateway/platforms/cli.py webhook-handler/main.py webhook-handler/tests/test_gateway_cli.py scripts/io.py
git commit -m "feat(gateway): CLI platform and a dependency-free terminal client"
```

---

### Task 16: Deploy, enable, and run the acceptance check

Everything so far is dormant. This task turns it on and proves it works with a
real account, which is the only check that can catch the failure the whole
design was built to prevent.

**Files:**
- Modify: `docs/superpowers/specs/2026-08-07-multi-platform-gateway-design.md` (correct the obsolete deploy note)
- Create: `docs/runbooks/multi-platform-gateway.md`

- [ ] **Step 1: Create the Telegram bot**

This is Ralph's step, in the Telegram app, and it produces the token the rest of
the task needs.

1. Message `@BotFather`, send `/newbot`, pick a display name and a username ending in `bot`.
2. Copy the token it returns. It looks like `1234567890:AA...`.
3. Send `/setprivacy` and choose **Enable**. Phase 1 refuses groups anyway, so the bot has no reason to see group messages.

Generate the webhook secret locally:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

- [ ] **Step 2: Add the three env vars on the server**

Appended by hand, never rewritten and never committed: this file holds the only copy of the production secrets.

```bash
ssh root@46.224.193.25 "cp /root/proxy-server/.env /root/proxy-server/.env.bak-$(date +%Y%m%d)"
```

Then append these three lines to `/root/proxy-server/.env`:

```
TELEGRAM_BOT_TOKEN=<from BotFather>
TELEGRAM_WEBHOOK_SECRET=<from step 1>
WEBUI_SECRET_KEY=<the value already used by open-webui>
```

`WEBUI_SECRET_KEY` almost certainly already exists in that file for the
open-webui service. Read it rather than inventing one, because a different value
would mint tokens Open WebUI rejects:

```bash
ssh root@46.224.193.25 "grep -c '^WEBUI_SECRET_KEY=' /root/proxy-server/.env"
```

If that prints `1`, the variable is already there and you only need to make sure
the `tasks` service receives it. In `docker-compose.unified.yml`, under the
`tasks` service `environment:` block, add:

```yaml
      - WEBUI_SECRET_KEY=${WEBUI_SECRET_KEY}
```

and under `webhook-handler`:

```yaml
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - TELEGRAM_WEBHOOK_SECRET=${TELEGRAM_WEBHOOK_SECRET}
      - GATEWAY_MODEL=${GATEWAY_MODEL:-auto_router.auto}
```

- [ ] **Step 3: Deploy the tasks service**

The orchestrator covers `mcp-servers/`, so it handles the tasks half:

```bash
ORCH_HOST=46.224.193.25 ./scripts/deploy_orchestrator.sh
```

If `rsync` is missing (Git Bash on Windows does not ship it), fall back to one
`scp` per changed file, rebuild `tasks`, and update `.deploy-state` by hand.
That file is JSON (`{"sha": ..., "deployed_at": ..., "deployed_by": ...}`) and
the script parses `['sha']`; a bare SHA breaks the next deploy.

Verify:

```bash
curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz
ssh root@46.224.193.25 "docker exec tasks sh -lc 'python -c \"import routes_gateway, owui_token, gateway_pairing; print(\\\"ok\\\")\"'"
ssh root@46.224.193.25 "docker exec -e PGPASSWORD=\$POSTGRES_PASSWORD postgres sh -lc 'psql -U \$POSTGRES_USER -d openwebui -t -c \"\\dt tasks.gateway_*\"'"
```

Expected: the health check returns, the import prints `ok`, and all three
`gateway_*` tables are listed. The tables appear because `db.py` ran the new
migration at startup.

- [ ] **Step 4: Deploy webhook-handler**

The orchestrator does **not** cover `webhook-handler/`. One `scp` per changed
file; never `scp -r`, which silently skips files.

```bash
ssh root@46.224.193.25 "mkdir -p /root/proxy-server/webhook-handler/gateway/platforms"
for f in gateway/__init__.py gateway/events.py gateway/base.py gateway/registry.py \
         gateway/owui.py gateway/pairing.py gateway/sessions.py gateway/pipeline.py \
         gateway/commands.py gateway/platforms/__init__.py \
         gateway/platforms/telegram.py gateway/platforms/cli.py \
         clients/tasks.py config.py main.py; do
  scp "webhook-handler/$f" "root@46.224.193.25:/root/proxy-server/webhook-handler/$f"
done
ssh root@46.224.193.25 "cd /root/proxy-server && find webhook-handler/gateway -name '*.py' -exec sed -i 's/\r\$//' {} + && sed -i 's/\r\$//' webhook-handler/main.py webhook-handler/config.py webhook-handler/clients/tasks.py"
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build webhook-handler"
```

The `sed` is not optional. This repo checks out CRLF on Windows, and a trailing
`\r` inside a Python string constant is invisible in a diff and produces a
webhook secret that never matches.

Verify:

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml ps webhook-handler"
ssh root@46.224.193.25 "docker logs --tail 40 webhook-handler | grep -i gateway"
```

Expected: `Up`, and a log line reading `gateway: Telegram webhook registered`.
If it says the webhook could not be registered, the token is wrong or the
container cannot reach `api.telegram.org`; check both before touching anything else.

- [ ] **Step 5: Confirm Telegram agrees**

```bash
ssh root@46.224.193.25 'TOKEN=$(docker exec webhook-handler printenv TELEGRAM_BOT_TOKEN); curl -s "https://api.telegram.org/bot$TOKEN/getWebhookInfo"'
```

Expected: `"url":"https://ai-ui.coolestdomain.win/webhook/telegram"`,
`"pending_update_count":0`, and no `last_error_message`. A
`last_error_message` of `Wrong response from the webhook: 503` means the
registry did not enable the platform, so one of the two env vars is missing
inside the container.

- [ ] **Step 6: Run the acceptance check with a real non-admin account**

This is the check the spec calls the empirical one. No unit test can replace it.

1. From a Telegram account, message the bot. Expect the pairing reply with a code.
2. Open `https://ai-ui.coolestdomain.win/tasks/gateway/link` signed in as a **non-admin** IO user. Paste the code. Expect "Connected".
3. Message the bot again with something only that user's Brain would know, for example "what am I working on".
4. **Check whose Brain answered**, which is the whole point:

```bash
ssh root@46.224.193.25 "docker logs --tail 200 tasks | grep -i 'graph/mine\|/context'"
```

   Expected: the context fetch carries **that non-admin user's email**. If it
   shows an admin address, stop and report: the design's central hop is wrong
   and every user is getting the admin's memory.

5. Send a real voice memo. Expect an answer that clearly responds to what was
   said, not a generic one.
6. Open Open WebUI in a browser as that same user. The Telegram conversation
   should be in the sidebar with both turns rendered, not an empty chat.
7. From a terminal:

```bash
python scripts/io.py "hello from my terminal"
```

   Expect a pairing code the first time. Pair it, then run it again and expect a
   real answer. Then send `/resume` and confirm the Telegram conversation is
   listed and can be picked up.

- [ ] **Step 7: Correct the spec**

The spec's final deployment bullet is now known to be wrong. In
`docs/superpowers/specs/2026-08-07-multi-platform-gateway-design.md`, replace:

```
- Telegram's webhook is registered by `connect()` at startup, so the public URL must
  exist in Caddy before first boot.
```

with:

```
- Telegram's webhook is registered by `connect()` at startup. No Caddy change is
  needed: `/etc/caddy/Caddyfile` already routes `/webhook/*` to port 8086, so
  the public URL exists as soon as the code deploys. Do not put any part of this
  under a bare `/gateway/` path, which Caddy sends to the api-gateway instead.
```

- [ ] **Step 8: Write the runbook**

Create `docs/runbooks/multi-platform-gateway.md` covering, in this order: what
the feature is and which platforms are live; the three env vars and which
service each belongs to; how to rotate the Telegram token (BotFather `/revoke`,
update `.env`, recreate webhook-handler, confirm with `getWebhookInfo`); how to
turn the whole thing off (remove `TELEGRAM_BOT_TOKEN`, recreate the container,
the route returns 503 and nothing else changes); how to unpair a user
(`DELETE FROM tasks.gateway_links WHERE email = ...`); and the three symptoms
worth naming, which are a `getWebhookInfo` `last_error_message`, a 503 from the
route meaning the env is missing inside the container, and answers that look
like somebody else's memory, meaning `WEBUI_SECRET_KEY` differs between the
tasks and open-webui containers.

- [ ] **Step 9: Commit**

```bash
git add docs/superpowers/specs/2026-08-07-multi-platform-gateway-design.md docs/runbooks/multi-platform-gateway.md docker-compose.unified.yml
git commit -m "docs(gateway): runbook, corrected deploy note, compose env wiring"
```

---

## Verified versus assumed

Carried forward from the spec and updated with what this plan checked on 2026-08-10.

| Claim | State | Evidence |
|---|---|---|
| A minted token can act as any user | verified in code, proven in Task 1 step 6 | HS256 over `WEBUI_SECRET_KEY`; `is_valid_token` is a blocklist |
| `/webhook/*` already reaches webhook-handler | verified | `/etc/caddy/Caddyfile:39` |
| `/gateway/*` is already the api-gateway | verified | `/etc/caddy/Caddyfile:32` |
| `X-User-Email` is injected on `/tasks/*` | verified | `api-gateway/main.py:423` and `:532` |
| Non-admins may transcribe | verified | `USER_PERMISSIONS_CHAT_STT` defaults to `True` |
| `audio/ogg` passes the STT allowlist | verified | empty list becomes `['audio/*', 'video/webm']` |
| `.ogg` passes the extension check, `.oga` does not | verified | `AUDIO_STT_ALLOWED_EXTENSIONS` default |
| `auto_router.auto` is a live free model | verified | `function` table: `auto_router`, active; `pipes()` returns `auto` |
| Chats can be created and appended | verified | `POST /chats/new` takes `ChatForm{chat: dict}` |
| The chat JSON shape renders in the sidebar | assumed | key names read from real rows; the render is only proven in Task 16 step 6 |
| Whisper fits under the open-webui memory cap | untested | the 2 minute and 10MB caps are the mitigation |
| Telegram delivery is reliable behind Caddy | untested | no bot exists yet; first real check is Task 16 |

