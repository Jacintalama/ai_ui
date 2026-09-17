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


def _default(name: str) -> str:
    for line in _tasks_block().splitlines():
        s = line.strip()
        prefix = "- %s=${%s:-" % (name, name)
        if s.startswith(prefix) and s.endswith("}"):
            return s[len(prefix):-1]
    raise AssertionError(name + " is not passed to the tasks service")


@pytest.mark.parametrize("name,expected", [
    ("AGENT_PAID_MODEL", "gpt-5.5"),
    ("AGENT_PAID_REASONING", "low"),
    ("AGENT_PAID_TIMEOUT_SECONDS", "90"),
    ("AGENT_PAID_DAILY_CAP", "40"),
    ("AGENT_PAID_PRICES", "gpt-5.5=5:30"),
])
def test_each_paid_setting_reaches_the_container_with_the_agreed_default(name, expected):
    assert _default(name) == expected


def test_the_compose_prices_parse_to_the_price_read_on_2026_09_17():
    # No braces in the value: compose interpolation ends ${VAR:-...} at the
    # first closing brace, so a JSON default would be cut short.
    assert agent_escalation.parse_prices(_default("AGENT_PAID_PRICES")) == {
        "gpt-5.5": (5.0, 30.0)}
