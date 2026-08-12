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


def test_a_broken_bot_config_is_dropped_rather_than_retried_forever(
        client, tasks_says, spawned):
    # A missing key is a bug or a bad row, and it will still be broken on the
    # next attempt. 503 here would make Telegram retry this message forever.
    tasks_says({k: v for k, v in CONFIG.items() if k != "token"})
    resp = client.post("/webhook/telegram/abc", json=UPDATE,
                       headers={"x-telegram-bot-api-secret-token": "s3cret"})
    assert resp.status_code == 200
    assert spawned == []


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
