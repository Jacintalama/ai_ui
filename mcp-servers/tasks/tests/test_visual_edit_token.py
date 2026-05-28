"""Tasks-side verify mirror — must match webhook-handler's sign output."""
import os
import sys
os.environ.setdefault("OAUTH_STATE_SECRET", "test-secret-123")

# Import the webhook-handler signer to produce a real token for the test.
WEBHOOK_HANDLER = os.path.join(os.path.dirname(__file__), "..", "..", "..", "webhook-handler")
sys.path.insert(0, os.path.abspath(WEBHOOK_HANDLER))
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
