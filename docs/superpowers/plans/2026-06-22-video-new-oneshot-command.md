# `/video new` one-shot create-with-screenshots — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/video new` slash command that creates a video draft from a description + attached screenshots in one shot, opening the user's private thread with the style/voice + Generate controls; keep the New-video button as a guided alternative.

**Architecture:** Extract the New-video modal's studio-opening logic into a shared `DiscordCommandHandler._open_video_studio(...)` (with an optional `screenshot_urls`); the modal submit and the new `/video new` branch both call it. A pure `_parse_video_new` helper turns the command payload into (title, prompt, urls). Register the `new` subcommand and lead the panel copy with it.

**Tech Stack:** Python 3.13, discord interactions over HTTP, pytest + pytest-asyncio. Work in worktree `C:/Users/alama/Desktop/Lukas Work/IO-integrate` on branch `fix/video-thread-image-intake`. Run tests from `webhook-handler/`.

---

## File Structure

- **Modify** `scripts/register_discord_commands.py` — add the `new` subcommand to `build_video_command_payload`.
- **Modify** `webhook-handler/tests/test_register_video_command.py` — assert the `new` subcommand shape.
- **Modify** `webhook-handler/handlers/discord_commands.py` — extract `_open_video_studio`; make `_handle_video_new_modal` a thin caller; add `_parse_video_new` + the `/video new` branch in `_handle_video_command`.
- **Create** `webhook-handler/tests/test_video_new.py` — tests for `_open_video_studio` + `_parse_video_new`.
- **Modify** `webhook-handler/handlers/video_panel.py` — embed copy.
- **Modify** `webhook-handler/tests/test_video_panel.py` — assert `/video new` in the embed.

---

## Task 1: Register the `new` subcommand

**Files:**
- Modify: `scripts/register_discord_commands.py` (`build_video_command_payload`, ~line 78-91)
- Test: `webhook-handler/tests/test_register_video_command.py`

- [ ] **Step 1: Write the failing test**

Append to `webhook-handler/tests/test_register_video_command.py`:

```python
def test_video_command_has_new_with_description_title_and_attachments():
    p = reg.build_video_command_payload()
    new = next(o for o in p["options"] if o["name"] == "new")
    by_name = {o["name"]: o for o in new["options"]}
    assert by_name["description"]["type"] == reg.STRING and by_name["description"]["required"] is True
    assert by_name["title"]["type"] == reg.STRING and by_name["title"]["required"] is False
    atts = [o for o in new["options"] if o["type"] == reg.ATTACHMENT]
    assert len(atts) == 12 and all(o["required"] is False for o in atts)
    # Discord rule: no required option after an optional one
    seen_optional = False
    for o in new["options"]:
        if not o["required"]:
            seen_optional = True
        else:
            assert not seen_optional, f"required '{o['name']}' after optional"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd webhook-handler && python -m pytest tests/test_register_video_command.py::test_video_command_has_new_with_description_title_and_attachments -q`
Expected: FAIL — `StopIteration` (no `new` subcommand yet).

- [ ] **Step 3: Add the `new` subcommand**

In `scripts/register_discord_commands.py`, replace the whole `build_video_command_payload` function with:

```python
def build_video_command_payload() -> dict:
    """A top-level /video command: `new` (one-shot create: describe + attach
    screenshots), `add` (up to 12 screenshot attachments), and `list`.
    Subcommands mirror the /aiui structure (type SUB_COMMAND)."""
    shot_opts = [(f"shot{i}", f"Screenshot {i}", False, ATTACHMENT) for i in range(1, 13)]
    new_opts = [
        ("description", "What the narrated walkthrough should say", True),
        ("title", "Title (optional)", False),
    ] + shot_opts
    return {
        "name": "video",
        "description": "Generate narrated videos from screenshots",
        "options": [
            {"name": "new", "description": "Create a video: describe it + attach screenshots",
             "type": SUB_COMMAND, "options": [_build_option(o) for o in new_opts]},
            {"name": "add", "description": "Add screenshots to your current video",
             "type": SUB_COMMAND, "options": [_build_option(o) for o in shot_opts]},
            {"name": "list", "description": "List your videos",
             "type": SUB_COMMAND, "options": []},
        ],
    }
```

- [ ] **Step 4: Run the register tests to verify pass**

Run: `cd webhook-handler && python -m pytest tests/test_register_video_command.py -q`
Expected: PASS (3 tests — the 2 existing + the new one).

- [ ] **Step 5: Commit**

```bash
git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" add scripts/register_discord_commands.py webhook-handler/tests/test_register_video_command.py
git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" commit -m "feat(video): register /video new subcommand (description + title + 12 shots)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Extract `_open_video_studio` (shared by modal + /video new)

**Files:**
- Modify: `webhook-handler/handlers/discord_commands.py` (`_handle_video_new_modal`, ~line 907-983)
- Test: `webhook-handler/tests/test_video_new.py` (create)

- [ ] **Step 1: Write the failing test**

Create `webhook-handler/tests/test_video_new.py`:

```python
"""Tests for the shared video-studio opener and the /video new payload parser."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from handlers.discord_commands import DiscordCommandHandler


def _handler(email="u@x.com"):
    h = DiscordCommandHandler.__new__(DiscordCommandHandler)
    tc = MagicMock()
    tc.create_video_draft = AsyncMock(return_value={"id": "job1"})
    tc.add_video_screenshots_urls = AsyncMock(return_value={"count": 2})
    tc.get_video_voices = AsyncMock(return_value={"voices": []})
    tc.fetch_bytes = AsyncMock(return_value=b"x")
    router = MagicMock()
    router._tasks_client = tc
    router._resolve_email = AsyncMock(return_value=email)
    h.router = router
    discord = MagicMock()
    discord.edit_original = AsyncMock()
    discord.post_channel_file = AsyncMock()
    discord.post_channel_message = AsyncMock()
    h.discord = discord
    h._get_or_make_thread = AsyncMock(return_value="thread1")
    return h, router, discord


@pytest.mark.asyncio
async def test_open_video_studio_with_screenshots_creates_draft_and_adds_urls():
    h, router, discord = _handler()
    await h._open_video_studio(
        interaction_token="t", user_id="100", user_name="alice", channel_id="c",
        title="My Demo", prompt="walk the dashboard",
        screenshot_urls=["http://cdn/1.png", "http://cdn/2.png"])
    router._tasks_client.create_video_draft.assert_awaited_once_with(
        "u@x.com", "My Demo", "walk the dashboard", "clean_product_demo", "amy")
    router._tasks_client.add_video_screenshots_urls.assert_awaited_once_with(
        "u@x.com", "job1", ["http://cdn/1.png", "http://cdn/2.png"])
    discord.post_channel_message.assert_awaited_once()
    content = discord.post_channel_message.await_args.args[1]
    assert "added 2 screenshot" in content.lower()


@pytest.mark.asyncio
async def test_open_video_studio_without_screenshots_skips_add():
    h, router, discord = _handler()
    await h._open_video_studio(
        interaction_token="t", user_id="100", user_name="alice", channel_id="c",
        title="My Demo", prompt="desc", screenshot_urls=None)
    router._tasks_client.add_video_screenshots_urls.assert_not_called()
    content = discord.post_channel_message.await_args.args[1]
    assert "drop your screenshots here" in content.lower()


@pytest.mark.asyncio
async def test_open_video_studio_not_linked_posts_card_no_draft():
    h, router, discord = _handler(email=None)
    await h._open_video_studio(
        interaction_token="t", user_id="100", user_name="alice", channel_id="c",
        title="t", prompt="d", screenshot_urls=["http://cdn/1.png"])
    router._tasks_client.create_video_draft.assert_not_called()
    discord.edit_original.assert_awaited()  # the not-linked card
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd webhook-handler && python -m pytest tests/test_video_new.py -q`
Expected: FAIL — `AttributeError: ... has no attribute '_open_video_studio'`.

- [ ] **Step 3: Add `_open_video_studio` and slim `_handle_video_new_modal`**

In `webhook-handler/handlers/discord_commands.py`, replace the entire `_handle_video_new_modal` method (the whole `async def _handle_video_new_modal(...)` through its `return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}`) with these TWO methods:

```python
    async def _open_video_studio(self, *, interaction_token: str, user_id: str,
                                 user_name: str, channel_id: str, title: str,
                                 prompt: str, screenshot_urls: "list[str] | None" = None) -> None:
        """Create a video draft, open the user's private video thread, point the
        ephemeral ACK at it, post the voice-sample MP3s + studio controls, and —
        when screenshot_urls is given (/video new) — push those screenshots onto
        the new draft. Shared by the 'New video' modal submit and `/video new`."""
        try:
            email = await self.router._resolve_email(user_id)
            if email is None:
                await self.discord.edit_original(
                    interaction_token=interaction_token,
                    content=onboarding.not_linked_text_discord(),
                    components=onboarding.link_button_row(),
                )
                return
            draft = await self.router._tasks_client.create_video_draft(
                email, title, prompt, "clean_product_demo", "amy")
            job_id = draft["id"]
            thread_id = await self._get_or_make_thread(
                user_id, channel_id, user_name, kind="video")
            target = thread_id or channel_id
            if thread_id:
                await self.discord.edit_original(
                    interaction_token=interaction_token,
                    content=f"Your video studio is ready → <#{thread_id}>",
                )
            else:
                await self.discord.edit_original(
                    interaction_token=interaction_token,
                    content="Your video studio is ready below.",
                )
            # Push any screenshots attached up-front (/video new). Best-effort: a
            # failure must not block the studio — the user can still drop images
            # in the thread or use /video add.
            added = 0
            if screenshot_urls:
                try:
                    res = await self.router._tasks_client.add_video_screenshots_urls(
                        email, job_id, screenshot_urls)
                    added = res.get("count", 0)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("video new: screenshot add failed user=%s: %s", user_id, exc)
            voices = (await self.router._tasks_client.get_video_voices()).get("voices", [])
            # Best-effort: post the voice preview clips so the user can listen
            # before picking. A failure here must never block the studio.
            try:
                files: "list[tuple[str, bytes, str]]" = []
                for v in voices[:6]:
                    sample_url = v.get("sample_url")
                    vid_id = v.get("id") or "voice"
                    if not sample_url:
                        continue
                    blob = await self.router._tasks_client.fetch_bytes(sample_url)
                    files.append((f"{vid_id}.mp3", blob, "audio/mpeg"))
                if files:
                    await self.discord.post_channel_file(
                        target, files[:10],
                        content="Voice previews — listen, then pick a voice below:")
            except Exception as exc:  # noqa: BLE001
                logger.warning("video voice-sample post failed user=%s: %s", user_id, exc)
            if added:
                studio_msg = (
                    f"Created **{title}** — added {added} screenshot"
                    f"{'s' if added != 1 else ''}. Pick a style + voice, drop more "
                    "here (or `/video add`), then hit **Generate video**."
                )
            else:
                studio_msg = (
                    "Pick a style + voice, then **drop your screenshots here** "
                    "(or use `/video add`), then hit **Generate video**."
                )
            await self.discord.post_channel_message(
                target, studio_msg,
                components=vid.build_studio_components(job_id, voices),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("_open_video_studio failed user=%s: %s", user_id, exc)
            try:
                await self.discord.edit_original(
                    interaction_token=interaction_token,
                    content="Couldn't open the video studio — please try again.",
                )
            except Exception:  # noqa: BLE001
                pass

    async def _handle_video_new_modal(self, payload: dict[str, Any]) -> dict[str, Any]:
        """'New video' modal submit → open the video studio (no up-front
        screenshots). ACK is ephemeral-deferred within 3s."""
        data = payload.get("data", {})
        title = self._extract_modal_value(data, vid.TITLE_INPUT)
        prompt = self._extract_modal_value(data, vid.PROMPT_INPUT)
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        self._spawn(self._open_video_studio(
            interaction_token=payload.get("token", ""),
            user_id=user.get("id", ""),
            user_name=user.get("username", "unknown"),
            channel_id=payload.get("channel_id", ""),
            title=title, prompt=prompt, screenshot_urls=None))
        return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}
```

- [ ] **Step 4: Run the new tests to verify pass**

Run: `cd webhook-handler && python -m pytest tests/test_video_new.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full suite (modal path unchanged)**

Run: `cd webhook-handler && python -m pytest -q`
Expected: all pass (confirms the `_handle_video_new_modal` refactor didn't break existing tests).

- [ ] **Step 6: Commit**

```bash
git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" add webhook-handler/handlers/discord_commands.py webhook-handler/tests/test_video_new.py
git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" commit -m "refactor(video): extract _open_video_studio shared by modal and /video new

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `_parse_video_new` + the `/video new` branch

**Files:**
- Modify: `webhook-handler/handlers/discord_commands.py` (`_handle_video_command` ~line 872-905; add `_parse_video_new` near `_all_attachments`)
- Test: `webhook-handler/tests/test_video_new.py`

- [ ] **Step 1: Write the failing tests**

Append to `webhook-handler/tests/test_video_new.py`:

```python
def test_parse_video_new_extracts_fields_and_urls():
    data = {
        "options": [{"name": "new", "type": 1, "options": [
            {"name": "description", "type": 3, "value": "walk the dashboard"},
            {"name": "title", "type": 3, "value": "My Demo"},
            {"name": "shot1", "type": 11, "value": "att1"},
        ]}],
        "resolved": {"attachments": {
            "att1": {"url": "http://cdn/1.png", "filename": "1.png",
                     "content_type": "image/png", "size": 10},
        }},
    }
    title, prompt, urls = DiscordCommandHandler._parse_video_new(data)
    assert title == "My Demo"
    assert prompt == "walk the dashboard"
    assert urls == ["http://cdn/1.png"]


def test_parse_video_new_defaults_title_from_description():
    data = {"options": [{"name": "new", "type": 1, "options": [
        {"name": "description", "type": 3, "value": "x" * 80},
    ]}], "resolved": {}}
    title, prompt, urls = DiscordCommandHandler._parse_video_new(data)
    assert title == "x" * 60
    assert prompt == "x" * 80
    assert urls == []


def test_parse_video_new_untitled_when_blank():
    data = {"options": [{"name": "new", "type": 1, "options": [
        {"name": "description", "type": 3, "value": "   "},
    ]}], "resolved": {}}
    title, prompt, urls = DiscordCommandHandler._parse_video_new(data)
    assert title == "Untitled video"
    assert prompt == ""
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd webhook-handler && python -m pytest tests/test_video_new.py -k parse_video_new -q`
Expected: FAIL — `AttributeError: ... has no attribute '_parse_video_new'`.

- [ ] **Step 3: Add `_parse_video_new`**

In `webhook-handler/handlers/discord_commands.py`, immediately AFTER the `_all_attachments` staticmethod (it ends with the list comprehension `return [...]`), add:

```python
    @staticmethod
    def _parse_video_new(data: dict) -> "tuple[str, str, list[str]]":
        """Parse the `/video new` payload → (title, prompt, screenshot_urls).
        Title falls back to the first 60 chars of the description, then to
        'Untitled video' when the description is blank too."""
        sub_opts = ((data.get("options") or [{}])[0].get("options")) or []

        def _opt(name: str) -> str:
            return next((o.get("value", "") for o in sub_opts if o.get("name") == name), "")

        prompt = (_opt("description") or "").strip()
        title = (_opt("title") or "").strip() or prompt[:60].strip() or "Untitled video"
        urls = [a["url"] for a in DiscordCommandHandler._all_attachments(data) if a.get("url")]
        return title, prompt, urls
```

- [ ] **Step 4: Add the `/video new` branch in `_handle_video_command`**

In `_handle_video_command`, find this prefix (the method start through the `channel_id =` line):

```python
        data = payload.get("data", {})
        options = data.get("options", [])
        sub = options[0].get("name") if options else "list"
        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        channel_id = payload.get("channel_id", "")
        notify_channel, notify_channel_rich = self._channel_notifiers(channel_id)
```

Replace it with (insert the `new` branch before `notify_channel = …`):

```python
        data = payload.get("data", {})
        options = data.get("options", [])
        sub = options[0].get("name") if options else "list"
        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        channel_id = payload.get("channel_id", "")

        if sub == "new":
            title, prompt, urls = self._parse_video_new(data)
            self._spawn(self._open_video_studio(
                interaction_token=interaction_token,
                user_id=user.get("id", ""),
                user_name=user.get("username", "unknown"),
                channel_id=channel_id, title=title, prompt=prompt,
                screenshot_urls=urls))
            return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}

        notify_channel, notify_channel_rich = self._channel_notifiers(channel_id)
```

Also update the method's docstring line `"""\`/video add\` (push the attached screenshots onto the current draft) and` to read:

```python
        """`/video new` (one-shot: describe + attach screenshots), `/video add`
        (push the attached screenshots onto the current draft) and `/video list`.
        ACK ephemeral-deferred."""
```

- [ ] **Step 5: Run parser tests + full suite**

Run: `cd webhook-handler && python -m pytest tests/test_video_new.py -q && python -m pytest -q`
Expected: both PASS.

- [ ] **Step 6: Commit**

```bash
git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" add webhook-handler/handlers/discord_commands.py webhook-handler/tests/test_video_new.py
git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" commit -m "feat(video): /video new branch + _parse_video_new payload parser

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Panel copy leads with /video new

**Files:**
- Modify: `webhook-handler/handlers/video_panel.py` (`build_video_embed`, ~line 47-56)
- Test: `webhook-handler/tests/test_video_panel.py`

- [ ] **Step 1: Write the failing test**

Append to `webhook-handler/tests/test_video_panel.py`:

```python
def test_video_embed_mentions_video_new_command():
    embed = build_video_embed()
    assert "/video new" in embed["description"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd webhook-handler && python -m pytest tests/test_video_panel.py::test_video_embed_mentions_video_new_command -q`
Expected: FAIL (current copy has no "/video new").

- [ ] **Step 3: Update the embed copy**

In `webhook-handler/handlers/video_panel.py`, in `build_video_embed`, find:

```python
            "```\n"
            "> turn screenshots into a narrated walkthrough\n"
            "> New video -> name it, pick style + voice\n"
            "> drop your screenshots in the thread (or /video add)\n"
            "> Generate -> we render it in your private thread\n"
            "```"
```

Replace with:

```python
            "```\n"
            "> turn screenshots into a narrated walkthrough\n"
            "> fastest: /video new  - attach screenshots + describe it\n"
            "> or New video -> drop screenshots in your thread\n"
            "> Generate -> we render it in your private thread\n"
            "```"
```

- [ ] **Step 4: Run the panel tests to verify pass**

Run: `cd webhook-handler && python -m pytest tests/test_video_panel.py -q`
Expected: PASS (both the new test and the existing `test_video_embed_mentions_dropping_screenshots` — the copy still contains "drop").

- [ ] **Step 5: Commit**

```bash
git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" add webhook-handler/handlers/video_panel.py webhook-handler/tests/test_video_panel.py
git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" commit -m "feat(video): panel leads with /video new one-shot command

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire webhook-handler suite**

Run: `cd webhook-handler && python -m pytest -q`
Expected: all pass. Do not deploy on red.

- [ ] **Step 2: Review the branch diff**

Run: `git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" status --short && git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" log --oneline integrate/video-recruiting..HEAD`
Expected: clean tree; the `/video new` commits plus the earlier drop-to-add commits listed.

---

## Task 6: Deploy to production (GATED — confirm with the user first)

**Do not run until the user confirms.** Production push. webhook-handler isn't covered by the orchestrator; deploy per-file (never `scp -r`).

- [ ] **Step 1: Confirm SSH + check for server drift before overwriting**

```bash
ssh -o ConnectTimeout=15 root@46.224.193.25 "echo ok"
```
The server currently runs the drop-to-add deploy. Before overwriting, CRLF-normalized hash-compare the server's current `discord_commands.py` and `video_panel.py` against the git blob that was deployed earlier today (find it with `git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" log --oneline` — the last "drop screenshots" commit), e.g. `git show <sha>:webhook-handler/handlers/discord_commands.py | tr -d '\r' | md5sum` vs `ssh root@46.224.193.25 "tr -d '\r' < /root/proxy-server/webhook-handler/handlers/discord_commands.py | md5sum"`. They should match. If they differ, the server has out-of-band drift — STOP and investigate before overwriting. After scp (Step 2), re-hash server vs local HEAD to confirm the upload landed.

- [ ] **Step 2: Copy the 2 changed bot files individually**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO-integrate/webhook-handler"
scp handlers/discord_commands.py root@46.224.193.25:/root/proxy-server/webhook-handler/handlers/discord_commands.py
scp handlers/video_panel.py      root@46.224.193.25:/root/proxy-server/webhook-handler/handlers/video_panel.py
```

- [ ] **Step 3: Rebuild webhook-handler + verify healthy**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build webhook-handler"
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml ps webhook-handler && docker compose -f docker-compose.unified.yml logs --tail 40 webhook-handler"
```
Expected: `Up (healthy)`; `Conversational voice bot ready`; no traceback.

- [ ] **Step 4: Register the new command (PUT replaces all; re-registers /aiui + /video)**

The register script isn't baked into the container; copy it in and run it with the guild id for instant registration (the container already has DISCORD_APPLICATION_ID + DISCORD_BOT_TOKEN in its env):

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO-integrate"
scp scripts/register_discord_commands.py root@46.224.193.25:/root/proxy-server/scripts/register_discord_commands.py
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml cp scripts/register_discord_commands.py webhook-handler:/tmp/reg.py && docker compose -f docker-compose.unified.yml exec -T -e DISCORD_GUILD_ID=1475498065518661794 webhook-handler python /tmp/reg.py"
```
Expected: `Registering /aiui (20 subcommands) and /video (guild 1475498065518661794)...` then `OK — 200`.

- [ ] **Step 5: Confirm `/video new` is registered**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml exec -T webhook-handler python -c \"import os,httpx; a=os.environ['DISCORD_APPLICATION_ID']; t=os.environ['DISCORD_BOT_TOKEN']; r=httpx.get(f'https://discord.com/api/v10/applications/{a}/guilds/1475498065518661794/commands', headers={'Authorization': f'Bot {t}'}); v=[c for c in r.json() if c['name']=='video'][0]; print(r.status_code, sorted(o['name'] for o in v['options']))\""
```
Expected: `200 ['add', 'list', 'new']`.

- [ ] **Step 6: Clean up the temp register script in the container**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml exec -T webhook-handler rm -f /tmp/reg.py"
```

- [ ] **Step 7: (Optional) re-post the panel** so the channel card shows the new copy. The existing card is cosmetic; the in-thread and `/video new` flows are already correct.
