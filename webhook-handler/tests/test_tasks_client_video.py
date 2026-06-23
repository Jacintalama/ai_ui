"""Tests for TasksClient video generation methods (Task B1).

All tests use fake _request / _internal_request to avoid real HTTP calls.
The fakes capture method/path/json so we can assert exact endpoint paths
and request bodies without a running tasks service.
"""
import pytest

from clients.tasks import TasksClient, TasksAPIError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client() -> TasksClient:
    return TasksClient(base_url="http://tasks-test:8210", internal_secret="test-secret")


def _fake_request_factory(return_json=None, return_content=b"", captures=None):
    """Return an async fake for client._request that records calls."""
    if captures is None:
        captures = {}

    async def fake_request(method, path, email, json=None, **kw):
        captures.update(method=method, path=path, email=email, json=json)

        class _R:
            content = return_content

            def json(self):
                return return_json or {}

        return _R()

    return fake_request, captures


def _fake_internal_request_factory(return_json=None, captures=None):
    if captures is None:
        captures = {}

    async def fake_internal_request(method, path, json=None, **kw):
        captures.update(method=method, path=path, json=json)

        class _R:
            def json(self):
                return return_json or {}

        return _R()

    return fake_internal_request, captures


# ---------------------------------------------------------------------------
# User-scoped video methods
# ---------------------------------------------------------------------------

async def test_create_video_draft_path_and_body():
    client = _make_client()
    fake, caps = _fake_request_factory(return_json={"job_id": "j1"})
    client._request = fake

    result = await client.create_video_draft(
        "user@test.com", title="My Video", prompt="A cool promo",
        style="cinematic", voice="adam",
    )

    assert caps["method"] == "POST"
    assert caps["path"] == "/api/video-jobs/draft"
    assert caps["email"] == "user@test.com"
    assert caps["json"] == {
        "title": "My Video",
        "prompt": "A cool promo",
        "style": "cinematic",
        "voice": "adam",
    }
    assert result == {"job_id": "j1"}


async def test_add_video_screenshots_urls_path_and_body():
    client = _make_client()
    fake, caps = _fake_request_factory(return_json={"ok": True})
    client._request = fake

    urls = ["https://cdn.example.com/a.png", "https://cdn.example.com/b.png"]
    result = await client.add_video_screenshots_urls("user@test.com", "job-abc", urls)

    assert caps["method"] == "POST"
    assert caps["path"] == "/api/video-jobs/job-abc/screenshots-by-url"
    assert caps["json"] == {"urls": urls}
    assert result == {"ok": True}


async def test_queue_video_path():
    client = _make_client()
    fake, caps = _fake_request_factory(return_json={"queued": True})
    client._request = fake

    result = await client.queue_video("user@test.com", "job-xyz")

    assert caps["method"] == "POST"
    assert caps["path"] == "/api/video-jobs/job-xyz/queue"
    assert caps["json"] is None
    assert result == {"queued": True}


async def test_download_video_bytes_returns_content():
    raw = b"\x00\x01\x02\x03FAKEMP4"
    client = _make_client()
    fake, caps = _fake_request_factory(return_content=raw)
    client._request = fake

    data = await client.download_video_bytes("user@test.com", "job-mp4")

    assert caps["method"] == "GET"
    assert caps["path"] == "/api/video-jobs/job-mp4/download"
    assert data == raw


async def test_get_current_video_draft_returns_none_on_404():
    client = _make_client()

    async def fake_404(method, path, email, **kw):
        raise TasksAPIError(404, "not found")

    client._request = fake_404

    result = await client.get_current_video_draft("user@test.com")
    assert result is None


async def test_get_current_video_draft_reraises_non_404():
    client = _make_client()

    async def fake_500(method, path, email, **kw):
        raise TasksAPIError(500, "internal error")

    client._request = fake_500

    with pytest.raises(TasksAPIError) as exc_info:
        await client.get_current_video_draft("user@test.com")
    assert exc_info.value.status == 500


async def test_capture_video_screenshots_posts_url():
    client = _make_client()
    captured = {}

    async def fake_request(method, path, user_email, **kwargs):
        captured.update(method=method, path=path, email=user_email, **kwargs)

        class _R:
            def json(self_inner):
                return {"screenshots": ["screenshot-1.png"], "count": 1}
        return _R()

    client._request = fake_request
    out = await client.capture_video_screenshots("u@x.com", "job1", "https://site.com")
    assert out["count"] == 1
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/video-jobs/job1/capture-from-url"
    assert captured["json"] == {"url": "https://site.com"}
    assert captured["timeout"] == 45.0


async def test_get_current_video_draft_returns_dict_on_success():
    client = _make_client()
    fake, caps = _fake_request_factory(return_json={"job_id": "draft-1", "status": "draft"})
    client._request = fake

    result = await client.get_current_video_draft("user@test.com")

    assert caps["path"] == "/api/video-jobs/current-draft"
    assert result == {"job_id": "draft-1", "status": "draft"}


async def test_set_video_draft_fields_style_only():
    client = _make_client()
    fake, caps = _fake_request_factory(return_json={"updated": True})
    client._request = fake

    result = await client.set_video_draft_fields("u@t.com", "job-1", style="documentary")

    assert caps["method"] == "POST"
    assert caps["path"] == "/api/video-jobs/job-1/draft-set"
    assert caps["json"] == {"style": "documentary"}
    assert result == {"updated": True}


async def test_set_video_draft_fields_voice_only():
    client = _make_client()
    fake, caps = _fake_request_factory(return_json={"updated": True})
    client._request = fake

    await client.set_video_draft_fields("u@t.com", "job-2", voice="bella")

    assert caps["json"] == {"voice": "bella"}


async def test_set_video_draft_fields_both():
    client = _make_client()
    fake, caps = _fake_request_factory(return_json={})
    client._request = fake

    await client.set_video_draft_fields("u@t.com", "job-3", style="cinematic", voice="adam")

    assert caps["json"] == {"style": "cinematic", "voice": "adam"}


async def test_set_video_draft_fields_neither_sends_empty_body():
    client = _make_client()
    fake, caps = _fake_request_factory(return_json={})
    client._request = fake

    await client.set_video_draft_fields("u@t.com", "job-4")

    assert caps["json"] == {}


async def test_get_video_voices_uses_system_email():
    client = _make_client()
    fake, caps = _fake_request_factory(return_json={"voices": []})
    client._request = fake

    result = await client.get_video_voices()

    assert caps["method"] == "GET"
    assert caps["path"] == "/api/video-jobs/voices"
    assert caps["email"] == "system@aiui.local"
    assert result == {"voices": []}


async def test_get_video_path():
    client = _make_client()
    fake, caps = _fake_request_factory(return_json={"job_id": "j9"})
    client._request = fake

    result = await client.get_video("u@t.com", "j9")

    assert caps["method"] == "GET"
    assert caps["path"] == "/api/video-jobs/j9"
    assert result == {"job_id": "j9"}


async def test_list_videos_path():
    client = _make_client()
    fake, caps = _fake_request_factory(return_json={"items": []})
    client._request = fake

    result = await client.list_videos("u@t.com")

    assert caps["method"] == "GET"
    assert caps["path"] == "/api/video-jobs"
    assert result == {"items": []}


async def test_refine_video_path_and_body():
    client = _make_client()
    fake, caps = _fake_request_factory(return_json={"refined": True})
    client._request = fake

    result = await client.refine_video("u@t.com", "job-r", "make it shorter")

    assert caps["method"] == "POST"
    assert caps["path"] == "/api/video-jobs/job-r/refine"
    assert caps["json"] == {"message": "make it shorter"}
    assert result == {"refined": True}


async def test_apply_video_path():
    client = _make_client()
    fake, caps = _fake_request_factory(return_json={"applied": True})
    client._request = fake

    result = await client.apply_video("u@t.com", "job-a")

    assert caps["method"] == "POST"
    assert caps["path"] == "/api/video-jobs/job-a/apply"
    assert result == {"applied": True}


async def test_video_versions_path():
    client = _make_client()
    fake, caps = _fake_request_factory(return_json={"versions": []})
    client._request = fake

    result = await client.video_versions("u@t.com", "job-v")

    assert caps["method"] == "GET"
    assert caps["path"] == "/api/video-jobs/job-v/versions"
    assert result == {"versions": []}


async def test_revert_video_path_and_body():
    client = _make_client()
    fake, caps = _fake_request_factory(return_json={"reverted": True})
    client._request = fake

    result = await client.revert_video("u@t.com", "job-rev", 2)

    assert caps["method"] == "POST"
    assert caps["path"] == "/api/video-jobs/job-rev/revert"
    assert caps["json"] == {"version_no": 2}
    assert result == {"reverted": True}


# ---------------------------------------------------------------------------
# Video-thread accessors (internal-scoped)
# ---------------------------------------------------------------------------

async def test_get_user_video_thread_returns_thread_id():
    client = _make_client()
    fake, caps = _fake_internal_request_factory(return_json={"thread_id": "T-999"})
    client._internal_request = fake

    result = await client.get_user_video_thread("discord-123")

    assert caps["method"] == "GET"
    assert caps["path"] == "/discord-links/discord-123/video-thread"
    assert result == "T-999"


async def test_get_user_video_thread_returns_none_when_missing():
    client = _make_client()
    fake, _ = _fake_internal_request_factory(return_json={})
    client._internal_request = fake

    result = await client.get_user_video_thread("discord-456")
    assert result is None


async def test_set_user_video_thread_posts_thread_id():
    client = _make_client()
    fake, caps = _fake_internal_request_factory(return_json={})
    client._internal_request = fake

    result = await client.set_user_video_thread("discord-789", "T-42")

    assert caps["method"] == "POST"
    assert caps["path"] == "/discord-links/discord-789/video-thread"
    assert caps["json"] == {"thread_id": "T-42"}
    assert result is True
