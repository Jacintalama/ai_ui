"""video_capability: mint/verify single-job download capability with video_dl domain."""
import base64
import hashlib
import hmac
import importlib


def _mod(monkeypatch, secret="s3cr3t"):
    monkeypatch.setenv("OAUTH_STATE_SECRET", secret)
    import video_capability
    importlib.reload(video_capability)
    return video_capability


def _edit_mod(monkeypatch, secret="s3cr3t"):
    monkeypatch.setenv("OAUTH_STATE_SECRET", secret)
    import edit_capability
    importlib.reload(edit_capability)
    return edit_capability


def test_roundtrip(monkeypatch):
    m = _mod(monkeypatch)
    cap = m.mint_video_capability("u@x.com", "my-app", "job-123", ttl=1800)
    assert m.verify_video_capability(cap) == {
        "owner": "u@x.com", "slug": "my-app", "video_job_id": "job-123"}


def test_expired(monkeypatch):
    m = _mod(monkeypatch)
    cap = m.mint_video_capability("u@x.com", "my-app", "job-123", ttl=-1)
    assert m.verify_video_capability(cap) is None


def test_tampered_signature(monkeypatch):
    m = _mod(monkeypatch)
    cap = m.mint_video_capability("u@x.com", "my-app", "job-123")
    flipped = cap[:-2] + ("AA" if not cap.endswith("AA") else "BB")
    assert m.verify_video_capability(flipped) is None


def test_wrong_secret_rejects(monkeypatch):
    m = _mod(monkeypatch)
    cap = m.mint_video_capability("u@x.com", "a", "j")
    m2 = _mod(monkeypatch, secret="different")
    assert m2.verify_video_capability(cap) is None


def test_no_secret_returns_none(monkeypatch):
    monkeypatch.setenv("OAUTH_STATE_SECRET", "")
    import video_capability
    importlib.reload(video_capability)
    assert video_capability.verify_video_capability("anything") is None


def test_no_secret_mint_raises(monkeypatch):
    monkeypatch.setenv("OAUTH_STATE_SECRET", "")
    import video_capability
    importlib.reload(video_capability)
    import pytest
    with pytest.raises(RuntimeError):
        video_capability.mint_video_capability("u@x.com", "my-app", "job-123")


def test_garbage_inputs(monkeypatch):
    m = _mod(monkeypatch)
    for bad in ("", "nope", "a.b.c", "...", "@@@.@@@"):
        assert m.verify_video_capability(bad) is None


def test_not_confusable_with_edit_token(monkeypatch):
    """A value signed with the edit_tok domain must NOT verify as a video capability."""
    m = _mod(monkeypatch)
    payload = b'{"owner":"u","slug":"a","video_job_id":"j","exp":9999999999}'
    sig = hmac.new(b"s3cr3t", b"edit_tok:" + payload, hashlib.sha256).digest()
    b = lambda x: base64.urlsafe_b64encode(x).decode().rstrip("=")
    assert m.verify_video_capability(b(payload) + "." + b(sig)) is None


def test_edit_capability_token_rejected_by_video(monkeypatch):
    """A token minted by edit_capability must NOT verify via verify_video_capability."""
    edit = _edit_mod(monkeypatch)
    video = _mod(monkeypatch)
    edit_cap = edit.mint_capability("u@x.com", "my-app", "task-123", ttl=1800)
    assert video.verify_video_capability(edit_cap) is None


def test_video_capability_token_rejected_by_edit(monkeypatch):
    """A token minted by video_capability must NOT verify via verify_capability."""
    video = _mod(monkeypatch)
    edit = _edit_mod(monkeypatch)
    vid_cap = video.mint_video_capability("u@x.com", "my-app", "job-123", ttl=1800)
    assert edit.verify_capability(vid_cap) is None
