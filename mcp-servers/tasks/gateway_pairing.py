"""Pairing code primitives for the multi-platform gateway.

Hardening lifted from NousResearch/hermes-agent's pairing.py, which had already
done the reading: hash at rest, a confusable-free alphabet, short expiry, single
use, a resend cooldown and a redemption lockout.

Pure functions only. The rows live in routes_gateway.py so this module stays
testable without a database.
"""
import hashlib
import hmac
import secrets

# 32 characters, no 0/O/1/I. A code is read off a phone and typed into a browser.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
CODE_TTL_SECONDS = 3600
RESEND_COOLDOWN_SECONDS = 600
MAX_REDEEM_ATTEMPTS = 5

# Domain separator, so a gateway code hash can never be confused with any other
# sha256 digest this codebase stores.
_DOMAIN = "gateway_pair:"


def generate_code() -> str:
    """A fresh code. `secrets`, not `random`: this is an auth credential."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(raw: str) -> str:
    """Upper-case and drop anything outside the alphabet.

    People paste codes with spaces, dashes and the wrong case. Rejecting those
    would read as "the code is wrong" when the code is fine.
    """
    return "".join(ch for ch in (raw or "").upper() if ch in CODE_ALPHABET)


def hash_code(code: str) -> str:
    return hashlib.sha256((_DOMAIN + normalize_code(code)).encode()).hexdigest()


def codes_match(code: str, code_hash: str) -> bool:
    """Constant-time compare, so timing does not leak a prefix."""
    return hmac.compare_digest(hash_code(code), code_hash or "")
