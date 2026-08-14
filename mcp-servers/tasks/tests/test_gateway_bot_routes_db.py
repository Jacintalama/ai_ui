"""One account must not be able to touch another's bot.

Runs in the container, where there is a real database:
  ssh root@46.224.193.25 "docker exec tasks sh -lc \\
    'cd /app && python -m pytest tests/test_gateway_bot_routes_db.py -q'"

Locally every test here ERRORs at setup with no Postgres, which is expected.
"""
import os

import pytest_asyncio

import pytest
from cryptography.fernet import InvalidToken
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("AIUI_FERNET_KEY",
                      "hUZ3RkVvY0JmS3FnWlp4TXcyN0RkNTZWc1RCQzNKS1E=")
os.environ.setdefault("GATEWAY_PUBLIC_URL", "https://io.example")

import routes_gateway
from auth import CurrentUser, current_user
from models import GatewayBot

OWNER = "owner-byob@example.com"
STRANGER = "stranger-byob@example.com"


@pytest_asyncio.fixture
async def app_for(monkeypatch):
    async def _get_me(token):
        return {"id": 1, "username": "someones_bot"}

    async def _noop(*a, **kw):
        return None

    monkeypatch.setattr(routes_gateway.telegram_api, "get_me", _get_me)
    monkeypatch.setattr(routes_gateway.telegram_api, "set_webhook", _noop)
    monkeypatch.setattr(routes_gateway.telegram_api, "delete_webhook", _noop)

    made = []

    def _build(email):
        app = FastAPI()
        app.include_router(routes_gateway.page_router)
        app.dependency_overrides[current_user] = lambda: CurrentUser(email=email)
        # raise_app_exceptions=False mirrors TestClient's
        # raise_server_exceptions=False: a route that returns 500 is the
        # assertion in one test below, not an error to re-raise here.
        client = AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test")
        made.append(client)
        return client

    yield _build
    for client in made:
        await client.aclose()


@pytest.fixture
def sent(monkeypatch):
    """Spies on every telegram_api.send_message call so a test can tell which
    chat id a bot actually messaged, without opening a socket."""
    calls: list[tuple[str, str, str]] = []

    async def _record(token, chat_id, text):
        calls.append((token, chat_id, text))

    monkeypatch.setattr(routes_gateway.telegram_api, "send_message", _record)
    return calls


@pytest.fixture
async def clean_bots(db_session_nondestructive):
    """The one place that deletes the GatewayBot rows these tests create,
    matched only on the two email constants above. Never broaden this delete."""
    yield
    await db_session_nondestructive.execute(
        GatewayBot.__table__.delete().where(GatewayBot.email.in_([OWNER, STRANGER])))
    await db_session_nondestructive.commit()


@pytest_asyncio.fixture
async def owner_bot(app_for, clean_bots):
    client = app_for(OWNER)
    resp = await client.post("/tasks/gateway/bots",
                       json={"platform": "telegram",
                             "token": "111:AAHownertokenvalue",
                             "allowed_ids": ""})
    assert resp.status_code == 200
    return resp.json()["bot_key"]


async def test_the_owner_sees_their_own_bot(owner_bot, app_for):
    body = (await app_for(OWNER).get("/tasks/gateway/bots")).json()
    assert [b["bot_key"] for b in body["bots"]] == [owner_bot]


async def test_a_stranger_sees_nothing(owner_bot, app_for):
    assert (await app_for(STRANGER).get("/tasks/gateway/bots")).json()["bots"] == []


async def test_a_stranger_cannot_toggle_it(owner_bot, app_for):
    resp = await app_for(STRANGER).patch(f"/tasks/gateway/bots/{owner_bot}",
                                   json={"enabled": False})
    assert resp.status_code == 404


async def test_a_stranger_cannot_test_it(owner_bot, app_for):
    resp = await app_for(STRANGER).post(f"/tasks/gateway/bots/{owner_bot}/test")
    assert resp.status_code == 404


async def test_a_stranger_cannot_delete_it(owner_bot, app_for):
    resp = await app_for(STRANGER).delete(f"/tasks/gateway/bots/{owner_bot}")
    assert resp.status_code == 404


async def test_the_token_never_comes_back_in_a_listing(owner_bot, app_for):
    body = (await app_for(OWNER).get("/tasks/gateway/bots")).json()
    assert "111:AAHownertokenvalue" not in str(body)


async def test_saving_twice_replaces_rather_than_duplicates(owner_bot, app_for):
    client = app_for(OWNER)
    await client.post("/tasks/gateway/bots",
                json={"platform": "telegram", "token": "222:AAHsecondtoken",
                      "allowed_ids": ""})
    assert len((await client.get("/tasks/gateway/bots")).json()["bots"]) == 1


async def test_a_webhook_failure_leaves_the_bot_saved_but_disabled(
        db_session_nondestructive, app_for, monkeypatch, clean_bots):
    # A half-live bot silently swallows messages. Better to keep the row and
    # let the page say it is broken.
    async def _boom(*a, **kw):
        raise routes_gateway.telegram_api.TelegramError("Bad webhook URL")
    monkeypatch.setattr(routes_gateway.telegram_api, "set_webhook", _boom)

    client = app_for(OWNER)
    resp = await client.post("/tasks/gateway/bots",
                       json={"platform": "telegram",
                             "token": "333:AAHwebhookfails",
                             "allowed_ids": ""})
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert "Bad webhook URL" in body["last_error"]

    listed = (await client.get("/tasks/gateway/bots")).json()["bots"]
    assert len(listed) == 1
    assert listed[0]["enabled"] is False
    assert "Bad webhook URL" in listed[0]["last_error"]


async def test_testing_an_unpaired_bot_checks_the_token_and_sends_nothing(
        owner_bot, app_for, sent):
    resp = await app_for(OWNER).post(f"/tasks/gateway/bots/{owner_bot}/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "alive" in body["detail"]
    assert sent == []     # nowhere to send yet, and no arbitrary id invented


async def test_testing_a_paired_bot_messages_the_owners_own_chat(
        db_session_nondestructive, owner_bot, app_for, sent):
    await db_session_nondestructive.execute(
        GatewayBot.__table__.update()
        .where(GatewayBot.bot_key == owner_bot)
        .values(owner_platform_user_id="4242"))
    await db_session_nondestructive.commit()

    resp = await app_for(OWNER).post(f"/tasks/gateway/bots/{owner_bot}/test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert [chat for _token, chat, _text in sent] == ["4242"]


async def test_a_stranger_never_sees_your_bot_on_the_channels_page(owner_bot, app_for):
    # The regression this guards: dropping the email filter on the bots query
    # would stitch one account's bot onto another account's Telegram row.
    rows = (await app_for(STRANGER).get("/tasks/gateway/connections")).json()["connections"]
    assert rows, "the page must still list every channel for a stranger"
    assert all(r["bot"] is None for r in rows)


async def test_your_own_bot_lands_on_your_telegram_row_and_nowhere_else(owner_bot, app_for):
    rows = (await app_for(OWNER).get("/tasks/gateway/connections")).json()["connections"]
    telegram = next(r for r in rows if r["platform"] == "telegram")
    assert telegram["bot"]["bot_key"] == owner_bot
    assert all(r["bot"] is None for r in rows if r["platform"] != "telegram")
    # The page never receives a token, only enough to recognise the bot.
    assert "111:AAHownertokenvalue" not in str(rows)


async def test_removing_a_bot_with_an_undecryptable_token_still_deletes_it(
        db_session_nondestructive, owner_bot, app_for, monkeypatch):
    """A rotated AIUI_FERNET_KEY or a corrupt blob must not trap a user with a
    bot they can no longer get rid of: deleteWebhook is skipped, the row is
    deleted anyway."""
    def _boom(blob):
        raise InvalidToken()
    monkeypatch.setattr(routes_gateway.gbots, "decrypt_token", _boom)

    resp = await app_for(OWNER).delete(f"/tasks/gateway/bots/{owner_bot}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "removed"

    remaining = (await db_session_nondestructive.execute(
        GatewayBot.__table__.select().where(GatewayBot.bot_key == owner_bot)
    )).first()
    assert remaining is None


async def test_toggling_a_bot_with_an_undecryptable_token_fails_cleanly(
        owner_bot, app_for, monkeypatch):
    """A decrypt failure on a route that still needs the token (unlike
    remove) must be a clean, actionable error, not a 500."""
    def _boom(blob):
        raise InvalidToken()
    monkeypatch.setattr(routes_gateway.gbots, "decrypt_token", _boom)

    resp = await app_for(OWNER).patch(f"/tasks/gateway/bots/{owner_bot}",
                                json={"enabled": False})
    assert resp.status_code == 503
    assert "could not be read" in resp.json()["detail"]


async def test_internal_endpoint_returns_500_on_decrypt_failure(
        owner_bot, monkeypatch):
    """A decrypt failure on the internal bot_config endpoint must return 500
    (permanent), not 503 (transient). webhook-handler treats 502/503/504 as
    transient and asks Telegram to redeliver. A decrypt failure will fail
    identically on every retry, so reporting it as transient would create an
    infinite retry loop. 500 signals permanent failure."""
    def _boom(blob):
        raise InvalidToken()
    monkeypatch.setattr(routes_gateway.gbots, "decrypt_token", _boom)
    # The test supplies its own internal secret rather than depending on
    # whatever the environment holds. Without this it authenticates against the
    # real one, gets a 403, and the assertion below reports a decrypt problem
    # that was never reached.
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", "test-internal-secret")

    # Create an internal client (bare router, not page_router)
    app = FastAPI()
    app.include_router(routes_gateway.router)
    internal_client = AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test")

    # Call the internal endpoint with the required header
    resp = await internal_client.get(
        f"/gateway/bots/{owner_bot}",
        headers={"X-Internal-Secret": "test-internal-secret"})

    # Must be 500, not 503
    assert resp.status_code == 500, (
        f"Expected 500 (permanent) but got {resp.status_code}. "
        "Decrypt failure is permanent and must not be retried by webhook-handler.")


async def test_internal_endpoint_returns_500_on_decrypt_failure(
        owner_bot, app_for, monkeypatch):
    """A decrypt failure on the internal bot_config endpoint must return 500
    (permanent), not 503 (transient). webhook-handler treats 502/503/504 as
    transient and asks Telegram to redeliver. A decrypt failure will fail
    identically on every retry, so reporting it as transient would create an
    infinite retry loop. 500 signals permanent failure."""
    from fastapi import Header

    def _boom(blob):
        raise InvalidToken()
    monkeypatch.setattr(routes_gateway.gbots, "decrypt_token", _boom)
    # The test supplies its own internal secret rather than depending on
    # whatever the environment holds. Without this it authenticates against the
    # real one, gets a 403, and the assertion below reports a decrypt problem
    # that was never reached.
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", "test-internal-secret")

    # Create an internal client (bare router, not page_router)
    app = FastAPI()
    app.include_router(routes_gateway.router)
    internal_client = AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test")

    # Call the internal endpoint with the required header
    resp = await internal_client.get(
        f"/gateway/bots/{owner_bot}",
        headers={"X-Internal-Secret": "test-internal-secret"})
    
    # Must be 500, not 503
    assert resp.status_code == 500, (
        f"Expected 500 (permanent) but got {resp.status_code}. "
        "Decrypt failure is permanent and must not be retried by webhook-handler.")
