"""App Builder builds run on APP_BUILD_MODEL when it is set.

Measured on production 2026-09-21, Claude Code 2.1.140 on the build host,
OpenRouter's Anthropic-compatible endpoint:

1. Claude Code sends the direct Anthropic key as x-api-key next to the
   OpenRouter token. With it, OpenRouter answers 400 "your request's
   provider.only preference permits only: anthropic" for openai/gpt-5.1-codex.
   Without it, the same request answers 200.
2. openai/gpt-5.1-codex refuses effort "high" (Claude Code's default) with
   400 "Supported values are: 'medium'". Builds send "low" today.

So a build on the override model drops the Anthropic key, sends the override
effort, and names the model on every slot Claude Code picks a model for.
Unset, a build is exactly what it was before.
"""
import os
import shutil
import stat
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import build_model
from local_executor import LocalExecutor
from remote_executor import RemoteExecutor

GPT = "openai/gpt-5.1-codex"


@pytest.fixture
def override(monkeypatch):
    monkeypatch.setenv("APP_BUILD_MODEL", GPT)
    monkeypatch.setenv("APP_BUILD_EFFORT", "medium")


@pytest.fixture
def no_override(monkeypatch):
    monkeypatch.delenv("APP_BUILD_MODEL", raising=False)
    monkeypatch.delenv("APP_BUILD_EFFORT", raising=False)


# ---- the settings ----------------------------------------------------------

def test_blank_model_is_no_override(monkeypatch):
    monkeypatch.setenv("APP_BUILD_MODEL", "   ")
    assert build_model.model() == ""
    assert build_model.cli_args() == []
    assert build_model.effort("low") == "low"


def test_override_disallows_the_tools_a_headless_build_cannot_use(override):
    # Task c09fb88f, 2026-09-22: EnterPlanMode, ExitPlanMode x14,
    # AskUserQuestion and EnterWorktree, four attempts, no app.
    args = build_model.cli_args()
    assert args[:2] == ["--model", GPT]
    assert args[args.index("--disallowedTools") + 1] == (
        "EnterPlanMode,ExitPlanMode,AskUserQuestion,EnterWorktree")


def test_override_effort_replaces_the_default(override):
    assert build_model.effort("low") == "medium"


def test_override_without_an_effort_keeps_the_default(monkeypatch):
    monkeypatch.setenv("APP_BUILD_MODEL", GPT)
    monkeypatch.delenv("APP_BUILD_EFFORT", raising=False)
    assert build_model.effort("low") == "low"


def test_effort_without_a_model_changes_nothing(monkeypatch):
    monkeypatch.delenv("APP_BUILD_MODEL", raising=False)
    monkeypatch.setenv("APP_BUILD_EFFORT", "medium")
    assert build_model.effort("low") == "low"


def test_every_model_slot_names_the_override(override):
    slots = build_model.model_slots()
    assert set(slots) == {
        "ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_FABLE_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL"}
    assert set(slots.values()) == {GPT}


# ---- the remote build (the host, which is where production builds run) ------

def _remote_cmd(effort_default: str = "low") -> str:
    ex = RemoteExecutor()
    return ex._build_remote_cmd("build it", "myapp",
                                build_model.effort(effort_default))


def test_remote_command_with_override(override):
    cmd = _remote_cmd()
    assert "--model " + GPT in cmd
    assert "--effort medium" in cmd
    assert "--disallowedTools EnterPlanMode,ExitPlanMode," in cmd
    source = cmd.index("source ~/.env")
    unset = cmd.index("unset ANTHROPIC_API_KEY")
    claude = cmd.index("claude --print")
    # After the source, or the source puts the key straight back.
    assert source < unset < claude
    assert "ANTHROPIC_DEFAULT_HAIKU_MODEL=" + GPT in cmd


def test_remote_command_without_override_is_unchanged(no_override):
    cmd = _remote_cmd()
    assert "--model" not in cmd
    assert "unset ANTHROPIC_API_KEY" not in cmd
    assert "ANTHROPIC_DEFAULT_" not in cmd
    assert "--effort low" in cmd


def test_remote_command_quotes_a_hostile_model(monkeypatch):
    monkeypatch.setenv("APP_BUILD_MODEL", "x; rm -rf /")
    cmd = _remote_cmd()
    assert "--model 'x; rm -rf /'" in cmd
    assert "=x; rm" not in cmd


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("sh"),
                    reason="runs the command text in a POSIX shell")
def test_remote_command_runs_claude_on_the_override_without_the_key(
        override, tmp_path):
    """The real command text, run by a real shell against a ~/.env shaped
    like the build host's, with a stand-in claude that prints what it got."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text(
        "ANTHROPIC_API_KEY=sk-ant-host\n"
        "ANTHROPIC_AUTH_TOKEN=sk-or-host\n"
        "ANTHROPIC_BASE_URL=https://openrouter.ai/api\n"
        "ANTHROPIC_MODEL=claude-sonnet-4-5\n")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "claude"
    fake.write_text(
        "#!/bin/sh\n"
        "echo \"key=${ANTHROPIC_API_KEY-UNSET}\"\n"
        "echo \"token=${ANTHROPIC_AUTH_TOKEN-UNSET}\"\n"
        "echo \"model_env=$ANTHROPIC_MODEL\"\n"
        "echo \"haiku=$ANTHROPIC_DEFAULT_HAIKU_MODEL\"\n"
        "echo \"subagent=$CLAUDE_CODE_SUBAGENT_MODEL\"\n"
        "echo \"args=$*\"\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    cmd = _remote_cmd().replace("cd /agent/work/myapp;", "cd %s;" % tmp_path)
    out = subprocess.run(
        ["bash", "-c", cmd], capture_output=True, text=True, timeout=30,
        env={"HOME": str(home), "PATH": "%s:/usr/bin:/bin" % bindir})
    assert out.returncode == 0, out.stderr
    got = dict(line.split("=", 1) for line in out.stdout.splitlines())
    assert got["key"] == "UNSET"
    assert got["token"] == "sk-or-host"
    assert got["model_env"] == GPT
    assert got["haiku"] == GPT
    assert got["subagent"] == GPT
    assert "--model %s" % GPT in got["args"]
    assert "--effort medium" in got["args"]


# ---- the local build (inside the tasks container) --------------------------

def _fake_proc():
    proc = MagicMock()
    proc.stdout = MagicMock()
    chunks = [b"COMPLETED: ok\n", b""]

    async def _read(_n):
        return chunks.pop(0)
    proc.stdout.read = AsyncMock(side_effect=_read)
    proc.wait = AsyncMock(return_value=0)
    proc.kill = MagicMock()
    proc.returncode = 0
    return proc


async def _local_spawn(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-container")
    spawn = AsyncMock(return_value=_fake_proc())
    with patch("asyncio.create_subprocess_exec", spawn):
        async for _ in LocalExecutor().run("prompt", slug=None,
                                           execution_id="x"):
            pass
    return spawn.call_args[0], spawn.call_args[1]["env"]


async def test_local_build_with_override(override, monkeypatch):
    args, env = await _local_spawn(monkeypatch)
    assert args[args.index("--model") + 1] == GPT
    assert args[args.index("--effort") + 1] == "medium"
    assert "EnterPlanMode" in args[args.index("--disallowedTools") + 1]
    assert "ANTHROPIC_API_KEY" not in env
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == GPT
    # The prompt stays the last argument.
    assert args[-1] == "prompt"


async def test_local_build_without_override_is_unchanged(no_override,
                                                         monkeypatch):
    args, env = await _local_spawn(monkeypatch)
    assert "--model" not in args
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-container"
    assert "ANTHROPIC_DEFAULT_HAIKU_MODEL" not in env
    assert args[args.index("--effort") + 1] == os.environ.get(
        "AIUI_AGENT_EFFORT", "low")
