"""Auto (Smart) routing: category + difficulty -> free vs paid target. Pure
logic, no network or key. Mirrors test_auto_router_pipe.py."""
import importlib.util
import pathlib

import pytest

PIPE_PATH = (pathlib.Path(__file__).resolve().parents[3]
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
    p = mod.Pipe()
    out = p._payload({"messages": [{"role": "user", "content": "hi"}],
                      "model": "x", "user": "u", "temperature": 0.3}, "gpt-5.5")
    assert out["model"] == "gpt-5.5" and out["temperature"] == 0.3
    assert "user" not in out
