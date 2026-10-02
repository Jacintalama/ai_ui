"""Both executors give a marked run the design skill, and nothing else.

Production builds run remote (the claude-agent user on the host), so the
remote command is the one that matters; the local one is kept in step so
flipping AGENT_BACKEND does not silently drop the rules.
"""
import shlex
import shutil
import stat
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import design_skill
from local_executor import LocalExecutor
from remote_executor import RemoteExecutor

SLUG = "crumb-and-co"


@pytest.fixture(autouse=True)
def _plain_build(monkeypatch):
    monkeypatch.delenv("APP_BUILD_MODEL", raising=False)
    monkeypatch.delenv("IMPECCABLE_MAX_BUDGET_USD", raising=False)


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


async def _local(**kw):
    spawn = AsyncMock(return_value=_fake_proc())
    with patch("asyncio.create_subprocess_exec", spawn):
        async for _ in LocalExecutor().run("prompt", slug=SLUG,
                                           execution_id="x", **kw):
            pass
    return list(spawn.call_args[0]), spawn.call_args[1]["env"]


async def test_a_local_marked_run_gets_the_flags_and_the_env():
    args, env = await _local(design="impeccable")
    assert args[args.index("--append-system-prompt") + 1] == \
        design_skill.system_prompt(SLUG)
    assert args[args.index("--max-budget-usd") + 1] == "1.50"
    assert args.count("--disallowedTools") == 1
    assert args[args.index("--disallowedTools") + 1] == \
        "AskUserQuestion,Task,Agent"
    assert env["IMPECCABLE_QUESTION_DISABLED"] == "1"


async def test_a_local_marked_run_on_an_override_model_has_one_tool_list(
        monkeypatch):
    monkeypatch.setenv("APP_BUILD_MODEL", "openai/gpt-5.1-codex")
    args, _ = await _local(design="impeccable")
    assert args.count("--disallowedTools") == 1
    tools = args[args.index("--disallowedTools") + 1].split(",")
    assert {"EnterPlanMode", "AskUserQuestion", "Task", "Agent"} <= set(tools)


async def test_the_local_prompt_is_never_read_as_a_tool_name():
    # --disallowedTools takes a list; without "--" the prompt after it
    # would be swallowed as one more tool name.
    args, _ = await _local(design="impeccable")
    assert args[-2:] == ["--", "prompt"]


async def test_a_local_unmarked_run_is_unchanged():
    args, env = await _local()
    for flag in ("--append-system-prompt", "--max-budget-usd",
                 "--disallowedTools"):
        assert flag not in args
    assert "IMPECCABLE_QUESTION_DISABLED" not in env
    assert args[-1] == "prompt"


def test_a_remote_marked_run_links_the_skill_before_claude_starts():
    cmd = RemoteExecutor()._build_remote_cmd("build it", SLUG, "low",
                                             "impeccable")
    link = cmd.index("ln -sfn")
    assert cmd.index("cd /agent/work/crumb-and-co;") < link
    assert link < cmd.index("IS_SANDBOX=1 claude")
    assert "export IMPECCABLE_QUESTION_DISABLED=1;" in cmd


def test_a_remote_marked_run_gets_the_flags_and_keeps_the_prompt_last():
    cmd = RemoteExecutor()._build_remote_cmd("build it", SLUG, "low",
                                             "impeccable")
    claude = shlex.split(cmd[cmd.index("claude --print"):])
    assert claude[claude.index("--append-system-prompt") + 1] == \
        design_skill.system_prompt(SLUG)
    assert claude[claude.index("--max-budget-usd") + 1] == "1.50"
    assert claude.count("--disallowedTools") == 1
    assert claude[claude.index("--disallowedTools") + 1] == \
        "AskUserQuestion,Task,Agent"
    assert claude[-2:] == ["--", "build it"]


def test_a_remote_unmarked_run_is_what_it_was_plus_the_cleanup():
    ex = RemoteExecutor()
    cmd = ex._build_remote_cmd("build it", SLUG, "low")
    assert cmd == ex._build_remote_cmd("build it", SLUG, "low", None)
    cleanup = "rm -f .claude/skills/impeccable 2>/dev/null || true; "
    # The command before design_skill existed (cf769ec3e), byte for byte.
    assert cmd.replace(cleanup, "", 1) == (
        "set -e; cd /agent/work/crumb-and-co; set -a; source ~/.env; "
        "set +a; IS_SANDBOX=1 claude --print --dangerously-skip-permissions "
        "--output-format stream-json --verbose --effort low -- 'build it'")
    assert cmd.index(cleanup) < cmd.index("IS_SANDBOX=1 claude")


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"),
                    reason="runs the command text in a real shell")
@pytest.mark.parametrize("installed", [True, False])
def test_the_remote_command_really_links_the_skill_and_still_builds(
        tmp_path, installed):
    """The real command text, run by bash against a ~/.env and a stand-in
    claude, the way it runs on the build host. Without the skill installed
    the link dangles and the build must still start: that is the fail-open
    promise."""
    home = tmp_path / "home"
    (home / ".impeccable" / "skills" / "impeccable").mkdir(parents=True) \
        if installed else home.mkdir()
    (home / ".env").write_text("ANTHROPIC_AUTH_TOKEN=sk-or-host\n")
    work = tmp_path / "work"
    work.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "claude"
    fake.write_text(
        "#!/bin/sh\n"
        "echo \"link=$(readlink .claude/skills/impeccable)\"\n"
        "echo \"question=${IMPECCABLE_QUESTION_DISABLED-UNSET}\"\n"
        "echo \"last=$(eval echo \\${$#})\"\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    cmd = RemoteExecutor()._build_remote_cmd("build it", SLUG, "low",
                                             "impeccable")
    cmd = cmd.replace("cd /agent/work/crumb-and-co;", "cd %s;" % work)
    out = subprocess.run(
        ["bash", "-c", cmd], capture_output=True, text=True, timeout=30,
        env={"HOME": str(home), "PATH": "%s:/usr/bin:/bin" % bindir})
    assert out.returncode == 0, out.stderr
    got = dict(line.split("=", 1) for line in out.stdout.splitlines())
    assert got["link"] == "%s/.impeccable/skills/impeccable" % home
    assert got["question"] == "1"
    assert got["last"] == "build it"


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"),
                    reason="runs the command text in a real shell")
def test_an_unmarked_run_really_removes_a_link_a_failed_marked_run_left(
        tmp_path):
    home = tmp_path / "home"
    (home / ".impeccable" / "skills" / "impeccable").mkdir(parents=True)
    (home / ".env").write_text("ANTHROPIC_AUTH_TOKEN=sk-or-host\n")
    work = tmp_path / "work"
    (work / ".claude" / "skills").mkdir(parents=True)
    (work / ".claude" / "skills" / "impeccable").symlink_to(
        home / ".impeccable" / "skills" / "impeccable")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "claude"
    fake.write_text(
        "#!/bin/sh\n"
        "if [ -e .claude/skills/impeccable ]; then echo link=present;"
        " else echo link=gone; fi\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    cmd = RemoteExecutor()._build_remote_cmd("build it", SLUG, "low")
    cmd = cmd.replace("cd /agent/work/crumb-and-co;", "cd %s;" % work)
    out = subprocess.run(
        ["bash", "-c", cmd], capture_output=True, text=True, timeout=30,
        env={"HOME": str(home), "PATH": "%s:/usr/bin:/bin" % bindir})
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "link=gone"
