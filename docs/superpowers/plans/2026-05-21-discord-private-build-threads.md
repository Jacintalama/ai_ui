# Discord App Builder — Private Per-App Threads + Fresh Welcome (Feature A) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clicking a template in `#app-builder` opens a private thread for that user where their whole build/enhance/publish conversation happens; the channel stays a clean welcome page; plus a reset to wipe + fresh-welcome.

**Architecture:** Add two `DiscordClient` thread methods. In the build modal-submit handler, open a private thread, add the user, reply ephemerally with a pointer, and point that build's notifiers at the thread id (everything else — watcher, publish, enhance, unpublish — already posts to wherever its button was clicked, so no change). Add a `--reset` to the setup script and refresh the welcome copy. webhook-handler only.

**Tech Stack:** Python 3, httpx, pytest (`asyncio_mode = auto`), Discord HTTP API v10. Tests run locally in `webhook-handler/.venv`.

---

## File Structure
- **Modify** `webhook-handler/clients/discord.py` — `create_private_thread`, `add_thread_member`.
- **Modify** `webhook-handler/handlers/discord_commands.py` — extract `_handle_build_modal_submit`, make it thread-aware (ephemeral defer + bg thread creation + fallback).
- **Modify** `webhook-handler/handlers/app_builder_panel.py` — refresh `PANEL_CONTENT` welcome copy.
- **Modify** `webhook-handler/scripts/setup_app_builder_channel.py` — `_delete_channel` + `--reset`.
- Tests: `test_discord_client_threads.py` (new), `test_app_builder_interactions.py`, `test_app_builder_panel.py`, `test_setup_app_builder_script.py`.

**Test command (from `webhook-handler/`):**
`& "C:\Users\Acer Philippines\Desktop\Lukas Project\ai_ui\webhook-handler\.venv\Scripts\python.exe" -m pytest -q`

---

## Task 1: DiscordClient thread helpers

**Files:** Modify `webhook-handler/clients/discord.py`; Create `webhook-handler/tests/test_discord_client_threads.py`.

- [ ] **Step 1: Write failing tests** — create `webhook-handler/tests/test_discord_client_threads.py`:
```python
"""DiscordClient private-thread helpers."""
import httpx
import pytest
import respx

from clients.discord import DiscordClient, DISCORD_API_BASE


def _client():
    return DiscordClient(application_id="app-1", bot_token="bot-tok")


@pytest.mark.asyncio
async def test_create_private_thread_returns_id():
    c = _client()
    with respx.mock:
        route = respx.post(f"{DISCORD_API_BASE}/channels/chan-1/threads").mock(
            return_value=httpx.Response(201, json={"id": "thread-9"})
        )
        tid = await c.create_private_thread("chan-1", "portfolio-ralph")
    assert tid == "thread-9"
    req = route.calls.last.request
    assert req.headers["authorization"] == "Bot bot-tok"
    import json as _j
    body = _j.loads(req.content)
    assert body["type"] == 12          # PRIVATE_THREAD
    assert body["name"] == "portfolio-ralph"


@pytest.mark.asyncio
async def test_create_private_thread_none_on_error():
    c = _client()
    with respx.mock:
        respx.post(f"{DISCORD_API_BASE}/channels/chan-1/threads").mock(
            return_value=httpx.Response(403, json={"message": "Missing Permissions"})
        )
        tid = await c.create_private_thread("chan-1", "x")
    assert tid is None


@pytest.mark.asyncio
async def test_add_thread_member_true_on_204():
    c = _client()
    with respx.mock:
        route = respx.put(
            f"{DISCORD_API_BASE}/channels/thread-9/thread-members/user-7"
        ).mock(return_value=httpx.Response(204))
        ok = await c.add_thread_member("thread-9", "user-7")
    assert ok is True
    assert route.calls.last.request.headers["authorization"] == "Bot bot-tok"


@pytest.mark.asyncio
async def test_add_thread_member_false_on_error():
    c = _client()
    with respx.mock:
        respx.put(
            f"{DISCORD_API_BASE}/channels/thread-9/thread-members/user-7"
        ).mock(return_value=httpx.Response(403))
        ok = await c.add_thread_member("thread-9", "user-7")
    assert ok is False
```

- [ ] **Step 2: Run, confirm FAIL** — `pytest tests/test_discord_client_threads.py -q` → AttributeError (methods missing).

- [ ] **Step 3: Implement** — add these methods to `DiscordClient` in `webhook-handler/clients/discord.py` (after `post_channel_message`; `httpx`, `logger`, `DISCORD_API_BASE`, `self.bot_token`, `self.timeout` already exist):
```python
    async def create_private_thread(self, parent_channel_id: str, name: str) -> str | None:
        """Create a private thread (type 12) under a text channel using the bot
        token. Returns the new thread id, or None on failure (never raises) so
        callers can fall back to posting in the parent channel. Requires the bot
        to have Create Private Threads."""
        url = f"{DISCORD_API_BASE}/channels/{parent_channel_id}/threads"
        body = {
            "name": name[:100],
            "type": 12,                    # PRIVATE_THREAD
            "invitable": False,
            "auto_archive_duration": 1440,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bot {self.bot_token}"},
                    json=body,
                )
                if response.status_code in (200, 201):
                    return response.json().get("id")
                logger.error(
                    f"Discord create thread error: {response.status_code} {response.text}"
                )
                return None
        except Exception as e:
            logger.error(f"Error creating Discord private thread: {e}")
            return None

    async def add_thread_member(self, thread_id: str, user_id: str) -> bool:
        """Add a user to a thread (so they see the private thread). Bot token.
        Never raises."""
        url = f"{DISCORD_API_BASE}/channels/{thread_id}/thread-members/{user_id}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.put(
                    url, headers={"Authorization": f"Bot {self.bot_token}"},
                )
                if response.status_code in (200, 204):
                    return True
                logger.error(
                    f"Discord add thread member error: {response.status_code} {response.text}"
                )
                return False
        except Exception as e:
            logger.error(f"Error adding Discord thread member: {e}")
            return False
```

- [ ] **Step 4: Run, confirm PASS** — `pytest tests/test_discord_client_threads.py -q` → 4 pass. Then full suite `-q` → green (was 120).

- [ ] **Step 5: Commit**
```bash
git add webhook-handler/clients/discord.py webhook-handler/tests/test_discord_client_threads.py
git commit -m "feat(discord): DiscordClient.create_private_thread + add_thread_member

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Thread the build modal-submit flow

**Files:** Modify `webhook-handler/handlers/discord_commands.py`; Test `webhook-handler/tests/test_app_builder_interactions.py`.

- [ ] **Step 1: Append failing tests** to `webhook-handler/tests/test_app_builder_interactions.py` (reuses `_handler`, `asyncio`, `pytest`, `AsyncMock`, `MagicMock`; `BUILD_PREFIX`, `DESCRIPTION_INPUT_ID` already imported):
```python
import asyncio as _aio


def _modal_payload(custom_id, value="a portfolio"):
    return {"type": 5, "id": "i", "token": "tok",
            "data": {"custom_id": custom_id,
                     "components": [{"type": 1, "components": [
                         {"type": 4, "custom_id": DESCRIPTION_INPUT_ID, "value": value}]}]},
            "member": {"user": {"id": "100", "username": "ralph"}}, "channel_id": "main-chan"}


@pytest.mark.asyncio
async def test_build_modal_opens_private_thread_and_is_ephemeral():
    captured = {}
    async def fake_build(ctx, key, desc):
        captured["ctx"] = ctx
    router = MagicMock(); router.run_panel_build = fake_build
    discord = MagicMock()
    discord.create_private_thread = AsyncMock(return_value="thread-9")
    discord.add_thread_member = AsyncMock(return_value=True)
    discord.edit_original = AsyncMock(return_value=True)
    discord.post_channel_message = AsyncMock(return_value=True)
    from handlers.discord_commands import DiscordCommandHandler
    handler = DiscordCommandHandler(discord_client=discord, command_router=router)

    resp = await handler.handle_interaction(_modal_payload(f"{BUILD_PREFIX}portfolio"))
    assert resp["type"] == 5
    assert resp["data"]["flags"] == 64           # ephemeral
    await _aio.sleep(0.05)                        # drain the bg task

    discord.create_private_thread.assert_awaited_once()
    args = discord.create_private_thread.await_args.args
    assert args[0] == "main-chan"                 # parent channel
    assert "ralph" in args[1]                     # thread name has the user
    discord.add_thread_member.assert_awaited_once_with("thread-9", "100")
    # the build ctx posts into the THREAD
    ctx = captured["ctx"]
    await ctx.notify_channel("hi")
    discord.post_channel_message.assert_awaited_with("thread-9", "hi")


@pytest.mark.asyncio
async def test_build_modal_falls_back_to_channel_when_thread_fails():
    captured = {}
    async def fake_build(ctx, key, desc):
        captured["ctx"] = ctx
    router = MagicMock(); router.run_panel_build = fake_build
    discord = MagicMock()
    discord.create_private_thread = AsyncMock(return_value=None)   # failure
    discord.add_thread_member = AsyncMock(return_value=True)
    discord.edit_original = AsyncMock(return_value=True)
    discord.post_channel_message = AsyncMock(return_value=True)
    from handlers.discord_commands import DiscordCommandHandler
    handler = DiscordCommandHandler(discord_client=discord, command_router=router)

    resp = await handler.handle_interaction(_modal_payload(f"{BUILD_PREFIX}"))
    assert resp["type"] == 5
    await _aio.sleep(0.05)

    discord.add_thread_member.assert_not_awaited()
    ctx = captured["ctx"]
    await ctx.notify_channel("hi")
    discord.post_channel_message.assert_awaited_with("main-chan", "hi")  # main channel
```

- [ ] **Step 2: Run, confirm FAIL** — `pytest tests/test_app_builder_interactions.py -q` → the new tests fail (no thread creation; response has no `flags`).

- [ ] **Step 3: Refactor `_handle_modal_submit` to dispatch the build branch.**
In `webhook-handler/handlers/discord_commands.py`, the build branch is currently the inline tail of `_handle_modal_submit` (after the `is_panel_modal` guard, the block that reads `interaction_token`/`member`/... builds the ctx and calls `run_panel_build`). REPLACE that entire inline tail — from the `if not is_panel_modal(custom_id):` guard through the final `return {"type": DEFERRED_CHANNEL_MESSAGE}` of that method — with:
```python
        if not is_panel_modal(custom_id):
            logger.info(f"Ignoring unknown modal custom_id: {custom_id}")
            return {"type": DEFERRED_UPDATE_MESSAGE}
        return await self._handle_build_modal_submit(payload, custom_id)
```
(The enhance-modal branch above it stays unchanged.)

- [ ] **Step 4: Add `_handle_build_modal_submit`.** Insert this method immediately after `_handle_modal_submit` (before `_extract_modal_value`):
```python
    async def _handle_build_modal_submit(self, payload: dict[str, Any], custom_id: str) -> dict[str, Any]:
        """Build-template modal submit. Open a PRIVATE THREAD for the user, post
        the build there, and ACK ephemerally with a pointer. Falls back to the
        main channel if thread creation fails. Returns an ephemeral deferred
        response within Discord's 3s window; the thread work runs in the
        background (mirrors the fire-and-forget build pattern)."""
        data = payload.get("data", {})
        template_key = template_key_from_modal(custom_id)
        description = self._extract_modal_value(data, DESCRIPTION_INPUT_ID)
        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        user_id = user.get("id", "")
        user_name = user.get("username", "unknown")
        channel_id = payload.get("channel_id", "")

        async def _open_and_build() -> None:
            target = channel_id
            in_thread = False
            thread_id = await self.discord.create_private_thread(
                channel_id, f"{template_key or 'app'}-{user_name}"[:90]
            )
            if thread_id:
                await self.discord.add_thread_member(thread_id, user_id)
                await self.discord.edit_original(
                    interaction_token=interaction_token,
                    content=f"✅ Opening your private build space → <#{thread_id}>",
                )
                target = thread_id
                in_thread = True

            if in_thread:
                async def respond(msg: str) -> None:
                    await self.discord.post_channel_message(target, msg)
            else:
                async def respond(msg: str) -> None:
                    await self.discord.edit_original(
                        interaction_token=interaction_token, content=msg,
                    )

            notify_channel, notify_channel_rich = self._channel_notifiers(target)
            ctx = CommandContext(
                user_id=user_id,
                user_name=user_name,
                channel_id=target,
                raw_text=f"aiuibuilder build {template_key or ''} {description}".strip(),
                subcommand="aiuibuilder",
                arguments="",
                platform="discord",
                respond=respond,
                metadata={
                    "interaction_id": payload.get("id", ""),
                    "interaction_token": interaction_token,
                    "guild_id": payload.get("guild_id", ""),
                },
                notify_channel=notify_channel,
                notify_channel_rich=notify_channel_rich,
            )
            await self.router.run_panel_build(ctx, template_key, description)

        asyncio.create_task(_open_and_build())
        # Ephemeral deferred ACK (flags=64) — only the clicking user sees it.
        return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}
```

- [ ] **Step 5: Run, confirm PASS** — `pytest tests/test_app_builder_interactions.py tests/test_discord_notify_wiring.py -q` → pass. Then full suite `-q` → green.

- [ ] **Step 6: Commit**
```bash
git add webhook-handler/handlers/discord_commands.py webhook-handler/tests/test_app_builder_interactions.py
git commit -m "feat(discord): build modal opens a private per-user thread (ephemeral, fallback)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Welcome copy + setup-script reset

**Files:** Modify `webhook-handler/handlers/app_builder_panel.py`, `webhook-handler/scripts/setup_app_builder_channel.py`; Test `webhook-handler/tests/test_app_builder_panel.py`, `webhook-handler/tests/test_setup_app_builder_script.py`.

- [ ] **Step 1: Append failing tests.**
To `webhook-handler/tests/test_app_builder_panel.py`:
```python
def test_panel_content_mentions_private_space():
    from handlers.app_builder_panel import PANEL_CONTENT
    assert "private" in PANEL_CONTENT.lower()
```
To `webhook-handler/tests/test_setup_app_builder_script.py`:
```python
def test_reset_deletes_existing_channel_then_recreates(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("DISCORD_GUILD_ID", "guild")
    monkeypatch.setenv("APP_BUILDER_SETUP_EMAIL", "admin@x.com")
    monkeypatch.setenv("APP_BUILDER_RESET", "1")

    calls = {}
    monkeypatch.setattr(setup, "_fetch_templates",
                        lambda url, email: [{"key": "portfolio", "label": "Portfolio", "emoji": "x"}])
    monkeypatch.setattr(setup, "_find_channel", lambda g, n, h: "old-chan")
    monkeypatch.setattr(setup, "_delete_channel",
                        lambda c, h: calls.update({"deleted": c}))
    monkeypatch.setattr(setup, "_create_channel",
                        lambda g, n, h: calls.update({"created": "new-chan"}) or "new-chan")
    monkeypatch.setattr(setup, "_post_panel", lambda c, p, h: "msg-1")
    monkeypatch.setattr(setup, "_pin", lambda c, m, h: None)

    assert setup.main() == 0
    assert calls["deleted"] == "old-chan"      # old channel deleted
    assert calls["created"] == "new-chan"      # fresh channel created


def test_no_reset_keeps_existing_channel(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("DISCORD_GUILD_ID", "guild")
    monkeypatch.setenv("APP_BUILDER_SETUP_EMAIL", "admin@x.com")
    # no APP_BUILDER_RESET

    deleted = {"n": 0}
    monkeypatch.setattr(setup, "_fetch_templates",
                        lambda url, email: [{"key": "portfolio", "label": "Portfolio", "emoji": "x"}])
    monkeypatch.setattr(setup, "_find_channel", lambda g, n, h: "old-chan")
    monkeypatch.setattr(setup, "_delete_channel",
                        lambda c, h: deleted.__setitem__("n", deleted["n"] + 1))
    monkeypatch.setattr(setup, "_create_channel", lambda g, n, h: "x")
    monkeypatch.setattr(setup, "_post_panel", lambda c, p, h: "msg-1")
    monkeypatch.setattr(setup, "_pin", lambda c, m, h: None)

    assert setup.main() == 0
    assert deleted["n"] == 0                    # never deleted without reset
```

- [ ] **Step 2: Run, confirm FAIL** — panel test fails (no "private" in copy); setup tests fail (`_delete_channel` missing / reset not honored).

- [ ] **Step 3a: Update welcome copy** — in `webhook-handler/handlers/app_builder_panel.py`, replace `PANEL_CONTENT` with:
```python
PANEL_CONTENT = (
    "\U0001f680 **AIUI App Builder**\n"
    "Pick a template and I'll open a **private space** just for you to build, "
    "preview, and publish your app — only you and the bot see it. Or hit "
    "**Blank** to start from scratch."
)
```

- [ ] **Step 3b: Add reset to the setup script** — in `webhook-handler/scripts/setup_app_builder_channel.py`:
Add a delete helper near `_create_channel`:
```python
def _delete_channel(channel_id: str, headers: dict) -> None:
    url = f"{DISCORD_API}/channels/{channel_id}"
    with httpx.Client(timeout=30.0) as client:
        r = client.delete(url, headers=headers)
    if r.status_code not in (200, 204):
        print(f"WARN: delete channel returned {r.status_code} {r.text}", file=sys.stderr)
```
In `main()`, read the reset flag after the other env reads:
```python
    reset = os.environ.get("APP_BUILDER_RESET", "").strip() == "1" or "--reset" in sys.argv
```
Then, in the create-or-reuse block, change the reuse branch so reset forces a fresh channel. Replace:
```python
        channel_id = _find_channel(guild_id, channel_name, headers)
        if channel_id:
            print(f"Reusing existing channel #{channel_name} ({channel_id})")
        else:
            channel_id = _create_channel(guild_id, channel_name, headers)
            print(f"Created channel #{channel_name} ({channel_id})")
```
with:
```python
        channel_id = _find_channel(guild_id, channel_name, headers)
        if channel_id and reset:
            print(f"Reset: deleting existing channel #{channel_name} ({channel_id})")
            _delete_channel(channel_id, headers)
            channel_id = None
        if channel_id:
            print(f"Reusing existing channel #{channel_name} ({channel_id})")
        else:
            channel_id = _create_channel(guild_id, channel_name, headers)
            print(f"Created channel #{channel_name} ({channel_id})")
```
Also update the module docstring usage block to mention `APP_BUILDER_RESET=1` (wipes + fresh welcome). (Cosmetic; keep it short.)

- [ ] **Step 4: Run, confirm PASS** — `pytest tests/test_app_builder_panel.py tests/test_setup_app_builder_script.py -q` → pass. Then full suite `-q` → green.

- [ ] **Step 5: Commit**
```bash
git add webhook-handler/handlers/app_builder_panel.py webhook-handler/scripts/setup_app_builder_channel.py webhook-handler/tests/test_app_builder_panel.py webhook-handler/tests/test_setup_app_builder_script.py
git commit -m "feat(discord): welcome copy mentions private space; setup --reset wipes channel

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Full verification
- [ ] **Step 1:** From `webhook-handler/`: `& "<venv python>" -m pytest -q` → all green, no regressions.
- [ ] **Step 2:** Fix any reds with systematic-debugging; don't weaken tests.
- [ ] **Step 3:** Final commit if Step 2 changed anything.

---

## Deployment (webhook-handler only)
1. `scp` each changed file (one per file, never `scp -r`): `webhook-handler/clients/discord.py`, `webhook-handler/handlers/discord_commands.py`, `webhook-handler/handlers/app_builder_panel.py`, `webhook-handler/scripts/setup_app_builder_channel.py`.
2. `docker compose -f docker-compose.unified.yml up -d --build webhook-handler`; verify bot `Up (healthy)` + clean startup.
3. **Grant the bot** *Create Private Threads* + *Send Messages in Threads* in the `aiui-teams` role (one-time toggle; like Manage Channels earlier).
4. **Reset the channel** (wipe + fresh welcome):
   `docker compose -f docker-compose.unified.yml exec -e DISCORD_GUILD_ID=1475498065518661794 -e APP_BUILDER_RESET=1 -e APP_BUILDER_SETUP_EMAIL=admin@example.com webhook-handler python /app/scripts/setup_app_builder_channel.py`
5. **Live verify:** click a template → a private thread opens with the build → preview + Publish/Enhance buttons appear in the thread → Publish works in the thread.

---

## Self-Review Notes
- **Spec coverage:** thread helpers (Task 1); thread the build modal submit + ephemeral + fallback (Task 2); welcome copy (Task 3); reset (Task 3); verify (Task 4); deploy + perms + reset run (Deployment). Enhance/Publish/Unpublish unchanged (post to wherever clicked = thread) — no task needed, by design. Slash command unchanged — by design. ✔
- **Type/name consistency:** `create_private_thread(parent, name)->str|None`, `add_thread_member(thread, user)->bool`, `_handle_build_modal_submit(payload, custom_id)`, `_channel_notifiers`, `PANEL_CONTENT`, `_delete_channel`, `APP_BUILDER_RESET` — consistent across tasks. ✔
- **No placeholders:** complete code/commands in every step. ✔
