"""Tests for POST /internal/schedule-result — the tasks→webhook-handler
callback that posts a finished scheduled-task result into the user's thread."""
import pytest
from httpx import ASGITransport, AsyncClient


class _FakeDiscord:
    def __init__(self):
        self.posted: list[tuple[str, str]] = []

    async def post_channel_message(self, channel_id, content, components=None):
        self.posted.append((channel_id, content, components))
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
    channel, content, _ = fake.posted[0]
    assert channel == "123"
    # Completed runs deliver output only — the schedule name is NOT echoed.
    assert "morning digest" not in content
    assert "Top 3 emails" in content


@pytest.mark.asyncio
async def test_failed_run_attaches_retry_button(monkeypatch):
    main_mod, fake = _wire(monkeypatch, "s3cret")
    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/internal/schedule-result",
            headers={"X-Internal-Secret": "s3cret"},
            json={"channel_id": "c", "schedule_name": "n", "status": "failed",
                  "result": "boom", "schedule_id": "sid9"},
        )
    assert resp.status_code == 200
    _, _, components = fake.posted[0]
    ids = {b["custom_id"] for row in (components or []) for b in row["components"]}
    assert "aiuisched:run:sid9" in ids


@pytest.mark.asyncio
async def test_completed_run_has_no_retry_button(monkeypatch):
    main_mod, fake = _wire(monkeypatch, "s3cret")
    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/internal/schedule-result",
            headers={"X-Internal-Secret": "s3cret"},
            json={"channel_id": "c", "schedule_name": "n", "status": "completed",
                  "result": "ok", "schedule_id": "sid9"},
        )
    _, _, components = fake.posted[0]
    assert not components


def test_format_schedule_result_truncates_completed_and_labels_skipped():
    import main as main_mod
    # Completed = output only (no name echo), still truncated under the cap.
    long_msg = main_mod._format_schedule_result("digest", "completed", "x" * 5000)
    assert "digest" not in long_msg
    assert len(long_msg) <= 2000
    # Non-completed (skipped/failed) still names the schedule.
    skipped = main_mod._format_schedule_result("d", "skipped", "")
    assert "d" in skipped


class _FakeSlack:
    def __init__(self):
        self.posted: list[dict] = []

    async def post_message(self, channel, text, thread_ts=None, *, blocks=None,
                           attachments=None):
        self.posted.append(
            {"channel": channel, "text": text, "blocks": blocks}
        )
        return "ts1"


def _wire_slack(monkeypatch, secret):
    import main as main_mod
    fake = _FakeSlack()
    monkeypatch.setattr(main_mod.settings, "internal_callback_secret", secret)
    monkeypatch.setattr(main_mod, "slack_client", fake)
    # Prove the Slack branch runs BEFORE the discord_client guard.
    monkeypatch.setattr(main_mod, "discord_client", None)
    return main_mod, fake


@pytest.mark.asyncio
async def test_slack_platform_posts_via_slack_client(monkeypatch):
    main_mod, slack = _wire_slack(monkeypatch, "s3cret")
    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/internal/schedule-result",
            headers={"X-Internal-Secret": "s3cret"},
            json={"platform": "slack", "channel_id": "C123",
                  "schedule_name": "morning digest", "status": "completed",
                  "result": "Top 3 emails: ..."},
        )
    assert resp.status_code == 200
    assert len(slack.posted) == 1
    call = slack.posted[0]
    assert call["channel"] == "C123"
    # Completed runs deliver output only — the schedule name is NOT echoed.
    assert "morning digest" not in call["text"]
    assert "Top 3 emails" in call["text"]
    assert call["blocks"] is None


@pytest.mark.asyncio
async def test_slack_failed_run_attaches_retry_blocks(monkeypatch):
    main_mod, slack = _wire_slack(monkeypatch, "s3cret")
    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/internal/schedule-result",
            headers={"X-Internal-Secret": "s3cret"},
            json={"platform": "slack", "channel_id": "C1", "schedule_name": "n",
                  "status": "failed", "result": "boom", "schedule_id": "sid9"},
        )
    assert resp.status_code == 200
    assert slack.posted[0]["blocks"] is not None


@pytest.mark.asyncio
async def test_default_platform_is_discord(monkeypatch):
    # Platform omitted → Discord path (existing behavior) still used.
    main_mod, fake = _wire(monkeypatch, "s3cret")
    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/internal/schedule-result",
            headers={"X-Internal-Secret": "s3cret"},
            json={"channel_id": "123", "schedule_name": "n",
                  "status": "completed", "result": "ok"},
        )
    assert resp.status_code == 200
    assert len(fake.posted) == 1
    assert fake.posted[0][0] == "123"
