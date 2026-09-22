"""The model App Builder builds run on.

A build is Claude Code pointed at OpenRouter. On the build host the
claude-agent user's ~/.env sets ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_TOKEN and
ANTHROPIC_MODEL (claude-sonnet-4-5 as of 2026-09-21); inside this container
compose sets the same three. APP_BUILD_MODEL, when set, replaces that model
for every build on both paths. Blank or unset, a build is exactly what it was.

Measured on production 2026-09-21 with Claude Code 2.1.140 on the build host:

1. Claude Code sends the direct Anthropic key (ANTHROPIC_API_KEY) as
   x-api-key beside the OpenRouter token. OpenRouter then pins the request
   to Anthropic: 400 "your request's provider.only preference permits only:
   anthropic" for openai/gpt-5.1-codex. The same request without the key
   answered 200. So an override build drops the key and authenticates with
   ANTHROPIC_AUTH_TOKEN alone, which a stub server confirmed it does.
2. openai/gpt-5.1-codex refuses effort "high" with 400 "Supported values are:
   'medium'". APP_BUILD_EFFORT is the effort sent with the override model.
3. Claude Code also picks models by alias for side calls (a Haiku call titled
   the session in one capture) and for subagents. Every slot is named, so a
   build calls the override model and nothing else.
4. A non-Claude model reaches for plan mode. Measured 2026-09-22 on a real
   build (task c09fb88f, openai/gpt-5.1-codex): attempt 1 called EnterPlanMode,
   wrote a plan and called ExitPlanMode 14 times, which a headless build can
   never approve; attempts 3 and 4 called AskUserQuestion and EnterWorktree
   and stopped to ask. Four attempts, $1.96 on OpenRouter, no app. So the
   override build passes --disallowedTools for those four tools, which
   removes them from the model's tool list (26 to 22, checked against a stub
   server on the build host the same day).

Read at call time, not import, like the executors' own AIUI_AGENT_EFFORT.
"""
from __future__ import annotations

import os
import shlex

#: The key that pins OpenRouter to Anthropic. See point 1 above.
ANTHROPIC_KEY_VAR = "ANTHROPIC_API_KEY"

#: Every variable Claude Code 2.1.x reads a model id from.
_MODEL_SLOTS = (
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_FABLE_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL",
)


def model() -> str:
    """The override model id, or "" for none."""
    return os.environ.get("APP_BUILD_MODEL", "").strip()


def effort(default: str) -> str:
    """The --effort for a build: APP_BUILD_EFFORT with the override model,
    otherwise the caller's default. An effort alone changes nothing, because
    it is the override model's value, not a general one."""
    chosen = os.environ.get("APP_BUILD_EFFORT", "").strip()
    return chosen if model() and chosen else default


#: Tools a headless build cannot use and a non-Claude model reaches for.
#: See point 4 above.
DISALLOWED_TOOLS = "EnterPlanMode,ExitPlanMode,AskUserQuestion,EnterWorktree"


def cli_args() -> list[str]:
    """Extra claude arguments: --model and --disallowedTools with the
    override, none without."""
    m = model()
    return ["--model", m, "--disallowedTools", DISALLOWED_TOOLS] if m else []


def model_slots() -> dict[str, str]:
    """Every model slot set to the override, or {} without one."""
    m = model()
    return {name: m for name in _MODEL_SLOTS} if m else {}


def local_env(env: dict[str, str]) -> dict[str, str]:
    """The environment for a claude subprocess in this container."""
    slots = model_slots()
    if not slots:
        return env
    out = {k: v for k, v in env.items() if k != ANTHROPIC_KEY_VAR}
    out.update(slots)
    return out


def remote_shell_prefix() -> str:
    """Shell run on the build host after ~/.env is sourced and before claude:
    drops the Anthropic key and exports every model slot. "" without an
    override. Must come after the source, or the source puts the key back."""
    slots = model_slots()
    if not slots:
        return ""
    exports = " ".join("%s=%s" % (k, shlex.quote(v)) for k, v in slots.items())
    return "unset %s; export %s; " % (ANTHROPIC_KEY_VAR, exports)
