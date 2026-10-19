"""The paid model settings reach the tasks container.

Compose only injects what a service declares, and this repo has lost
WEBUI_SECRET_KEY, the Telegram credentials and GATEWAY_MODEL that way. A
setting the code reads but compose never passes silently runs on the code's
default, which here means spending money on a model nobody chose on purpose.
"""
import re

import pytest

import agent_escalation
from conftest import repo_root_or_skip

COMPOSE = repo_root_or_skip() / "docker-compose.unified.yml"

pytestmark = pytest.mark.skipif(
    not COMPOSE.exists(), reason="compose file not present in this checkout")

TEXT = COMPOSE.read_text(encoding="utf-8")


def _tasks_block() -> str:
    start = TEXT.index("\n  tasks:")
    rest = TEXT[start + 1:]
    m = re.search(r"\n  [a-z0-9_-]+:\n", rest)
    return rest[: m.start()] if m else rest


def _declared(name: str) -> tuple[str, str]:
    """(operator, default) of NAME=${NAME<operator><default>} in the tasks
    service: ":-" or "-"."""
    for line in _tasks_block().splitlines():
        m = re.fullmatch(r"- %s=\$\{%s(:?-)(.*)\}" % (name, name), line.strip())
        if m:
            return m.group(1), m.group(2)
    raise AssertionError(name + " is not passed to the tasks service")


def _default(name: str) -> str:
    return _declared(name)[1]


def _reaches_container(name: str, env: dict[str, str]) -> str:
    """What compose hands the container, by the rule in the compose docs
    (interpolation, same as POSIX sh): ${VAR:-d} gives d when VAR is unset
    or empty, ${VAR-d} gives d only when VAR is unset."""
    operator, default = _declared(name)
    if name not in env:
        return default
    if operator == ":-" and env[name] == "":
        return default
    return env[name]


@pytest.mark.parametrize("name,expected", [
    ("AGENT_PAID_MODEL", "gpt-5.5"),
    # none, not low: measured live 2026-09-17 17:13 UTC, OpenAI answered 400
    # "Function tools with reasoning_effort are not supported for gpt-5.5 in
    # /v1/chat/completions ... set reasoning_effort to 'none'", and every
    # agent turn carries tools.
    ("AGENT_PAID_REASONING", "none"),
    ("AGENT_PAID_TIMEOUT_SECONDS", "90"),
    # 0 since 2026-10-19: escalation to gpt-5.5 is off while every agent
    # runs on GLM.
    ("AGENT_PAID_DAILY_CAP", "0"),
    ("AGENT_PAID_PRICES",
     "gpt-5.5=5:30,z-ai/glm-5.3-flash=0.0352:0.2,z-ai/glm-4.7-flash=0.0605:0.4"),
])
def test_each_paid_setting_reaches_the_container_with_the_agreed_default(name, expected):
    assert _default(name) == expected
    assert _reaches_container(name, {}) == expected


@pytest.mark.parametrize("name", ["AGENT_PAID_MODEL", "AGENT_PAID_REASONING"])
def test_a_model_or_reasoning_set_blank_in_env_reaches_the_container_blank(name):
    """The design turns the feature off with a blank AGENT_PAID_MODEL and
    stops sending reasoning_effort with a blank AGENT_PAID_REASONING. With
    ${VAR:-default} a blank line in .env was replaced by the default, so
    neither worked through compose (review, 2026-09-18)."""
    assert _reaches_container(name, {name: ""}) == ""


@pytest.mark.parametrize("name", ["AGENT_PAID_TIMEOUT_SECONDS",
                                  "AGENT_PAID_DAILY_CAP", "AGENT_PAID_PRICES"])
def test_a_number_or_price_set_blank_still_gets_its_default(name):
    # Blank means nothing for these: the code reads a blank number as its
    # default anyway, and a blank price would record every paid run's cost
    # as unknown. AGENT_PAID_DAILY_CAP=0, not blank, is the off switch.
    assert _reaches_container(name, {name: ""}) == _default(name)


def test_blank_model_in_the_container_turns_the_feature_off(monkeypatch):
    monkeypatch.setattr(agent_escalation, "DAILY_CAP", 40)
    monkeypatch.setattr(agent_escalation, "PAID_MODEL", _reaches_container(
        "AGENT_PAID_MODEL", {"AGENT_PAID_MODEL": ""}).strip())
    assert not agent_escalation.enabled()


def test_the_compose_prices_parse_to_the_prices_read_on_their_dates():
    # No braces in the value: compose interpolation ends ${VAR:-...} at the
    # first closing brace, so a JSON default would be cut short. gpt-5.5
    # read 2026-09-17 from OpenAI; the two GLMs 2026-10-19 from OpenRouter's
    # public model list.
    assert agent_escalation.parse_prices(_default("AGENT_PAID_PRICES")) == {
        "gpt-5.5": (5.0, 30.0), "z-ai/glm-5.3-flash": (0.0352, 0.2),
        "z-ai/glm-4.7-flash": (0.0605, 0.4)}


def test_the_compose_cap_turns_escalation_off(monkeypatch):
    monkeypatch.setattr(agent_escalation, "PAID_MODEL", "gpt-5.5")
    monkeypatch.setattr(agent_escalation, "DAILY_CAP", int(
        _reaches_container("AGENT_PAID_DAILY_CAP", {})))
    assert not agent_escalation.enabled()


@pytest.mark.parametrize("name,expected", [
    # 2026-10-19: the owner asked for the cheapest GLM; nemotron free ids
    # replaced.
    ("AGENT_DEFAULT_MODEL", "z-ai/glm-5.3-flash"),
    ("AGENT_FREE_MODELS", "z-ai/glm-5.3-flash,z-ai/glm-4.7-flash"),
    # Left alone on purpose: whether GLM wants it is checked against a real
    # call separately.
    ("AGENT_FREE_REASONING", "none"),
])
def test_the_agent_pool_reaches_the_container_as_glm(name, expected):
    assert _reaches_container(name, {}) == expected


def test_the_compose_pool_matches_the_code_default():
    import agent_runner
    assert _default("AGENT_FREE_MODELS").split(",") == agent_runner.FREE_MODELS
    assert _default("AGENT_DEFAULT_MODEL") == agent_runner.FREE_MODELS[0]
