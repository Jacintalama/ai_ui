"""Auto (Smart) routing: category + difficulty -> free vs paid target. Pure
logic, no network or key. Mirrors test_auto_router_pipe.py."""
import importlib.util
import pathlib

import pytest

from conftest import repo_root_or_skip

PIPE_PATH = (repo_root_or_skip()
             / "open-webui-functions" / "auto_smart_pipe.py")


def _load():
    spec = importlib.util.spec_from_file_location("auto_smart_pipe", PIPE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return _load()


def test_pipe_file_exists():
    assert PIPE_PATH.is_file()


def test_easy_general_stays_free(mod):
    cat, hard = mod.route("what's a nice coffee shop name?", 400)
    assert cat == "general" and hard is False


def test_short_coding_stays_free(mod):
    cat, hard = mod.route("what does the python len() do?", 400)
    assert cat == "coder" and hard is False


def test_code_fence_escalates_to_paid(mod):
    cat, hard = mod.route("fix this\n```\ndef f(x) return x\n```", 400)
    assert cat == "coder" and hard is True


def test_hard_coding_keywords_escalate(mod):
    cat, hard = mod.route("help me debug and optimize this slow algorithm", 400)
    assert cat == "coder" and hard is True


def test_proof_reasoning_escalates(mod):
    cat, hard = mod.route("prove that the square root of 2 is irrational", 400)
    assert cat == "reasoning" and hard is True


def test_simple_math_stays_free(mod):
    # Category may be general or reasoning; what matters is it does NOT escalate.
    cat, hard = mod.route("solve: what is 2+2?", 400)
    assert cat == "reasoning" and hard is False


def test_trivial_question_stays_free(mod):
    _, hard = mod.route("what is 2+2?", 400)
    assert hard is False


def test_long_prompt_escalates(mod):
    cat, hard = mod.route("tell me about dogs. " * 40, 400)  # > 400 chars
    assert hard is True


def test_empty_is_free_general(mod):
    cat, hard = mod.route("   ", 400)
    assert cat == "general" and hard is False


def test_target_free_and_paid_mapping(mod):
    p = mod.Pipe()
    prov, model, tier = p._target("coder", hard=False)
    assert (prov, tier, model) == ("openrouter", "free", p.valves.FREE_CODER)
    prov, model, tier = p._target("coder", hard=True)
    assert (prov, tier, model) == ("openai", "paid", p.valves.PAID_CODER)
    prov, model, tier = p._target("reasoning", hard=True)
    assert model == p.valves.PAID_REASONING
    prov, model, tier = p._target("general", hard=False)
    assert model == p.valves.FREE_GENERAL


def test_pipes_exposes_auto_smart(mod):
    assert mod.Pipe().pipes() == [{"id": "auto-smart", "name": "Auto (Smart)"}]


def test_payload_drops_extra_fields(mod):
    # Model switched from gpt-5.5 to gpt-4o on 2026-07-23. This test's intent is
    # "extras dropped, model overridden, temperature passes through", but on
    # gpt-5.5 the live API rejects temperature outright, so the original form
    # asserted the bug. gpt-4o is the model where every clause here is true.
    # gpt-5.5's real contract is covered by the reasoning-model tests below.
    p = mod.Pipe()
    out = p._payload({"messages": [{"role": "user", "content": "hi"}],
                      "model": "x", "user": "u", "temperature": 0.3}, "gpt-4o")
    assert out["model"] == "gpt-4o" and out["temperature"] == 0.3
    assert "user" not in out


# --- request contract per model family -------------------------------------
# Live bug found 2026-07-23: _payload forwarded max_tokens/temperature to
# whatever model was picked, but PAID_GENERAL/CODER/REASONING all default to
# gpt-5.5. The real OpenAI API answers:
#   "Unsupported parameter: 'max_tokens' is not supported with this model.
#    Use 'max_completion_tokens' instead."
# so every escalated request failed on gpt-5.5 and silently fell back to the
# gpt-4o candidate. The paid tier was unreachable dead config.
# Same split fusion_engine.PROVIDER_REGISTRY already encodes as openai_new.

@pytest.mark.parametrize("model", ["gpt-5", "gpt-5.5", "o3"])
def test_reasoning_models_get_max_completion_tokens(mod, model):
    out = mod.Pipe()._payload(
        {"messages": [{"role": "user", "content": "q"}], "max_tokens": 100}, model)
    assert "max_completion_tokens" in out, f"{model} needs max_completion_tokens"
    assert "max_tokens" not in out, f"{model} rejects max_tokens outright"


@pytest.mark.parametrize("model", ["gpt-5", "gpt-5.5", "o3"])
def test_reasoning_models_never_get_temperature(mod, model):
    out = mod.Pipe()._payload(
        {"messages": [{"role": "user", "content": "q"}], "temperature": 0.7}, model)
    assert "temperature" not in out, f"{model} rejects temperature"


@pytest.mark.parametrize("model", ["gpt-4o", "gpt-4.1"])
def test_legacy_openai_models_keep_max_tokens_and_temperature(mod, model):
    """Regression guard: the fallback candidate must keep working."""
    out = mod.Pipe()._payload(
        {"messages": [{"role": "user", "content": "q"}],
         "max_tokens": 100, "temperature": 0.7}, model)
    assert out.get("max_tokens") == 100
    assert out.get("temperature") == 0.7
    assert "max_completion_tokens" not in out


def test_free_openrouter_models_keep_max_tokens(mod):
    """The free tier is plain OpenAI-compatible; do not rewrite its params."""
    out = mod.Pipe()._payload(
        {"messages": [{"role": "user", "content": "q"}],
         "max_tokens": 100, "temperature": 0.7}, "openai/gpt-oss-20b:free")
    assert out.get("max_tokens") == 100
    assert out.get("temperature") == 0.7


def test_paid_defaults_are_covered_by_the_contract_rule(mod):
    """Whatever the paid valves default to must be a model the payload rule
    knows about, or this bug silently comes back on the next model bump."""
    v = mod.Pipe().valves
    for name in ("PAID_GENERAL", "PAID_CODER", "PAID_REASONING"):
        model = getattr(v, name)
        out = mod.Pipe()._payload(
            {"messages": [{"role": "user", "content": "q"}],
             "max_tokens": 100, "temperature": 0.7}, model)
        assert not ("max_tokens" in out and "max_completion_tokens" in out), \
            f"{name}={model} produced both token params"
        if mod._needs_completion_tokens(model):
            assert "max_tokens" not in out and "temperature" not in out, \
                f"{name}={model} would be rejected by the API"
