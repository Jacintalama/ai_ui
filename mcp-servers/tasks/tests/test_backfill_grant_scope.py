"""The backfill must never grant a wildcard read to somebody's agent.

This is the one bug on this branch that could not be seen from a single commit.
The script was written when no agent existed, so "every model row that lacks a
wildcard grant" meant "every base model". Once agents shipped, that same phrase
also meant "every private agent", because absence of a grant IS what makes an
agent private. The compose file tells the next operator to re-run this script
whenever models go missing, so it is a live path, not a hypothetical one.
"""
import importlib.util
import pathlib

import pytest

SCRIPT = (pathlib.Path(__file__).resolve().parents[1]
          / "scripts" / "backfill_model_grants.py")


def load_script():
    spec = importlib.util.spec_from_file_location("backfill_model_grants", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# What an admin really sees: base models discovered from the connections, plus
# every user's agent, because an admin sees all rows.
API_MODELS = [
    {"id": "gpt-4o-mini", "name": "gpt-4o-mini",
     "info": {"meta": {"capabilities": {"vision": True}}}},
    {"id": "openai/gpt-5", "name": "GPT 5", "info": {"meta": {}}},
    {"id": "agent-someones-private-a1b2", "name": "Somebody's Private Agent",
     "info": {"base_model_id": "gpt-4o-mini", "meta": {}}},
    # A derived model that does not use the agent- prefix. Open WebUI's own
    # Workspace builder makes these, so the prefix alone is not enough.
    {"id": "my-custom-preset", "name": "My Preset",
     "info": {"base_model_id": "gpt-4o-mini", "meta": {}}},
]


@pytest.fixture
def generated_sql(tmp_path, monkeypatch):
    mod = load_script()
    monkeypatch.setattr(mod, "admin_models", lambda token: API_MODELS)
    monkeypatch.setenv("ADMIN_TOKEN", "test-token-not-a-real-one")
    out = tmp_path / "apply.sql"
    monkeypatch.setenv("BACKFILL_OUT", str(out))
    assert mod.main() == 0
    return out.read_text(encoding="utf-8")


def test_no_agent_is_ever_granted(generated_sql):
    grant = [ln for ln in generated_sql.splitlines()
             if "INSERT INTO access_grant" in ln]
    assert len(grant) == 1, "expected exactly one grant statement"
    assert "agent-someones-private-a1b2" not in grant[0]
    assert "my-custom-preset" not in grant[0]


def test_the_grant_is_scoped_to_an_explicit_id_list(generated_sql):
    """A grant written as "every row without one" is the actual defect. Even
    with agents filtered out of the id list, that phrasing would still reach
    every agent created after this ran."""
    grant = [ln for ln in generated_sql.splitlines()
             if "INSERT INTO access_grant" in ln][0]
    assert "m.id IN (" in grant, "the grant is not scoped to an id list"
    assert "'gpt-4o-mini'" in grant and "'openai/gpt-5'" in grant


def test_derived_models_get_no_model_row_either(generated_sql):
    """They already exist, and re-inserting one would fight the real owner."""
    inserts = [ln for ln in generated_sql.splitlines()
               if "INSERT INTO model " in ln]
    assert inserts, "expected model inserts for the base models"
    assert not any("agent-someones-private-a1b2" in ln for ln in inserts)
    assert not any("my-custom-preset" in ln for ln in inserts)


def test_the_base_models_are_still_granted(generated_sql):
    """The fix must not break what the script is for."""
    assert "INSERT INTO model " in generated_sql
    for wanted in ("gpt-4o-mini", "openai/gpt-5"):
        assert wanted in generated_sql
