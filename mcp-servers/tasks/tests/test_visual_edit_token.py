"""Tasks-side verify mirror — must match webhook-handler's sign output."""
import os
import sys
os.environ.setdefault("OAUTH_STATE_SECRET", "test-secret-123")

# Import the webhook-handler signer to produce a real token for the test.
WEBHOOK_HANDLER = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "webhook-handler")
)
assert os.path.isdir(WEBHOOK_HANDLER), (
    f"webhook-handler not found at {WEBHOOK_HANDLER} — "
    "cross-module token test needs both services on disk"
)
sys.path.insert(0, WEBHOOK_HANDLER)
from handlers.visual_edit_token import sign_edit_token  # noqa: E402

from visual_edit_token import verify_edit_token, EDIT_TOKEN_TTL_SECONDS  # noqa: E402


def test_cross_module_verify_matches_sign():
    tok = sign_edit_token("my-slug", "ralph@example.com")
    assert verify_edit_token(tok, "my-slug") == "ralph@example.com"


def test_wrong_slug_rejected():
    from handlers.visual_edit_token import sign_edit_token
    tok = sign_edit_token("slug-a", "ralph@example.com")
    assert verify_edit_token(tok, "slug-b") is None


def test_ttl_constants_match():
    """Both sides MUST have the same TTL or they'll disagree on expiry."""
    from handlers.visual_edit_token import EDIT_TOKEN_TTL_SECONDS as WH_TTL
    assert WH_TTL == EDIT_TOKEN_TTL_SECONDS == 1800


def test_verify_returns_none_when_secret_missing(monkeypatch):
    """If OAUTH_STATE_SECRET is empty/unset, verify must return None (not raise).
    Distinct from sign_edit_token which raises RuntimeError under the same condition."""
    import importlib
    import visual_edit_token
    monkeypatch.setenv("OAUTH_STATE_SECRET", "")
    importlib.reload(visual_edit_token)
    try:
        assert visual_edit_token.verify_edit_token("a.b.c", "any-slug") is None
    finally:
        # Restore the module's _SECRET so later tests still work.
        monkeypatch.setenv("OAUTH_STATE_SECRET", "test-secret-123")
        importlib.reload(visual_edit_token)


def test_old_unprefixed_token_rejected():
    """A token signed WITHOUT the edit_tok: domain prefix must no longer verify
    (domain-separation guard)."""
    import base64, hashlib, hmac, time
    secret = b"test-secret-123"
    owner, slug = "ralph@example.com", "my-slug"
    ts = str(int(time.time()))
    old_sig = hmac.new(secret, f"{owner}:{ts}:{slug}".encode(), hashlib.sha256).digest()
    b = lambda x: base64.urlsafe_b64encode(x).decode().rstrip("=")
    old_token = f"{b(owner.encode())}.{b(ts.encode())}.{b(old_sig)}"
    assert verify_edit_token(old_token, slug) is None
