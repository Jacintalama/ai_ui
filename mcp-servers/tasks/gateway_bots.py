"""Pure helpers for a bot that belongs to one user.

No database and no network, so every rule here is testable without either.

crypto_utils is imported INSIDE the functions on purpose: it raises at import
time when AIUI_FERNET_KEY is unset, and importing it at module scope would take
the whole tasks service down at boot instead of failing one save with a message
the user can act on.
"""
import secrets


def new_bot_key() -> str:
    """The opaque path segment in /webhook/telegram/{bot_key}.

    Not a secret, but unguessable anyway: a guessable one would let anyone
    probe which bots exist."""
    return secrets.token_hex(16)


def new_webhook_secret() -> str:
    """What Telegram echoes back in x-telegram-bot-api-secret-token.

    Separate from bot_key so the public part of the URL is never the
    credential."""
    return secrets.token_hex(16)


def encrypt_token(token: str) -> str:
    from crypto_utils import encrypt
    return encrypt(token)


def decrypt_token(blob: str) -> str:
    from crypto_utils import decrypt
    return decrypt(blob)


def mask_token(token: str) -> str:
    """What the browser is allowed to see: enough to recognise, never enough
    to use."""
    if len(token) < 8:
        return "..."
    return "..." + token[-4:]


def parse_allowed_ids(raw: str) -> str:
    """Normalize the allow list to comma-separated digits.

    Anything non-numeric is dropped rather than kept: a Telegram user id is a
    number, so a stray @handle is a mistake, and keeping it would leave the
    owner believing they had restricted access when they had not."""
    out = [part.strip() for part in (raw or "").split(",")]
    return ",".join(p for p in out if p.isdigit())


def is_allowed(allowed_ids: str, owner_platform_user_id: str | None,
               sender_id: str) -> bool:
    """May this sender talk to this bot?

    An explicit allow list wins outright. With no list, the bot serves only the
    account that claimed it, and an unclaimed bot serves whoever arrives first
    so that the owner can claim their own bot by messaging it."""
    allowed = [p for p in (allowed_ids or "").split(",") if p]
    if allowed:
        return str(sender_id) in allowed
    if not owner_platform_user_id:
        return True
    return str(sender_id) == str(owner_platform_user_id)
