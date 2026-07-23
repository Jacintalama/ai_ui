"""Build a Gmail draft's base64url-encoded raw MIME message.

Stdlib only (email + base64) so it stays importable and testable without the
FastAPI app, the Fernet key, or network access.
"""
import base64
from email.mime.text import MIMEText


def build_draft_raw(
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    bcc: str | None = None,
) -> str:
    """Return a base64url-encoded MIME message for a new (non-reply) draft.

    Raises ValueError if `to` is missing so a bad tool call fails loudly
    instead of creating a draft with no recipient.
    """
    if not to or not to.strip():
        raise ValueError("recipient (to) is required")
    msg = MIMEText(body or "", "plain")
    msg["To"] = to
    msg["Subject"] = subject or ""
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
