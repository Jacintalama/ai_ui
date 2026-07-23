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
    instead of creating a draft with no recipient. Also raises ValueError if
    any header field (`to`, `subject`, `cc`, `bcc`) contains a carriage
    return or newline, since those are written verbatim as MIME headers and
    would otherwise make `email` raise a non-ValueError deep in encoding
    (which the endpoint can't turn into a clean 422). `body` is exempt: it
    legitimately contains newlines.
    """
    if not to or not to.strip():
        raise ValueError("recipient (to) is required")
    for field_name, value in (("to", to), ("subject", subject), ("cc", cc), ("bcc", bcc)):
        if value is not None and ("\r" in value or "\n" in value):
            raise ValueError("header fields may not contain newlines")
    msg = MIMEText(body or "", "plain")
    msg["To"] = to
    msg["Subject"] = subject or ""
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
