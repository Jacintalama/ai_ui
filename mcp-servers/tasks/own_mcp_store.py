"""The rows of tasks.own_mcp_servers (migration 075).

Every read and write is by (email, ...) first: there is no way in here to
reach a row without naming whose it is. The address and token are decrypted
only by ``secrets_of``, and only the call path and the re-listing use it.
"""
from __future__ import annotations

import json
import os
from typing import Any

import crypto_utils

DATABASE_URL = os.environ.get("DATABASE_URL", "")
#: Failed checks in a row before a card says the server is not answering.
FAILS_BEFORE_DOWN = 3

_COLUMNS = "id::text AS id, slug, label, host, tools, check_ok, fails, checked_at"


async def _connect():
    import asyncpg
    return await asyncpg.connect(DATABASE_URL)


def _row(record: Any) -> dict:
    row = dict(record)
    tools = row.get("tools")
    if isinstance(tools, str):
        try:
            tools = json.loads(tools)
        except ValueError:
            tools = []
    row["tools"] = tools if isinstance(tools, list) else []
    return row


def _norm(email: str) -> str:
    return (email or "").strip().lower()


async def list_for(email: str) -> list[dict]:
    """This person's servers, oldest first, never with secrets."""
    conn = await _connect()
    try:
        rows = await conn.fetch(
            f"SELECT {_COLUMNS} FROM tasks.own_mcp_servers "
            "WHERE email = $1 ORDER BY created_at", _norm(email))
    finally:
        await conn.close()
    return [_row(r) for r in rows]


async def all_rows() -> list[dict]:
    """Every server, with its owner, for the sweep. Never with secrets."""
    conn = await _connect()
    try:
        rows = await conn.fetch(
            f"SELECT email, {_COLUMNS} FROM tasks.own_mcp_servers")
    finally:
        await conn.close()
    return [_row(r) for r in rows]


async def by_slug(email: str, slug: str) -> dict | None:
    conn = await _connect()
    try:
        row = await conn.fetchrow(
            f"SELECT {_COLUMNS} FROM tasks.own_mcp_servers "
            "WHERE email = $1 AND slug = $2", _norm(email), slug)
    finally:
        await conn.close()
    return _row(row) if row else None


async def secrets_of(email: str, server_id: str) -> dict | None:
    """{"url", "token"} for this person's server, None when it is not theirs."""
    conn = await _connect()
    try:
        blob = await conn.fetchval(
            "SELECT secrets_encrypted FROM tasks.own_mcp_servers "
            "WHERE email = $1 AND id::text = $2", _norm(email), server_id)
    finally:
        await conn.close()
    if not blob:
        return None
    values = json.loads(crypto_utils.decrypt(blob))
    return {"url": values.get("url", ""), "token": values.get("token", "")}


async def add(email: str, slug: str, label: str, host: str, url: str,
              token: str, tools: list[dict]) -> str:
    blob = crypto_utils.encrypt(json.dumps({"url": url, "token": token}))
    conn = await _connect()
    try:
        return await conn.fetchval(
            "INSERT INTO tasks.own_mcp_servers "
            "(email, slug, label, host, secrets_encrypted, tools) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb) RETURNING id::text",
            _norm(email), slug, label, host, blob, json.dumps(tools))
    finally:
        await conn.close()


async def set_tools(email: str, server_id: str, tools: list[dict]) -> bool:
    """A fresh snapshot after a good listing; resets the failure count."""
    conn = await _connect()
    try:
        done = await conn.execute(
            "UPDATE tasks.own_mcp_servers SET tools = $3::jsonb, "
            "check_ok = TRUE, fails = 0, checked_at = now() "
            "WHERE email = $1 AND id::text = $2",
            _norm(email), server_id, json.dumps(tools))
    finally:
        await conn.close()
    return done.endswith(" 1")


async def record_check(email: str, server_id: str, ok: bool) -> None:
    """One more good or failed check. Three failures in a row mark it down."""
    conn = await _connect()
    try:
        if ok:
            await conn.execute(
                "UPDATE tasks.own_mcp_servers SET check_ok = TRUE, fails = 0, "
                "checked_at = now() WHERE email = $1 AND id::text = $2",
                _norm(email), server_id)
        else:
            await conn.execute(
                "UPDATE tasks.own_mcp_servers SET fails = fails + 1, "
                "check_ok = (fails + 1) < $3, checked_at = now() "
                "WHERE email = $1 AND id::text = $2",
                _norm(email), server_id, FAILS_BEFORE_DOWN)
    finally:
        await conn.close()


async def remove(email: str, server_id: str) -> bool:
    conn = await _connect()
    try:
        done = await conn.execute(
            "DELETE FROM tasks.own_mcp_servers "
            "WHERE email = $1 AND id::text = $2", _norm(email), server_id)
    finally:
        await conn.close()
    return done.endswith(" 1")
