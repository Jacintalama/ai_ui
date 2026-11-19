"""An automation key says what it may do (2026-11-19).

Until now an `iok_` key could do one thing, run the owner's agents
(`/api/tasks/agents/run`). n8n is getting a second door, running ONE tool
with the person's connection (`/api/tasks/tools/run`), and a key made to
run agents must not quietly gain it. So a key carries scopes, every key
that already exists is `{agents}`, and a key AIUI makes for n8n is
`{tools}`. A `tools` key also carries the write steps the person approved
when AIUI built a workflow, and which n8n credential holds it.
"""
import pathlib
from unittest.mock import AsyncMock

import automation_keys as ak

OWNER = "a@example.com"


def _owner(**kw):
    row = {"id": "k", "email": OWNER, "scopes": ["tools"],
           "allowed_writes": [], "n8n_credential_id": None}
    row.update(kw)
    return row


async def test_a_key_made_on_the_agents_page_runs_agents_only(monkeypatch):
    seen = {}

    async def create(email, label, key_hash, prefix, scopes=None):
        seen["scopes"] = scopes
        return {"id": "k1", "label": label, "prefix": prefix,
                "scopes": list(scopes)}
    monkeypatch.setattr(ak, "_create", create)
    row = await ak.create(OWNER, "n8n")
    assert seen["scopes"] == (ak.SCOPE_AGENTS,)
    assert row["key"].startswith("iok_")


async def test_a_key_for_n8n_runs_tools(monkeypatch):
    seen = {}

    async def create(email, label, key_hash, prefix, scopes=None):
        seen["scopes"] = scopes
        return {"id": "k1"}
    monkeypatch.setattr(ak, "_create", create)
    await ak.create(OWNER, "n8n (made by AIUI)", scopes=(ak.SCOPE_TOOLS,))
    assert seen["scopes"] == ("tools",)


async def test_an_unknown_scope_is_refused(monkeypatch):
    monkeypatch.setattr(ak, "_create", AsyncMock())
    try:
        await ak.create(OWNER, "x", scopes=("admin",))
    except ValueError:
        return
    raise AssertionError("an unknown scope was accepted")


async def test_owner_for_returns_the_whole_owner(monkeypatch):
    monkeypatch.setattr(ak, "_owner_for_hash_seam",
                        AsyncMock(return_value=_owner(allowed_writes=["github.review_pull_request"])))
    got = await ak.owner_for(ak.make_key())
    assert got["email"] == OWNER
    assert got["scopes"] == ["tools"]
    assert got["allowed_writes"] == ["github.review_pull_request"]


async def test_owner_for_refuses_what_is_not_a_key_without_asking(monkeypatch):
    seam = AsyncMock()
    monkeypatch.setattr(ak, "_owner_for_hash_seam", seam)
    assert await ak.owner_for("Bearer nonsense") is None
    seam.assert_not_called()


async def test_owner_for_never_raises(monkeypatch):
    monkeypatch.setattr(ak, "_owner_for_hash_seam",
                        AsyncMock(side_effect=RuntimeError("down")))
    assert await ak.owner_for(ak.make_key()) is None


async def test_allow_writes_passes_the_steps_through(monkeypatch):
    seam = AsyncMock()
    monkeypatch.setattr(ak, "_allow_writes_seam", seam)
    await ak.allow_writes(OWNER, "k", ["github.review_pull_request"])
    seam.assert_awaited_once_with(OWNER, "k", ["github.review_pull_request"])


async def test_allow_writes_with_nothing_touches_nothing(monkeypatch):
    seam = AsyncMock()
    monkeypatch.setattr(ak, "_allow_writes_seam", seam)
    await ak.allow_writes(OWNER, "k", [])
    seam.assert_not_called()


def test_the_real_agents_lookup_requires_the_agents_scope():
    """email_for is what /agents/run trusts. Its query must ask for the
    scope, or a tools-only key in n8n could run any of the person's agents.
    Read from the source because the query needs a database to run."""
    import inspect
    src = inspect.getsource(ak._email_for_hash)
    assert "SCOPE_AGENTS" in src and "scopes" in src


def test_migration_070_is_additive_and_defaults_existing_keys_to_agents():
    sql = (pathlib.Path(ak.__file__).parent / "migrations"
           / "070_automation_key_scopes.sql").read_text(encoding="utf-8")
    code = "\n".join(line for line in sql.splitlines()
                     if not line.strip().startswith("--"))
    assert "ADD COLUMN IF NOT EXISTS scopes" in code
    assert "DEFAULT '{agents}'" in code
    assert "ADD COLUMN IF NOT EXISTS allowed_writes" in code
    assert "ADD COLUMN IF NOT EXISTS n8n_credential_id" in code
    assert "DROP" not in code.upper()


def test_the_rollback_exists():
    p = (pathlib.Path(ak.__file__).parent / "migrations" / "rollbacks"
         / "070_automation_key_scopes.down.sql")
    assert p.exists()


def test_the_model_knows_the_new_columns():
    from models import AutomationKey
    cols = AutomationKey.__table__.columns
    assert {"scopes", "allowed_writes", "n8n_credential_id"} <= set(cols.keys())


def test_the_agents_page_says_what_a_key_can_do():
    html = (pathlib.Path(ak.__file__).parent / "static"
            / "agents.html").read_text(encoding="utf-8")
    assert "Runs tools (n8n)" in html and "Runs agents" in html
