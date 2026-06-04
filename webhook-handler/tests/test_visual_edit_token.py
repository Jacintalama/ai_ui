"""Visual-edit token: HMAC-SHA256 over owner:ts:slug with OAUTH_STATE_SECRET.
Format mirrors handlers.oauth_state but the signing payload includes slug, so
a token issued for slug A cannot be replayed against slug B.
"""
import os
import time
os.environ.setdefault("OAUTH_STATE_SECRET", "test-secret-123")

from handlers.visual_edit_token import (
    sign_edit_token, verify_edit_token, EDIT_TOKEN_TTL_SECONDS,
)


def test_sign_verify_roundtrip():
    tok = sign_edit_token("my-slug", "ralph@example.com")
    assert verify_edit_token(tok, "my-slug") == "ralph@example.com"


def test_wrong_slug_rejected():
    tok = sign_edit_token("slug-a", "ralph@example.com")
    assert verify_edit_token(tok, "slug-b") is None


def test_tampered_owner_rejected():
    tok = sign_edit_token("my-slug", "ralph@example.com")
    head, ts, sig = tok.split(".")
    # swap the owner segment for a different one — signature should fail
    import base64
    other = base64.urlsafe_b64encode(b"someone-else@example.com").decode().rstrip("=")
    bad = f"{other}.{ts}.{sig}"
    assert verify_edit_token(bad, "my-slug") is None


def test_expired_rejected(monkeypatch):
    tok = sign_edit_token("my-slug", "ralph@example.com")
    # advance time past the TTL (capture real time.time before patching to
    # avoid recursion, since handlers.visual_edit_token.time is the same
    # module object as the test module's `time` import)
    real_time = time.time
    monkeypatch.setattr("handlers.visual_edit_token.time.time",
                        lambda: real_time() + EDIT_TOKEN_TTL_SECONDS + 10)
    assert verify_edit_token(tok, "my-slug") is None


def test_malformed_returns_none():
    assert verify_edit_token("", "x") is None
    assert verify_edit_token("not.a.valid.token", "x") is None
    assert verify_edit_token("only-one-part", "x") is None


def test_ttl_is_generous_so_chat_links_dont_go_stale():
    # The link token is long-lived (default 30 days); the *capability* minted on
    # load is the short-lived credential. Must be well beyond a single session.
    assert EDIT_TOKEN_TTL_SECONDS >= 86400
