# MCP Access from VM-Hosted App-Builder Agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** [docs/superpowers/specs/2026-05-15-mcp-access-from-vm-agent-design.md](../specs/2026-05-15-mcp-access-from-vm-agent-design.md)

**Goal:** Give the isolated `claude-agent` access to 8 of our FastAPI services as proper MCP tools during an app-builder build, authenticating with the user's JWT. (`tasks` and `scheduler` deferred per spec §2.)

**Architecture:** One stdio MCP wrapper per backend service, all sharing a `GatewayClient` base. The orchestrator forwards the user's JWT to the agent VM via SSH `SendEnv`; each wrapper sends it as `Authorization: Bearer` to the API Gateway. No backend service code changes — but Caddy + `api-gateway/main.py:proxy_handler` get matching new branches so the MCP service prefixes (`/gmail/*`, `/gdrive/*`, `/calendar/*`, `/meetings/*`, `/web-search/*`, `/meeting-kb/*`, `/dashboard/*`, `/excel-creator/*`) actually flow through the gateway (today Caddy bypasses it for 4 of these).

**Tech Stack:** Python 3.12, `mcp.server` SDK (stdio), `httpx` (async), `pytest` + `pytest-asyncio`, existing `RemoteExecutor` SSH transport.

**Branch:** `feat/vm-agent-flight-mcp` (continue on existing branch).

---

## File Structure

**Created:**
- `mcp-servers/io-mcp-wrappers/pyproject.toml`
- `mcp-servers/io-mcp-wrappers/io_mcp_base/__init__.py`
- `mcp-servers/io-mcp-wrappers/io_mcp_base/errors.py`
- `mcp-servers/io-mcp-wrappers/io_mcp_base/client.py`
- `mcp-servers/io-mcp-wrappers/io_mcp_base/server.py`
- `mcp-servers/io-mcp-wrappers/io_mcp_<svc>/__init__.py` (× 8)
- `mcp-servers/io-mcp-wrappers/io_mcp_<svc>/__main__.py` (× 8)
- `mcp-servers/io-mcp-wrappers/io_mcp_<svc>/tools.py` (× 8)
- `mcp-servers/io-mcp-wrappers/tests/__init__.py`
- `mcp-servers/io-mcp-wrappers/tests/test_gateway_client.py`
- `mcp-servers/io-mcp-wrappers/tests/test_errors.py`
- `mcp-servers/io-mcp-wrappers/tests/test_server.py`
- `mcp-servers/io-mcp-wrappers/tests/test_<svc>_wrapper.py` (× 8)
- `scripts/smoke_mcp_access.sh`

**Modified:**
- `Caddyfile` — change 4 direct routes to gateway routes, add 4 new gateway routes
- `api-gateway/main.py` — add 8 prefix branches in `proxy_handler`
- `mcp-servers/tasks/main.py` — extract user JWT from request, pass to executor
- `mcp-servers/tasks/remote_executor.py` — accept `user_jwt` param, `SendEnv` extension
- `mcp-servers/tasks/tests/test_remote_executor.py` — one new test
- `api-gateway/tests/` — new test for the 8 prefix branches (or smoke-only if no test infra exists)
- `scripts/provision_agent_vm.sh` — install io-mcp-wrappers, register via `claude mcp add`
- `docs/agent-vm/README.md` — new env vars, wrapper registry

---

## Task 1: Package skeleton

**Files:**
- Create: `mcp-servers/io-mcp-wrappers/pyproject.toml`
- Create: `mcp-servers/io-mcp-wrappers/io_mcp_base/__init__.py`
- Create: `mcp-servers/io-mcp-wrappers/tests/__init__.py`
- Create: `mcp-servers/io-mcp-wrappers/tests/test_package_imports.py`

- [ ] **Step 1.1: Create the package skeleton**

`mcp-servers/io-mcp-wrappers/pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "io-mcp-wrappers"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "mcp>=1.0.0",
  "httpx>=0.27",
]

[project.optional-dependencies]
test = ["pytest>=8", "pytest-asyncio>=0.23", "respx>=0.21"]

[tool.setuptools.packages.find]
where = ["."]
include = ["io_mcp_*"]
```

`mcp-servers/io-mcp-wrappers/io_mcp_base/__init__.py`:
```python
"""Shared base for IO MCP stdio wrappers."""
```

`mcp-servers/io-mcp-wrappers/tests/__init__.py`: (empty)

`mcp-servers/io-mcp-wrappers/tests/test_package_imports.py`:
```python
def test_io_mcp_base_imports():
    import io_mcp_base  # noqa: F401
```

- [ ] **Step 1.2: Verify package installs and the smoke test passes**

```bash
cd mcp-servers/io-mcp-wrappers
python -m venv .venv
.venv/Scripts/pip install -e .[test]
.venv/Scripts/pytest tests/test_package_imports.py -v
```
Expected: 1 passed.

- [ ] **Step 1.3: Commit**

```bash
git add mcp-servers/io-mcp-wrappers/pyproject.toml mcp-servers/io-mcp-wrappers/io_mcp_base/__init__.py mcp-servers/io-mcp-wrappers/tests/__init__.py mcp-servers/io-mcp-wrappers/tests/test_package_imports.py
git commit -m "feat(io-mcp-wrappers): package skeleton + smoke import test"
```

---

## Task 2: `GatewayError` with secret-hygiene contract

This task locks in the most important property of the whole feature: **the JWT can never appear in any stringified error**. Write the paranoid tests first.

**Files:**
- Create: `mcp-servers/io-mcp-wrappers/io_mcp_base/errors.py`
- Create: `mcp-servers/io-mcp-wrappers/tests/test_errors.py`

- [ ] **Step 2.1: Write the failing tests**

`tests/test_errors.py`:
```python
"""GatewayError MUST NEVER stringify with the Authorization header in it."""
import httpx

from io_mcp_base.errors import GatewayError


def _request_with_jwt(jwt: str) -> httpx.Request:
    return httpx.Request(
        "GET",
        "http://172.22.0.1:8080/gmail/search",
        headers={"Authorization": f"Bearer {jwt}"},
    )


SECRET = "secret-token-do-not-leak-12345"


def test_str_does_not_contain_jwt():
    err = GatewayError(kind="auth", detail="gateway rejected token",
                      request=_request_with_jwt(SECRET))
    assert SECRET not in str(err)


def test_repr_does_not_contain_jwt():
    err = GatewayError(kind="auth", detail="gateway rejected token",
                      request=_request_with_jwt(SECRET))
    assert SECRET not in repr(err)


def test_str_does_not_contain_authorization_header_key():
    err = GatewayError(kind="auth", detail="gateway rejected token",
                      request=_request_with_jwt(SECRET))
    assert "Authorization" not in str(err)


def test_kind_and_detail_round_trip():
    err = GatewayError(kind="rate_limit", detail="slow down", retry_after=42)
    assert err.kind == "rate_limit"
    assert err.detail == "slow down"
    assert err.retry_after == 42


def test_init_without_request_works():
    err = GatewayError(kind="network", detail="connection reset")
    assert err.kind == "network"
    assert "secret" not in str(err).lower()


def test_chained_exception_repr_no_leak():
    """If GatewayError wraps an httpx exception that stringifies the request,
    our __repr__ must STILL strip the header.
    """
    try:
        raise httpx.HTTPError("boom")
    except httpx.HTTPError as inner:
        err = GatewayError(kind="server", detail="500",
                          request=_request_with_jwt(SECRET), cause=inner)
    assert SECRET not in repr(err)
    assert SECRET not in str(err)
```

- [ ] **Step 2.2: Run the tests to confirm they fail**

```bash
cd mcp-servers/io-mcp-wrappers
.venv/Scripts/pytest tests/test_errors.py -v
```
Expected: 6 failures, all `ModuleNotFoundError: No module named 'io_mcp_base.errors'`.

- [ ] **Step 2.3: Write the minimal implementation**

`io_mcp_base/errors.py`:
```python
"""GatewayError — typed wrapper around HTTP failures, NEVER stringifies the
Authorization header.

The paranoid invariant: if a JWT is in the request headers when GatewayError
is constructed, that JWT must not appear in str() or repr() of the error.
This is what protects against the leak Lukas flagged in the 2026-05-14
standup: agent reads its own logs/error to debug -> log content goes back
out to the internet.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import httpx


ErrorKind = Literal["auth", "not_found", "rate_limit", "server", "network", "internal"]


@dataclass
class GatewayError(Exception):
    kind: ErrorKind
    detail: str = ""
    retry_after: int | None = None
    request: httpx.Request | None = None
    cause: BaseException | None = None

    def __post_init__(self) -> None:
        # Strip Authorization from any stored request copy. Even if upstream
        # code passes in a request with the header, we never retain it.
        if self.request is not None and "Authorization" in self.request.headers:
            # httpx.Request.headers is mutable; remove in place on our copy.
            self.request.headers.pop("Authorization", None)
        # Initialize Exception with a sanitized message.
        super().__init__(self._safe_message())

    def _safe_message(self) -> str:
        parts = [f"GatewayError(kind={self.kind!r}"]
        if self.detail:
            parts.append(f"detail={self.detail!r}")
        if self.retry_after is not None:
            parts.append(f"retry_after={self.retry_after}")
        if self.request is not None:
            parts.append(f"method={self.request.method}")
            parts.append(f"url={self.request.url}")
        return ", ".join(parts) + ")"

    def __str__(self) -> str:
        return self._safe_message()

    def __repr__(self) -> str:
        return self._safe_message()
```

- [ ] **Step 2.4: Run the tests; all 6 should pass**

```bash
.venv/Scripts/pytest tests/test_errors.py -v
```
Expected: 6 passed.

- [ ] **Step 2.5: Commit**

```bash
git add mcp-servers/io-mcp-wrappers/io_mcp_base/errors.py mcp-servers/io-mcp-wrappers/tests/test_errors.py
git commit -m "feat(io-mcp-wrappers): GatewayError with secret-hygiene contract"
```

---

## Task 3: `GatewayClient` — env validation (fail-fast)

**Files:**
- Create: `mcp-servers/io-mcp-wrappers/io_mcp_base/client.py`
- Create: `mcp-servers/io-mcp-wrappers/tests/test_gateway_client.py`

- [ ] **Step 3.1: Write the failing tests**

`tests/test_gateway_client.py`:
```python
import pytest

from io_mcp_base.client import GatewayClient


def test_missing_jwt_raises(monkeypatch):
    monkeypatch.setenv("IO_GATEWAY_URL", "http://172.22.0.1:8080")
    monkeypatch.delenv("IO_USER_JWT", raising=False)
    with pytest.raises(RuntimeError, match="IO_USER_JWT"):
        GatewayClient()


def test_empty_jwt_raises(monkeypatch):
    monkeypatch.setenv("IO_GATEWAY_URL", "http://172.22.0.1:8080")
    monkeypatch.setenv("IO_USER_JWT", "")
    with pytest.raises(RuntimeError, match="IO_USER_JWT"):
        GatewayClient()


def test_missing_gateway_url_raises(monkeypatch):
    monkeypatch.setenv("IO_USER_JWT", "abc.def.ghi")
    monkeypatch.delenv("IO_GATEWAY_URL", raising=False)
    with pytest.raises(RuntimeError, match="IO_GATEWAY_URL"):
        GatewayClient()


def test_valid_env_constructs(monkeypatch):
    monkeypatch.setenv("IO_GATEWAY_URL", "http://172.22.0.1:8080")
    monkeypatch.setenv("IO_USER_JWT", "abc.def.ghi")
    client = GatewayClient()
    assert client.base_url == "http://172.22.0.1:8080"
```

- [ ] **Step 3.2: Run; confirm failures**

```bash
.venv/Scripts/pytest tests/test_gateway_client.py -v
```
Expected: 4 failures.

- [ ] **Step 3.3: Implement minimal `GatewayClient`**

`io_mcp_base/client.py`:
```python
"""GatewayClient — httpx wrapper that authenticates every call to the
API Gateway as the user whose JWT is in IO_USER_JWT.

Reads env at construct time and fails fast if anything is missing.
Logs MUST NEVER contain the JWT; errors MUST NEVER stringify the
Authorization header. See test_gateway_client.py for the contract.
"""
from __future__ import annotations

import os


class GatewayClient:
    def __init__(self) -> None:
        jwt = os.environ.get("IO_USER_JWT", "")
        gateway = os.environ.get("IO_GATEWAY_URL", "")
        if not jwt:
            raise RuntimeError("IO_USER_JWT not set (or empty)")
        if not gateway:
            raise RuntimeError("IO_GATEWAY_URL not set")
        self._jwt = jwt
        self.base_url = gateway.rstrip("/")
```

- [ ] **Step 3.4: All 4 tests pass**

```bash
.venv/Scripts/pytest tests/test_gateway_client.py -v
```
Expected: 4 passed.

- [ ] **Step 3.5: Commit**

```bash
git add mcp-servers/io-mcp-wrappers/io_mcp_base/client.py mcp-servers/io-mcp-wrappers/tests/test_gateway_client.py
git commit -m "feat(io-mcp-wrappers): GatewayClient env validation"
```

---

## Task 4: `GatewayClient` — happy-path GET/POST with auth

**Files:**
- Modify: `mcp-servers/io-mcp-wrappers/io_mcp_base/client.py`
- Modify: `mcp-servers/io-mcp-wrappers/tests/test_gateway_client.py`

- [ ] **Step 4.1: Append failing tests**

Add to `tests/test_gateway_client.py`:
```python
import respx
import httpx


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("IO_GATEWAY_URL", "http://172.22.0.1:8080")
    monkeypatch.setenv("IO_USER_JWT", "abc.def.ghi")
    return GatewayClient()


@pytest.mark.asyncio
@respx.mock
async def test_get_sends_bearer(client):
    route = respx.get("http://172.22.0.1:8080/gmail/search").mock(
        return_value=httpx.Response(200, json={"results": []}),
    )
    data = await client.get("/gmail/search", params={"q": "hello"})
    assert data == {"results": []}
    assert route.called
    sent = route.calls.last.request
    assert sent.headers["Authorization"] == "Bearer abc.def.ghi"
    assert sent.url.params["q"] == "hello"


@pytest.mark.asyncio
@respx.mock
async def test_post_sends_bearer_and_body(client):
    route = respx.post("http://172.22.0.1:8080/gmail/send").mock(
        return_value=httpx.Response(200, json={"id": "m1"}),
    )
    data = await client.post("/gmail/send", json={"to": "a@b.com"})
    assert data == {"id": "m1"}
    sent = route.calls.last.request
    assert sent.headers["Authorization"] == "Bearer abc.def.ghi"
```

- [ ] **Step 4.2: Run; confirm failures**

```bash
.venv/Scripts/pytest tests/test_gateway_client.py -v
```
Expected: 2 new failures (AttributeError for `client.get` / `client.post`).

- [ ] **Step 4.3: Add `get` / `post` to `GatewayClient`**

Append to `io_mcp_base/client.py`:
```python
import httpx
from typing import Any

from .errors import GatewayError


class GatewayClient:  # extend existing class (replace whole class body)
    def __init__(self) -> None:
        jwt = os.environ.get("IO_USER_JWT", "")
        gateway = os.environ.get("IO_GATEWAY_URL", "")
        if not jwt:
            raise RuntimeError("IO_USER_JWT not set (or empty)")
        if not gateway:
            raise RuntimeError("IO_GATEWAY_URL not set")
        self._jwt = jwt
        self.base_url = gateway.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._jwt}"}

    async def get(self, path: str, *, params: dict[str, Any] | None = None,
                  timeout: float = 30.0) -> Any:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(self.base_url + path,
                                     params=params, headers=self._headers())
            return self._handle(resp)

    async def post(self, path: str, *, json: dict[str, Any] | None = None,
                   timeout: float = 30.0) -> Any:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(self.base_url + path,
                                      json=json, headers=self._headers())
            return self._handle(resp)

    def _handle(self, resp: httpx.Response) -> Any:
        if 200 <= resp.status_code < 300:
            return resp.json() if resp.content else None
        # full error mapping comes in Task 5
        raise GatewayError(kind="server", detail=str(resp.status_code),
                          request=resp.request)
```

(Make sure to replace the original short `__init__`-only body, not append two classes.)

- [ ] **Step 4.4: Tests pass**

```bash
.venv/Scripts/pytest tests/test_gateway_client.py -v
```
Expected: 6 passed (4 from Task 3 still passing + 2 new).

- [ ] **Step 4.5: Commit**

```bash
git add mcp-servers/io-mcp-wrappers/io_mcp_base/client.py mcp-servers/io-mcp-wrappers/tests/test_gateway_client.py
git commit -m "feat(io-mcp-wrappers): GatewayClient happy-path get/post with bearer auth"
```

---

## Task 5: Error envelope mapping (401, 404, 429, 5xx, network)

**Files:**
- Modify: `mcp-servers/io-mcp-wrappers/io_mcp_base/client.py`
- Modify: `mcp-servers/io-mcp-wrappers/tests/test_gateway_client.py`

- [ ] **Step 5.1: Failing tests**

Append to `tests/test_gateway_client.py`:
```python
from io_mcp_base.errors import GatewayError


@pytest.mark.asyncio
@respx.mock
async def test_401_returns_auth_error(client):
    respx.get("http://172.22.0.1:8080/x").mock(return_value=httpx.Response(401))
    with pytest.raises(GatewayError) as ei:
        await client.get("/x")
    assert ei.value.kind == "auth"


@pytest.mark.asyncio
@respx.mock
async def test_404_returns_not_found(client):
    respx.get("http://172.22.0.1:8080/x").mock(return_value=httpx.Response(404))
    with pytest.raises(GatewayError) as ei:
        await client.get("/x")
    assert ei.value.kind == "not_found"


@pytest.mark.asyncio
@respx.mock
async def test_429_returns_rate_limit_with_retry_after(client):
    respx.get("http://172.22.0.1:8080/x").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "30"}),
    )
    with pytest.raises(GatewayError) as ei:
        await client.get("/x")
    assert ei.value.kind == "rate_limit"
    assert ei.value.retry_after == 30


@pytest.mark.asyncio
@respx.mock
async def test_5xx_returns_server(client):
    respx.get("http://172.22.0.1:8080/x").mock(return_value=httpx.Response(500))
    with pytest.raises(GatewayError) as ei:
        await client.get("/x")
    assert ei.value.kind == "server"


@pytest.mark.asyncio
@respx.mock
async def test_network_error_returns_network(client):
    respx.get("http://172.22.0.1:8080/x").mock(
        side_effect=httpx.ConnectError("conn refused"),
    )
    with pytest.raises(GatewayError) as ei:
        await client.get("/x")
    assert ei.value.kind == "network"
```

- [ ] **Step 5.2: Run; confirm failures (some kinds wrong)**

```bash
.venv/Scripts/pytest tests/test_gateway_client.py -v
```
Expected: 4-5 failures.

- [ ] **Step 5.3: Replace `_handle` and wrap `get`/`post` with network-error catch**

In `io_mcp_base/client.py`, replace `_handle` and update `get`/`post`:
```python
    def _handle(self, resp: httpx.Response) -> Any:
        sc = resp.status_code
        if 200 <= sc < 300:
            return resp.json() if resp.content else None
        if sc == 401 or sc == 403:
            raise GatewayError(kind="auth", detail="gateway rejected token",
                              request=resp.request)
        if sc == 404:
            raise GatewayError(kind="not_found", request=resp.request)
        if sc == 429:
            try:
                retry_after = int(resp.headers.get("Retry-After", "0"))
            except ValueError:
                retry_after = 0
            raise GatewayError(kind="rate_limit", retry_after=retry_after,
                              request=resp.request)
        if 500 <= sc < 600:
            raise GatewayError(kind="server", detail=str(sc),
                              request=resp.request)
        # Unknown 4xx — treat as server (rare)
        raise GatewayError(kind="server", detail=str(sc), request=resp.request)

    async def _do(self, method: str, path: str, *, params=None, json=None,
                  timeout: float = 30.0) -> Any:
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                resp = await c.request(method, self.base_url + path,
                                        params=params, json=json,
                                        headers=self._headers())
                return self._handle(resp)
        except httpx.TimeoutException as e:
            raise GatewayError(kind="network", detail="timeout", cause=e) from e
        except httpx.NetworkError as e:
            raise GatewayError(kind="network", detail=str(e)[:120], cause=e) from e

    async def get(self, path: str, *, params=None, timeout: float = 30.0) -> Any:
        return await self._do("GET", path, params=params, timeout=timeout)

    async def post(self, path: str, *, json=None, timeout: float = 30.0) -> Any:
        return await self._do("POST", path, json=json, timeout=timeout)
```

- [ ] **Step 5.4: All tests pass**

```bash
.venv/Scripts/pytest tests/test_gateway_client.py -v
```
Expected: 11 passed.

- [ ] **Step 5.5: Commit**

```bash
git add mcp-servers/io-mcp-wrappers/io_mcp_base/client.py mcp-servers/io-mcp-wrappers/tests/test_gateway_client.py
git commit -m "feat(io-mcp-wrappers): map HTTP errors to typed GatewayError envelope"
```

---

## Task 6: Retry policy (one retry on 5xx and timeout)

**Files:**
- Modify: `io_mcp_base/client.py`
- Modify: `tests/test_gateway_client.py`

- [ ] **Step 6.1: Failing tests**

Append:
```python
@pytest.mark.asyncio
@respx.mock
async def test_500_retries_once_then_raises(client):
    route = respx.get("http://172.22.0.1:8080/x").mock(
        return_value=httpx.Response(500),
    )
    with pytest.raises(GatewayError):
        await client.get("/x")
    assert route.call_count == 2  # one retry


@pytest.mark.asyncio
@respx.mock
async def test_500_then_200_succeeds(client):
    route = respx.get("http://172.22.0.1:8080/x").mock(
        side_effect=[httpx.Response(500), httpx.Response(200, json={"ok": 1})],
    )
    data = await client.get("/x")
    assert data == {"ok": 1}
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_401_does_NOT_retry(client):
    route = respx.get("http://172.22.0.1:8080/x").mock(
        return_value=httpx.Response(401),
    )
    with pytest.raises(GatewayError):
        await client.get("/x")
    assert route.call_count == 1  # NO retry on auth
```

- [ ] **Step 6.2: Run; confirm failures**

```bash
.venv/Scripts/pytest tests/test_gateway_client.py -v
```

- [ ] **Step 6.3: Wrap `_do` with retry**

Replace `_do` in `client.py`:
```python
    async def _do(self, method: str, path: str, *, params=None, json=None,
                  timeout: float = 30.0) -> Any:
        last_err: GatewayError | None = None
        for attempt in (1, 2):
            try:
                async with httpx.AsyncClient(timeout=timeout) as c:
                    resp = await c.request(method, self.base_url + path,
                                            params=params, json=json,
                                            headers=self._headers())
                    try:
                        return self._handle(resp)
                    except GatewayError as e:
                        if e.kind in ("server",) and attempt == 1:
                            last_err = e
                            await asyncio.sleep(1.0)
                            continue
                        raise
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                err = GatewayError(
                    kind="network",
                    detail="timeout" if isinstance(e, httpx.TimeoutException)
                                     else str(e)[:120],
                    cause=e,
                )
                if attempt == 1:
                    last_err = err
                    await asyncio.sleep(1.0)
                    continue
                raise err from e
        assert last_err is not None
        raise last_err
```

Add `import asyncio` to the top of `client.py`.

- [ ] **Step 6.4: Tests pass**

```bash
.venv/Scripts/pytest tests/test_gateway_client.py -v
```
Expected: 14 passed.

- [ ] **Step 6.5: Commit**

```bash
git add mcp-servers/io-mcp-wrappers/io_mcp_base/client.py mcp-servers/io-mcp-wrappers/tests/test_gateway_client.py
git commit -m "feat(io-mcp-wrappers): retry once on 5xx and network errors"
```

---

## Task 7: Log hygiene — JWT never in stderr

**Files:**
- Modify: `io_mcp_base/client.py`
- Modify: `tests/test_gateway_client.py`

- [ ] **Step 7.1: Failing test**

Append:
```python
@pytest.mark.asyncio
@respx.mock
async def test_jwt_never_in_stderr(monkeypatch, capsys):
    monkeypatch.setenv("IO_GATEWAY_URL", "http://172.22.0.1:8080")
    monkeypatch.setenv("IO_USER_JWT", "secret-jwt-do-not-leak")
    c = GatewayClient()
    respx.get("http://172.22.0.1:8080/x").mock(return_value=httpx.Response(200, json={}))
    await c.get("/x")
    # And an error path
    respx.get("http://172.22.0.1:8080/y").mock(return_value=httpx.Response(401))
    try:
        await c.get("/y")
    except GatewayError:
        pass
    captured = capsys.readouterr()
    assert "secret-jwt-do-not-leak" not in captured.err
    assert "secret-jwt-do-not-leak" not in captured.out
```

- [ ] **Step 7.2: Run; confirm currently passes (no logging yet) or fails (if added prematurely)**

```bash
.venv/Scripts/pytest tests/test_gateway_client.py::test_jwt_never_in_stderr -v
```

If it passes — good, no leaks yet. The test is the regression guard for future logging changes.

- [ ] **Step 7.3: Add an INFO-level access log to `_do` that does NOT log headers**

Append to `_do`'s success branch in `client.py`, right before `return self._handle(resp)`:
```python
                    # Access log — METHOD URL STATUS, NEVER headers or body
                    import sys
                    print(f"[io-mcp] {method} {path} -> {resp.status_code}",
                          file=sys.stderr, flush=True)
```

- [ ] **Step 7.4: Tests still pass (no leak)**

```bash
.venv/Scripts/pytest tests/test_gateway_client.py -v
```
Expected: 15 passed.

- [ ] **Step 7.5: Commit**

```bash
git add mcp-servers/io-mcp-wrappers/io_mcp_base/client.py mcp-servers/io-mcp-wrappers/tests/test_gateway_client.py
git commit -m "feat(io-mcp-wrappers): access log to stderr (no headers, no body)"
```

---

## Task 8: `build_server` factory + tool envelope helpers

**Files:**
- Create: `mcp-servers/io-mcp-wrappers/io_mcp_base/server.py`
- Create: `mcp-servers/io-mcp-wrappers/tests/test_server.py`

- [ ] **Step 8.1: Failing tests**

`tests/test_server.py`:
```python
import json
import pytest
from mcp.types import Tool, TextContent

from io_mcp_base.server import build_server, ok_response, error_response
from io_mcp_base.errors import GatewayError


def test_ok_response_envelope():
    tc = ok_response({"id": "x"})
    assert isinstance(tc, list) and len(tc) == 1 and isinstance(tc[0], TextContent)
    body = json.loads(tc[0].text)
    assert body == {"ok": True, "data": {"id": "x"}}


def test_error_response_from_gateway_error():
    err = GatewayError(kind="auth", detail="gateway rejected token")
    tc = error_response(err)
    body = json.loads(tc[0].text)
    assert body == {"error": "auth", "detail": "gateway rejected token"}


def test_error_response_with_retry_after():
    err = GatewayError(kind="rate_limit", retry_after=30)
    body = json.loads(error_response(err)[0].text)
    assert body == {"error": "rate_limit", "retry_after": 30}


def test_error_response_swallows_internal_exception():
    err = ValueError("something broke with details")
    body = json.loads(error_response(err)[0].text)
    assert body == {"error": "internal"}
    # MUST NOT leak the exception message
    assert "details" not in json.dumps(body)


@pytest.mark.asyncio
async def test_build_server_registers_tools():
    tool = Tool(name="echo", description="t", inputSchema={"type": "object"})
    async def handler(args):
        return ok_response({"echoed": args})
    srv = build_server("io-echo", [(tool, handler)])
    tools = await srv.request_handlers[type(srv).list_tools_request_handler].__func__(srv, None)  # type: ignore  # noqa
    # smoke check: server has at least the one tool we registered
    assert srv.name == "io-echo"
```

(The last assertion is a smoke check; the MCP SDK's exact internal API for inspecting registered tools varies — replace with whatever the SDK exposes. If introspection is awkward, drop that test and verify via a stdio integration test in Task 12.)

- [ ] **Step 8.2: Run; confirm failures**

```bash
.venv/Scripts/pytest tests/test_server.py -v
```

- [ ] **Step 8.3: Implement `server.py`**

`io_mcp_base/server.py`:
```python
"""Factory for stdio MCP servers. Each wrapper hands `build_server` its
name and a list of (Tool, handler) pairs; the factory returns a configured
mcp.server.Server.

Tool responses use a consistent envelope:
  success:  {"ok": true, "data": <result>}
  failure:  {"error": "<kind>", "detail"?: "...", "retry_after"?: N}

GatewayError is mapped automatically. Any other exception becomes
{"error": "internal"} — the agent never sees the original message,
which protects against unintended leaks per the spec's secret hygiene
section.
"""
from __future__ import annotations

import json
from typing import Awaitable, Callable

from mcp.server import Server
from mcp.types import Tool, TextContent

from .errors import GatewayError


ToolHandler = Callable[[dict], Awaitable[list[TextContent]]]


def ok_response(data) -> list[TextContent]:
    return [TextContent(type="text",
                        text=json.dumps({"ok": True, "data": data}))]


def error_response(err: Exception) -> list[TextContent]:
    if isinstance(err, GatewayError):
        body: dict = {"error": err.kind}
        if err.detail:
            body["detail"] = err.detail
        if err.retry_after is not None:
            body["retry_after"] = err.retry_after
    else:
        body = {"error": "internal"}
    return [TextContent(type="text", text=json.dumps(body))]


def build_server(name: str, tools: list[tuple[Tool, ToolHandler]]) -> Server:
    server: Server = Server(name)
    tool_specs = [t for t, _ in tools]
    handlers = {t.name: h for t, h in tools}

    @server.list_tools()
    async def _list() -> list[Tool]:
        return tool_specs

    @server.call_tool()
    async def _call(tool_name: str, arguments: dict) -> list[TextContent]:
        h = handlers.get(tool_name)
        if h is None:
            return error_response(ValueError(f"unknown tool: {tool_name}"))
        try:
            return await h(arguments)
        except GatewayError as e:
            return error_response(e)
        except Exception as e:  # noqa: BLE001 — paranoia: sanitize all errors
            return error_response(e)

    return server


async def run_stdio(server: Server) -> None:
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())
```

- [ ] **Step 8.4: Tests pass**

```bash
.venv/Scripts/pytest tests/test_server.py -v
```
Expected: at least the first 4 envelope tests pass; the 5th may need adjusting based on the MCP SDK version actually in use. If unstable, simplify to just `assert srv.name == "io-echo"`.

- [ ] **Step 8.5: Commit**

```bash
git add mcp-servers/io-mcp-wrappers/io_mcp_base/server.py mcp-servers/io-mcp-wrappers/tests/test_server.py
git commit -m "feat(io-mcp-wrappers): build_server factory + ok/error envelopes"
```

---

## Task 9: Orchestrator — `RemoteExecutor` accepts `user_jwt` and forwards via SendEnv

**Files:**
- Modify: `mcp-servers/tasks/remote_executor.py`
- Modify: `mcp-servers/tasks/tests/test_remote_executor.py`

- [ ] **Step 9.1: Failing test**

Add to `tests/test_remote_executor.py`:
```python
@pytest.mark.asyncio
async def test_user_jwt_forwarded_via_sendenv(monkeypatch):
    """When run() is given user_jwt, the build-ssh call must use
    SendEnv=AIUI_AGENT_EFFORT,IO_USER_JWT and have IO_USER_JWT in the
    subprocess env.
    """
    monkeypatch.setattr("os.path.exists", lambda _p: True)
    seen_env = {}
    seen_args = []

    async def fake_spawn(*args, **kwargs):
        seen_args.append(args)
        if kwargs.get("env"):
            seen_env.update(kwargs["env"])
        cmd = args[0]
        if cmd == "ssh" and "claude --print" in args[-1]:
            return _fake_proc([
                b'{"type":"result","subtype":"success","is_error":false,'
                b'"result":"COMPLETED: ok"}\n',
            ], returncode=0)
        return _fake_proc([], returncode=0)

    with patch("asyncio.create_subprocess_exec",
               AsyncMock(side_effect=fake_spawn)):
        ex = RemoteExecutor()
        async for _ in ex.run("build it", slug="myapp", execution_id="e",
                              user_jwt="abc.def.ghi"):
            pass

    build_ssh = next(a for a in seen_args
                     if a[0] == "ssh" and "claude --print" in a[-1])
    # The SendEnv flag pair should now include IO_USER_JWT
    sendenv_indices = [i for i, v in enumerate(build_ssh)
                       if v == "-o" and i + 1 < len(build_ssh)
                       and "SendEnv=" in build_ssh[i + 1]]
    assert sendenv_indices, "no -o SendEnv= flag found on the build ssh"
    sendenv_value = build_ssh[sendenv_indices[0] + 1]
    assert "IO_USER_JWT" in sendenv_value
    # The subprocess env passed to ssh contains the JWT
    assert seen_env.get("IO_USER_JWT") == "abc.def.ghi"
```

- [ ] **Step 9.2: Run; confirm failure**

```bash
cd mcp-servers/tasks
pytest tests/test_remote_executor.py::test_user_jwt_forwarded_via_sendenv -v
```
Expected: FAIL — `run()` doesn't accept `user_jwt`.

- [ ] **Step 9.3: Update `RemoteExecutor.run` and `_stream`**

In `remote_executor.py`, change the `run` signature and pipe through:
```python
    async def run(
        self,
        prompt: str,
        slug: str | None,
        execution_id: str,
        user_jwt: str | None = None,
    ) -> AsyncIterator[str]:
        # ... existing validation ...
        host = os.environ["AGENT_HOST"]
        user = os.environ.get("AGENT_USER", "claude-agent")
        key  = os.environ["AGENT_SSH_KEY_PATH"]
        effort = os.environ.get("AIUI_AGENT_EFFORT", "low")
        # ... existing health check + push ...
        remote_cmd = self._build_remote_cmd(prompt, slug, effort)
        try:
            async for line in self._stream(host, user, key, remote_cmd, user_jwt):
                # ... unchanged loop body ...
```

And update `_stream`:
```python
    async def _stream(self, host, user, key, remote_cmd,
                      user_jwt: str | None = None) -> AsyncIterator[str]:
        sendenv = "AIUI_AGENT_EFFORT"
        env_pass: dict[str, str] | None = None
        if user_jwt:
            sendenv = "AIUI_AGENT_EFFORT,IO_USER_JWT"
            env_pass = {**os.environ, "IO_USER_JWT": user_jwt}
        self._proc = await asyncio.create_subprocess_exec(
            "ssh", "-i", key, *self._SSH_OPTS,
            "-o", f"SendEnv={sendenv}",
            f"{user}@{host}", remote_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env_pass,
        )
        # ... rest unchanged ...
```

- [ ] **Step 9.4: All tests pass — new one + the existing 17**

```bash
pytest tests/test_remote_executor.py -v
```
Expected: 18 passed.

- [ ] **Step 9.5: Commit**

```bash
git add mcp-servers/tasks/remote_executor.py mcp-servers/tasks/tests/test_remote_executor.py
git commit -m "feat(remote_executor): forward user_jwt to agent via SendEnv"
```

---

## Task 10: Orchestrator — extract JWT from request, pass to executor

**Files:**
- Modify: `mcp-servers/tasks/main.py` (locate the build trigger route — search for `RemoteExecutor` and the place that constructs/calls `run()`)
- Modify: `mcp-servers/tasks/agent_executor.py` if needed (Protocol)

- [ ] **Step 10.1: Locate the executor call site**

```bash
grep -n "executor.run(\|\.run(prompt" mcp-servers/tasks/main.py mcp-servers/tasks/routes_*.py
```

- [ ] **Step 10.2: Pull JWT from request and thread through**

The build-trigger route already has a `Request` object (for `current_admin` dependency) — read `Authorization` header from it. Pattern:

```python
@router.post("/execute")
async def execute(req: Request, body: ExecuteBody,
                  user=Depends(current_admin)):
    raw = req.headers.get("Authorization", "")
    user_jwt = raw.removeprefix("Bearer ").strip() if raw.startswith("Bearer ") else None
    # ... existing executor build ...
    async for chunk in executor.run(prompt, slug=slug, execution_id=eid,
                                     user_jwt=user_jwt):
        yield chunk
```

If the executor is accessed through a Protocol (see `agent_executor.py`), add `user_jwt: str | None = None` to the Protocol's `run` signature so `LocalExecutor` and `RemoteExecutor` share the type.

- [ ] **Step 10.3: Add a test that verifies main.py passes JWT through**

Pattern: in an existing build-trigger test (look in `tests/test_routes_execution.py` or similar), assert the mocked executor receives `user_jwt=<expected>` when called with `Authorization: Bearer xyz`.

- [ ] **Step 10.4: Tests pass**

```bash
pytest mcp-servers/tasks/tests/ -v -k "execute"
```

- [ ] **Step 10.5: Commit**

```bash
git add mcp-servers/tasks/main.py mcp-servers/tasks/agent_executor.py mcp-servers/tasks/tests/
git commit -m "feat(tasks): extract user JWT from build request, forward to executor"
```

---

## Task 10b: Caddy + API Gateway — route MCP service prefixes through the gateway

This is the new infrastructure step that makes the spec's auth model real. Today Caddy direct-routes `/gmail/*`, `/gdrive/*`, `/calendar/*`, `/meetings/*` to the MCP backends, bypassing the API Gateway. We change Caddy to route those (and 4 new prefixes) through the gateway, and add matching branches to the gateway's `proxy_handler`.

This task **also fixes a pre-existing bug**: today browser users hitting `/gmail/auth/google/start` all share `default@local` tokens because no `X-User-Email` is injected. After this change, the gateway sets the header from validated JWT/cookie.

**Files:**
- Modify: `Caddyfile` (sections currently around lines 182-209)
- Modify: `api-gateway/main.py` (the `proxy_handler` function around line 302-437)

- [ ] **Step 10b.1: Update Caddyfile**

Change these four `handle` blocks (currently direct routes to MCP backends):
```
handle /gdrive/* { uri strip_prefix /gdrive; reverse_proxy mcp-gdrive:8000 }
handle /gmail/* { uri strip_prefix /gmail; reverse_proxy mcp-gmail:8000 }
handle /calendar/* { uri strip_prefix /calendar; reverse_proxy mcp-calendar:8000 }
handle /meetings/* { uri strip_prefix /meetings; reverse_proxy mcp-meetings:8000 }
```

Replace with gateway routes (do NOT strip the prefix — the gateway needs to see it to dispatch). Also update the section comments above each block from e.g. "# Google Drive MCP connector" to "# Google Drive MCP connector (via api-gateway for X-User-Email injection)" so future readers don't think these are direct routes anymore.

```
handle /gdrive/* { reverse_proxy api-gateway:8080 }
handle /gmail/* { reverse_proxy api-gateway:8080 }
handle /calendar/* { reverse_proxy api-gateway:8080 }
handle /meetings/* { reverse_proxy api-gateway:8080 }
```

Add four new `handle` blocks (place near the existing MCP connector blocks, ~line 200):
```
handle /web-search/* { reverse_proxy api-gateway:8080 }
handle /meeting-kb/* { reverse_proxy api-gateway:8080 }
handle /dashboard/* { reverse_proxy api-gateway:8080 }
handle /excel-creator/* { reverse_proxy api-gateway:8080 }
```

- [ ] **Step 10b.2: Update `api-gateway/main.py:proxy_handler`**

Inside the routing chain — specifically AFTER the existing `elif full_path.startswith("/servers") or ... "/openapi"` branch (around line 431-433) and BEFORE the final `else:` that falls through to Open WebUI — insert 8 new branches. Ordering of the 8 doesn't matter for correctness (the prefixes are disjoint), but placement relative to the existing chain does — they MUST come before the final `else` so Open WebUI doesn't capture them:

```python
    # /gmail/*, /gdrive/*, /calendar/*, /meetings/*, /web-search/*,
    # /dashboard/*, /excel-creator/*, /meeting-kb/* — strip the prefix
    # and forward to the corresponding mcp-* service. The gateway has
    # already validated JWT and built gateway_headers above, so the
    # backend will see X-User-Email correctly set (it falls back to
    # "default@local" if absent, which is the pre-spec behavior).
    elif full_path.startswith("/web-search/"):
        backend_url = os.getenv("WEB_SEARCH_URL", "http://mcp-web-search:8000")
        backend_path = full_path[len("/web-search"):]
    elif full_path.startswith("/gmail/"):
        backend_url = os.getenv("GMAIL_URL", "http://mcp-gmail:8000")
        backend_path = full_path[len("/gmail"):]
    elif full_path.startswith("/gdrive/"):
        backend_url = os.getenv("GDRIVE_URL", "http://mcp-gdrive:8000")
        backend_path = full_path[len("/gdrive"):]
    elif full_path.startswith("/calendar/"):
        backend_url = os.getenv("CALENDAR_URL", "http://mcp-calendar:8000")
        backend_path = full_path[len("/calendar"):]
    elif full_path.startswith("/meetings/"):
        backend_url = os.getenv("MEETINGS_URL", "http://mcp-meetings:8000")
        backend_path = full_path[len("/meetings"):]
    elif full_path.startswith("/meeting-kb/"):
        backend_url = os.getenv("MEETING_KB_URL", "http://meeting-kb:8200")
        backend_path = full_path[len("/meeting-kb"):]
    elif full_path.startswith("/dashboard/"):
        backend_url = os.getenv("DASHBOARD_URL", "http://mcp-dashboard:8000")
        backend_path = full_path[len("/dashboard"):]
    elif full_path.startswith("/excel-creator/"):
        backend_url = os.getenv("EXCEL_CREATOR_URL", "http://mcp-excel-creator:8000")
        backend_path = full_path[len("/excel-creator"):]
```

Note: the existing `/mcp/meeting-kb/api` branch (line 401-403) handles the legacy uploader path; keep it untouched. The new `/meeting-kb/*` branch is purely additive.

- [ ] **Step 10b.3: Local sanity-check (no Hetzner deploy yet)**

```bash
cd api-gateway
python -c "import ast; ast.parse(open('main.py').read()); print('OK')"
```
Expected: `OK`. Sanity-syntax check; full test suite for proxy_handler doesn't exist as a unit test today.

If you want a regression test, add one quick smoke test that asserts the 8 prefix branches resolve to the expected backend URLs by importing `proxy_handler` and asserting backend_url for given paths via patched `forward_request`. Optional; if test infra is sparse, rely on Step 10b.4 instead.

- [ ] **Step 10b.4: Deploy to Hetzner and live-verify**

```bash
# From operator workstation, deploy the two changed files
scp Caddyfile root@46.224.193.25:/root/proxy-server/Caddyfile
scp api-gateway/main.py root@46.224.193.25:/root/proxy-server/api-gateway/main.py

# Restart only the two services that changed
ssh root@46.224.193.25 \
  "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build api-gateway caddy"

# The Hetzner box has Caddy on :80 behind Cloudflare (HTTP) and :443 (TLS).
# Smoke from inside the box uses :80 directly. If :80 is bound only to a
# specific interface, run the curl from inside the caddy container instead:
#   docker compose exec caddy curl -sS http://api-gateway:8080/web-search/web_search ...
# That bypasses Caddy and hits the gateway directly — equivalent end-to-end
# for verifying the new branches.

# Smoke 1: legacy browser flow still works (use a real user's session cookie)
ssh root@46.224.193.25 \
  "curl -s -o /dev/null -w '%{http_code}\\n' \
   -H 'Cookie: token=<a real token>' \
   http://localhost/gmail/auth/google/status"
# Expected: 200 (with valid token) or 401 (with invalid cookie) — NOT 404, NOT 502

# Smoke 2: agent-style auth header reaches the backend with correct user
ssh root@46.224.193.25 \
  "curl -sS -H 'Authorization: Bearer <real JWT>' \
   -H 'Content-Type: application/json' \
   -X POST http://localhost/web-search/web_search \
   -d '{\"query\":\"test\",\"count\":1}'"
# Expected: JSON results or a Brave-API-related error (NOT 404, NOT 502, NOT "default@local")
```

If either smoke check fails, fix BEFORE moving on. The wrappers are useless without this layer working.

- [ ] **Step 10b.5: Commit**

```bash
git add Caddyfile api-gateway/main.py
git commit -m "feat(gateway): route MCP service prefixes through api-gateway for JWT/X-User-Email injection"
```

---

## Task 11: Provisioning — install io-mcp-wrappers + register wrappers on the agent VM

**Files:**
- Modify: `scripts/provision_agent_vm.sh`

- [ ] **Step 11.1: Edit `provision_agent_vm.sh`**

After step `[7/8]` (flights-mcp install), add a new step that does the same for `io-mcp-wrappers`:

```bash
echo "==> [7b/8] io-mcp-wrappers install + register each wrapper"
scp -r "${REPO_ROOT}/mcp-servers/io-mcp-wrappers" root@${AGENT_HOST}:/tmp/io-mcp-wrappers
${SSH} bash -se <<'EOF'
set -euo pipefail
rm -rf /opt/io-mcp
mv /tmp/io-mcp-wrappers /opt/io-mcp
python3 -m venv /opt/io-mcp/venv
/opt/io-mcp/venv/bin/pip install -e /opt/io-mcp >/dev/null

# Append IO_GATEWAY_URL to claude-agent's .profile (idempotent)
grep -q 'IO_GATEWAY_URL' /home/claude-agent/.profile || \
  echo 'export IO_GATEWAY_URL=http://172.22.0.1:8080' >> /home/claude-agent/.profile
chown claude-agent:claude-agent /home/claude-agent/.profile

# Allow ssh to pass IO_USER_JWT to the agent shell (idempotent)
grep -q '^AcceptEnv .*IO_USER_JWT' /etc/ssh/sshd_config || \
  sed -i 's/^AcceptEnv AIUI_AGENT_EFFORT$/AcceptEnv AIUI_AGENT_EFFORT IO_USER_JWT/' /etc/ssh/sshd_config
systemctl reload ssh

# Register each wrapper for claude-agent (user scope, idempotent —
# claude mcp add is idempotent on identical config)
sudo -u claude-agent bash -c '
  source ~/.env
  for svc in web_search gdrive gmail calendar meetings meeting_kb dashboard excel_creator; do
    name="io-${svc//_/-}"
    claude mcp add --scope user "$name" \
      /opt/io-mcp/venv/bin/python -m "io_mcp_$svc" || true
  done
'
EOF
```

- [ ] **Step 11.2: Dry-run check on the agent VM**

```bash
# From the operator workstation, with the same env vars used originally
./scripts/provision_agent_vm.sh
```

Confirm:
```bash
ssh claude-agent@<agent-host> "claude mcp list" | grep -E '^io-'
```
Expected: lists `io-web-search`, `io-gdrive`, `io-gmail`, `io-calendar`, `io-meetings`, `io-meeting-kb`, `io-dashboard`, `io-excel-creator` (8 total).

(If wrapper modules don't exist yet — Tasks 12–19 — `claude mcp add` still records the config; the wrappers will fail at first invocation until their modules are written. That's expected.)

- [ ] **Step 11.3: Commit**

```bash
git add scripts/provision_agent_vm.sh
git commit -m "feat(provision): install io-mcp-wrappers and register all 8 wrappers"
```

---

## Task 12: `io-web-search` wrapper (template for all other wrappers)

This wrapper is the simplest — one tool, one endpoint, no auth state. Use it as the template for Tasks 13–20.

**Files:**
- Create: `mcp-servers/io-mcp-wrappers/io_mcp_web_search/__init__.py`
- Create: `mcp-servers/io-mcp-wrappers/io_mcp_web_search/__main__.py`
- Create: `mcp-servers/io-mcp-wrappers/io_mcp_web_search/tools.py`
- Create: `mcp-servers/io-mcp-wrappers/tests/test_web_search_wrapper.py`

- [ ] **Step 12.1: Confirm the upstream route**

```bash
grep -n "@app.post\|@app.get" mcp-servers/web-search/main.py
```

Expected: `POST /web_search` accepting `WebSearchRequest({"query": str, "count": int=5})`. After Task 10b, this is reachable through the gateway at `POST /web-search/web_search`.

- [ ] **Step 12.2: Write the failing tests**

`tests/test_web_search_wrapper.py`:
```python
import json
import pytest
from unittest.mock import AsyncMock

from io_mcp_web_search.tools import web_search_tool_spec, make_web_search_handler


@pytest.mark.asyncio
async def test_calls_gateway_search(monkeypatch):
    client = AsyncMock()
    client.post = AsyncMock(return_value={"results": [{"title": "a", "url": "u", "snippet": "s"}]})
    handler = make_web_search_handler(client)
    result = await handler({"query": "hello", "count": 3})
    client.post.assert_called_once_with("/web-search/web_search",
                                         json={"query": "hello", "count": 3})
    body = json.loads(result[0].text)
    assert body["ok"] is True
    assert body["data"]["results"][0]["url"] == "u"


@pytest.mark.asyncio
async def test_auth_error_envelope(monkeypatch):
    from io_mcp_base.errors import GatewayError
    client = AsyncMock()
    client.post = AsyncMock(side_effect=GatewayError(kind="auth",
                                                      detail="gateway rejected token"))
    handler = make_web_search_handler(client)
    result = await handler({"query": "x"})
    body = json.loads(result[0].text)
    assert body == {"error": "auth", "detail": "gateway rejected token"}


def test_tool_spec_shape():
    t = web_search_tool_spec()
    assert t.name == "web_search"
    assert "query" in t.inputSchema["properties"]
    assert "query" in t.inputSchema["required"]
```

- [ ] **Step 12.3: Run; confirm failures**

```bash
cd mcp-servers/io-mcp-wrappers
.venv/Scripts/pytest tests/test_web_search_wrapper.py -v
```

- [ ] **Step 12.4: Implement the wrapper**

`io_mcp_web_search/__init__.py`: empty.

`io_mcp_web_search/tools.py`:
```python
"""io-web-search MCP wrapper — exposes Brave-backed web search as a tool."""
from __future__ import annotations

from mcp.types import Tool, TextContent

from io_mcp_base.client import GatewayClient
from io_mcp_base.server import ok_response


def web_search_tool_spec() -> Tool:
    return Tool(
        name="web_search",
        description=(
            "Search the public web via the platform's web-search service. "
            "Returns up to `count` results with title, url, and snippet."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "count": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            },
            "required": ["query"],
        },
    )


def make_web_search_handler(client: GatewayClient):
    async def handler(args: dict) -> list[TextContent]:
        payload = {"query": args["query"], "count": args.get("count", 5)}
        data = await client.post("/web-search/web_search", json=payload)
        return ok_response(data)
    return handler
```

`io_mcp_web_search/__main__.py`:
```python
"""Entry point: `python -m io_mcp_web_search` for `claude mcp add`."""
import asyncio

from io_mcp_base.client import GatewayClient
from io_mcp_base.server import build_server, run_stdio
from .tools import web_search_tool_spec, make_web_search_handler


def main() -> None:
    client = GatewayClient()  # raises if env missing
    server = build_server("io-web-search",
                          [(web_search_tool_spec(), make_web_search_handler(client))])
    asyncio.run(run_stdio(server))


if __name__ == "__main__":
    main()
```

- [ ] **Step 12.5: Tests pass**

```bash
.venv/Scripts/pytest tests/test_web_search_wrapper.py -v
```
Expected: 3 passed.

- [ ] **Step 12.6: Commit**

```bash
git add mcp-servers/io-mcp-wrappers/io_mcp_web_search mcp-servers/io-mcp-wrappers/tests/test_web_search_wrapper.py
git commit -m "feat(io-web-search): MCP wrapper for the web-search service"
```

---

## Task 13–19: Remaining 7 wrappers (follow Task 12 pattern)

For each wrapper below, follow the same 6 steps from Task 12:
1. Discover upstream routes via `grep "@app\." mcp-servers/<svc>/main.py`
2. Write failing tests (3 minimum: happy path, auth error envelope, tool spec shape)
3. Run, confirm failure
4. Implement `<svc>/__init__.py`, `tools.py`, `__main__.py`
5. Run tests; all green
6. Commit per wrapper

Routes confirmed from actual backends (re-grep `mcp-servers/<svc>/main.py` if anything looks off):

| # | Wrapper | Tools — MCP name → gateway path → backend route |
|---|---|---|
| 13 | `io_mcp_gdrive` | `gdrive_search` → `POST /gdrive/gdrive_search_files`; `gdrive_read_file` → `POST /gdrive/gdrive_read_file`; `gdrive_list_files` → `POST /gdrive/gdrive_list_files`. Cap file content at 5MB in `gdrive_read_file` — return `{"error":"too_large"}` if upstream returns >5MB. |
| 14 | `io_mcp_gmail` | `gmail_search` → `POST /gmail/gmail_search_emails`; `gmail_send` → `POST /gmail/gmail_send_email`; `gmail_read` → `POST /gmail/gmail_read_email`. The wrapper must NEVER log message bodies (base `_do` log line is METHOD + URL + STATUS only — already correct). |
| 15 | `io_mcp_calendar` | `calendar_list_events` → `POST /calendar/calendar_list_events`; `calendar_create_event` → `POST /calendar/calendar_create_event`. (Backend uses POST for both — see `mcp-servers/calendar/main.py:437,514`.) |
| 16 | `io_mcp_meetings` | `meetings_list` → `GET /meetings/`; `meetings_get` → `GET /meetings/{id}`. Backend's routes are at the root (`/`, `/{id}`); the gateway strips `/meetings` so `/meetings/abc` → backend `/abc`. |
| 17 | `io_mcp_meeting_kb` | `meeting_kb_search` → `POST /meeting-kb/search_meetings`; `meeting_kb_get` → `POST /meeting-kb/get_meeting`; `meeting_kb_list` → `POST /meeting-kb/list_meetings`. Note: this is a NEW prefix on the same backend as the legacy `/mcp/meeting-kb/api/*` upload route (which we keep untouched). The two prefixes are intentional — one for the MCP search/get/list surface, one for the upload API. |
| 18 | `io_mcp_dashboard` | `dashboard_create` → `POST /dashboard/create_simple_dashboard`. |
| 19 | `io_mcp_excel_creator` | `excel_create_workbook` → `POST /excel-creator/create_simple_excel`. Return JSON metadata only, not file bytes. |

**Note: `io_mcp_tasks` was originally Task 16 and is now deferred to v2** (per spec §2 out-of-scope). The `tasks` service is the orchestrator itself; its `routes_projects.py` is mounted at `/api/projects` with no clean read-only `GET /` or `GET /{slug}` listing route, and Lukas didn't ask for it specifically. Total wrappers for v1: 8 (`web_search` + tasks 13–19 above).

If any upstream route differs from this table when you grep, follow what's actually in `mcp-servers/<svc>/main.py` and update the wrapper to match. Commit the actual route used.


---

## Task 21: End-to-end smoke script

**Files:**
- Create: `scripts/smoke_mcp_access.sh`

- [ ] **Step 21.1: Write the script**

```bash
#!/usr/bin/env bash
# Smoke-test the io-mcp-wrappers end-to-end on the live agent VM.
#
# Prereqs:
#   - Task 11 has been run (provisioning extended)
#   - Tasks 12-19 wrappers committed and re-deployed
#   - $AGENT_HOST and $ORCH_HOST set; user has a valid JWT in $IO_USER_JWT
#
# Strategy:
#   1. Positive: ask the agent to run a prompt that exercises 2 different
#      MCPs (web_search + gmail). Assert tool_use events for both, plus
#      COMPLETED in the terminal result event.
#   2. Negative: same prompt with IO_USER_JWT=bad. Assert tool_results
#      contain {"error":"auth"} and the bad JWT string never appears in
#      the orchestrator log or claude's stream.

set -euo pipefail

: "${AGENT_HOST:?}"
: "${ORCH_HOST:?}"
: "${IO_USER_JWT:?}"

POSITIVE_PROMPT='Search the web for "anthropic claude release notes" and
return a one-line summary as text. End your message with COMPLETED.'

# Positive — kick off a build through the orchestrator's HTTP API
echo "==> [smoke 1/2] positive build"
slug="smoke-mcp-$(date +%s)"
resp=$(curl -sS -H "Authorization: Bearer $IO_USER_JWT" \
  -H "Content-Type: application/json" \
  -X POST "https://${ORCH_HOST}/tasks/api/execute" \
  -d "$(printf '{"slug":"%s","prompt":"%s"}' "$slug" "$POSITIVE_PROMPT")")
echo "$resp"
echo "$resp" | grep -q '"tool_use"' || { echo "FAIL: no tool_use event"; exit 1; }
echo "$resp" | grep -q 'io-web-search' || { echo "FAIL: io-web-search not used"; exit 1; }
echo "$resp" | grep -q 'COMPLETED' || { echo "FAIL: no COMPLETED"; exit 1; }
echo "    positive smoke OK"

# Negative — bad JWT
echo "==> [smoke 2/2] negative build (bad JWT)"
slug="smoke-mcp-neg-$(date +%s)"
neg=$(IO_USER_JWT=BAD curl -sS -H "Authorization: Bearer BAD-TOKEN-DO-NOT-LEAK" \
  -H "Content-Type: application/json" \
  -X POST "https://${ORCH_HOST}/tasks/api/execute" \
  -d "$(printf '{"slug":"%s","prompt":"%s"}' "$slug" "$POSITIVE_PROMPT")" || true)
echo "$neg" | grep -q '"error":"auth"' || { echo "FAIL: bad JWT did not produce auth error"; exit 1; }
echo "$neg" | grep -q 'BAD-TOKEN-DO-NOT-LEAK' && { echo "FAIL: bad JWT leaked into response"; exit 1; }
echo "    negative smoke OK (no leak, clean auth error)"
chmod +x scripts/smoke_mcp_access.sh
```

(Replace the orchestrator API path if the actual route differs — verify against `mcp-servers/tasks/routes_execution.py`.)

- [ ] **Step 21.2: Make executable and run against the live agent VM**

```bash
chmod +x scripts/smoke_mcp_access.sh
AGENT_HOST=46.224.193.25 ORCH_HOST=ai-ui.coolestdomain.win IO_USER_JWT=<real-jwt> ./scripts/smoke_mcp_access.sh
```
Expected: both checks print OK.

- [ ] **Step 21.3: Commit**

```bash
git add scripts/smoke_mcp_access.sh
git commit -m "feat(scripts): end-to-end smoke for io-mcp-wrappers"
```

---

## Task 22: Operator docs update

**Files:**
- Modify: `docs/agent-vm/README.md`

- [ ] **Step 22.1: Add a "MCP wrappers" section**

Append to `docs/agent-vm/README.md`:
```markdown
## MCP Wrappers (added 2026-05-15)

### Env vars
- `IO_GATEWAY_URL` — set in `/home/claude-agent/.profile` (default `http://172.22.0.1:8080`)
- `IO_USER_JWT` — forwarded per-build via SSH `SendEnv` from the orchestrator. Never persisted on the agent.

### Registered wrappers
Run `claude mcp list` as `claude-agent` to see all `io-*` wrappers.
Reference: [spec](../superpowers/specs/2026-05-15-mcp-access-from-vm-agent-design.md).

### Common operator tasks
- **Add a new wrapper:** create `mcp-servers/io-mcp-wrappers/io_mcp_<svc>/` following the `io_mcp_web_search` template, then add `<svc>` to the `for svc in …` loop in `scripts/provision_agent_vm.sh` step `[7b/8]`, then re-run provisioning.
- **Verify the JWT plumbing for a build:** `journalctl -u ssh --since "10 min ago" | grep IO_USER_JWT` (you should see ssh log lines mentioning `IO_USER_JWT` was passed; **the value itself must NOT appear in any log**).

### Out of scope (deferred to heartbeat spec)
Cron / scheduled / no-live-user invocations don't carry a user JWT, so the wrappers will fail-fast on `auth` for those flows. Use the manual app-builder flow only until the heartbeat spec lands.
```

- [ ] **Step 22.2: Commit**

```bash
git add docs/agent-vm/README.md
git commit -m "docs(agent-vm): document io-mcp-wrappers env vars and operator tasks"
```

---

## Final verification (before merge)

- [ ] **All unit tests green**

```bash
cd mcp-servers/io-mcp-wrappers
.venv/Scripts/pytest -v
```

```bash
cd mcp-servers/tasks
docker compose -f docker-compose.unified.yml exec tasks pytest tests/ -v
# or local: pytest tests/ -v
```
Expected: io-mcp-wrappers tests all pass; tasks tests show 18/18 in `test_remote_executor.py` (was 17).

- [ ] **End-to-end smoke**

```bash
./scripts/smoke_mcp_access.sh
```
Expected: both positive and negative pass.

- [ ] **Inspect logs for JWT leakage (manual verification of Lukas's primary concern)**

After running a build:
```bash
# On the orchestrator host:
docker compose logs tasks --since 10m | grep -i "bearer\|jwt\|authorization" || echo "CLEAN"

# On the agent VM:
ssh claude-agent@$AGENT_HOST "journalctl --user -u claude --since '10 min ago' 2>/dev/null | grep -i 'bearer\|jwt' || echo CLEAN"
```
Expected: `CLEAN` from both.

- [ ] **Then proceed to the `finishing-a-development-branch` skill** to decide on PR vs merge.

---

## Success criteria (from spec §10, recap)

- Layer-1 + Layer-2 unit tests green
- Two paranoid secret-hygiene tests present and green
- `scripts/smoke_mcp_access.sh` passes end-to-end (positive AND negative)
- `mcp-servers/tasks/tests/test_remote_executor.py` — 18 tests passing
- A live build using `io-web-search` AND `io-gmail` produces output and rsyncs back cleanly
- No JWT appears in orchestrator logs, agent stderr, or claude's stream-json for a successful build
