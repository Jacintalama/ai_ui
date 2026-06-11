"""Fernet symmetric encryption for sensitive tokens (OAuth access/refresh).

The key is loaded from the AIUI_FERNET_KEY env var at import time. Generate
one with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Vendored from mcp-servers/tasks/crypto_utils.py — keep in sync.
"""
import os

from cryptography.fernet import Fernet

_KEY = os.environ.get("AIUI_FERNET_KEY")
if not _KEY:
    raise RuntimeError(
        "AIUI_FERNET_KEY is not set. Generate one with "
        "`python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'` "
        "and add it to the host .env."
    )

_FERNET = Fernet(_KEY.encode() if isinstance(_KEY, str) else _KEY)


def encrypt(plaintext: str) -> str:
    """Encrypt a string. Returns URL-safe base64."""
    return _FERNET.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str:
    """Decrypt a Fernet token. Raises InvalidToken if tampered or wrong key."""
    return _FERNET.decrypt(ciphertext.encode("ascii")).decode("utf-8")
