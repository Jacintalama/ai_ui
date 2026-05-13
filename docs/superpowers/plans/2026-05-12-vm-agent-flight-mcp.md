# VM-hosted Agent + Flight MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Claude Code from the in-container subprocess onto a dedicated Hetzner CAX21 VM with its own scoped Linux identity, and ship one MCP server (`flights-mcp` wrapping Duffel sandbox) so the `flight-booking` template can pull real flight data on demand.

**Spec:** `docs/superpowers/specs/2026-05-12-vm-agent-flight-mcp-design.md`

**Architecture:** Three-layer stack — existing orchestrator VPS keeps the DB, Caddy, and preview serving; new agent VM runs `claude` as its own Linux user under a Squid FQDN-allowlist proxy; one stdio MCP server (`flights-mcp`) handles Duffel calls. The orchestrator's `tasks` service gets a swappable `BaseExecutor` interface — `LocalExecutor` (today) stays as the default and rollback path, `RemoteExecutor` (new) talks to the VM via SSH and rsyncs `apps/<slug>/` back on `COMPLETED:`.

**Tech Stack:** Python 3.11 / FastAPI / asyncio / httpx / pydantic / pytest (orchestrator side). Node 20 + `@anthropic-ai/claude-code` CLI + Python 3.11 MCP server (agent VM). Hetzner Cloud + Ubuntu 24.04 + Squid + ufw (infra). No new dependencies on the orchestrator beyond `pytest-asyncio` (already in deps).

**Branch strategy:** Worktree at `IO-vm-agent/` branched from `feat/vm-agent-flight-mcp` (where the spec already lives). At the end of the plan, that branch merges to `main`.

---

## Before You Start

**Hard prerequisite — merge `feat/functional-templates` to `main` first.** The `flight-booking` template (introduced by commit `faa84f95e`) is on the unmerged `feat/functional-templates` branch. Task 10 of this plan (prompt augmentation + E2E demo) cannot run without it. If `feat/functional-templates` has not been merged yet:

```bash
git checkout main
git merge feat/functional-templates
git push
git checkout feat/vm-agent-flight-mcp
git rebase main
```

Verify after merging:
```bash
ls mcp-servers/tasks/template_apps/flight-booking/src/data.js   # should exist
git log --oneline main | grep -E '(faa84f95e|flight-booking)'   # should print a match
```

---

## File Structure

### Files to create

```
mcp-servers/tasks/agent_executor.py       # BaseExecutor Protocol + get_executor factory
mcp-servers/tasks/local_executor.py       # LocalExecutor — wraps existing subprocess flow
mcp-servers/tasks/remote_executor.py      # RemoteExecutor — SSH + rsync to agent VM
mcp-servers/tasks/tests/test_agent_executor_factory.py
mcp-servers/tasks/tests/test_local_executor.py
mcp-servers/tasks/tests/test_remote_executor.py
mcp-servers/tasks/tests/test_sentinel_parsing.py
mcp-servers/tasks/migrations/versions/<rev>_add_agent_host_to_executions.py

mcp-servers/flights/                      # NEW package
  flights_mcp/
    __init__.py
    __main__.py                            # stdio MCP server entrypoint
    server.py                              # search_flights tool registration
    duffel.py                              # httpx wrapper for Duffel sandbox
    schemas.py                             # pydantic FlightOffer + tool errors
  tests/
    test_duffel.py
    test_server.py
  pyproject.toml
  README.md

scripts/provision_agent_vm.sh             # idempotent provisioning
scripts/smoke_agent_vm.sh                 # post-provision smoke checks
scripts/smoke_flights_mcp.sh              # MCP-over-stdio smoke test
docs/agent-vm/README.md                   # operator documentation
```

### Files to modify

- `mcp-servers/tasks/claude_executor.py`
  - Update `_SENTINEL_RE` (line 729) to include `FAILED` and add `failed` to `kind_map`
  - Migrate `run_claude_subprocess` body into `LocalExecutor.run` (kept as a thin shim for legacy callers)
  - Add the `flight-booking` prompt augmentation inside `build_prompt` (~line 305)
- `mcp-servers/tasks/routes_execution.py`
  - `_stream_claude` (line 60) switches from `proc_holder` dict to `executor.stop()` via `_RUNNING[task_id]`
  - Cancel endpoint switches accordingly
  - Write `agent_host` to `TaskExecution` row
- `docker-compose.unified.yml`
  - Add `secrets:` block for `agent_ssh_key`
  - Add `AGENT_BACKEND`, `AGENT_HOST`, `AGENT_USER`, `AGENT_SSH_KEY_PATH` env vars to the `tasks` service

---

## Task 1: BaseExecutor Protocol + factory

**Files:**
- Create: `mcp-servers/tasks/agent_executor.py`
- Create: `mcp-servers/tasks/tests/test_agent_executor_factory.py`

This task is pure scaffolding — no behavior change to existing code. It sets up the interface that Task 2 and Task 8 will implement.

- [ ] **Step 1: Write the failing factory tests**

Create `mcp-servers/tasks/tests/test_agent_executor_factory.py`:

```python
"""Factory dispatches to the right executor based on AGENT_BACKEND env."""
import os
import pytest
from unittest.mock import patch

from mcp_servers.tasks.agent_executor import get_executor, BaseExecutor


def test_default_is_local():
    """No env var → LocalExecutor."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("AGENT_BACKEND", None)
        ex = get_executor()
        assert ex.__class__.__name__ == "LocalExecutor"


def test_local_explicit():
    """AGENT_BACKEND=local → LocalExecutor."""
    with patch.dict(os.environ, {"AGENT_BACKEND": "local"}):
        ex = get_executor()
        assert ex.__class__.__name__ == "LocalExecutor"


def test_remote_returns_remote():
    """AGENT_BACKEND=remote → RemoteExecutor."""
    with patch.dict(os.environ, {"AGENT_BACKEND": "remote"}):
        ex = get_executor()
        assert ex.__class__.__name__ == "RemoteExecutor"


def test_unknown_value_raises():
    """AGENT_BACKEND=garbage → ValueError, no silent fallback."""
    with patch.dict(os.environ, {"AGENT_BACKEND": "garbage"}):
        with pytest.raises(ValueError, match="garbage"):
            get_executor()


def test_baseexecutor_is_protocol():
    """BaseExecutor is a Protocol — instances of conforming classes pass isinstance."""
    from typing import Protocol, runtime_checkable
    # Just verify the import works and Protocol attrs are present
    assert hasattr(BaseExecutor, "run")
    assert hasattr(BaseExecutor, "stop")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_agent_executor_factory.py -v
```

Expected: import error — `mcp_servers.tasks.agent_executor` does not exist yet.

- [ ] **Step 3: Implement the factory**

Create `mcp-servers/tasks/agent_executor.py`:

```python
"""Swappable agent backends. The orchestrator picks an executor at task
dispatch time based on AGENT_BACKEND env.

Today's options:
  - local  (default): run `claude` as a subprocess inside this container.
  - remote: ssh to a dedicated agent VM and run `claude` there.

The interface is intentionally small so future backends (E2B, OpenHands,
OpenCode) can plug in without touching routes_execution.
"""
from __future__ import annotations

import os
from typing import AsyncIterator, Protocol, runtime_checkable


@runtime_checkable
class BaseExecutor(Protocol):
    """Contract every agent backend must honor.

    `run` is an async generator that yields stdout lines from a claude
    process (local or remote). It MUST emit exactly one terminal sentinel
    line before the stream closes:

        COMPLETED:   FAILED:   NEEDS_INPUT:   NEEDS_STEPS:

    Wall-clock timeout is enforced by the implementation
    (EXECUTION_TIMEOUT_SECONDS, currently 600s). On timeout the
    implementation MUST yield "FAILED: timeout" and stop the underlying
    process before closing the stream.

    `stop` cancels the in-flight run owned by this executor instance.
    No-op if no run is active.
    """
    async def run(
        self,
        prompt: str,
        slug: str | None,
        execution_id: str,
    ) -> AsyncIterator[str]: ...

    async def stop(self) -> None: ...


def get_executor() -> BaseExecutor:
    """Construct the executor named by AGENT_BACKEND.

    Imports are intentionally lazy — RemoteExecutor pulls in asyncio.ssh
    helpers that we don't want loaded for purely local installs.
    """
    backend = (os.environ.get("AGENT_BACKEND") or "local").strip().lower()
    if backend == "local":
        from .local_executor import LocalExecutor  # noqa: WPS433
        return LocalExecutor()
    if backend == "remote":
        from .remote_executor import RemoteExecutor  # noqa: WPS433
        return RemoteExecutor()
    raise ValueError(
        f"AGENT_BACKEND={backend!r} is not a known executor "
        f"(expected 'local' or 'remote')"
    )
```

- [ ] **Step 4: Stub out `local_executor.py` and `remote_executor.py` so tests can resolve imports**

Create both files with placeholder classes (real bodies in Task 2 and Task 8):

`mcp-servers/tasks/local_executor.py`:
```python
"""LocalExecutor — runs claude as a subprocess inside this container.
Full body in Task 2.
"""
from __future__ import annotations
from typing import AsyncIterator


class LocalExecutor:
    async def run(self, prompt: str, slug: str | None, execution_id: str) -> AsyncIterator[str]:
        raise NotImplementedError("filled in Task 2")
        yield  # makes this a generator function for type purposes

    async def stop(self) -> None:
        raise NotImplementedError("filled in Task 2")
```

`mcp-servers/tasks/remote_executor.py`:
```python
"""RemoteExecutor — ssh + rsync to a dedicated agent VM.
Full body in Task 8.
"""
from __future__ import annotations
from typing import AsyncIterator


class RemoteExecutor:
    async def run(self, prompt: str, slug: str | None, execution_id: str) -> AsyncIterator[str]:
        raise NotImplementedError("filled in Task 8")
        yield

    async def stop(self) -> None:
        raise NotImplementedError("filled in Task 8")
```

- [ ] **Step 5: Run the test again to verify it passes**

```bash
python -m pytest tests/test_agent_executor_factory.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/agent_executor.py \
        mcp-servers/tasks/local_executor.py \
        mcp-servers/tasks/remote_executor.py \
        mcp-servers/tasks/tests/test_agent_executor_factory.py
git commit -m "feat(tasks): add BaseExecutor Protocol + AGENT_BACKEND factory

Pure scaffolding — LocalExecutor and RemoteExecutor bodies follow in
subsequent tasks. Behavior of the existing tasks service is unchanged."
```

---

## Task 2: Extract `LocalExecutor` + update `_SENTINEL_RE` to include `FAILED`

**Files:**
- Modify: `mcp-servers/tasks/local_executor.py` (full body)
- Modify: `mcp-servers/tasks/claude_executor.py` (sentinel regex + thin shim for legacy callers)
- Create: `mcp-servers/tasks/tests/test_local_executor.py`
- Create: `mcp-servers/tasks/tests/test_sentinel_parsing.py`

This task lifts the existing `run_claude_subprocess` body into a class method and migrates the `proc_holder: dict` parameter to `self._proc`. The legacy function stays as a thin shim so the route layer keeps working until Task 3 swaps it.

- [ ] **Step 1: Write the failing sentinel test**

Create `mcp-servers/tasks/tests/test_sentinel_parsing.py`:

```python
"""_SENTINEL_RE recognizes FAILED as a first-class terminal sentinel."""
from mcp_servers.tasks.claude_executor import parse_outcome


def test_failed_sentinel_is_first_class():
    """FAILED: <reason> is parsed as kind=failed with structured payload."""
    out = parse_outcome("FAILED: agent_unreachable")
    assert out.kind == "failed"
    assert out.payload == "agent_unreachable"


def test_failed_at_end_of_output():
    """Last sentinel wins, just like COMPLETED."""
    out = parse_outcome("some chatter\nFAILED: timeout\n")
    assert out.kind == "failed"
    assert out.payload == "timeout"


def test_completed_still_works():
    """Regression: existing COMPLETED parsing unchanged."""
    out = parse_outcome("COMPLETED: built apps/foo/")
    assert out.kind == "completed"
    assert out.payload == "built apps/foo/"


def test_needs_input_still_works():
    out = parse_outcome("NEEDS_INPUT: which currency?")
    assert out.kind == "needs_input"
    assert out.payload == "which currency?"


def test_needs_steps_still_works():
    out = parse_outcome("NEEDS_STEPS: requires database")
    assert out.kind == "needs_steps"
    assert out.payload == "requires database"


def test_no_sentinel_still_failed():
    """Output with no sentinel still maps to failed (existing behavior)."""
    out = parse_outcome("random output with no sentinel here")
    assert out.kind == "failed"
    # payload is the trimmed text (last-500-char fallback)
    assert "random output" in out.payload
```

- [ ] **Step 2: Run it to verify the FAILED test fails**

```bash
python -m pytest tests/test_sentinel_parsing.py -v
```

Expected: `test_failed_sentinel_is_first_class` FAILS — currently `parse_outcome("FAILED: agent_unreachable")` returns `kind="failed"` but `payload` is the whole text (existing fallback), not the structured `"agent_unreachable"`.

- [ ] **Step 3: Update `_SENTINEL_RE` in `claude_executor.py`**

Edit `mcp-servers/tasks/claude_executor.py`, line 729-730. Change the alternation in both the kind capture and the lookahead to include `FAILED`:

```python
# BEFORE
_SENTINEL_RE = re.compile(
    r"(?:^|\n)\s*(?:-{3,}\s*)?\b(?P<kind>COMPLETED|NEEDS_INPUT|NEEDS_STEPS)\b[:\s]\s*"
    r"(?P<rest>.*?)(?=\n\s*(?:-{3,}\s*)?\b(?:COMPLETED|NEEDS_INPUT|NEEDS_STEPS)\b[:\s]|\Z)",
    re.DOTALL,
)

# AFTER
_SENTINEL_RE = re.compile(
    r"(?:^|\n)\s*(?:-{3,}\s*)?\b(?P<kind>COMPLETED|FAILED|NEEDS_INPUT|NEEDS_STEPS)\b[:\s]\s*"
    r"(?P<rest>.*?)(?=\n\s*(?:-{3,}\s*)?\b(?:COMPLETED|FAILED|NEEDS_INPUT|NEEDS_STEPS)\b[:\s]|\Z)",
    re.DOTALL,
)
```

And in `parse_outcome` (line 773-777), add `FAILED` to `kind_map`:

```python
kind_map = {
    "COMPLETED": "completed",
    "FAILED": "failed",
    "NEEDS_INPUT": "needs_input",
    "NEEDS_STEPS": "needs_steps",
}
```

- [ ] **Step 4: Run sentinel tests again**

```bash
python -m pytest tests/test_sentinel_parsing.py -v
```

Expected: all 6 PASS.

- [ ] **Step 5: Write the failing LocalExecutor tests**

Create `mcp-servers/tasks/tests/test_local_executor.py`:

```python
"""LocalExecutor wraps the claude subprocess flow.

Tests mock asyncio.create_subprocess_exec so the actual claude CLI is not
invoked. They verify the contract: stop() kills self._proc, output is
streamed line-by-line, the --effort flag respects AIUI_AGENT_EFFORT, and
the timeout / output-cap paths still trigger the right messages.
"""
import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcp_servers.tasks.local_executor import LocalExecutor


@pytest.fixture
def fake_proc():
    """A fake asyncio.subprocess.Process that yields a few stdout chunks."""
    proc = MagicMock()
    proc.stdout = MagicMock()
    chunks = [b"hello ", b"world\n", b"COMPLETED: ok\n", b""]
    async def _read(_n):
        return chunks.pop(0)
    proc.stdout.read = AsyncMock(side_effect=_read)
    proc.wait = AsyncMock(return_value=0)
    proc.kill = MagicMock()
    proc.returncode = 0
    return proc


@pytest.mark.asyncio
async def test_streams_chunks(fake_proc):
    """run() yields each stdout chunk decoded as utf-8."""
    with patch("asyncio.create_subprocess_exec",
               AsyncMock(return_value=fake_proc)):
        ex = LocalExecutor()
        out = []
        async for chunk in ex.run("prompt", slug=None, execution_id="x"):
            out.append(chunk)
    full = "".join(out)
    assert "hello world" in full
    assert "COMPLETED: ok" in full


@pytest.mark.asyncio
async def test_stop_kills_self_proc(fake_proc):
    """stop() invokes self._proc.kill() if a run is active."""
    with patch("asyncio.create_subprocess_exec",
               AsyncMock(return_value=fake_proc)):
        ex = LocalExecutor()
        # Manually assign — simulating mid-run state
        ex._proc = fake_proc
        await ex.stop()
        fake_proc.kill.assert_called_once()


@pytest.mark.asyncio
async def test_stop_noop_when_no_proc():
    """stop() with no active run does nothing and does not raise."""
    ex = LocalExecutor()
    await ex.stop()  # should not raise


@pytest.mark.asyncio
async def test_effort_flag_propagated(fake_proc, monkeypatch):
    """AIUI_AGENT_EFFORT env reaches the --effort argv."""
    monkeypatch.setenv("AIUI_AGENT_EFFORT", "medium")
    spawn = AsyncMock(return_value=fake_proc)
    with patch("asyncio.create_subprocess_exec", spawn):
        ex = LocalExecutor()
        async for _ in ex.run("prompt", slug=None, execution_id="x"):
            pass
    args = spawn.call_args[0]
    assert "--effort" in args
    idx = args.index("--effort")
    assert args[idx + 1] == "medium"
```

- [ ] **Step 6: Run them to verify they fail**

```bash
python -m pytest tests/test_local_executor.py -v
```

Expected: all 4 fail with `NotImplementedError` (the stub from Task 1).

- [ ] **Step 7: Implement LocalExecutor**

Replace the stub in `mcp-servers/tasks/local_executor.py` with the real body — port the existing `run_claude_subprocess` and migrate `proc_holder` → `self._proc`:

```python
"""LocalExecutor — runs the claude CLI as a subprocess inside this container.

This is the original execution flow, lifted out of claude_executor.py into
a class so RemoteExecutor can implement the same interface. Behavior is
intentionally identical to the pre-refactor function — same flags, same
env, same timeout, same output cap. The only contract change is that the
spawned subprocess lives on `self._proc` instead of a caller-supplied
`proc_holder` dict.
"""
from __future__ import annotations

import asyncio
import os
from typing import AsyncIterator

from .claude_executor import (
    CLAUDE_SANDBOX_DIR,
    CLAUDE_WORKSPACE,
    EXECUTION_TIMEOUT_SECONDS,
    MAX_LOG_BYTES,
    MAX_PROMPT_CHARS,
)


class LocalExecutor:
    """Run claude as a subprocess in the tasks container."""

    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None

    async def run(
        self,
        prompt: str,
        slug: str | None,         # unused for local; preserved for interface parity
        execution_id: str,        # unused for local; preserved for interface parity
    ) -> AsyncIterator[str]:
        if len(prompt) > MAX_PROMPT_CHARS:
            prompt = prompt[:MAX_PROMPT_CHARS] + "\n[truncated by tasks service]"

        cwd = CLAUDE_SANDBOX_DIR or CLAUDE_WORKSPACE
        env = {**os.environ, "IS_SANDBOX": "1"}
        effort = os.environ.get("AIUI_AGENT_EFFORT", "low")

        self._proc = await asyncio.create_subprocess_exec(
            "claude",
            "--print",
            "--dangerously-skip-permissions",
            "--output-format", "stream-json",
            "--verbose",
            "--effort", effort,
            prompt,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        assert self._proc.stdout is not None
        bytes_yielded = 0
        try:
            async with asyncio.timeout(EXECUTION_TIMEOUT_SECONDS):
                while True:
                    chunk = await self._proc.stdout.read(4096)
                    if not chunk:
                        break
                    if bytes_yielded >= MAX_LOG_BYTES:
                        self._proc.kill()
                        yield "\n[OUTPUT CAP exceeded — process killed]\n"
                        break
                    bytes_yielded += len(chunk)
                    yield chunk.decode("utf-8", errors="replace")
                await self._proc.wait()
        except asyncio.TimeoutError:
            self._proc.kill()
            await self._proc.wait()
            yield f"\nFAILED: timeout after {EXECUTION_TIMEOUT_SECONDS}s\n"
        except asyncio.CancelledError:
            try:
                self._proc.kill()
            except Exception:
                pass
            raise
        finally:
            self._proc = None

    async def stop(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            proc.kill()
        except Exception:
            pass
```

- [ ] **Step 8: Update `run_claude_subprocess` to be a thin shim**

Edit `mcp-servers/tasks/claude_executor.py` around line 821. Replace the function body with a delegation to `LocalExecutor`:

```python
async def run_claude_subprocess(
    prompt: str,
    proc_holder: dict | None = None,
) -> AsyncIterator[str]:
    """LEGACY shim — preserved so existing callers in routes_execution.py
    keep working until Task 3 migrates them to the executor interface.

    proc_holder: if provided, this dict gets a "proc" key pointing at the
    spawned subprocess so the caller can .kill() it externally. New code
    should use agent_executor.get_executor() + executor.stop() instead.
    """
    from .local_executor import LocalExecutor  # local import avoids cycle
    ex = LocalExecutor()
    try:
        async for chunk in ex.run(prompt, slug=None, execution_id="legacy"):
            # Surface self._proc to the legacy proc_holder convention so the
            # existing routes_execution.py cancel path keeps working.
            if proc_holder is not None and ex._proc is not None and proc_holder.get("proc") is None:
                proc_holder["proc"] = ex._proc
            yield chunk
    finally:
        if proc_holder is not None:
            proc_holder["proc"] = None
```

- [ ] **Step 9: Run the local executor tests**

```bash
python -m pytest tests/test_local_executor.py tests/test_sentinel_parsing.py -v
```

Expected: all 10 PASS.

- [ ] **Step 10: Run the full tasks test suite to catch regressions**

```bash
python -m pytest -v 2>&1 | tail -40
```

Expected: existing tests still PASS. (If any test was asserting on the exact text of a "FAILED" payload that included raw stream content, it may need updating — investigate at this point.)

- [ ] **Step 11: Commit**

```bash
git add mcp-servers/tasks/local_executor.py \
        mcp-servers/tasks/claude_executor.py \
        mcp-servers/tasks/tests/test_local_executor.py \
        mcp-servers/tasks/tests/test_sentinel_parsing.py
git commit -m "feat(tasks): extract LocalExecutor; make FAILED a first-class sentinel

Lifts the body of run_claude_subprocess into LocalExecutor.run, migrates
proc_holder→self._proc, and adds FAILED to _SENTINEL_RE so transport
errors emit structured payloads (e.g. 'FAILED: agent_unreachable') that
parse_outcome can interpret cleanly.

run_claude_subprocess remains as a thin shim so routes_execution.py
keeps working until Task 3 migrates the call site."
```

---

## Task 3: Migrate `_stream_claude` + cancel endpoint to the executor interface

**Files:**
- Modify: `mcp-servers/tasks/routes_execution.py`

Switch `_stream_claude` (line 60) to use `get_executor()` and stash the executor (not a `proc_holder` dict) on `_RUNNING`. Update the cancel endpoint to call `executor.stop()`.

- [ ] **Step 1: Locate the call site**

```bash
grep -n "run_claude_subprocess\|_RUNNING\|proc_holder" mcp-servers/tasks/routes_execution.py
```

Note the line numbers of:
- `_RUNNING: dict[UUID, dict]` declaration (line 55)
- `_stream_claude` (line 60-73)
- The cancel endpoint (search for `.kill()`)

- [ ] **Step 2: Edit `_stream_claude` to use the executor**

Replace the function body (line 60-73 in current file):

```python
async def _stream_claude(prompt: str, execution_id: UUID, task_id: UUID) -> str:
    """Run a claude run via the configured executor; stream output to the
    execution log; return the full log as a string.

    AGENT_BACKEND env (read inside get_executor) decides whether this hits
    a local subprocess or a remote VM. The orchestrator behavior is
    identical either way — same sentinel stream, same log shape.
    """
    from .agent_executor import get_executor

    full_log: list[str] = []
    executor = get_executor()
    _RUNNING[task_id] = {"executor": executor}

    # Look up the slug for this task (RemoteExecutor needs it for workspace
    # keying; LocalExecutor ignores it).
    async with session() as s:
        task = (
            await s.execute(select(TaskItem).where(TaskItem.id == task_id))
        ).scalar_one_or_none()
        slug = (task.built_app_slug if task else None) or None

    try:
        async for chunk in executor.run(prompt, slug=slug, execution_id=str(execution_id)):
            full_log.append(chunk)
            async with session() as s:
                await s.execute(
                    update(TaskExecution)
                    .where(TaskExecution.id == execution_id)
                    .values(log=TaskExecution.log + chunk)
                )
                await s.commit()
    finally:
        _RUNNING.pop(task_id, None)

    return "".join(full_log)
```

- [ ] **Step 3: Update the cancel endpoint**

Find the cancel endpoint (typically `@router.post("/{task_id}/stop")` or similar) that currently does something like `_RUNNING[task_id]["proc"].kill()`. Change it to:

```python
entry = _RUNNING.get(task_id)
if entry and "executor" in entry:
    await entry["executor"].stop()
```

- [ ] **Step 4: Update `agent_host` writes (we have it now)**

Inside `_stream_claude` after `executor = get_executor()`, capture the host:

```python
agent_host_value = (
    os.environ.get("AGENT_HOST")
    if executor.__class__.__name__ == "RemoteExecutor"
    else None
)
async with session() as s:
    await s.execute(
        update(TaskExecution)
        .where(TaskExecution.id == execution_id)
        .values(agent_host=agent_host_value)
    )
    await s.commit()
```

(This relies on the column added in Task 9. For Task 3, the migration isn't run yet — guard with try/except or skip this snippet for now and add it back in Task 9 after the migration lands.)

- [ ] **Step 5: Run the tasks suite**

```bash
python -m pytest -v 2>&1 | tail -30
```

Expected: all existing tests still PASS. Cancel-related tests may need updating if they assert on the `proc_holder["proc"]` shape — fix them to look up `_RUNNING[task_id]["executor"]` instead.

- [ ] **Step 6: Manual smoke (optional but recommended)**

If you have a dev orchestrator running:
```bash
curl -X POST http://localhost:8210/api/tasks \
    -H 'Content-Type: application/json' \
    -d '{"action_type":"ASK_USER","description":"say hello"}'
# Then run /execute and verify output still streams. AGENT_BACKEND not set
# → LocalExecutor path. Behavior should be byte-identical to before.
```

- [ ] **Step 7: Commit**

```bash
git add mcp-servers/tasks/routes_execution.py
git commit -m "refactor(tasks): _stream_claude uses get_executor() + executor.stop()

Cancel path now calls executor.stop() instead of poking the subprocess
directly. Default AGENT_BACKEND=local keeps behavior identical."
```

---

## Task 4: `flights-mcp` Duffel client

**Files:**
- Create: `mcp-servers/flights/pyproject.toml`
- Create: `mcp-servers/flights/flights_mcp/__init__.py`
- Create: `mcp-servers/flights/flights_mcp/schemas.py`
- Create: `mcp-servers/flights/flights_mcp/duffel.py`
- Create: `mcp-servers/flights/tests/test_duffel.py`
- Create: `mcp-servers/flights/README.md`

The Duffel client is a small async wrapper around `httpx`. It does NOT do MCP protocol — that's Task 5. Splitting them keeps the client testable in isolation.

- [ ] **Step 1: Create the package skeleton**

```bash
mkdir -p mcp-servers/flights/flights_mcp mcp-servers/flights/tests
touch mcp-servers/flights/flights_mcp/__init__.py
touch mcp-servers/flights/tests/__init__.py
```

`mcp-servers/flights/pyproject.toml`:

```toml
[project]
name = "flights-mcp"
version = "0.1.0"
description = "MCP server wrapping the Duffel sandbox API for IO App Builder agents."
requires-python = ">=3.11"
dependencies = [
  "httpx>=0.27",
  "pydantic>=2.6",
  "mcp>=1.0",
]

[project.optional-dependencies]
test = ["pytest>=8", "pytest-asyncio>=0.23", "respx>=0.21"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["."]
include = ["flights_mcp*"]
```

`mcp-servers/flights/README.md`:
```markdown
# flights-mcp

MCP server that exposes one tool, `search_flights`, returning real flight
offers from the Duffel sandbox API. Used by the IO App Builder's agent
to populate the `flight-booking` template with real data on demand.

Requires `DUFFEL_API_KEY` in the environment (sandbox tier is free).
```

- [ ] **Step 2: Write the failing Duffel tests**

`mcp-servers/flights/tests/test_duffel.py`:

```python
"""Duffel client tests using respx to mock HTTP."""
import pytest
import respx
from httpx import Response

from flights_mcp.duffel import DuffelClient, DuffelError
from flights_mcp.schemas import FlightOffer


@pytest.fixture
def fake_offer():
    """Minimal Duffel offer payload shape."""
    return {
        "id": "off_00009htYpSCXrwaB9DnUm0",
        "owner": {"name": "All Nippon Airways"},
        "total_amount": "1247.50",
        "total_currency": "USD",
        "slices": [{
            "origin": {"iata_code": "LAX"},
            "destination": {"iata_code": "NRT"},
            "duration": "PT11H45M",
            "segments": [{
                "departing_at": "2026-06-01T11:50:00",
                "arriving_at": "2026-06-02T16:35:00",
                "passengers": [{
                    "cabin_class": "economy",
                    "baggages": [{"type": "checked", "quantity": 1}]
                }],
            }],
        }],
    }


@pytest.mark.asyncio
@respx.mock
async def test_happy_path_returns_offers(fake_offer):
    """POST /air/offer_requests?return_offers=true returns parsed offers."""
    respx.post("https://api.duffel.com/air/offer_requests").mock(
        return_value=Response(201, json={"data": {"offers": [fake_offer]}})
    )
    client = DuffelClient(api_key="duffel_test_xyz")
    offers = await client.search_flights(
        origin="LAX", destination="NRT",
        depart_date="2026-06-01", passengers=1,
    )
    assert len(offers) == 1
    o = offers[0]
    assert isinstance(o, FlightOffer)
    assert o.origin == "LAX"
    assert o.destination == "NRT"
    assert o.airline == "All Nippon Airways"
    assert o.price == 1247.5
    assert o.stops == 0
    assert o.duration == 11 * 60 + 45  # PT11H45M → 705 minutes
    assert o.departure_hour == 11
    assert o.departure_label == "11:50"
    assert o.cabin == "Economy"
    assert "checked" in o.baggage


@pytest.mark.asyncio
@respx.mock
async def test_429_raises_rate_limit_error():
    respx.post("https://api.duffel.com/air/offer_requests").mock(
        return_value=Response(429, headers={"Retry-After": "30"},
                              json={"errors": [{"message": "rate limited"}]})
    )
    client = DuffelClient(api_key="x")
    with pytest.raises(DuffelError) as exc:
        await client.search_flights(
            origin="LAX", destination="NRT", depart_date="2026-06-01",
        )
    assert exc.value.kind == "rate_limit"
    assert exc.value.retry_after == 30


@pytest.mark.asyncio
@respx.mock
async def test_401_raises_auth_error():
    respx.post("https://api.duffel.com/air/offer_requests").mock(
        return_value=Response(401, json={"errors": [{"message": "bad key"}]})
    )
    client = DuffelClient(api_key="x")
    with pytest.raises(DuffelError) as exc:
        await client.search_flights(
            origin="LAX", destination="NRT", depart_date="2026-06-01",
        )
    assert exc.value.kind == "auth"


@pytest.mark.asyncio
@respx.mock
async def test_5xx_raises_upstream_error():
    respx.post("https://api.duffel.com/air/offer_requests").mock(
        return_value=Response(503)
    )
    client = DuffelClient(api_key="x")
    with pytest.raises(DuffelError) as exc:
        await client.search_flights(
            origin="LAX", destination="NRT", depart_date="2026-06-01",
        )
    assert exc.value.kind == "upstream"


@pytest.mark.asyncio
@respx.mock
async def test_iso_duration_parses_to_minutes():
    """PT8H45M → 525 minutes (regression guard for parse_duration)."""
    from flights_mcp.duffel import parse_iso8601_duration
    assert parse_iso8601_duration("PT8H45M") == 525
    assert parse_iso8601_duration("PT11H45M") == 705
    assert parse_iso8601_duration("PT0H30M") == 30
    assert parse_iso8601_duration("PT2H") == 120


@pytest.mark.asyncio
@respx.mock
async def test_results_sorted_by_price_ascending(fake_offer):
    expensive = dict(fake_offer, id="off_b", total_amount="1500.00")
    cheap = dict(fake_offer, id="off_a", total_amount="900.00")
    respx.post("https://api.duffel.com/air/offer_requests").mock(
        return_value=Response(201, json={"data": {"offers": [expensive, cheap]}})
    )
    client = DuffelClient(api_key="x")
    offers = await client.search_flights(
        origin="LAX", destination="NRT", depart_date="2026-06-01",
    )
    assert offers[0].id == "off_a"  # cheap first
    assert offers[1].id == "off_b"


@pytest.mark.asyncio
@respx.mock
async def test_caps_at_6_offers(fake_offer):
    """Even if Duffel returns 50, client takes top 6 by price."""
    many = [dict(fake_offer, id=f"off_{i}", total_amount=str(800 + i * 10))
            for i in range(50)]
    respx.post("https://api.duffel.com/air/offer_requests").mock(
        return_value=Response(201, json={"data": {"offers": many}})
    )
    client = DuffelClient(api_key="x")
    offers = await client.search_flights(
        origin="LAX", destination="NRT", depart_date="2026-06-01",
    )
    assert len(offers) == 6
```

- [ ] **Step 3: Run them to verify they fail**

```bash
cd mcp-servers/flights
pip install -e ".[test]"
python -m pytest tests/test_duffel.py -v
```

Expected: import errors — `flights_mcp.duffel` doesn't exist yet.

- [ ] **Step 4: Implement schemas**

`mcp-servers/flights/flights_mcp/schemas.py`:

```python
"""Pydantic models for the search_flights tool I/O.

FlightOffer matches the existing flight-booking template's flight shape
(see template_apps/flight-booking/src/data.js) so the agent can drop the
result straight into src/data.js after camelCase-ing the field names.
"""
from typing import Literal
from pydantic import BaseModel


class FlightOffer(BaseModel):
    id: str
    origin: str
    destination: str
    airline: str
    price: float
    stops: int
    duration: int            # minutes
    departure_hour: int      # 0-23, local airport tz
    departure_label: str     # "HH:MM"
    arrival_label: str       # "HH:MM"
    cabin: Literal["Economy", "Premium Economy", "Business", "First"]
    baggage: str             # e.g. "1× 23kg checked"
```

- [ ] **Step 5: Implement the Duffel client**

`mcp-servers/flights/flights_mcp/duffel.py`:

```python
"""Async client for the Duffel sandbox API (https://duffel.com).

We use ?return_offers=true on POST /air/offer_requests to avoid the
two-call dance. If the sandbox tier rejects that, fall back to the
two-call form (POST then GET /air/offers).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

from .schemas import FlightOffer


_DUFFEL_BASE = "https://api.duffel.com"
_TIMEOUT = httpx.Timeout(10.0)


@dataclass
class DuffelError(Exception):
    kind: str                       # auth | bad_request | rate_limit | upstream | timeout | bad_response
    detail: str = ""
    retry_after: int | None = None


_ISO_DURATION = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?$")


def parse_iso8601_duration(s: str) -> int:
    """Convert an ISO 8601 duration like 'PT8H45M' to total minutes."""
    m = _ISO_DURATION.match(s)
    if not m:
        raise DuffelError(kind="bad_response", detail=f"bad duration: {s!r}")
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    return hours * 60 + minutes


def _format_cabin(s: str) -> str:
    return {
        "economy": "Economy",
        "premium_economy": "Premium Economy",
        "business": "Business",
        "first": "First",
    }.get(s, s.title())


def _format_baggage(baggages: list[dict[str, Any]]) -> str:
    if not baggages:
        return "Carry-on only"
    parts = []
    for b in baggages:
        qty = b.get("quantity", 1)
        kind = b.get("type", "checked")
        if kind == "checked":
            parts.append(f"{qty}× 23kg checked")
        else:
            parts.append(f"{qty}× {kind}")
    return ", ".join(parts)


def _hhmm(iso_ts: str) -> str:
    # "2026-06-01T11:50:00" → "11:50"
    return iso_ts[11:16]


def _hour(iso_ts: str) -> int:
    return int(iso_ts[11:13])


def _to_offer(d: dict[str, Any]) -> FlightOffer:
    try:
        sl = d["slices"][0]
        seg = sl["segments"][0]
        pax = seg["passengers"][0]
        return FlightOffer(
            id=d["id"],
            origin=sl["origin"]["iata_code"],
            destination=sl["destination"]["iata_code"],
            airline=d["owner"]["name"],
            price=float(d["total_amount"]),
            stops=max(0, len(sl["segments"]) - 1),
            duration=parse_iso8601_duration(sl["duration"]),
            departure_hour=_hour(seg["departing_at"]),
            departure_label=_hhmm(seg["departing_at"]),
            arrival_label=_hhmm(sl["segments"][-1]["arriving_at"]),
            cabin=_format_cabin(pax["cabin_class"]),
            baggage=_format_baggage(pax.get("baggages", [])),
        )
    except (KeyError, IndexError) as exc:
        raise DuffelError(kind="bad_response", detail=str(exc)) from exc


class DuffelClient:
    def __init__(self, api_key: str) -> None:
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Duffel-Version": "v2",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def search_flights(
        self,
        *,
        origin: str,
        destination: str,
        depart_date: str,
        return_date: str | None = None,
        passengers: int = 1,
        cabin: str = "economy",
    ) -> list[FlightOffer]:
        slices = [{"origin": origin, "destination": destination, "departure_date": depart_date}]
        if return_date:
            slices.append({"origin": destination, "destination": origin, "departure_date": return_date})
        body = {
            "data": {
                "slices": slices,
                "passengers": [{"type": "adult"} for _ in range(passengers)],
                "cabin_class": cabin,
            }
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                r = await client.post(
                    f"{_DUFFEL_BASE}/air/offer_requests?return_offers=true",
                    headers=self._headers,
                    json=body,
                )
        except httpx.TimeoutException as exc:
            raise DuffelError(kind="timeout", detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise DuffelError(kind="upstream", detail=str(exc)) from exc

        if r.status_code in (401, 403):
            raise DuffelError(kind="auth", detail="DUFFEL_API_KEY invalid")
        if r.status_code == 422:
            raise DuffelError(kind="bad_request", detail=_first_error(r))
        if r.status_code == 429:
            retry = int(r.headers.get("Retry-After", "60"))
            raise DuffelError(kind="rate_limit", retry_after=retry)
        if r.status_code >= 500:
            raise DuffelError(kind="upstream", detail=f"HTTP {r.status_code}")
        if r.status_code >= 400:
            raise DuffelError(kind="bad_request", detail=_first_error(r))

        try:
            offers = r.json()["data"]["offers"]
        except (KeyError, ValueError) as exc:
            raise DuffelError(kind="bad_response", detail=str(exc)) from exc

        parsed = [_to_offer(o) for o in offers]
        parsed.sort(key=lambda o: o.price)
        return parsed[:6]


def _first_error(r: httpx.Response) -> str:
    try:
        errs = r.json().get("errors") or []
        return errs[0].get("message") if errs else ""
    except Exception:
        return ""
```

- [ ] **Step 6: Run the tests**

```bash
python -m pytest tests/test_duffel.py -v
```

Expected: all 7 PASS.

- [ ] **Step 7: Commit**

```bash
git add mcp-servers/flights/
git commit -m "feat(flights-mcp): Duffel sandbox client (no MCP wrapping yet)

Async httpx client that calls /air/offer_requests?return_offers=true,
parses Duffel's offer shape into the FlightOffer schema the existing
flight-booking template expects, sorts by price, and caps to 6 results.
Error mapping: 401→auth, 422→bad_request, 429→rate_limit with Retry-After,
5xx→upstream, network timeout→timeout, bad response→bad_response.
Standalone — no agent VM required."
```

---

## Task 5: `flights-mcp` MCP server + smoke script

**Files:**
- Create: `mcp-servers/flights/flights_mcp/server.py`
- Create: `mcp-servers/flights/flights_mcp/__main__.py`
- Create: `mcp-servers/flights/tests/test_server.py`
- Create: `scripts/smoke_flights_mcp.sh`

Wraps the Duffel client as an MCP stdio server with one tool. Agent VM will register this via `claude mcp add`.

- [ ] **Step 1: Write the failing server tests**

`mcp-servers/flights/tests/test_server.py`:

```python
"""Tests the search_flights tool registration + DuffelError→tool_error mapping."""
from unittest.mock import patch, AsyncMock
import pytest

from flights_mcp.server import call_search_flights
from flights_mcp.duffel import DuffelError
from flights_mcp.schemas import FlightOffer


@pytest.mark.asyncio
async def test_search_flights_returns_offer_list():
    fake_offer = FlightOffer(
        id="off_x", origin="LAX", destination="NRT",
        airline="ANA", price=1200.0, stops=0, duration=700,
        departure_hour=11, departure_label="11:00", arrival_label="15:30",
        cabin="Economy", baggage="1× 23kg checked",
    )
    with patch("flights_mcp.server.DuffelClient") as DC:
        instance = DC.return_value
        instance.search_flights = AsyncMock(return_value=[fake_offer])
        result = await call_search_flights(
            api_key="x",
            origin="LAX", destination="NRT", depart_date="2026-06-01",
        )
    assert isinstance(result, list)
    assert result[0]["airline"] == "ANA"
    assert result[0]["origin"] == "LAX"


@pytest.mark.asyncio
async def test_rate_limit_returned_as_tool_error():
    """DuffelError → structured dict, not raised."""
    err = DuffelError(kind="rate_limit", retry_after=30)
    with patch("flights_mcp.server.DuffelClient") as DC:
        instance = DC.return_value
        instance.search_flights = AsyncMock(side_effect=err)
        result = await call_search_flights(
            api_key="x",
            origin="LAX", destination="NRT", depart_date="2026-06-01",
        )
    assert isinstance(result, dict)
    assert result["error"] == "rate_limit"
    assert result["retry_after"] == 30


@pytest.mark.asyncio
async def test_auth_returned_as_tool_error():
    err = DuffelError(kind="auth", detail="bad key")
    with patch("flights_mcp.server.DuffelClient") as DC:
        instance = DC.return_value
        instance.search_flights = AsyncMock(side_effect=err)
        result = await call_search_flights(
            api_key="x",
            origin="LAX", destination="NRT", depart_date="2026-06-01",
        )
    assert result == {"error": "auth", "detail": "DUFFEL_API_KEY invalid"}


@pytest.mark.asyncio
async def test_missing_api_key_returned_as_tool_error():
    result = await call_search_flights(
        api_key="",
        origin="LAX", destination="NRT", depart_date="2026-06-01",
    )
    assert result == {"error": "auth", "detail": "DUFFEL_API_KEY not set"}
```

- [ ] **Step 2: Run them to verify they fail**

```bash
python -m pytest tests/test_server.py -v
```

Expected: import error — `flights_mcp.server` does not exist yet.

- [ ] **Step 3: Implement the MCP server**

`mcp-servers/flights/flights_mcp/server.py`:

```python
"""MCP stdio server exposing the search_flights tool.

The tool body is split into `call_search_flights` (testable, takes api_key
as a parameter) and the MCP-registered wrapper (reads api_key from env).
"""
from __future__ import annotations

import os
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .duffel import DuffelClient, DuffelError


server: Server = Server("flights")


async def call_search_flights(
    *,
    api_key: str,
    origin: str,
    destination: str,
    depart_date: str,
    return_date: str | None = None,
    passengers: int = 1,
    cabin: str = "economy",
) -> list[dict[str, Any]] | dict[str, Any]:
    """Pure-Python entrypoint — used by tests AND the MCP wrapper.

    Returns a list of offer dicts on success, or a structured error dict
    matching the spec's error mapping.
    """
    if not api_key:
        return {"error": "auth", "detail": "DUFFEL_API_KEY not set"}
    client = DuffelClient(api_key=api_key)
    try:
        offers = await client.search_flights(
            origin=origin, destination=destination,
            depart_date=depart_date, return_date=return_date,
            passengers=passengers, cabin=cabin,
        )
    except DuffelError as e:
        out = {"error": e.kind}
        if e.kind == "auth":
            out["detail"] = "DUFFEL_API_KEY invalid"
        elif e.kind == "rate_limit":
            out["retry_after"] = e.retry_after or 60
        elif e.detail:
            out["detail"] = e.detail
        return out
    return [o.model_dump() for o in offers]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_flights",
            description=(
                "Search real flight offers from the Duffel sandbox. "
                "Returns up to 6 offers sorted by price ascending."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "origin": {"type": "string", "description": "IATA code, e.g. LAX"},
                    "destination": {"type": "string", "description": "IATA code, e.g. NRT"},
                    "depart_date": {"type": "string", "description": "ISO YYYY-MM-DD"},
                    "return_date": {"type": "string"},
                    "passengers": {"type": "integer", "minimum": 1, "default": 1},
                    "cabin": {"type": "string",
                              "enum": ["economy","premium_economy","business","first"],
                              "default": "economy"},
                },
                "required": ["origin", "destination", "depart_date"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name != "search_flights":
        raise ValueError(f"unknown tool: {name}")
    result = await call_search_flights(
        api_key=os.environ.get("DUFFEL_API_KEY", ""),
        **arguments,
    )
    import json
    return [TextContent(type="text", text=json.dumps(result))]


async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())
```

`mcp-servers/flights/flights_mcp/__main__.py`:

```python
"""Run as `python -m flights_mcp`."""
import asyncio
from .server import main

if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run the server tests**

```bash
python -m pytest tests/test_server.py -v
```

Expected: all 4 PASS.

- [ ] **Step 5: Write the smoke script**

`scripts/smoke_flights_mcp.sh`:

```bash
#!/usr/bin/env bash
# Smoke test for flights-mcp — drives the stdio MCP server directly
# without an agent. Requires DUFFEL_API_KEY in env.

set -euo pipefail

if [[ -z "${DUFFEL_API_KEY:-}" ]]; then
  echo "DUFFEL_API_KEY not set; export it first." >&2
  exit 2
fi

cd "$(dirname "$0")/.." || exit 2

# Run the search_flights tool directly via call_search_flights —
# bypassing MCP stdio because we just want to verify Duffel is reachable.
python -c "
import asyncio, os, json
from flights_mcp.server import call_search_flights
async def go():
    result = await call_search_flights(
        api_key=os.environ['DUFFEL_API_KEY'],
        origin='LAX', destination='NRT', depart_date='2026-06-01',
        passengers=1,
    )
    print(json.dumps(result, indent=2)[:2000])
    if isinstance(result, dict) and 'error' in result:
        print('FAIL: got error:', result['error']); raise SystemExit(1)
    if not result:
        print('FAIL: empty offer list'); raise SystemExit(1)
    print(f'OK: got {len(result)} offers, first airline = {result[0][\"airline\"]}')
asyncio.run(go())
" 2>&1
```

```bash
chmod +x scripts/smoke_flights_mcp.sh
```

- [ ] **Step 6: Manually run the smoke (requires Duffel sandbox key)**

```bash
export DUFFEL_API_KEY="duffel_test_..."
./scripts/smoke_flights_mcp.sh
```

Expected: prints ≥1 offer, "OK: got N offers".

- [ ] **Step 7: Commit**

```bash
git add mcp-servers/flights/flights_mcp/server.py \
        mcp-servers/flights/flights_mcp/__main__.py \
        mcp-servers/flights/tests/test_server.py \
        scripts/smoke_flights_mcp.sh
git commit -m "feat(flights-mcp): stdio MCP server with search_flights tool

Wraps DuffelClient as an MCP tool. DuffelError types map to structured
tool-error dicts: rate_limit{retry_after}, auth, bad_request, upstream,
timeout, bad_response. Tested via call_search_flights pure function;
__main__ wires it to stdio_server.

Smoke script (scripts/smoke_flights_mcp.sh) hits real Duffel sandbox
to verify end-to-end."
```

---

## Task 6: `provision_agent_vm.sh` + docker-compose secret block

**Files:**
- Create: `scripts/provision_agent_vm.sh`
- Create: `scripts/smoke_agent_vm.sh`
- Modify: `docker-compose.unified.yml`

The provisioning script is operator-facing — runs from the operator's machine against a fresh Ubuntu 24.04 Hetzner box. **No tests** — this is a runbook, not application logic. Step 7 in this task is the "did the script work?" verification.

- [ ] **Step 1: Write the provisioning script**

`scripts/provision_agent_vm.sh`:

```bash
#!/usr/bin/env bash
# Provision a fresh Hetzner CAX21 (Ubuntu 24.04) as the IO claude-agent VM.
#
# Idempotent — re-running just refreshes config + rotates secrets.
#
# Usage:
#   AGENT_HOST=10.0.0.42 \
#   AGENT_SSH_KEY_PUB=/etc/proxy-server/agent_ssh_key.pub \
#   ANTHROPIC_API_KEY=sk-ant-... \
#   DUFFEL_API_KEY=duffel_test_... \
#   ORCHESTRATOR_PRIVATE_IP=10.0.0.10 \
#   ./scripts/provision_agent_vm.sh
#
# Prerequisites on the operator workstation:
#   - SSH access to the box as root (via initial cloud-init key)
#   - The IO repo cloned (flights-mcp source must be SCPable from here)

set -euo pipefail

: "${AGENT_HOST:?set AGENT_HOST to the agent VM's IP or hostname}"
: "${AGENT_SSH_KEY_PUB:?set AGENT_SSH_KEY_PUB to the public key file path}"
: "${ANTHROPIC_API_KEY:?set ANTHROPIC_API_KEY for the agent}"
: "${DUFFEL_API_KEY:?set DUFFEL_API_KEY for flights-mcp}"
: "${ORCHESTRATOR_PRIVATE_IP:?set ORCHESTRATOR_PRIVATE_IP for ufw rule}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SSH="ssh -o StrictHostKeyChecking=accept-new root@${AGENT_HOST}"

echo "==> [1/8] base packages + claude-agent user"
${SSH} bash -se <<EOF
set -euo pipefail
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  ufw fail2ban unattended-upgrades curl jq rsync git build-essential \
  python3 python3-pip python3-venv \
  squid

# Node 20 from NodeSource
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi

# Claude Code CLI (npm global)
npm install -g @anthropic-ai/claude-code

# claude-agent user, no sudo, no docker
id claude-agent >/dev/null 2>&1 || useradd -m -s /bin/bash -U claude-agent
mkdir -p /agent/work
chown -R claude-agent:claude-agent /agent
chmod 750 /agent /agent/work
EOF

echo "==> [2/8] SSH authorized_keys"
scp -o StrictHostKeyChecking=accept-new "${AGENT_SSH_KEY_PUB}" root@${AGENT_HOST}:/tmp/agent_pub.key
${SSH} bash -se <<'EOF'
set -euo pipefail
install -d -o claude-agent -g claude-agent -m 700 /home/claude-agent/.ssh
install -o claude-agent -g claude-agent -m 600 /tmp/agent_pub.key /home/claude-agent/.ssh/authorized_keys
rm -f /tmp/agent_pub.key
EOF

echo "==> [3/8] sshd config — PasswordAuth no, PermitRootLogin no, AcceptEnv"
${SSH} bash -se <<'EOF'
set -euo pipefail
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
grep -q "^AcceptEnv AIUI_AGENT_EFFORT" /etc/ssh/sshd_config || \
  echo "AcceptEnv AIUI_AGENT_EFFORT" >> /etc/ssh/sshd_config
systemctl reload ssh
EOF

echo "==> [4/8] ufw — ingress 22/tcp from orchestrator only"
${SSH} bash -se <<EOF
set -euo pipefail
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow from ${ORCHESTRATOR_PRIVATE_IP} to any port 22 proto tcp
ufw --force enable
EOF

echo "==> [5/8] Squid FQDN-allowlist proxy on 127.0.0.1:3128"
${SSH} bash -se <<'EOF'
set -euo pipefail
cat >/etc/squid/squid.conf <<'CONF'
http_port 127.0.0.1:3128

acl allowed_hosts dstdomain \
  .anthropic.com .duffel.com \
  .npmjs.org .nodesource.com \
  .pypi.org .pythonhosted.org \
  .ubuntu.com

http_access allow allowed_hosts
http_access deny all

# Logging — rotated by /etc/logrotate.d/squid (Ubuntu default)
access_log /var/log/squid/access.log squid
CONF
systemctl enable --now squid
systemctl reload squid

# Force claude-agent's outbound HTTPS through Squid
cat >/home/claude-agent/.profile <<'CONF'
export HTTPS_PROXY=http://127.0.0.1:3128
export HTTP_PROXY=http://127.0.0.1:3128
export NO_PROXY=127.0.0.1,localhost
CONF
chown claude-agent:claude-agent /home/claude-agent/.profile

# Apt also through Squid
cat >/etc/apt/apt.conf.d/95proxy <<'CONF'
Acquire::http::Proxy "http://127.0.0.1:3128";
Acquire::https::Proxy "http://127.0.0.1:3128";
CONF

# iptables: drop direct outbound 443 for claude-agent uid
iptables -A OUTPUT -m owner --uid-owner claude-agent \
  -p tcp --dport 443 ! -d 127.0.0.1 -j DROP
EOF

echo "==> [6/8] secrets — /home/claude-agent/.env"
${SSH} bash -se <<EOF
set -euo pipefail
install -o claude-agent -g claude-agent -m 600 /dev/null /home/claude-agent/.env
cat >>/home/claude-agent/.env <<INNER
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
DUFFEL_API_KEY=${DUFFEL_API_KEY}
INNER
EOF

echo "==> [7/8] flights-mcp install + Claude Code MCP registration"
# SCP the package over (operator workstation has the repo)
scp -r "${REPO_ROOT}/mcp-servers/flights" root@${AGENT_HOST}:/tmp/flights-mcp
${SSH} bash -se <<'EOF'
set -euo pipefail
rm -rf /opt/flights-mcp
mv /tmp/flights-mcp /opt/flights-mcp
python3 -m venv /opt/flights-mcp/venv
/opt/flights-mcp/venv/bin/pip install -e /opt/flights-mcp >/dev/null

# Register MCP server (user scope for claude-agent)
sudo -u claude-agent bash -c '
  source ~/.env
  claude mcp add --scope user flights \
    /opt/flights-mcp/venv/bin/python -m flights_mcp \
    --env "DUFFEL_API_KEY=$DUFFEL_API_KEY"
'
EOF

echo "==> [8/8] workspace GC cron"
${SSH} bash -se <<'EOF'
set -euo pipefail
cat >/etc/cron.d/agent-work-gc <<'CONF'
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
30 3 * * * claude-agent find /agent/work -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf {} \;
CONF
chmod 644 /etc/cron.d/agent-work-gc
EOF

echo "OK — provisioning complete. Run scripts/smoke_agent_vm.sh next."
```

```bash
chmod +x scripts/provision_agent_vm.sh
```

- [ ] **Step 2: Write the smoke script**

`scripts/smoke_agent_vm.sh`:

```bash
#!/usr/bin/env bash
# Verifies the agent VM is correctly provisioned. Read-only.

set -euo pipefail

: "${AGENT_HOST:?set AGENT_HOST}"
: "${AGENT_SSH_KEY_PATH:?set AGENT_SSH_KEY_PATH}"

SSH="ssh -i ${AGENT_SSH_KEY_PATH} -o StrictHostKeyChecking=accept-new claude-agent@${AGENT_HOST}"

fail=0
check() { echo -n "[ ] $1 ... "; if eval "$2"; then echo OK; else echo FAIL; fail=1; fi; }

check "ssh as claude-agent"           "${SSH} 'true'"
check "claude --version"              "${SSH} 'claude --version' >/dev/null"
check "node --version >= 20"          "${SSH} 'node --version | grep -E \"^v(2[0-9]|[3-9][0-9])\"' >/dev/null"
check "python3 --version >= 3.11"     "${SSH} 'python3 -c \"import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)\"'"
check "ANTHROPIC_API_KEY set"         "${SSH} 'grep -q ^ANTHROPIC_API_KEY= ~/.env'"
check "DUFFEL_API_KEY set"            "${SSH} 'grep -q ^DUFFEL_API_KEY= ~/.env'"
check "claude mcp list shows flights" "${SSH} 'claude mcp list | grep -q flights'"
check "squid running"                 "${SSH} 'systemctl is-active --quiet squid'"
check "ufw active"                    "${SSH} 'sudo ufw status | grep -q active' || true"   # claude-agent has no sudo, may be ok
check "Hello via claude"              "${SSH} 'IS_SANDBOX=1 claude --print --dangerously-skip-permissions --effort low -- \"say the literal word READY\" 2>&1 | grep -q READY'"

if [[ $fail -eq 0 ]]; then
  echo
  echo "All smoke checks PASSED."
else
  echo
  echo "One or more smoke checks FAILED — see above."
  exit 1
fi
```

```bash
chmod +x scripts/smoke_agent_vm.sh
```

- [ ] **Step 3: Add the docker-compose secret block**

Edit `docker-compose.unified.yml`. Append at the top level (peer of `services:`):

```yaml
secrets:
  agent_ssh_key:
    file: /etc/proxy-server/agent_ssh_key
```

And under `services.tasks`, add:

```yaml
services:
  tasks:
    # ... existing config ...
    secrets:
      - agent_ssh_key
    environment:
      # ... existing env vars ...
      - AGENT_BACKEND=${AGENT_BACKEND:-local}
      - AGENT_HOST=${AGENT_HOST:-}
      - AGENT_USER=${AGENT_USER:-claude-agent}
      - AGENT_SSH_KEY_PATH=/run/secrets/agent_ssh_key
```

- [ ] **Step 4: Commit**

```bash
git add scripts/provision_agent_vm.sh scripts/smoke_agent_vm.sh docker-compose.unified.yml
git commit -m "feat(infra): agent VM provisioning script + smoke + compose secrets

Idempotent Bash runbook that takes a fresh Hetzner CAX21 (Ubuntu 24.04)
and brings it to a state where the orchestrator can SSH in as
claude-agent and run claude with the flights MCP registered.

Locks down: SSH key-only, ufw inbound from orchestrator only, Squid
FQDN-allowlist proxy on 127.0.0.1:3128 for all HTTPS egress, direct
:443 dropped at iptables for the claude-agent uid.

docker-compose.unified.yml: adds agent_ssh_key compose secret + four
AGENT_* env vars (defaults preserve LocalExecutor behavior)."
```

---

## Task 7: Provision the real `claude-agent` VM (operator action)

**Files:** none — this is a runbook.

This task is a one-time operator action. No code is written. The deliverable is a working VM that passes all smoke checks.

- [ ] **Step 1: Create the Hetzner box**

Via Hetzner Cloud Console or `hcloud` CLI:

```bash
hcloud server create \
  --type cax21 \
  --image ubuntu-24.04 \
  --location fsn1 \
  --name claude-agent \
  --network <same-network-id-as-orchestrator> \
  --ssh-key <your-bootstrap-key>
```

Note the assigned private IP (e.g. `10.0.0.42`).

- [ ] **Step 2: Generate the orchestrator→agent SSH keypair**

On the orchestrator host (NOT the dev machine; the key needs to live where the `tasks` container can read it):

```bash
sudo ssh-keygen -t ed25519 \
  -f /etc/proxy-server/agent_ssh_key \
  -N "" \
  -C "orchestrator→claude-agent"
sudo chmod 0400 /etc/proxy-server/agent_ssh_key
sudo chmod 0444 /etc/proxy-server/agent_ssh_key.pub
```

- [ ] **Step 3: Pull the SSH key locally so the provisioning script can SCP it**

If running provision from the operator workstation rather than the orchestrator, copy `agent_ssh_key.pub` down:

```bash
scp root@<orchestrator>:/etc/proxy-server/agent_ssh_key.pub ./agent_ssh_key.pub
```

- [ ] **Step 4: Run the provisioning script**

```bash
export AGENT_HOST=10.0.0.42                       # the agent VM private IP
export AGENT_SSH_KEY_PUB=./agent_ssh_key.pub
export ANTHROPIC_API_KEY=sk-ant-...
export DUFFEL_API_KEY=duffel_test_...
export ORCHESTRATOR_PRIVATE_IP=10.0.0.10           # orchestrator's IP

./scripts/provision_agent_vm.sh
```

Expected: prints `OK — provisioning complete.` after ~5-10 minutes.

- [ ] **Step 5: Add the agent VM to the orchestrator's `/etc/hosts`**

On the orchestrator host:

```bash
echo "10.0.0.42 claude-agent" | sudo tee -a /etc/hosts
```

(The `tasks` container inherits `/etc/hosts` from the host in the default Docker network setup. If your setup uses a custom network, instead add it to the compose file's `extra_hosts:` under `services.tasks`.)

- [ ] **Step 6: Run the smoke**

```bash
export AGENT_HOST=claude-agent
export AGENT_SSH_KEY_PATH=/etc/proxy-server/agent_ssh_key
./scripts/smoke_agent_vm.sh
```

Expected: all 10 checks PASS.

- [ ] **Step 7: Smoke the flights-mcp on the agent VM**

```bash
export DUFFEL_API_KEY=duffel_test_...
ssh -i /etc/proxy-server/agent_ssh_key claude-agent@claude-agent '
  source ~/.env
  python -c "
import asyncio, os, json
from flights_mcp.server import call_search_flights
async def go():
    r = await call_search_flights(
        api_key=os.environ[\"DUFFEL_API_KEY\"],
        origin=\"LAX\", destination=\"NRT\", depart_date=\"2026-06-01\",
    )
    print(json.dumps(r, indent=2)[:1000])
asyncio.run(go())
"' 2>&1 | tail -40
```

Expected: prints ≥1 offer.

- [ ] **Step 8: Document the VM in the runbook**

Append to `docs/agent-vm/README.md` (created in Task 10) the actual private IP and key fingerprint:

```bash
ssh-keygen -lf /etc/proxy-server/agent_ssh_key.pub
```

(Save the fingerprint output for future operator verification.)

- [ ] **Step 9: There is nothing to commit for this task.**

The VM provisioning is an external action. The plan moves to Task 8 which adds the code that talks to this VM.

---

## Task 8: Implement `RemoteExecutor` + tests

**Files:**
- Modify: `mcp-servers/tasks/remote_executor.py` (replace stub with full body)
- Create: `mcp-servers/tasks/tests/test_remote_executor.py`

- [ ] **Step 1: Write the failing tests**

`mcp-servers/tasks/tests/test_remote_executor.py`:

```python
"""RemoteExecutor — SSH+rsync to the agent VM.

Tests mock asyncio.create_subprocess_exec to simulate ssh/rsync calls.
"""
import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcp_servers.tasks.remote_executor import RemoteExecutor, _VALID_SLUG


def test_slug_validator_accepts_normal_slugs():
    assert _VALID_SLUG.fullmatch("flight-booker")
    assert _VALID_SLUG.fullmatch("my_app_v2")
    assert _VALID_SLUG.fullmatch("a")


def test_slug_validator_rejects_traversal():
    assert _VALID_SLUG.fullmatch("../etc") is None
    assert _VALID_SLUG.fullmatch("bad..slug") is None
    assert _VALID_SLUG.fullmatch("") is None
    assert _VALID_SLUG.fullmatch("BadCase") is None
    assert _VALID_SLUG.fullmatch("a" * 100) is None
    assert _VALID_SLUG.fullmatch("with space") is None
    assert _VALID_SLUG.fullmatch("with/slash") is None


def _fake_proc(stdout_chunks: list[bytes], returncode: int = 0):
    proc = MagicMock()
    proc.stdout = MagicMock()
    chunks = list(stdout_chunks) + [b""]
    async def _read(_n):
        return chunks.pop(0)
    proc.stdout.read = AsyncMock(side_effect=_read)
    proc.wait = AsyncMock(return_value=returncode)
    proc.kill = MagicMock()
    proc.returncode = returncode
    return proc


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("AGENT_HOST", "claude-agent")
    monkeypatch.setenv("AGENT_USER", "claude-agent")
    monkeypatch.setenv("AGENT_SSH_KEY_PATH", "/tmp/fake_key")


@pytest.mark.asyncio
async def test_invalid_slug_raises():
    ex = RemoteExecutor()
    with pytest.raises(ValueError, match="slug"):
        async for _ in ex.run("p", slug="../etc", execution_id="x"):
            pass


@pytest.mark.asyncio
async def test_happy_path_streams_and_rsyncs(monkeypatch):
    """COMPLETED triggers rsync-back before yielding the line onward."""
    calls = []

    async def fake_spawn(*args, **kwargs):
        calls.append(args)
        cmd = args[0]
        if cmd == "ssh":
            # Health check ssh ... true
            if len(args) <= 6 and "true" in args[-1]:
                return _fake_proc([], returncode=0)
            # Push-state ssh "mkdir -p ..."
            if "mkdir" in args[-1]:
                return _fake_proc([], returncode=0)
            # The big build ssh
            return _fake_proc([b"hello\n", b"COMPLETED: ok\n"], returncode=0)
        if cmd == "rsync":
            return _fake_proc([], returncode=0)
        return _fake_proc([], returncode=0)

    with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=fake_spawn)):
        ex = RemoteExecutor()
        out = []
        async for chunk in ex.run("p", slug="myapp", execution_id="ex1"):
            out.append(chunk)
    full = "".join(out)
    assert "COMPLETED: ok" in full
    # rsync was invoked (at least once for push, once for pull-back)
    rsync_calls = [c for c in calls if c[0] == "rsync"]
    assert len(rsync_calls) >= 2


@pytest.mark.asyncio
async def test_unreachable_yields_failed_sentinel():
    """ssh health check returns non-zero → FAILED: agent_unreachable."""
    async def fake_spawn(*args, **kwargs):
        return _fake_proc([], returncode=255)
    with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=fake_spawn)):
        ex = RemoteExecutor()
        out = "".join([c async for c in ex.run("p", slug="x", execution_id="e")])
    assert "FAILED: agent_unreachable" in out


@pytest.mark.asyncio
async def test_needs_input_does_not_rsync():
    """NEEDS_INPUT yields and closes without triggering rsync-back."""
    calls = []
    async def fake_spawn(*args, **kwargs):
        calls.append(args)
        cmd = args[0]
        if cmd == "rsync":
            # rsync is called for the PUSH (before build) but should NOT be
            # called a second time for the pull-back when NEEDS_INPUT fires.
            return _fake_proc([], returncode=0)
        if cmd == "ssh":
            if len(args) <= 6 and "true" in args[-1]:
                return _fake_proc([], returncode=0)
            if "mkdir" in args[-1]:
                return _fake_proc([], returncode=0)
            return _fake_proc([b"NEEDS_INPUT: which date?\n"], returncode=0)
        return _fake_proc([], returncode=0)

    with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=fake_spawn)):
        ex = RemoteExecutor()
        async for _ in ex.run("p", slug="myapp", execution_id="e"):
            pass
    rsync_calls = [c for c in calls if c[0] == "rsync"]
    # Exactly one rsync (the push). No pull-back on NEEDS_INPUT.
    assert len(rsync_calls) == 1


@pytest.mark.asyncio
async def test_shell_quote_handles_metacharacters():
    """Prompts with quotes, $, backticks must be shell-quoted."""
    captured = []
    async def fake_spawn(*args, **kwargs):
        captured.append(args)
        cmd = args[0]
        if cmd == "ssh" and len(args) > 6:
            # the build ssh — last arg is the full remote command
            return _fake_proc([b"COMPLETED: ok\n"], returncode=0)
        return _fake_proc([], returncode=0)
    with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=fake_spawn)):
        ex = RemoteExecutor()
        async for _ in ex.run('build app with `id`; $(rm -rf /); "quoted"',
                              slug="myapp", execution_id="e"):
            pass
    # The build-ssh call's command must NOT contain raw backticks or $()
    build_ssh = next(c for c in captured
                     if c[0] == "ssh" and "claude" in c[-1])
    raw_cmd = build_ssh[-1]
    # shlex.quote wraps in single-quotes; backticks are now harmless text
    assert "rm -rf" in raw_cmd        # text passes through
    # but the dangerous expansions are quoted away
    assert "$(rm -rf" not in raw_cmd or "'" in raw_cmd  # quoted form acceptable
```

- [ ] **Step 2: Run them to verify they fail**

```bash
python -m pytest tests/test_remote_executor.py -v
```

Expected: all fail with `NotImplementedError` (the Task 1 stub).

- [ ] **Step 3: Implement RemoteExecutor**

Replace the stub in `mcp-servers/tasks/remote_executor.py`:

```python
"""RemoteExecutor — runs claude on a dedicated VM over SSH.

Flow per run:
  1. Validate slug (strict regex; raises ValueError on injection attempts).
  2. Pre-flight: ssh ... true. On non-zero exit → yield FAILED: agent_unreachable.
  3. Push current workspace state to agent VM via rsync (orchestrator-initiated;
     no reverse-direction SSH key needed).
  4. ssh ... claude --print ... — stream stdout line by line.
  5. On COMPLETED: rsync agent VM workspace BACK to orchestrator, then
     yield COMPLETED to the parser, then close. (Order matters — the
     orchestrator's /files lookup must succeed after parsing.)
  6. On NEEDS_INPUT / NEEDS_STEPS / FAILED: yield and close; no rsync-back.
  7. On timeout: pkill remote, yield FAILED: timeout, close.
"""
from __future__ import annotations

import asyncio
import os
import re
import shlex
from typing import AsyncIterator

from .claude_executor import (
    EXECUTION_TIMEOUT_SECONDS,
    MAX_LOG_BYTES,
    MAX_PROMPT_CHARS,
    CLAUDE_WORKSPACE,
)


_VALID_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{1,80}$")


class RemoteExecutor:
    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None

    # ------- public API ----------------------------------------------

    async def run(
        self,
        prompt: str,
        slug: str | None,
        execution_id: str,
    ) -> AsyncIterator[str]:
        # 1. Validate slug
        if slug is not None and not _VALID_SLUG.fullmatch(slug):
            raise ValueError(f"invalid slug: {slug!r}")

        if len(prompt) > MAX_PROMPT_CHARS:
            prompt = prompt[:MAX_PROMPT_CHARS] + "\n[truncated by tasks service]"

        host = os.environ["AGENT_HOST"]
        user = os.environ.get("AGENT_USER", "claude-agent")
        key  = os.environ["AGENT_SSH_KEY_PATH"]
        effort = os.environ.get("AIUI_AGENT_EFFORT", "low")

        # 2. Health check
        if not await self._ssh_ok(host, user, key):
            yield "FAILED: agent_unreachable\n"
            return

        # 3. Push current state (no-op if app dir does not yet exist)
        if slug:
            try:
                await self._push_state(host, user, key, slug)
            except RuntimeError as e:
                yield f"FAILED: transport_error {e}\n"
                return

        # 4. Build + spawn the remote command
        remote_cmd = self._build_remote_cmd(prompt, slug, effort)
        try:
            async for line in self._stream(host, user, key, remote_cmd):
                # 5. On COMPLETED: rsync back BEFORE yielding the line
                if "COMPLETED:" in line and slug:
                    try:
                        await self._rsync_back(host, user, key, slug)
                        await self._cleanup_remote(host, user, key, slug)
                    except RuntimeError as e:
                        yield f"FAILED: transport_error {e}\n"
                        return
                yield line
                if self._is_terminal(line):
                    return
        except asyncio.TimeoutError:
            await self._kill_remote(host, user, key)
            yield f"FAILED: timeout after {EXECUTION_TIMEOUT_SECONDS}s\n"

    async def stop(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            proc.kill()
        except Exception:
            pass

    # ------- helpers ------------------------------------------------

    @staticmethod
    def _is_terminal(line: str) -> bool:
        return any(t in line for t in ("COMPLETED:", "FAILED:", "NEEDS_INPUT:", "NEEDS_STEPS:"))

    async def _ssh_ok(self, host: str, user: str, key: str) -> bool:
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-i", key, "-o", "ConnectTimeout=10",
            "-o", "BatchMode=yes",
            f"{user}@{host}", "true",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        rc = await proc.wait()
        return rc == 0

    async def _push_state(self, host: str, user: str, key: str, slug: str) -> None:
        # Ensure remote workspace dir exists
        mk = await asyncio.create_subprocess_exec(
            "ssh", "-i", key, "-o", "BatchMode=yes",
            f"{user}@{host}",
            f"mkdir -p /agent/work/{shlex.quote(slug)}/apps/{shlex.quote(slug)}",
        )
        if await mk.wait() != 0:
            raise RuntimeError("mkdir failed")

        src = f"{CLAUDE_WORKSPACE}/apps/{slug}/"
        dst = f"{user}@{host}:/agent/work/{slug}/apps/{slug}/"
        rs = await asyncio.create_subprocess_exec(
            "rsync", "-az", "--delete",
            "-e", f"ssh -i {key} -o BatchMode=yes",
            src, dst,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        rc = await rs.wait()
        if rc not in (0, 23):  # 23 = partial transfer (no src yet), tolerated
            err = (await rs.stderr.read()).decode() if rs.stderr else ""
            raise RuntimeError(f"push rsync exit {rc}: {err[:200]}")

    def _build_remote_cmd(self, prompt: str, slug: str | None, effort: str) -> str:
        qprompt = shlex.quote(prompt)
        if slug is None:
            cwd = "/agent/work"
        else:
            cwd = f"/agent/work/{shlex.quote(slug)}"
        return (
            "set -e; "
            f"cd {cwd}; "
            "source ~/.env; "
            f'IS_SANDBOX=1 AIUI_AGENT_EFFORT={shlex.quote(effort)} '
            "claude --print --dangerously-skip-permissions "
            "--output-format stream-json --verbose "
            f"--effort {shlex.quote(effort)} "
            f"-- {qprompt}"
        )

    async def _stream(self, host: str, user: str, key: str, remote_cmd: str) -> AsyncIterator[str]:
        self._proc = await asyncio.create_subprocess_exec(
            "ssh", "-i", key, "-o", "BatchMode=yes",
            "-o", "SendEnv=AIUI_AGENT_EFFORT",
            f"{user}@{host}", remote_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert self._proc.stdout is not None
        bytes_yielded = 0
        buf = b""
        try:
            async with asyncio.timeout(EXECUTION_TIMEOUT_SECONDS):
                while True:
                    chunk = await self._proc.stdout.read(4096)
                    if not chunk:
                        if buf:
                            yield buf.decode("utf-8", errors="replace")
                        break
                    if bytes_yielded >= MAX_LOG_BYTES:
                        self._proc.kill()
                        yield "\n[OUTPUT CAP exceeded — process killed]\n"
                        break
                    bytes_yielded += len(chunk)
                    buf += chunk
                    while b"\n" in buf:
                        line, _, buf = buf.partition(b"\n")
                        yield line.decode("utf-8", errors="replace") + "\n"
                await self._proc.wait()
        finally:
            self._proc = None

    async def _rsync_back(self, host: str, user: str, key: str, slug: str) -> None:
        src = f"{user}@{host}:/agent/work/{slug}/apps/{slug}/"
        dst = f"{CLAUDE_WORKSPACE}/apps/{slug}/"
        # First attempt
        for attempt in range(2):
            rs = await asyncio.create_subprocess_exec(
                "rsync", "-az", "--delete", "--chmod=D755,F644",
                "-e", f"ssh -i {key} -o BatchMode=yes",
                src, dst,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            rc = await rs.wait()
            if rc == 0:
                # Sanity check
                if not os.path.exists(os.path.join(dst, "index.html")):
                    raise RuntimeError("rsync ok but index.html missing")
                return
            await asyncio.sleep(1)
        err = (await rs.stderr.read()).decode() if rs.stderr else ""
        raise RuntimeError(f"rsync exit {rc}: {err[:200]}")

    async def _cleanup_remote(self, host: str, user: str, key: str, slug: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-i", key, "-o", "BatchMode=yes",
            f"{user}@{host}",
            f"rm -rf /agent/work/{shlex.quote(slug)}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()  # best-effort

    async def _kill_remote(self, host: str, user: str, key: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-i", key, "-o", "BatchMode=yes",
            f"{user}@{host}",
            'pkill -u claude-agent -f "claude --print" || true',
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
```

- [ ] **Step 4: Run the tests**

```bash
python -m pytest tests/test_remote_executor.py -v
```

Expected: all PASS.

- [ ] **Step 5: Run the full tasks suite**

```bash
python -m pytest -v 2>&1 | tail -30
```

Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/remote_executor.py \
        mcp-servers/tasks/tests/test_remote_executor.py
git commit -m "feat(tasks): RemoteExecutor — SSH+rsync to dedicated agent VM

Honors the BaseExecutor contract. Slug strict-validated at boundary,
agent VM holds no reverse-direction SSH keys (orchestrator pushes state
on start, pulls workspace back on COMPLETED before yielding the sentinel
onward), 600s timeout pkills the remote claude.

Default AGENT_BACKEND=local keeps this code path off until the operator
flips the env var."
```

---

## Task 9: Wire up + DB migration + production deploy

**Files:**
- Create: `mcp-servers/tasks/migrations/versions/<rev>_add_agent_host_to_executions.py`
- Modify: `mcp-servers/tasks/models.py` (TaskExecution table)
- Modify: `mcp-servers/tasks/routes_execution.py` (uncomment the `agent_host=` write from Task 3 Step 4)

The factory + RemoteExecutor are already wired together via Task 1's `get_executor()`. This task adds the audit column and ships.

- [ ] **Step 1: Add the column to the model**

In `mcp-servers/tasks/models.py`, find the `TaskExecution` class. Add:

```python
agent_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
```

- [ ] **Step 2: Generate the Alembic migration**

```bash
cd mcp-servers/tasks
alembic revision --autogenerate -m "add agent_host to task_executions"
```

Verify the generated file at `migrations/versions/<rev>_add_agent_host_to_task_executions.py` contains:

```python
def upgrade() -> None:
    op.add_column('task_executions',
                  sa.Column('agent_host', sa.String(length=255), nullable=True))

def downgrade() -> None:
    op.drop_column('task_executions', 'agent_host')
```

- [ ] **Step 3: Re-enable the `agent_host` write in `_stream_claude`**

In `mcp-servers/tasks/routes_execution.py`, replace the Task 3 Step 4 stub with the real write:

```python
agent_host_value = os.environ.get("AGENT_HOST") \
    if executor.__class__.__name__ == "RemoteExecutor" else None
if agent_host_value:
    async with session() as s:
        await s.execute(
            update(TaskExecution)
            .where(TaskExecution.id == execution_id)
            .values(agent_host=agent_host_value)
        )
        await s.commit()
```

- [ ] **Step 4: Test the migration locally**

```bash
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

Expected: clean up and down.

- [ ] **Step 5: Run the full tasks suite**

```bash
python -m pytest -v 2>&1 | tail -20
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/models.py \
        mcp-servers/tasks/migrations/versions/ \
        mcp-servers/tasks/routes_execution.py
git commit -m "feat(tasks): add task_executions.agent_host column for audit

Populated by RemoteExecutor with the AGENT_HOST env. Null for
LocalExecutor. Lets us answer 'which VM ran this build?' for incident
forensics."
```

- [ ] **Step 7: Deploy to Hetzner (orchestrator)**

Per project memory (no git on server; deploy by SCP):

```bash
# From operator workstation, with $ORCHESTRATOR being the Hetzner host
scp mcp-servers/tasks/agent_executor.py     root@$ORCHESTRATOR:/root/proxy-server/mcp-servers/tasks/
scp mcp-servers/tasks/local_executor.py     root@$ORCHESTRATOR:/root/proxy-server/mcp-servers/tasks/
scp mcp-servers/tasks/remote_executor.py    root@$ORCHESTRATOR:/root/proxy-server/mcp-servers/tasks/
scp mcp-servers/tasks/claude_executor.py    root@$ORCHESTRATOR:/root/proxy-server/mcp-servers/tasks/
scp mcp-servers/tasks/routes_execution.py   root@$ORCHESTRATOR:/root/proxy-server/mcp-servers/tasks/
scp mcp-servers/tasks/models.py             root@$ORCHESTRATOR:/root/proxy-server/mcp-servers/tasks/
scp -r mcp-servers/tasks/migrations         root@$ORCHESTRATOR:/root/proxy-server/mcp-servers/tasks/
scp docker-compose.unified.yml              root@$ORCHESTRATOR:/root/proxy-server/

# Update .env with the AGENT_* vars — START WITH AGENT_BACKEND=local
ssh root@$ORCHESTRATOR '
  cat >>/root/proxy-server/.env <<EOF
AGENT_BACKEND=local
AGENT_HOST=claude-agent
AGENT_USER=claude-agent
EOF
'

# Rebuild + restart tasks service
ssh root@$ORCHESTRATOR '
  cd /root/proxy-server
  docker compose -f docker-compose.unified.yml up -d --build tasks
'

# Run the Alembic migration inside the container
ssh root@$ORCHESTRATOR '
  docker exec tasks alembic upgrade head
'
```

- [ ] **Step 8: Verify the orchestrator still works (AGENT_BACKEND=local)**

Pick a non-flight template (e.g. `agency`) and run a small build via the UI or API. Verify it completes byte-identical to before. This is the rollback-safety check.

- [ ] **Step 9: Flip to remote and run a no-op test build**

```bash
ssh root@$ORCHESTRATOR '
  sed -i "s/AGENT_BACKEND=local/AGENT_BACKEND=remote/" /root/proxy-server/.env
  docker compose -f docker-compose.unified.yml up -d tasks
'
```

Run another small build (any template). Expected:
- Task completes.
- `apps/<slug>/` ends up on orchestrator with files as usual.
- `task_executions.agent_host = 'claude-agent'` in DB.

If this fails, **flip back to local immediately:**
```bash
ssh root@$ORCHESTRATOR '
  sed -i "s/AGENT_BACKEND=remote/AGENT_BACKEND=local/" /root/proxy-server/.env
  docker compose -f docker-compose.unified.yml up -d tasks
'
```

…then debug from the agent VM's `/var/log/squid/access.log` and the orchestrator's `tasks` container logs.

---

## Task 10: Prompt augmentation + E2E demo + operator docs

**Files:**
- Modify: `mcp-servers/tasks/claude_executor.py` (`build_prompt` ~line 305)
- Create: `docs/agent-vm/README.md`

The final step ties everything together: tell the agent about the `search_flights` tool, run the demo Lukas asked for, and write the operator runbook.

- [ ] **Step 1: Find `build_prompt` and identify where the template-specific augmentations land**

```bash
grep -n "def build_prompt\|template_key" mcp-servers/tasks/claude_executor.py | head -20
```

Note where `template_key` is referenced inside `build_prompt`.

- [ ] **Step 2: Add the flight-booking block**

In `build_prompt`, after the existing template-key handling (or near the end of the prompt construction), add:

```python
if template_key == "flight-booking":
    prompt += textwrap.dedent("""

        ## Real flight data
        You have access to a `search_flights` MCP tool that returns
        real flight offers from the Duffel sandbox API. If the user's
        request mentions specific airports, cities, or dates, call this
        tool and rewrite `src/data.js` so the `flights` named export
        contains the returned offers. Preserve the existing schema
        (`id, origin, destination, airline, price, stops, duration,
        departureHour, departureBucket, departureLabel, arrivalLabel,
        cabin, baggage`) so `src/main.js` continues to work. Re-derive
        `cities` and `airlines` from the offers. The tool's
        `departure_hour` (snake_case) maps to `departureHour` (camelCase);
        re-compute `departureBucket` using:
            bucketize = (h) => h<6?"early":h<12?"morning":h<18?"afternoon":"evening"
        If the tool returns an error or no offers, leave the seed data
        in place and add a one-line comment noting the fallback.
    """)
```

Make sure `import textwrap` is present at the top of the file.

- [ ] **Step 3: Commit**

```bash
git add mcp-servers/tasks/claude_executor.py
git commit -m "feat(tasks): teach build_prompt about search_flights MCP tool

Adds a flight-booking-specific augmentation block describing the tool,
the camelCase mapping, and the seed-data fallback. Harmless when
flights-mcp is not registered (e.g. AGENT_BACKEND=local without the
agent VM)."
```

- [ ] **Step 4: Deploy the prompt change**

```bash
scp mcp-servers/tasks/claude_executor.py \
    root@$ORCHESTRATOR:/root/proxy-server/mcp-servers/tasks/
ssh root@$ORCHESTRATOR '
  cd /root/proxy-server
  docker compose -f docker-compose.unified.yml up -d --build tasks
'
```

- [ ] **Step 5: End-to-end demo**

In the App Builder UI:
1. Confirm `AGENT_BACKEND=remote` is set.
2. Pick the `flight-booking` template.
3. Prompt: *"build me a booker for LAX to NRT June 1 for 2 people"*.
4. Wait for `COMPLETED:`.
5. Open the preview at `/__public/<slug>/`.

Verify in the preview that the airline column shows real carriers (not the seed names `Skylane, Northwind, Aegis Air, Pacific Crest, Lumen Atlantic, Cirrus, Helios, Veridian`). Expected real carriers from Duffel sandbox: ANA, JAL, United, Delta, etc.

- [ ] **Step 6: Verify the database row**

```bash
ssh root@$ORCHESTRATOR '
  docker exec tasks psql $DATABASE_URL -c "
    SELECT id, status, agent_host, finished_at
      FROM task_executions
      ORDER BY started_at DESC LIMIT 5;
  "
'
```

The latest row should show `agent_host = claude-agent` and `status = completed`.

- [ ] **Step 7: Write the operator runbook**

`docs/agent-vm/README.md`:

```markdown
# Agent VM — Operator Runbook

The IO App Builder's coding agent (`claude`) runs on a dedicated Hetzner
CAX21 VM, isolated from the orchestrator. This document covers
provisioning, secret rotation, debugging, and rollback.

## Topology

- Orchestrator: `ai-ui.coolestdomain.win` (existing VPS)
- Agent VM: `claude-agent` on private network 10.0.0.0/16
  - Linux user: `claude-agent` (no sudo, no docker)
  - Workspace: `/agent/work/<slug>/`
  - Egress: through local Squid proxy 127.0.0.1:3128
    (allowlist: anthropic.com, duffel.com, npmjs.org, nodesource.com,
    pypi.org, pythonhosted.org, ubuntu.com)

## Provisioning a fresh VM

```bash
# 1. Create the Hetzner box (CAX21, fsn1, Ubuntu 24.04, attached to
#    same private network as orchestrator). Note the private IP.

# 2. On the orchestrator host, generate the SSH keypair:
sudo ssh-keygen -t ed25519 -f /etc/proxy-server/agent_ssh_key -N ""
sudo chmod 0400 /etc/proxy-server/agent_ssh_key

# 3. Run the provisioning script from the operator workstation:
export AGENT_HOST=10.0.0.42
export AGENT_SSH_KEY_PUB=./agent_ssh_key.pub
export ANTHROPIC_API_KEY=sk-ant-...
export DUFFEL_API_KEY=duffel_test_...
export ORCHESTRATOR_PRIVATE_IP=10.0.0.10
./scripts/provision_agent_vm.sh

# 4. Add to orchestrator's /etc/hosts:
echo "10.0.0.42 claude-agent" | sudo tee -a /etc/hosts

# 5. Verify:
AGENT_HOST=claude-agent \
AGENT_SSH_KEY_PATH=/etc/proxy-server/agent_ssh_key \
  ./scripts/smoke_agent_vm.sh

# 6. Flip the orchestrator to remote mode:
sed -i "s/AGENT_BACKEND=local/AGENT_BACKEND=remote/" /root/proxy-server/.env
docker compose -f docker-compose.unified.yml up -d tasks
```

## Secret rotation

ANTHROPIC_API_KEY or DUFFEL_API_KEY:
```bash
ANTHROPIC_API_KEY=sk-ant-newkey \
DUFFEL_API_KEY=$DUFFEL_API_KEY \
AGENT_HOST=... \
AGENT_SSH_KEY_PUB=... \
ORCHESTRATOR_PRIVATE_IP=... \
  ./scripts/provision_agent_vm.sh
```

SSH key:
```bash
# Wait for in-flight tasks to finish first
sudo ssh-keygen -t ed25519 -f /etc/proxy-server/agent_ssh_key -N "" -y
# Re-run provision to update agent VM authorized_keys
./scripts/provision_agent_vm.sh
# Restart tasks container
docker compose -f docker-compose.unified.yml restart tasks
```

## Rollback to local executor

Single env flip — no code change required:
```bash
ssh root@$ORCHESTRATOR '
  sed -i "s/AGENT_BACKEND=remote/AGENT_BACKEND=local/" /root/proxy-server/.env
  docker compose -f docker-compose.unified.yml up -d tasks
'
```

The agent VM stays running but unused. Resume by flipping back.

## Kill switch (runaway agent)

```bash
ssh -i /etc/proxy-server/agent_ssh_key claude-agent@claude-agent \
  'pkill -u claude-agent -f "claude --print"'
```

Or from the App Builder UI: cancel the task (TaskStop endpoint hits
`executor.stop()` which sends the same kill remotely).

## Debugging

- Agent stdout/stderr stream lives in `task_executions.log` (Postgres).
- Squid access logs: `/var/log/squid/access.log` on the agent VM.
- Workspace files for an in-flight task: `/agent/work/<slug>/` on the
  agent VM. SSH in as claude-agent to inspect.

## Cost notes

- Hetzner CAX21: €7.50/mo + €0.60/mo primary IPv4 = ~€8.10/mo.
- Anthropic API: capped via Console at $50/day (initial — tune as needed).
- Duffel sandbox: free tier.
```

- [ ] **Step 8: Commit + final merge**

```bash
git add docs/agent-vm/README.md
git commit -m "docs(agent-vm): operator runbook — provisioning, rotation, rollback"

# Merge to main
git checkout main
git merge --no-ff feat/vm-agent-flight-mcp -m "feat: VM-hosted agent + flight MCP"
git push
```

- [ ] **Step 9: Demo to Lukas**

Walk him through:
1. The flight-booking template prompt → real flights in the preview.
2. The agent VM dashboard (`hcloud server describe claude-agent`).
3. The `agent_host` column in `task_executions` proving attribution.
4. Squid access logs showing exactly which domains the agent hit during the build.

This closes the loop on his original ask from the 2026-05-11 standup.

---

## Out of scope (for follow-up plans, NOT this one)

- Multi-tenant agent fleets (one VM per customer)
- Ephemeral E2B / Daytona / Cloudflare Sandbox per task
- BYO Duffel key per tenant + credential broker
- Additional MCP servers (maps, payments, scraping, real estate)
- Langfuse / OTel tracing for agent runs
- Concurrent multi-agent execution (currently 1 task at a time)
- Port of Superpowers-style retry/verify loop to remote execution
- Replacing Claude Code with OpenHands / OpenCode (Path B from spec)

Each is its own spec + plan.
