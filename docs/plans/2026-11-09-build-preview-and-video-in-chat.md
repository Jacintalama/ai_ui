# A Finished Build Or Video Shows In The Main Chat Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** A build or video started from the main chat ends with the app or video on screen, including after a reload, without depending on how the model worded its reply.

**Architecture:** The page reads declared artifacts from the saved chat, cached and fetched only when the thread has settled, and redraws panels from that cache. The service adds any `[aiui-artifact]` line from this turn's tool results that the answer lacks. Status reads stop asking for approval.

**Tech Stack:** Python (tasks service, pytest), plain browser JS in `mcp-servers/gdrive/integrations-ui.js`, node for running its real sections, Playwright against the real site.

Design: `docs/plans/2026-11-09-build-preview-and-video-in-chat-design.md`. Commands run from `mcp-servers/tasks/`.

---

### Task 1: Status reads do not ask

**Files:** Modify `agent_tools.py` (`READ_METHODS`); Test `tests/test_agent_tools_classify.py`.

1. Failing test: `not is_write_tool("build_status")`, `not is_write_tool("video_status")`, and `is_write_tool("make_video")` stays True.
2. Run `python -m pytest tests/test_agent_tools_classify.py -q -k status`; expect FAIL.
3. Add both names to `READ_METHODS` with a comment saying why.
4. Pass, commit.

### Task 2: The service keeps the marker

**Files:** Create `agent_artifacts.py`; Modify `agent_runner.py` (the two normal returns of `_chat`); Test `tests/test_agent_artifacts.py`.

- `declared_this_turn(convo)`: `[aiui-artifact]` lines from `role: tool` messages after the last user message, in order, once each.
- `carried(answer, convo)`: the answer with any missing line added after a blank line (a reference definition cannot interrupt a paragraph). Empty answers stay empty.
- `_chat` applies it only when `agent_activity.in_main_chat()`.

Tests: added when dropped; not doubled when kept; earlier turns ignored; not added outside the main chat; no marker means unchanged text.

### Task 3: Two approvals read as a sentence

**Files:** Modify `routes_agent_turn.py` (`approval_question`); Test `tests/test_plain_approvals.py`.

Exactly one call, named `create_app` or `make_video`: "Build this app?" or "Make a video of <url>?", then the name and the whole description (600 characters), then the existing last line. Text comes only from the call's own arguments. Everything else keeps the current format.

### Task 4: The page reads the saved message

**Files:** Modify `mcp-servers/gdrive/integrations-ui.js`; Test `tests/test_the_page_reads_the_saved_message.py` (real section under node).

- `aiuiSavedApps(chain)`: each app with the id of the last message declaring it.
- `aiuiReadSaved(chatId, html)`: redraw from cache every scan; fetch on first look, or when the thread changed and held still for one scan. A failed fetch retries. `aiuiCloseWith` forces the next read.
- `aiuiWatchBuilds` calls it before anything can return early, and no longer has its own chat fetch.
- `aiuiShowAppInline(chatId, slug, messageId)` puts the panel in that message, waiting up to three scans for the row, then the last reply.
- A plain interval calls `aiuiWatchBuilds`, because a thread that has gone quiet produces no mutation to scan on.

### Task 5: Video follows the same path

**Files:** Modify `integrations-ui.js`, `open-webui-functions/video_tool.py`; Test same file, `tests/test_the_video_shows_inline.py`.

- `aiuiWatchVideos(chain, chatId)` runs from the saved read, so a chat with no build is watched.
- A finished video is redrawn in its closing message (job fetched once per id, cached).
- `make_video` also ends with `[aiui-artifact]: #video/<id>`. "Its id is" stays for chats already written.

### Task 6: Proof

1. Full tasks suite locally; only the known no-database errors.
2. Branch script served into the real site by Playwright route, on chat `1705ac23` (no panel today): panel present, inside its message row, iframe answers.
3. PR. After merge and deploy: one real build, panel on screen after finish and after reload. Update the video tool row through the API with `access_grants` passed back. One real video.
