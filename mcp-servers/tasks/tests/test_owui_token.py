"""mint_owui_token must produce a token Open WebUI's own decoder accepts.

Open WebUI signs session JWTs HS256 over WEBUI_SECRET_KEY. Up to 0.11.x its
is_valid_token was a revocation blocklist, so a fresh token with a random jti
passed; from 0.12.0 it also requires the session_stamp claim to equal
public.auth.session_stamp for that user (NULL matches an absent claim). These
tests pin the wire format and the stamp lookup; the real proof that Open WebUI
accepts a token is a call against the running server, which no unit test can
replace.
"""
import base64
import hashlib
import hmac
import json
import logging
from contextlib import asynccontextmanager

import pytest

import owui_token


def _decode(token: str) -> tuple[dict, dict, bytes, bytes]:
    header_b64, payload_b64, sig_b64 = token.split(".")

    def unb64(s: str) -> bytes:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

    signing_input = f"{header_b64}.{payload_b64}".encode()
    return (
        json.loads(unb64(header_b64)),
        json.loads(unb64(payload_b64)),
        unb64(sig_b64),
        signing_input,
    )


def test_mint_produces_three_part_hs256_token(monkeypatch):
    monkeypatch.setenv("WEBUI_SECRET_KEY", "test-secret")
    token = owui_token.mint_owui_token("user-abc")

    header, payload, sig, signing_input = _decode(token)
    assert header == {"alg": "HS256", "typ": "JWT"}
    assert payload["id"] == "user-abc"
    assert payload["exp"] - payload["iat"] == 60
    assert payload["jti"]

    expected = hmac.new(b"test-secret", signing_input, hashlib.sha256).digest()
    assert hmac.compare_digest(sig, expected)


def test_each_mint_has_a_distinct_jti(monkeypatch):
    monkeypatch.setenv("WEBUI_SECRET_KEY", "test-secret")
    a = _decode(owui_token.mint_owui_token("user-abc"))[1]
    b = _decode(owui_token.mint_owui_token("user-abc"))[1]
    assert a["jti"] != b["jti"]


def test_ttl_is_honoured(monkeypatch):
    monkeypatch.setenv("WEBUI_SECRET_KEY", "test-secret")
    payload = _decode(owui_token.mint_owui_token("user-abc", ttl_seconds=5))[1]
    assert payload["exp"] - payload["iat"] == 5


def test_fails_closed_without_a_secret(monkeypatch):
    monkeypatch.setenv("WEBUI_SECRET_KEY", "")
    with pytest.raises(RuntimeError):
        owui_token.mint_owui_token("user-abc")


def test_rejects_an_empty_user_id(monkeypatch):
    monkeypatch.setenv("WEBUI_SECRET_KEY", "test-secret")
    with pytest.raises(ValueError):
        owui_token.mint_owui_token("")


@pytest.mark.parametrize("ttl", [0, -1, -3600])
def test_rejects_a_non_positive_ttl(monkeypatch, ttl):
    # An already-expired token would be rejected downstream and read as a model
    # outage, which is a confusing way to learn about a caller's bad argument.
    monkeypatch.setenv("WEBUI_SECRET_KEY", "test-secret")
    with pytest.raises(ValueError):
        owui_token.mint_owui_token("user-abc", ttl_seconds=ttl)


# ---------------------------------------------------------------------------
# Open WebUI 0.12.0: is_valid_token compares the token's session_stamp claim
# with public.auth.session_stamp for that user and rejects on any difference.
# A NULL column reads as None, and so does a missing claim, so the claim must be
# present exactly when the column holds a value and absent when it does not.
# ---------------------------------------------------------------------------


def test_a_stamp_is_carried_as_a_claim_and_still_signed(monkeypatch):
    monkeypatch.setenv("WEBUI_SECRET_KEY", "test-secret")
    token = owui_token.mint_owui_token(
        "user-abc", ttl_seconds=5, session_stamp="stamp-123")

    header, payload, sig, signing_input = _decode(token)
    assert header == {"alg": "HS256", "typ": "JWT"}
    assert payload["session_stamp"] == "stamp-123"
    # Nothing else moves: no typ claim (Open WebUI defaults it to 'session',
    # which is what its own login tokens carry), same id and lifetime.
    assert set(payload) == {"id", "jti", "iat", "exp", "session_stamp"}
    assert payload["id"] == "user-abc"
    assert payload["exp"] - payload["iat"] == 5

    expected = hmac.new(b"test-secret", signing_input, hashlib.sha256).digest()
    assert hmac.compare_digest(sig, expected)


@pytest.mark.parametrize("stamp", [None, ""])
def test_no_stamp_means_no_claim(monkeypatch, stamp):
    # Omitted, not null: decoded.get('session_stamp') is then None, which is
    # exactly what a NULL column compares equal to.
    monkeypatch.setenv("WEBUI_SECRET_KEY", "test-secret")
    payload = _decode(owui_token.mint_owui_token(
        "user-abc", session_stamp=stamp))[1]
    assert set(payload) == {"id", "jti", "iat", "exp"}


class _Result:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


def _fake_session(row=None, error=None, seen=None):
    class _S:
        async def execute(self, statement, params=None):
            if seen is not None:
                seen.append((str(statement), params))
            if error:
                raise error
            return _Result(row)

    @asynccontextmanager
    async def _session():
        yield _S()

    return _session


def _missing_column_error():
    """What SQLAlchemy over asyncpg really raises when public.auth has no
    session_stamp column (Open WebUI 0.11.x): asyncpg's UndefinedColumnError,
    translated by the dialect's own table, wrapped in sqlalchemy.exc."""
    import asyncpg
    import sqlalchemy.exc
    from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_dbapi

    raw = asyncpg.exceptions.UndefinedColumnError(
        'column "session_stamp" does not exist')
    dbapi = AsyncAdapt_asyncpg_dbapi(asyncpg)
    mapping = dbapi._asyncpg_error_translate
    cls = next(mapping[k] for k in type(raw).__mro__ if k in mapping)
    translated = cls("%s: %s" % (type(raw), raw))
    translated.pgcode = translated.sqlstate = raw.sqlstate
    translated.__cause__ = raw
    return sqlalchemy.exc.ProgrammingError(
        "SELECT session_stamp FROM public.auth WHERE id = $1", ("u",), translated)


async def test_the_stamp_is_read_from_open_webuis_auth_row(monkeypatch):
    seen = []
    monkeypatch.setattr(owui_token, "session",
                        _fake_session(row=("stamp-123",), seen=seen))
    assert await owui_token.session_stamp_for("user-abc") == "stamp-123"
    assert len(seen) == 1
    sql, params = seen[0]
    assert "session_stamp" in sql and "public.auth" in sql
    assert params == {"id": "user-abc"}


async def test_a_null_stamp_is_none(monkeypatch):
    monkeypatch.setattr(owui_token, "session", _fake_session(row=(None,)))
    assert await owui_token.session_stamp_for("user-abc") is None


async def test_no_auth_row_is_none(monkeypatch):
    monkeypatch.setattr(owui_token, "session", _fake_session(row=None))
    assert await owui_token.session_stamp_for("user-abc") is None


async def test_an_empty_user_id_never_touches_the_database(monkeypatch):
    seen = []
    monkeypatch.setattr(owui_token, "session", _fake_session(seen=seen))
    assert await owui_token.session_stamp_for("") is None
    assert seen == []


async def test_a_missing_column_is_none_and_warns_once(monkeypatch, caplog):
    # Open WebUI 0.11.x has no such column. Every call must still mint a
    # working token, and the log must not fill with one line per agent turn.
    monkeypatch.setattr(owui_token, "_missing_column_warned", False)
    monkeypatch.setattr(owui_token, "session",
                        _fake_session(error=_missing_column_error()))
    with caplog.at_level(logging.WARNING, logger=owui_token.logger.name):
        assert await owui_token.session_stamp_for("user-abc") is None
        assert await owui_token.session_stamp_for("user-abc") is None
        assert await owui_token.session_stamp_for("user-def") is None
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "session_stamp" in warnings[0].getMessage()


async def test_any_other_database_error_is_none(monkeypatch):
    monkeypatch.setattr(owui_token, "session",
                        _fake_session(error=RuntimeError("db down")))
    assert await owui_token.session_stamp_for("user-abc") is None
