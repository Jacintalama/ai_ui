"""The build model settings reach the tasks container.

Compose only injects what a service declares. A setting build_model reads
but compose never passes would leave every build on the host's Claude model
while this repo says GPT-5.1 Codex.
"""
import pytest

from conftest import repo_root_or_skip
from test_agent_paid_env import _declared, _reaches_container

COMPOSE = repo_root_or_skip() / "docker-compose.unified.yml"

pytestmark = pytest.mark.skipif(
    not COMPOSE.exists(), reason="compose file not present in this checkout")


@pytest.mark.parametrize("name,expected", [
    # Blank: the host's Claude model. GPT-5.1 Codex is opt-in through .env
    # after the 2026-09-22 build that spent $1.96 and made nothing.
    ("APP_BUILD_MODEL", ""),
    # medium only: gpt-5.1-codex answered 400 "Supported values are:
    # 'medium'" to Claude Code's default "high" (2026-09-21).
    ("APP_BUILD_EFFORT", "medium"),
])
def test_each_build_setting_reaches_the_container_with_its_default(name,
                                                                    expected):
    assert _declared(name) == ("-", expected)
    assert _reaches_container(name, {}) == expected


def test_a_blank_build_model_in_env_goes_back_to_the_host_model():
    # Blank has to reach the container blank: that is how builds go back to
    # the host's Claude model without a code change.
    assert _reaches_container("APP_BUILD_MODEL", {"APP_BUILD_MODEL": ""}) == ""


def test_a_model_set_in_env_reaches_the_container():
    assert _reaches_container("APP_BUILD_MODEL", {
        "APP_BUILD_MODEL": "openai/gpt-5.1-codex"}) == "openai/gpt-5.1-codex"
