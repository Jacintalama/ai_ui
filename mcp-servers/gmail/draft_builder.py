"""Build a Gmail draft's base64url-encoded raw MIME message.

Stdlib only (email + base64) so it stays importable and testable without the
FastAPI app, the Fernet key, or network access.
"""
import base64
import binascii
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
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
    header_fields = (("to", to), ("subject", subject), ("cc", cc), ("bcc", bcc))
    for field_name, value in header_fields:
        if value is not None and ("\r" in value or "\n" in value):
            raise ValueError(f"{field_name} may not contain newlines")
    msg = MIMEText(body or "", "plain")
    msg["To"] = to
    msg["Subject"] = subject or ""
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


def build_draft_raw_with_attachment(
    to: str,
    subject: str,
    body: str,
    filename: str,
    content_b64: str,
    mime_type: str,
    cc: str | None = None,
    bcc: str | None = None,
) -> str:
    """Like build_draft_raw, but multipart with one binary attachment.

    `content_b64` is standard base64 (what the Documents tool already holds);
    invalid base64 raises ValueError so the endpoint can 422 cleanly. Header
    validation matches build_draft_raw.
    """
    if not to or not to.strip():
        raise ValueError("recipient (to) is required")
    for field_name, value in (("to", to), ("subject", subject),
                              ("cc", cc), ("bcc", bcc),
                              ("filename", filename)):
        if value is not None and ("\r" in value or "\n" in value):
            raise ValueError(f"{field_name} may not contain newlines")
    try:
        payload = base64.b64decode(content_b64 or "", validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("content_b64 is not valid base64")
    if not payload:
        raise ValueError("attachment is empty")
    maintype, _, subtype = (mime_type or "application/octet-stream").partition("/")
    msg = MIMEMultipart()
    msg["To"] = to
    msg["Subject"] = subject or ""
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    msg.attach(MIMEText(body or "", "plain"))
    att = MIMEApplication(payload, _subtype=subtype or "octet-stream")
    att.set_type(mime_type or "application/octet-stream")
    att.add_header("Content-Disposition", "attachment",
                   filename=filename or "attachment")
    msg.attach(att)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
