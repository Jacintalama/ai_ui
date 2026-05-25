"""Tests for POST /internal/schedule-result — the tasks→webhook-handler
callback that posts a finished scheduled-task result into the user's thread."""
import pytest
from httpx import ASGITransport, AsyncClient


class _FakeDiscord:
    def __init__(self):
        self.posted: list[tuple[str, str]] = []

    async def post_channel_message(self, channel_id, content):
        self.posted.append((channel_id, content))
        return True


def _wire(monkeypatch, secret):
    import main as main_mod
    fake = _FakeDiscord()
    monkeypatch.setattr(main_mod.settings, "internal_callback_secret", secret)
    monkeypatch.setattr(main_mod, "discord_client", fake)
    return main_mod, fake


@pytest.mark.asyncio
async def test_rejects_wrong_secret(monkeypatch):
    main_mod, fake = _wire(monkeypatch, "s3cret")
    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/internal/schedule-result",
            headers={"X-Internal-Secret": "wrong"},
            json={"channel_id": "123", "schedule_name": "n",
                  "status": "completed", "result": "hi"},
        )
    assert resp.status_code == 403
    assert fake.posted == []


@pytest.mark.asyncio
async def test_rejects_when_no_secret_configured(monkeypatch):
    # Fail closed: an empty configured secret must never accept callbacks.
    main_mod, fake = _wire(monkeypatch, "")
    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/internal/schedule-result",
            headers={"X-Internal-Secret": ""},
            json={"channel_id": "1", "result": "x"},
        )
    assert resp.status_code == 403
    assert fake.posted == []


@pytest.mark.asyncio
async def test_posts_result_to_channel_on_good_secret(monkeypatch):
    main_mod, fake = _wire(monkeypatch, "s3cret")
    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/internal/schedule-result",
            headers={"X-Internal-Secret": "s3cret"},
            json={"channel_id": "123", "schedule_name": "morning digest",
                  "status": "completed", "result": "Top 3 emails: ..."},
        )
    assert resp.status_code == 200
    assert len(fake.posted) == 1
    channel, content = fake.posted[0]
    assert channel == "123"
    assert "morning digest" in content
    assert "Top 3 emails" in content


def test_format_schedule_result_truncates_and_labels():
    import main as main_mod
    long_msg = main_mod._format_schedule_result("digest", "completed", "x" * 5000)
    assert "digest" in long_msg
    assert len(long_msg) <= 2000
    skipped = main_mod._format_schedule_result("d", "skipped", "")
    assert "d" in skipped
