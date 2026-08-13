"""The build agent can be pointed at an Anthropic-compatible gateway.

Why this exists. On 2026-08-12 every build was failing in 487ms with "Credit
balance is too low" — the Anthropic key was empty, and 45 builds had died that
way since at least 2026-08-10. The platform had OpenRouter credit sitting
unused, so the agent needed a way to run through it.

The agent is the Claude Code CLI, spawned as a subprocess by
`local_executor.py`, which passes `{**os.environ, ...}`. So the whole switch is
environment: no Python change, and nothing in the request path to break.

Three things were established against the live API rather than assumed, and
each is pinned below because each one cost a wrong turn:

1. **OpenRouter speaks the Anthropic wire format.** Its own docs say it is
   OpenAI-compatible only; `POST /api/v1/messages` in fact returns
   `{"type":"message","role":"assistant","content":[...]}` and honours
   `tools` (verified: `stop_reason: tool_use`). Tool use is the part that
   matters — a build is nothing but tool calls.

2. **The base URL must not end in `/v1`.** The CLI appends `/v1/messages`
   itself, so `.../api/v1` becomes `.../api/v1/v1/messages` and 404s. The CLI
   reports that 404 as *"There's an issue with the selected model … It may not
   exist or you may not have access to it"*, which sends you hunting a
   model-name bug that isn't there. Only `ANTHROPIC_LOG=debug` shows the real
   URL.

3. **The model id must be one the CLI accepts.** It validates the name locally
   before sending, so an OpenRouter slug (`anthropic/claude-sonnet-4.5`) is
   rejected client-side even though OpenRouter resolves it. A bare Anthropic id
   (`claude-sonnet-4-5`) satisfies the CLI *and* resolves on OpenRouter.

These are config assertions, deliberately. The failure was config, and the
existing tests could not have seen it — the same gap that left
MEETINGS_INGEST_SECRET unplumbed for nine days.
"""
import pathlib
import re

import pytest

COMPOSE = pathlib.Path(__file__).resolve().parents[3] / "docker-compose.unified.yml"

pytestmark = pytest.mark.skipif(
    not COMPOSE.exists(), reason="compose file not present in this checkout")

TEXT = COMPOSE.read_text(encoding="utf-8")


def _tasks_block() -> str:
    """The `tasks` service block, up to the next top-level service."""
    start = TEXT.index("\n  tasks:")
    rest = TEXT[start + 1:]
    m = re.search(r"\n  [a-z0-9_-]+:\n", rest)
    return rest[: m.start()] if m else rest


def _env_line(name: str) -> str:
    for line in _tasks_block().splitlines():
        s = line.strip()
        if s.startswith(f"- {name}=") and not s.startswith("#"):
            return s
    return ""


def test_the_tasks_service_still_exists():
    """Guards every assertion below against a rename silently emptying them."""
    assert "\n  tasks:" in TEXT


@pytest.mark.parametrize("var", [
    "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_MODEL"])
def test_the_gateway_vars_reach_the_container(var):
    """local_executor spawns the CLI with `{**os.environ}`, so a variable the
    container never receives cannot reach the agent."""
    assert _env_line(var), (
        f"{var} is not passed to the tasks service, so the build agent cannot "
        f"be pointed at a gateway")


@pytest.mark.parametrize("var", [
    "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_MODEL"])
def test_unset_means_stock_anthropic(var):
    """This is a toggle, not a migration. An operator who sets nothing must get
    exactly the previous behaviour, so every gateway var defaults to empty."""
    line = _env_line(var)
    assert ":-}" in line, (
        f"{line} has no empty default; an unset gateway would change the "
        f"Anthropic path instead of leaving it alone")


def test_the_anthropic_key_is_not_repurposed():
    """The toggle is one variable. Overwriting ANTHROPIC_API_KEY with a
    gateway token would make going back a credential swap, and would lose the
    real key from .env in the process."""
    line = _env_line("ANTHROPIC_API_KEY")
    assert line.endswith("${ANTHROPIC_API_KEY:-}"), (
        f"ANTHROPIC_API_KEY is fed from something other than itself ({line})")


def test_the_base_url_trap_is_documented_where_it_is_configured():
    """The doubled-/v1 404 is misreported by the CLI as a missing model. The
    next person hits it at 2am; the warning has to be in the compose file, not
    only in a commit message."""
    block = _tasks_block()
    assert re.search(r"/v1", block) and re.search(
        r"(not end in|NOT end in|append)", block), (
        "nothing near the gateway vars warns that the base URL must omit /v1")


def test_the_model_id_trap_is_documented():
    """An OpenRouter slug is rejected by the CLI's local validation even though
    OpenRouter accepts it — the opposite of what you would guess."""
    block = _tasks_block()
    assert "claude-sonnet-4-5" in block or "OpenRouter slug" in block, (
        "nothing documents that the model id must be CLI-acceptable, not an "
        "OpenRouter slug")
