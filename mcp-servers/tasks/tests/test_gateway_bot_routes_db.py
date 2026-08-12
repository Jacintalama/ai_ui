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
def sent(monkeypatch):
    """Spies on every telegram_api.send_message call so a test can tell which
    chat id a bot actually messaged, without opening a socket."""
    calls: list[tuple[str, str, str]] = []

    async def _record(token, chat_id, text):
        calls.append((token, chat_id, text))

    monkeypatch.setattr(routes_gateway.telegram_api, "send_message", _record)
    return calls


@pytest.fixture
async def clean_bots(db_session):
    """The one place that deletes the GatewayBot rows these tests create,
    matched only on the two email constants above. Never broaden this delete."""
    yield
    await db_session.execute(
        GatewayBot.__table__.delete().where(GatewayBot.email.in_([OWNER, STRANGER])))
    await db_session.commit()


@pytest.fixture
async def owner_bot(app_for, clean_bots):
    client = app_for(OWNER)
    resp = client.post("/tasks/gateway/bots",
                       json={"platform": "telegram",
                             "token": "111:AAHownertokenvalue",
                             "allowed_ids": ""})
    assert resp.status_code == 200
    return resp.json()["bot_key"]


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


async def test_a_webhook_failure_leaves_the_bot_saved_but_disabled(
        db_session, app_for, monkeypatch, clean_bots):
    # A half-live bot silently swallows messages. Better to keep the row and
    # let the page say it is broken.
    async def _boom(*a, **kw):
        raise routes_gateway.telegram_api.TelegramError("Bad webhook URL")
    monkeypatch.setattr(routes_gateway.telegram_api, "set_webhook", _boom)

    client = app_for(OWNER)
    resp = client.post("/tasks/gateway/bots",
                       json={"platform": "telegram",
                             "token": "333:AAHwebhookfails",
                             "allowed_ids": ""})
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert "Bad webhook URL" in body["last_error"]

    listed = client.get("/tasks/gateway/bots").json()["bots"]
    assert len(listed) == 1
    assert listed[0]["enabled"] is False
    assert "Bad webhook URL" in listed[0]["last_error"]


async def test_testing_an_unpaired_bot_checks_the_token_and_sends_nothing(
        owner_bot, app_for, sent):
    resp = app_for(OWNER).post(f"/tasks/gateway/bots/{owner_bot}/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "alive" in body["detail"]
    assert sent == []     # nowhere to send yet, and no arbitrary id invented


async def test_testing_a_paired_bot_messages_the_owners_own_chat(
        db_session, owner_bot, app_for, sent):
    await db_session.execute(
        GatewayBot.__table__.update()
        .where(GatewayBot.bot_key == owner_bot)
        .values(owner_platform_user_id="4242"))
    await db_session.commit()

    resp = app_for(OWNER).post(f"/tasks/gateway/bots/{owner_bot}/test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert [chat for _token, chat, _text in sent] == ["4242"]
