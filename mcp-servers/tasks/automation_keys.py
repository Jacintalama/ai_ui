"""Automation keys (2026-10-27): a key that runs an agent from outside.

An n8n workflow, a script, anything off the box that wants to say "run Ada
on this" needs to prove whose agents it may run. The gateway proves a
person by their Open WebUI session, which an automation does not have. So a
person makes a key on the Agents page, puts it in n8n, and every call with
it is scoped to their agents, the way everything else here is scoped to
X-User-Email.

Only the hash is stored (migration 059). The key is shown once when made.
A revoked key stays as a row, so the owner can see what it was, and never
matches again.

The database calls at the bottom are seams: tests replace them.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("automation_keys")

#: Every key starts with this, so one can be recognised in a log or a
#: config by eye and never mistaken for an Open WebUI token.
KEY_PREFIX = "iok_"
#: How many characters of the key the owner sees afterwards.
SHOWN_CHARS = 8
#: Active keys one person may hold. Enough for a few workflows; small
#: enough that a leaked account cannot mint keys without end.
MAX_ACTIVE_KEYS = 10
MAX_LABEL_CHARS = 60


def make_key() -> str:
    """A fresh key: the prefix and 32 characters nobody can guess."""
    return KEY_PREFIX + secrets.token_urlsafe(24)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def prefix_of(key: str) -> str:
    return key[:len(KEY_PREFIX) + SHOWN_CHARS]


def looks_like_key(value) -> bool:
    return (isinstance(value, str) and value.startswith(KEY_PREFIX)
            and 20 <= len(value) <= 80)


def clean_label(label) -> str:
    return " ".join(str(label or "").split())[:MAX_LABEL_CHARS]


def _row(k) -> dict:
    return {"id": str(k.id), "label": k.label or "", "prefix": k.prefix,
            "created_at": k.created_at.isoformat() if k.created_at else None,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "revoked_at": k.revoked_at.isoformat() if k.revoked_at else None}


# --- the database -----------------------------------------------------------

async def _create_row(email: str, label: str, key_hash: str, prefix: str) -> dict:
    from sqlalchemy import select, func
    from db import session
    from models import AutomationKey
    async with session() as s:
        active = (await s.execute(
            select(func.count()).select_from(AutomationKey)
            .where(AutomationKey.user_email == email,
                   AutomationKey.revoked_at.is_(None)))).scalar_one()
        if active >= MAX_ACTIVE_KEYS:
            raise TooManyKeys()
        row = AutomationKey(id=uuid.uuid4(), user_email=email, label=label,
                            key_hash=key_hash, prefix=prefix,
                            created_at=datetime.now(timezone.utc))
        s.add(row)
        await s.commit()
        return _row(row)


async def _list_rows(email: str) -> list[dict]:
    from sqlalchemy import select
    from db import session
    from models import AutomationKey
    async with session() as s:
        rows = (await s.execute(
            select(AutomationKey).where(AutomationKey.user_email == email)
            .order_by(AutomationKey.created_at.desc()))).scalars().all()
    return [_row(k) for k in rows]


async def _revoke_row(email: str, key_id: str) -> bool:
    from sqlalchemy import select
    from db import session
    from models import AutomationKey
    try:
        kid = uuid.UUID(str(key_id))
    except ValueError:
        return False
    async with session() as s:
        row = (await s.execute(
            select(AutomationKey).where(AutomationKey.id == kid,
                                        AutomationKey.user_email == email)
        )).scalar_one_or_none()
        if row is None or row.revoked_at is not None:
            return False
        row.revoked_at = datetime.now(timezone.utc)
        await s.commit()
    return True


async def _email_for_hash(key_hash: str) -> str | None:
    """The owner of a live key with this hash, stamping its last use."""
    from sqlalchemy import select
    from db import session
    from models import AutomationKey
    async with session() as s:
        row = (await s.execute(
            select(AutomationKey).where(AutomationKey.key_hash == key_hash)
        )).scalar_one_or_none()
        if row is None or row.revoked_at is not None:
            return None
        row.last_used_at = datetime.now(timezone.utc)
        await s.commit()
        return row.user_email


class TooManyKeys(Exception):
    pass


#: Seams. Tests replace these rather than opening a database.
_create = _create_row
_list = _list_rows
_revoke = _revoke_row
_email_for_hash_seam = _email_for_hash


# --- what the routes call -----------------------------------------------------

async def create(email: str, label: str) -> dict:
    """A new key for this person. Returns the row with the key itself in
    `key`, the one time it is ever shown. Raises TooManyKeys."""
    key = make_key()
    row = await _create(email, clean_label(label), hash_key(key), prefix_of(key))
    return dict(row, key=key)


async def list_keys(email: str) -> list[dict]:
    return await _list(email)


async def revoke(email: str, key_id: str) -> bool:
    return await _revoke(email, key_id)


async def email_for(key) -> str | None:
    """Whose key this is, or None for anything that is not a live key.
    Never raises: a database outage reads as "not a key"."""
    if not looks_like_key(key):
        return None
    try:
        return await _email_for_hash_seam(hash_key(key))
    except Exception:                                       # noqa: BLE001
        logger.warning("automation key lookup failed", exc_info=True)
        return None
