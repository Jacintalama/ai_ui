"""edit_capability: mint/verify single-task capability with edit_cap domain."""
import base64
import hashlib
import hmac
import importlib


def _mod(monkeypatch, secret="s3cr3t"):
    monkeypatch.setenv("OAUTH_STATE_SECRET", secret)
    import edit_capability
    importlib.reload(edit_capability)
    return edit_capability


def test_roundtrip(monkeypatch):
    m = _mod(monkeypatch)
    cap = m.mint_capability("u@x.com", "my-app", "task-123", ttl=1800)
    assert m.verify_capability(cap) == {
        "owner": "u@x.com", "slug": "my-app", "task_id": "task-123"}


def test_expired(monkeypatch):
    m = _mod(monkeypatch)
    cap = m.mint_capability("u@x.com", "my-app", "task-123", ttl=-1)
    assert m.verify_capability(cap) is None


def test_tampered_signature(monkeypatch):
    m = _mod(monkeypatch)
    cap = m.mint_capability("u@x.com", "my-app", "task-123")
    flipped = cap[:-2] + ("AA" if not cap.endswith("AA") else "BB")
    assert m.verify_capability(flipped) is None


def test_wrong_secret_rejects(monkeypatch):
    m = _mod(monkeypatch)
    cap = m.mint_capability("u@x.com", "a", "t")
    m2 = _mod(monkeypatch, secret="different")
    assert m2.verify_capability(cap) is None


def test_no_secret_returns_none(monkeypatch):
    monkeypatch.setenv("OAUTH_STATE_SECRET", "")
    import edit_capability
    importlib.reload(edit_capability)
    assert edit_capability.verify_capability("anything") is None


def test_garbage_inputs(monkeypatch):
    m = _mod(monkeypatch)
    for bad in ("", "nope", "a.b.c", "...", "@@@.@@@"):
        assert m.verify_capability(bad) is None


def test_not_confusable_with_edit_token(monkeypatch):
    """A value signed with the edit_tok domain must NOT verify as a capability."""
    m = _mod(monkeypatch)
    payload = b'{"owner":"u","slug":"a","task_id":"t","exp":9999999999}'
    sig = hmac.new(b"s3cr3t", b"edit_tok:" + payload, hashlib.sha256).digest()
    b = lambda x: base64.urlsafe_b64encode(x).decode().rstrip("=")
    assert m.verify_capability(b(payload) + "." + b(sig)) is None
