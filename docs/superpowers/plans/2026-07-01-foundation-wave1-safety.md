# Foundation Wave 1: Safety — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the SSRF hole on user-supplied capture URLs, cap the gateway classification concurrency, and put a memory limit on the webhook-handler container — the cheap, high-value safety slice of Foundation.

**Architecture:** A new pure `handlers/url_guard.py` validator applied at the two capture entry points; a module-level `asyncio.Semaphore` around the gateway chat path in `commands.py`; a `deploy.resources.limits.memory` block on the webhook-handler service in compose. Webhook-handler + compose only — no tasks-service rebuild.

**Tech Stack:** Python 3.11, pytest (`cd webhook-handler && python -m pytest -q`), Docker Compose.

This is Wave 1 of 3 for the Foundation sub-project (spec: `docs/superpowers/specs/2026-07-01-foundation-identity-and-state-design.md`). Wave 2 = identity (entry-gating), Wave 3 = durable state (tasks service).

---

## File structure

- Create `webhook-handler/handlers/url_guard.py` — SSRF-safe URL validation. One responsibility.
- Modify `webhook-handler/handlers/commands.py` — apply the guard in `run_video_capture`; add `_CHAT_SEMAPHORE` + wrap `handle_chat_message`.
- Modify `webhook-handler/handlers/slack_interactions.py` — apply the guard in `_run_slack_video`.
- Modify `docker-compose.unified.yml` — memory limit on webhook-handler.
- Tests: new `webhook-handler/tests/test_url_guard.py`; extend `webhook-handler/tests/test_intent_gateway.py`.

Run tests: `cd "C:/Users/alama/Desktop/Lukas Work/IO/webhook-handler" && python -m pytest -q`

---

### Task 1: SSRF-safe URL guard

**Files:**
- Create: `webhook-handler/handlers/url_guard.py`
- Test: `webhook-handler/tests/test_url_guard.py`

- [ ] **Step 1: Write the failing tests** — create `tests/test_url_guard.py`:

```python
"""SSRF guard: only public http(s) URLs pass; private/loopback/link-local/
metadata hosts are blocked (literal IPs need no DNS; hostnames are resolved)."""
from handlers.url_guard import is_safe_public_url, _is_blocked_ip


def test_blocked_ip_classifier():
    for bad in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1",
                "169.254.169.254", "::1", "0.0.0.0", "fd00::1"):
        assert _is_blocked_ip(bad) is True, bad
    for ok in ("8.8.8.8", "1.1.1.1", "93.184.216.34"):
        assert _is_blocked_ip(ok) is False, ok


def test_scheme_and_host_rules():
    assert is_safe_public_url("ftp://example.com") is False       # scheme
    assert is_safe_public_url("file:///etc/passwd") is False
    assert is_safe_public_url("notaurl") is False                 # no host
    assert is_safe_public_url("") is False


def test_literal_ip_urls_need_no_dns():
    assert is_safe_public_url("http://169.254.169.254/latest/meta-data") is False
    assert is_safe_public_url("http://127.0.0.1:8080/") is False
    assert is_safe_public_url("https://10.0.0.5/") is False
    assert is_safe_public_url("https://[::1]/") is False


def test_hostname_resolution(monkeypatch):
    # resolver returns (family, type, proto, canonname, sockaddr) tuples
    def fake(host, port, *a, **k):
        ip = {"public.example": "93.184.216.34", "evil.example": "10.1.2.3"}[host]
        return [(2, 1, 6, "", (ip, 0))]
    monkeypatch.setattr("handlers.url_guard.socket.getaddrinfo", fake)
    assert is_safe_public_url("https://public.example/x") is True
    assert is_safe_public_url("http://public.example/x") is True   # http allowed
    assert is_safe_public_url("https://evil.example/x") is False    # resolves private


def test_unresolvable_host_is_blocked(monkeypatch):
    def boom(host, port, *a, **k):
        raise OSError("nxdomain")
    monkeypatch.setattr("handlers.url_guard.socket.getaddrinfo", boom)
    assert is_safe_public_url("https://nope.invalid/") is False
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `python -m pytest tests/test_url_guard.py -q`
Expected: FAIL (module `handlers.url_guard` does not exist).

- [ ] **Step 3: Implement** — create `handlers/url_guard.py`:

```python
"""SSRF-safe URL validation for user-supplied capture URLs.

Allows only public http(s) URLs. Blocks private / loopback / link-local /
reserved / multicast / unspecified IPs, including the cloud metadata address
169.254.169.254 — whether the URL uses a literal IP or a hostname that resolves
to one. Used before handing a user URL to the headless-browser capture.
"""
import ipaddress
import socket
from urllib.parse import urlparse


def _is_blocked_ip(ip_str: str) -> bool:
    """True if the address is anything but a normal public unicast address."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparseable -> treat as unsafe
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
        or ip.is_multicast or ip.is_unspecified
    )


def is_safe_public_url(url: str) -> bool:
    """True only for a public http(s) URL. Literal-IP hosts are checked directly;
    hostnames are DNS-resolved and rejected if ANY answer is a non-public IP.
    Any parse/resolution error -> unsafe (fail closed)."""
    try:
        p = urlparse((url or "").strip())
    except Exception:  # noqa: BLE001
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = p.hostname
    if not host:
        return False
    # Literal IP (v4 or v6, possibly bracketed) -> no DNS needed.
    try:
        ipaddress.ip_address(host)
        return not _is_blocked_ip(host)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:  # noqa: BLE001 - DNS failure -> unsafe
        return False
    if not infos:
        return False
    return all(not _is_blocked_ip(info[4][0]) for info in infos)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_url_guard.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/url_guard.py webhook-handler/tests/test_url_guard.py
git commit -m "feat(safety): SSRF-safe URL guard for capture URLs"
```

---

### Task 2: Apply the guard at the two capture entry points

**Files:**
- Modify: `webhook-handler/handlers/commands.py` (`run_video_capture`, ~2760)
- Modify: `webhook-handler/handlers/slack_interactions.py` (`_run_slack_video`, ~1227)
- Test: `webhook-handler/tests/test_url_guard.py` (add call-site tests)

- [ ] **Step 1: Write the failing tests** — append to `tests/test_url_guard.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from handlers import commands as cmd
from handlers.commands import CommandRouter, CommandContext


def _router():
    return CommandRouter(openwebui_client=MagicMock(), n8n_client=MagicMock(api_key=""),
                         discord_user_email_map={"1": "a@x.com"}, tasks_client=MagicMock())


def _ctx():
    return CommandContext(user_id="1", user_name="t", channel_id="c", raw_text="",
                          subcommand="video", arguments="", platform="discord",
                          respond=AsyncMock(), metadata={})


async def test_run_video_capture_blocks_unsafe_url(monkeypatch):
    r = _router()
    r._resolve_email_for_ctx = AsyncMock(return_value="a@x.com")
    r._tasks_client.get_current_video_draft = AsyncMock(return_value={"id": "d1"})
    r._tasks_client.capture_video_screenshots = AsyncMock()
    ctx = _ctx()
    await r.run_video_capture(ctx, "http://169.254.169.254/latest/meta-data")
    r._tasks_client.capture_video_screenshots.assert_not_awaited()
    ctx.respond.assert_awaited()  # a friendly refusal was sent
```

- [ ] **Step 2: Run test, verify it fails**

Run: `python -m pytest tests/test_url_guard.py::test_run_video_capture_blocks_unsafe_url -q`
Expected: FAIL (capture is still called on the metadata URL).

- [ ] **Step 3: Implement** — in `handlers/commands.py`, add the import near the top (with the other `from handlers import ...`):

```python
from handlers.url_guard import is_safe_public_url
```

In `run_video_capture`, immediately after the `if not draft:` guard block (before the `from urllib.parse import urlparse` line), insert:

```python
        if not is_safe_public_url(url):
            await ctx.respond(
                "I can only capture public web pages (http/https). That address "
                "looks internal or unreachable — try a public site URL.")
            return
```

In `handlers/slack_interactions.py`, in `_run_slack_video`, add the import at the top (with the other handler imports):

```python
from handlers.url_guard import is_safe_public_url
```

and right after `url = fields.get("url") or ""` / before the capture call (`host = urlsplit(url)...` / `capture_video_screenshots`), insert a guard:

```python
            if not is_safe_public_url(url):
                await self._post_video_error(
                    user_id, origin_channel,
                    "that URL isn't a public web page. Try a public https site.")
                return
```

(Verify exact surrounding lines when editing; the guard must sit before `capture_video_screenshots` is called.)

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_url_guard.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/commands.py webhook-handler/handlers/slack_interactions.py webhook-handler/tests/test_url_guard.py
git commit -m "feat(safety): block SSRF URLs at both video-capture entry points"
```

---

### Task 3: Bound gateway classification concurrency

**Files:**
- Modify: `webhook-handler/handlers/commands.py` (module-level semaphore + `handle_chat_message`)
- Test: `webhook-handler/tests/test_intent_gateway.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_intent_gateway.py`:

```python
import asyncio


async def test_handle_chat_message_bounded_concurrency(monkeypatch):
    monkeypatch.setattr(cmd.settings, "intent_router_enabled", True)
    monkeypatch.setattr(cmd, "_CHAT_SEMAPHORE", asyncio.Semaphore(1))
    state = {"cur": 0, "max": 0}

    async def slow_classify(text, ow, model):
        state["cur"] += 1
        state["max"] = max(state["max"], state["cur"])
        await asyncio.sleep(0.03)
        state["cur"] -= 1
        return ir.IntentResult("question", 0.9, "hi")

    monkeypatch.setattr(ir, "classify", slow_classify)
    r = _router()
    r._handle_ask = AsyncMock()
    await asyncio.gather(*(r.handle_chat_message(_ctx("hello there friend")) for _ in range(4)))
    assert state["max"] == 1  # the semaphore serialized them
```

- [ ] **Step 2: Run test, verify it fails**

Run: `python -m pytest tests/test_intent_gateway.py::test_handle_chat_message_bounded_concurrency -q`
Expected: FAIL (`cmd` has no `_CHAT_SEMAPHORE`, or max > 1).

- [ ] **Step 3: Implement** — in `handlers/commands.py`, add near the other module-level constants (after imports, before the dataclasses):

```python
# Caps concurrent gateway classifications so a chatty channel can't spawn
# unbounded simultaneous LLM calls (the intent router runs on every 3+ word
# message in a visible channel). Queued messages wait for a slot.
_CHAT_SEMAPHORE = asyncio.Semaphore(8)
```

Ensure `import asyncio` is present at the top of the file (it is, for background tasks; add it if missing).

Wrap the body of `handle_chat_message` so the classify+render runs under the semaphore:

```python
    async def handle_chat_message(self, ctx: CommandContext, *, threshold: float = 0.75) -> bool:
        """Gateway plain-text entry (Discord, any channel -- no slash). Flag-gated;
        the higher confidence bar (vs the 0.6 slash/Slack default) avoids misfiring
        in shared channels. Delegates the decision to plan_chat_step and renders it.
        Bounded by _CHAT_SEMAPHORE so a burst can't spawn unbounded LLM calls."""
        if not settings.intent_router_enabled:
            return False
        async with _CHAT_SEMAPHORE:
            step = await self.plan_chat_step(
                ctx.user_id or "", ctx.arguments or "", threshold=threshold)
            return await self._render_chat_step(ctx, step)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_intent_gateway.py -q`
Expected: PASS (all gateway tests, including the new one).

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/commands.py webhook-handler/tests/test_intent_gateway.py
git commit -m "feat(safety): bound gateway classification concurrency with a semaphore"
```

---

### Task 4: Memory limit on the webhook-handler container

**Files:**
- Modify: `docker-compose.unified.yml` (webhook-handler service)

- [ ] **Step 1: Inspect the current webhook-handler service block**

Run: `grep -n -A 30 "webhook-handler:" docker-compose.unified.yml | head -50`
Confirm whether a `deploy:`/`resources:` block already exists and match the indentation + style used by peer services (the audit noted peers use `deploy.resources.limits`).

- [ ] **Step 2: Add the limit** — in the `webhook-handler:` service, add (matching peer style; ~512M given it runs FastAPI + the gateway + the voice pipeline + watchers):

```yaml
    deploy:
      resources:
        limits:
          memory: 512M
        reservations:
          memory: 256M
```

If a `deploy:` block already exists, add only the `resources` subtree; do not duplicate keys.

- [ ] **Step 3: Validate the compose file locally**

Run: `docker compose -f docker-compose.unified.yml config >/dev/null && echo OK`
Expected: `OK` (no YAML/schema error). If Docker isn't available locally, instead verify indentation by eye against a peer service and rely on the server-side `config` check at deploy.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.unified.yml
git commit -m "feat(safety): cap webhook-handler container memory (512M) to protect the box"
```

---

### Task 5: Full suite + deploy (webhook-handler only) + verify

- [ ] **Step 1: Full local suite green**

Run: `cd "C:/Users/alama/Desktop/Lukas Work/IO/webhook-handler" && python -m pytest -q`
Expected: all pass (prior 1133 + the new url_guard/gateway tests). Fix any red before deploying.

- [ ] **Step 2: Push branch**

```bash
gh auth switch -u Jacintalama
git push fork feat/just-chat-intent-router
```

- [ ] **Step 3: Drift-check changed files server-vs-baseline (CRLF-normalized)**

For `handlers/commands.py`, `handlers/slack_interactions.py`, `docker-compose.unified.yml` compare the server copy to the previous fork tip; for the new `handlers/url_guard.py` confirm it is absent on the server. If any server file has drifted from baseline by unrelated code, STOP and merge instead of overwrite. (Compose especially may be ahead — treat it carefully; add only the resources subtree onto the server copy if it differs.)

- [ ] **Step 4: Deploy (per-file scp, never scp -r) + rebuild**

```bash
scp webhook-handler/handlers/url_guard.py        root@46.224.193.25:/root/proxy-server/webhook-handler/handlers/url_guard.py
scp webhook-handler/handlers/commands.py         root@46.224.193.25:/root/proxy-server/webhook-handler/handlers/commands.py
scp webhook-handler/handlers/slack_interactions.py root@46.224.193.25:/root/proxy-server/webhook-handler/handlers/slack_interactions.py
# compose: only if drift-check said the server block is safe to replace; otherwise edit the server copy in place to add the resources subtree
scp docker-compose.unified.yml                   root@46.224.193.25:/root/proxy-server/docker-compose.unified.yml
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml config >/dev/null && docker compose -f docker-compose.unified.yml up -d --build webhook-handler"
```

- [ ] **Step 5: Verify**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml ps webhook-handler && docker inspect --format '{{.HostConfig.Memory}}' webhook-handler"
```
Expected: `Up (healthy)`; the memory value is non-zero (~536870912 for 512M). Then an in-container check that the guard is live:
```bash
ssh root@46.224.193.25 "docker exec webhook-handler python -c \"from handlers.url_guard import is_safe_public_url as f; print(f('http://169.254.169.254/'), f('https://example.com'))\""
```
Expected: `False True` (or `False`/`True` depending on DNS; the metadata URL must be `False`).

- [ ] **Step 6: Update memory** — note Wave 1 shipped in `memory/project_intent_router.md` (or a new foundation memory), and that Waves 2 (identity) and 3 (persistence) are next.

---

## Self-review

**Spec coverage (Component 3 only — this is Wave 1):** SSRF guard → Tasks 1–2; concurrency guard → Task 3; container memory limit → Task 4. Identity (Component 1) and durable state (Component 2) are Waves 2 and 3, tracked in the spec. ✓

**Placeholder scan:** none — every step has real code/commands. The one "verify exact surrounding lines" note in Task 2 is a safety instruction for a live edit, not a missing code block (the guard snippet is given). ✓

**Type consistency:** `is_safe_public_url(url) -> bool` and `_is_blocked_ip(ip_str) -> bool` are defined in Task 1 and used identically in Task 2. `_CHAT_SEMAPHORE` defined and referenced by the same name in Task 3 (module-global so the monkeypatch in the test binds the same symbol the method reads). ✓

**Deviation from spec:** the guard allows both http and https (not https-only) — blocking SSRF by IP class regardless of scheme, without rejecting legitimate plain-http public sites. Noted intentionally.
