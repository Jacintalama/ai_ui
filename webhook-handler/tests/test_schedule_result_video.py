"""Tests for POST /internal/schedule-result attaching the finished MP4 on
Discord when the payload names a completed video schedule (Task 8).

Delivery must never get worse than today: any attach failure (download raises,
oversized blob, post_channel_file returns False) falls through to the existing
text post.
"""
import pytest
from httpx import ASGITransport, AsyncClient


class _FakeDiscord:
    def __init__(self, file_ok=True):
        self.posted: list[tuple[str, str, object]] = []
        self.posted_files: list[tuple[str, list, str]] = []
        self._file_ok = file_ok

    async def post_channel_message(self, channel_id, content, components=None):
        self.posted.append((channel_id, content, components))
        return True

    async def post_channel_file(self, channel_id, files, content="", components=None):
        self.posted_files.append((channel_id, files, content))
        return self._file_ok


class _FakeTasksClient:
    def __init__(self, blob=b"", raise_on_download=False):
        self._blob = blob
        self._raise = raise_on_download
        self.calls: list[tuple[str, str]] = []

    async def download_video_bytes(self, user_email, job_id):
        self.calls.append((user_email, job_id))
        if self._raise:
            raise RuntimeError("download failed")
        return self._blob


def _wire(monkeypatch, secret, discord, tasks_client):
    import main as main_mod
    monkeypatch.setattr(main_mod.settings, "internal_callback_secret", secret)
    monkeypatch.setattr(main_mod, "discord_client", discord)
    monkeypatch.setattr(main_mod, "command_router", type(
        "R", (), {"_tasks_client": tasks_client}
    )())
    return main_mod


@pytest.mark.asyncio
async def test_video_schedule_attaches_mp4_on_discord(monkeypatch):
    # Case 1: discord + video_job_id + small blob -> post_channel_file called
    # with ("<schedule_name>.mp4", blob, "video/mp4"), content == formatted
    # message, and post_channel_message NOT called.
    blob = b"fake-mp4-bytes"
    discord = _FakeDiscord(file_ok=True)
    tasks_client = _FakeTasksClient(blob=blob)
    main_mod = _wire(monkeypatch, "s3cret", discord, tasks_client)

    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/internal/schedule-result",
            headers={"X-Internal-Secret": "s3cret"},
            json={
                "channel_id": "123",
                "schedule_name": "morning walkthrough",
                "status": "completed",
                "result": "Your video is ready.",
                "video_job_id": "job-1",
                "video_user_email": "user@example.com",
            },
        )

    assert resp.status_code == 200
    assert tasks_client.calls == [("user@example.com", "job-1")]
    assert len(discord.posted_files) == 1
    channel_id, files, content = discord.posted_files[0]
    assert channel_id == "123"
    assert files == [("morning walkthrough.mp4", blob, "video/mp4")]
    expected_message = main_mod._format_schedule_result(
        "morning walkthrough", "completed", "Your video is ready.", platform="discord"
    )
    assert content == expected_message
    assert discord.posted == []


@pytest.mark.asyncio
async def test_video_schedule_oversized_blob_falls_back_to_text(monkeypatch):
    # Case 2: discord + video_job_id + blob > VIDEO_ATTACH_MAX_MB -> falls
    # through to post_channel_message with the formatted text.
    import main as main_mod
    from handlers.commands import VIDEO_ATTACH_MAX_MB

    oversized_blob = b"x" * (VIDEO_ATTACH_MAX_MB * 1024 * 1024 + 1)
    discord = _FakeDiscord(file_ok=True)
    tasks_client = _FakeTasksClient(blob=oversized_blob)
    main_mod = _wire(monkeypatch, "s3cret", discord, tasks_client)

    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/internal/schedule-result",
            headers={"X-Internal-Secret": "s3cret"},
            json={
                "channel_id": "123",
                "schedule_name": "big walkthrough",
                "status": "completed",
                "result": "Your video is ready.",
                "video_job_id": "job-2",
                "video_user_email": "user@example.com",
            },
        )

    assert resp.status_code == 200
    assert discord.posted_files == []
    assert len(discord.posted) == 1
    channel_id, content, _components = discord.posted[0]
    assert channel_id == "123"
    expected_message = main_mod._format_schedule_result(
        "big walkthrough", "completed", "Your video is ready.", platform="discord"
    )
    assert content == expected_message


@pytest.mark.asyncio
async def test_video_schedule_download_error_falls_back_to_text(monkeypatch):
    # Case 3: download raises -> falls through to post_channel_message
    # (delivered).
    discord = _FakeDiscord(file_ok=True)
    tasks_client = _FakeTasksClient(raise_on_download=True)
    main_mod = _wire(monkeypatch, "s3cret", discord, tasks_client)

    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/internal/schedule-result",
            headers={"X-Internal-Secret": "s3cret"},
            json={
                "channel_id": "123",
                "schedule_name": "broken walkthrough",
                "status": "completed",
                "result": "Your video is ready.",
                "video_job_id": "job-3",
                "video_user_email": "user@example.com",
            },
        )

    assert resp.status_code == 200
    assert discord.posted_files == []
    assert len(discord.posted) == 1
    channel_id, content, _components = discord.posted[0]
    assert channel_id == "123"
    expected_message = main_mod._format_schedule_result(
        "broken walkthrough", "completed", "Your video is ready.", platform="discord"
    )
    assert content == expected_message


@pytest.mark.asyncio
async def test_payload_without_video_fields_is_unchanged(monkeypatch):
    # A payload without video fields behaves byte-identically to before:
    # no download attempted, text post used directly.
    discord = _FakeDiscord(file_ok=True)
    tasks_client = _FakeTasksClient()
    main_mod = _wire(monkeypatch, "s3cret", discord, tasks_client)

    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/internal/schedule-result",
            headers={"X-Internal-Secret": "s3cret"},
            json={
                "channel_id": "123",
                "schedule_name": "n",
                "status": "completed",
                "result": "ok",
            },
        )

    assert resp.status_code == 200
    assert tasks_client.calls == []
    assert discord.posted_files == []
    assert len(discord.posted) == 1
