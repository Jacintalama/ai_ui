# AI Agents page, Phase 0 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship the six no-regret fixes from docs/plans/2026-10-05-ai-agents-workspace-design.md (Phase 0) before the three-pane layout.

**Architecture:** Small edits in task-panel.js (shell), office.html, agents.html, agent-chat.css/js, routes_agents.py and agent_chat_render.py, each test-first. A shared postMessage protocol (aiui:open-pane, aiui-agents-ask, aiui-office-open, aiui-office-edit) keeps every link inside Open WebUI.

**Tech Stack:** FastAPI, static HTML/JS, htmx, pytest + Playwright (local, stubbed).

**Status:** Drafted by six agents from the real code and cross-checked by a seventh on 2026-10-05. The cross-check corrections below are NOT yet merged into the task text: apply them while executing. Phase 1 gets its own plan after Phase 0 lands.

---

## Cross-check: task order

1. Optional Task 0, not in any draft. In tests/test_static_page_js.py line 20, change _ID_RE to r'(?<![\w-])id="([^"]+)"' so the pre-existing office.html false positive goes green and every later baseline reads 0 failed. Measured: 28/28 on both today's tree and the merged tree. Add a tiny red-first unit case so the change is test-first.
2. P0-5 Task 1 (agent_chat_render.thread PASS filter). It is Python only and isolated.
3. P0-4 Task 1 (default_model on GET /api/tasks/agents/tools), then P0-4 Task 2 (openForm grouping and default).
4. P0-3 Task 1 (contrast, font, focus ring), then Task 2 (dialogs and the single Escape handler; it shares openForm with P0-4, so locate edits by anchor), then Task 3 (the aiui-agents-ask receiver). The receiver lands before the shell sender.
5. P0-1 Task 1, then Task 2, then Task 3, strictly in that order (Task 2 edits Task 1's code). Task 3 adds the aiui:open-pane listener that P0-2 depends on.
6. P0-2 Task 1 (office links; it needs P0-1 Task 3 to work end to end), then Task 2 (hue), then Task 3 (dots, outline, reduced motion).
7. P0-6 Task 1, then Task 2, last. Its tests drive the real task-panel.js, agents.html and office.html together, so running it last serves as the integration check on the merged state.
8. Then run the whole-suite command, and deploy everything as one unit: one tasks rebuild for every static file and the two Python modules, plus the index.html bind mount with --force-recreate. Run git fetch and `git branch -r --contains` first.

## Cross-check: collisions

- Measured: all six drafts merge without textual conflict. I took each drafter's finished agents.html and office.html, three-way merged them over today's files with git merge-file (base = repo), and got 0 conflicts. I then ran the whole suite on the merged tree: 769 passed, 1 failed (the known test_element_ids_are_unique[office.html]), 2 skipped, in 442 s. Evidence is in scratchpad/plan/crosscheck/ (combined_run.txt, lf/m_agents.html, lf/m_office.html).
- Measured: all 94 new tests run against today's code give exactly 67 failures, each one a test a draft calls red, and 27 guards pass. Breakdown: shell 4+3+5, office 7+3+3, a11y 10+6+1+2, model 2+7, pass 4+1, poll 4+5. Evidence: today_red.txt, 67 failed and 334 passed.
- agents.html openForm: P0-4 Task 2 edits lines 2349-2368 and P0-3 Task 2 edits 2388-2391 of the same function. They merge cleanly. Whichever lands second must locate its edit by the quoted anchor, because the line numbers shift.
- agents.html message listeners: P0-3 Task 3 (in the ?ask= IIFE), P0-6 Task 1 (in the main IIFE), P0-6 Task 2 (in the dock IIFE after 3061) and P0-2 Task 1 (in the dock IIFE at 3133-3146) touch separate regions. They add no clashing names to a shared scope; P0-6 Task 2 reuses the dock IIFE's existing `body`.
- agents.html prefill duplication: P0-3's prefillAsk (?ask= IIFE) and P0-2's prefill (dock IIFE) are two copies of the same logic. They do not conflict. Merge them into one in Phase 1, when the dock moves.
- office.html: P0-2 edits 142-143, 215, 436-437, 553-569, 1026, 1056, 1109-1112, 1132 and 1526-1547. P0-6 inserts before 1301 and edits 1588. There is no overlap.
- task-panel.js and openwebui-overrides/index.html are touched only by P0-1. Its Task 2 rewrites Task 1's code, so apply P0-1 strictly as Task 1, then 2, then 3. The cache key is bumped three times; only the last value matters.
- Contradiction: an ask over 2000 characters is dropped by the shell (P0-1) but truncated by the page (P0-3). This is harmless today. Pick one policy (see the a11y correction).
- Contradiction in behaviour: the hosted office Chat pill opens that agent's private conversation (aiui-office-ask with agent). The standalone office pane in the shell sends aiui:open-pane with ask 'Iris, '. The shell trims that to 'Iris,' and P0-3 puts it in the ROOM composer. The same click behaves two ways, which DESIGN.md's Don'ts forbid. Either accept it for Phase 0 or extend the protocol with an optional agent id (an owner decision).
- P0-2 decides it is inside the shell from window.top.__aiuiTaskPanelLoaded, not from window.top !== window. P0-1 must keep task-panel.js lines 11-12, and it does.
- P0-3 Task 2 pins exactly one '"Escape"' in agents.html, which constrains Phase 1.
- Deploy coupling: P0-2 Task 1 calls preventDefault and needs P0-1 Task 3's listener live. P0-1 Task 3's ask hand-off needs P0-3 Task 3's receiver live. All the static files are in the tasks image, so ship them in one tasks rebuild. Bind-mount index.html with --force-recreate in the same window.
- The pre-existing failure test_element_ids_are_unique[office.html] is a false positive: `\bid=` also matches `data-id=`. P0-2's 3c line split adds a second matched value to it. Measured: changing tests/test_static_page_js.py line 20 to `_ID_RE = re.compile(r'(?<![\w-])id="([^"]+)"')` makes test_static_page_js 28/28 green on both today's tree and the merged tree, and no static page has a real duplicate id.

## Cross-check: protocol consistency

The six drafts use the shared protocol with the same type names and fields. There are four deliberate deviations and one gap.

Matches (all verified in the drafted code):
1. Shell (P0-1): listens for {type:"aiui:open-pane", path}. It checks origin === location.origin. The path must be the urlPath of a NAV_ENTRIES embed entry. It opens the pane through openAiuiEmbed, the same call a sidebar click makes. Only for path "/ai-agents" with a string ask, trimmed and 1 to 2000 characters, it posts {type:"aiui-agents-ask", ask} to the agents frame's contentWindow with targetOrigin location.origin, after that frame has loaded.
2. Agents page receiver (P0-3 Task 3): accepts aiui-agents-ask only when the page is framed, source === window.parent and origin === location.origin. It fills the composer through prefillAsk, the same function ?ask= uses, and never sends.
3. Agents page sender (P0-2's openPane): posts {type:"aiui:open-pane", path} to window.parent with location.origin, only when window.parent !== window.
4. Office hosted (P0-2): sends aiui-office-ask {ask, agent, name}, aiui-office-open {path} or aiui-office-edit {id} to window.parent with origin. The host's existing listener checks origin and that the source is its own office frame. On aiui-office-open the host forwards aiui:open-pane. On aiui-office-edit it opens openForm, for the viewer's own agents only.
5. Office framed directly in the shell (P0-2): posts aiui:open-pane {path, ask?} to window.top with origin. Paths are "/graph", "/ai-agents" and "/ai-agents/office", all of which are real NAV_ENTRIES urlPaths.
6. P0-6 adds no new protocol. It reuses the existing {aiuiFrameVisible} message with origin and window.parent checks.
7. No listener added by any draft lacks an origin check or a source check.

Deviations, all deliberate and documented:
1. The shell also requires the source to be one of its own direct pane frames. This blocks chat artifacts and App Builder previews, and is stricter than rule 1.
2. The office detects the shell by window.top.__aiuiTaskPanelLoaded === true, not merely window.top !== window. A pinned test (/bare framing) needs this. Corollary: a docked office that has not finished its host handshake posts to top and is dropped. Requiring window.parent === window.top in inShell() closes that gap.
3. The shell drops asks over 2000 characters; the page truncates at 2000. Pick one.
4. The shell trims the ask, so the trailing space in "Iris, " is lost. The ?ask= path and the hosted office keep it.

Gap: aiui:open-pane has no agent id. The same robot Chat click therefore opens a private conversation when the office is docked, but prefills the room when the office is the standalone pane. That needs an owner decision: accept it for Phase 0, or add an optional agent field in Phase 1.

## Whole-suite command

cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/ tests/test_static_page_js.py tests/test_feature_pages_embed.py tests/test_nav_entries.py tests/test_agents_page_access.py tests/test_agents_page_memory.py tests/test_agent_chat_page.py tests/test_agent_chat_render.py tests/test_agent_chat_room.py tests/test_agent_tools_endpoint.py tests/test_agent_seed.py tests/test_agent_tool_reach.py tests/test_agent_name_header.py tests/test_agent_free_fallback.py -q -p no:cacheprovider

Baseline, measured today on HEAD 8052d7b78: 675 passed, 1 failed, 2 skipped (678 collected), about 370 s.
- The 1 failure is the pre-existing false positive test_static_page_js.py::test_element_ids_are_unique[office.html].
- The 2 skips are the live tests test_agent_panel_live and test_agents_take_turns_live.
- Of the 675, 585 come from the browser suite plus the static files, and 90 from the five extra Python files.

Expected after all six drafts: 769 passed, 1 failed (the same test), 2 skipped (772 collected, 94 new tests). I measured this on a scratch tree with every draft's finished files three-way merged, in 442 s. With the optional Task 0 regex fix the result is 770 passed, 0 failed, 2 skipped.

Not included above: the P0-5 slow suites (test_agent_chat_round, test_agent_app_card, test_agent_chat_approval, test_agent_chat_queue, test_agent_chat_endpoint; about 157 tests, about 8 minutes). Only P0-5 affects them. Its drafter measured them green, and I did not re-run them. Evidence files are in C:/Users/alama/AppData/Local/Temp/claude/C--Users-alama-Desktop-Lukas-Work-IO/25f6c77a-8e01-460d-b899-203a222150ca/scratchpad/plan/crosscheck/: baseline_all.txt, combined_run.txt, today_red.txt, and the merged files in lf/.

## Cross-check for shell: fix-needed

**wrong_refs:**
- Every task-panel.js line and anchor checked against today's file: 1369-1383 aiuiSidebarRightEdge, 1442 cssText, 1454-1462 reposition, 1511-1513, 1531-1533, 1544, 1639-1640, 1673-1676, onAuthRoute at 1016, the __aiuiTaskPanelLoaded flag at 11-12, and the cache key at openwebui-overrides/index.html:300. All are correct. The anchor 'pending = false;' plus its comment line occurs exactly once.
- The pinned-constraints note says test_sidebar_injection.py:165-177. test_the_pane_never_covers_the_sidebar actually runs from line 163 to 175.
- Task 3 Step 4, third line: `node --check mcp-servers/tasks/static/task-panel.js` runs right after `cd .../mcp-servers/tasks`. In a shell that keeps its cwd, that path does not exist.
- Step 5 of all three tasks runs `git add mcp-servers/tasks/...` with no cd. After Step 4 the cwd is mcp-servers/tasks, so git fails with 'pathspec did not match'.

**code_problems:**
- None blocking. The listener checks the origin and requires the source to be a direct pane frame from AIUI_FRAMES. The path must be a NAV_ENTRIES embed urlPath. The ask is posted with targetOrigin location.origin, only to the agents frame, after it loads, and is never sent.
- Red-first holds against today's repo: test_pane_edge 4 failed, 2 passed; test_phone_shell 3 failed, 3 passed; test_open_pane_message 5 failed, 7 passed. That is exactly the stated counts.
- Behaviour seam with P0-2: the shell trims the ask, so the standalone office Chat pill's 'Iris, ' arrives as 'Iris,' in the ROOM composer. The hosted office instead opens Iris's private conversation. The protocol carries no agent id. See protocol_consistency.
- Deviations from the design doc are deliberate and backed by live evidence: #sidebar is checked first at 30-520px wide and over 200px tall, and phones get a 47px top offset. They need the owner's nod.
- No test isolates the !onAuthRoute() guard (acknowledged in the draft). The scanSidebar hook forces one layout read per DOM-change frame while a pane is open, which is minor.
- The fixtures contain no user text and no emails (checked: only the <title> text).

**corrections:**
- Task 3 Step 4, replace `node --check mcp-servers/tasks/static/task-panel.js` with `node --check "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks/static/task-panel.js"`.
- Task 1, 2 and 3 Step 5: prefix each git add with `cd "C:/Users/alama/Desktop/Lukas Work/IO" && `.
- Pinned-constraints bullet: change `test_sidebar_injection.py:165-177` to `test_sidebar_injection.py:163-175`.

## Cross-check for office: fix-needed

**wrong_refs:**
- office.html refs are all correct: 142-143, 215-216, 436-437, 553-569, 1026, 1056, 1109-1112, 1132, and 1526-1547 (ending before the #side listener at 1549). Every anchor occurs exactly once.
- agents.html 3133-3146, openForm 2322, edit call 2779 and __aiuiAgents 2790-2793 are correct. test_office_inline.py 49 and 73-76 are correct, 603 lines. test_office_page.py 12-22 is correct, 1057 lines. _with_handoff is at 812. The test_agent_chat_turn_targets.py:33-36 import pattern is correct.
- Task 1 Step 4, second command: it lists 12 files and omits tests/test_agents_page_access.py, so it yields 377 passed, not the stated 386. 386 includes access's 9 tests.
- Step 5 of all three tasks: the plan says 'Run every command from .../mcp-servers/tasks', then runs `git add mcp-servers/tasks/static/office.html ...`. That pathspec fails from that directory.

**code_problems:**
- The 3c edit splits `data-id="' + esc(m.id) +` and `'"` across two lines. The id regex in test_static_page_js reads `data-id=` as `id=`, so this adds a second false-positive duplicate to the already failing test_element_ids_are_unique[office.html]. Measured on the merged tree: the failure now lists 2 values instead of 1.
- Race (minor): inShell() is true for a docked office whose host handshake has not arrived yet. Clicking then calls preventDefault and posts to window.top, and the shell drops the message because the source is not a direct pane frame. The result is a dead click.
- PANE_OF matches on a.pathname, so any future href="#..." anchor would resolve to /tasks/office and open the office pane. No such anchor exists today.
- Behaviour gap, not a bug: inside the shell, the standalone office's Chat pill prefills the room with 'Iris,'. Its Edit agent opens AI Agents without the form.
- The prefill() helper duplicates P0-3's prefillAsk(). Consolidate in Phase 1.
- Deploy dependency: the shell path calls preventDefault and relies on P0-1 Task 3's listener. If it ships without that listener, The Brain and Chat in the standalone office pane do nothing.
- Red-first holds against today's repo: Task 1 7 failed plus 1 guard; Task 2 3 failed; Task 3 3 failed.
- Escaping is right: data-id uses esc(m.id) and the aria-label uses esc(m.name). No dashes or emoji are added. Every a[href] keeps target=_top.

**corrections:**
- Task 1, 2 and 3 Step 5: prefix with `cd "C:/Users/alama/Desktop/Lukas Work/IO" && `.
- Task 1 Step 4 note: change 'measured: 386 passed before and after' to '377 passed before and after (386 if tests/test_agents_page_access.py is added to the list)'.
- Task 1 3c, new line, written on one line: `      '<a class="btn ghost edit-agent" target="_top" data-id="' + esc(m.id) + '" href="/tasks/agents">Edit agent</a>' +`. Alternatively land the optional Task 0 regex fix.
- Optional hardening for 3d, first line of inShell(): `if (window.top === window || window.parent !== window.top) return false;`. Only a direct shell pane posts aiui:open-pane, which is the only kind the shell accepts. A not-yet-hosted docked office then follows its link as it does today.
- Optional hardening for 3d, right after `if (!a) return;`: `if ((a.getAttribute("href") || "").charAt(0) === "#") return;`.

## Cross-check for a11y: ok

**wrong_refs:**
- None. Checked: agents.html 16, 23, 136-137, 541-548, 674, 887, 903-904, 915-916, 2388-2391, 2517, 2630, 2665-2681, 2784-2787 (inside the wireForm IIFE 2613-2788, so closeConnections is in scope), and 2819-2835. agent-chat.css 27-30, 128, 169, 253-257 and 306-309. agent-chat.js 119 and 145-147. test_agents_ask_prefill.py 23, 42-47 and 139 (urllib.parse is already imported). test_agent_chat_page.py has 172 lines, with _page and _script at 14 and 18. refreshToolsKeepingChoices is async, so the .then call is safe.

**code_problems:**
- Listeners are right: the aiui-agents-ask receiver checks that the page is framed, that the source is window.parent and the origin is location.origin, and that the ask is a non-blank string. It reuses prefillAsk, the same function ?ask= uses, and never sends.
- Policy mismatch with P0-1: the receiver slices an over-2000 ask to 2000, while the shell drops it. This is harmless because the shell never forwards more than 2000 characters, but the two should state one policy.
- Pre-existing violations remain and are not fixed here. The aiui:connections-changed listener (agents.html 1382-1387) checks neither origin nor source. openConnections posts aiui:open-connections with targetOrigin '*' (2662). Both need a separate task.
- test_escape_is_handled_in_one_place pins exactly one '"Escape"' in agents.html, so any later Escape handling must go through this handler.
- Red-first holds against today's repo: Task 1 10 failed; Task 2 6 failed in the a11y file plus 1 in test_agent_chat_page; Task 3 2 failed with 7 guards. Delete and Forget all still use window.confirm, and the tests that pin it passed on the merged tree.
- CSS follows DESIGN.md: a 2px periwinkle ring with 2px offset, muted #8b8b95, no glow, and no new font sizes.

**corrections:**
- None required.
- Optional, to share P0-1's drop policy: in Task 3 replace `prefillAsk(msg.ask.slice(0, 2000));` with `if (msg.ask.length > 2000) return;` followed by `prefillAsk(msg.ask);`. Then rename the last test to test_an_overlong_question_is_ignored, asserting input_value() == "" plus an _arrived check. It becomes a guard, because it passes today.

## Cross-check for model: fix-needed

**wrong_refs:**
- Most refs are correct: routes_agents.py 80-88 (_default_model) and 645-648 (list_tools), router prefix '/agents' at 51, _installed_tool_ids at 294 and _connected_providers at 312. routes_agent_turn.py 108-109 and test_agent_memory_routes.py 254-262 are correct. test_agent_tools_endpoint.py has 122 lines and 10 tests today. agents.html 1015, 1838-1839, 1936-1967, 1942-1943, 2219, 2349-2356 and 2367-2368 are correct. test_agents_page.py: the warning test spans 1409-1420 and the tools comment is at 1423. test_agents_tools_live.py:339 is correct.
- Both Step 5 commits: the plan says 'Run every command from mcp-servers/tasks', then runs `git add mcp-servers/tasks/routes_agents.py ...`, whose pathspec fails there.

**code_problems:**
- None blocking. Options are built with createElement and textContent, and optgroup labels are constants. tools_for_email is unchanged, so routes_agent_turn is not affected.
- Red-first holds against today's repo: Task 1 2 failed plus 1 guard; Task 2 7 failed plus 2 guards.
- The test client's AsyncClient is never closed. This is the same pattern as the existing test, so it is minor.
- Both openForm edits sit in the same function as P0-3 Task 2's edit at 2388-2391. They merge cleanly (verified); apply them by anchor, not by line number.

**corrections:**
- Task 1 and Task 2 Step 5: prefix with `cd "C:/Users/alama/Desktop/Lukas Work/IO" && `.

## Cross-check for pass: ok

**wrong_refs:**
- None. Checked: agent_chat_render.py 14, 344 (def thread), 350-351 and 387-400. agent_routing.py ROUTE_FOOTER 424-426, is_pass 437-464, and its only import is `re` (line 19), so there is no cycle. test_agent_chat_render.py has 305 lines, with CALLS at line 10. test_agent_chat_room.py: STORED_SMART_PASS at 260, _app at 57 returning (app, mod, _, rows), _hdr at 17, ADA and MIA at 13-14, and the anchors at 355 and 358. Counts today are render 27 and room 21.

**code_problems:**
- Red-first holds against today's repo: 5 failed (4 render, 1 room), and the PASS-then-answer guard passes.
- Not covered, by scope: a live Auto (Smart) answer still shows its routing footer until reload. DESIGN.md says 'routed to' must never show on the main surface. It needs a one-line follow-up in agent_bubble, which the draft flags.
- The tested copy puts `import agent_routing` after the blank line that follows line 14. The plan's 3a replacement gives the same code, so it makes no difference.

**corrections:**
- None required.

## Cross-check for poll: ok

**wrong_refs:**
- None. Checked: agents.html 1728-1737, 1769 (render calls loadActivity), 862, 2414, 2963 (var body), 3060-3061, and 27 ([hidden] display none !important). office.html 1212, 1261 (resync), 1288 (EventSource), 1301 and 1588. task-panel.js 1405 (aiuiFrameVisible), 1417, 1420, 1517, 1518 and 1532. projects.html 3268.

**code_problems:**
- Listeners are right: all three new message listeners check origin === location.origin and source === window.parent. The forward to the office frame uses targetOrigin location.origin.
- Red-first holds against today's repo: Task 1 4 failed; Task 2 5 failed.
- Minor gap: the agents page's own office show() does not forward {aiuiFrameVisible:true} to the office frame. After the page's Hide then Show, the floor waits up to 30 s for its tick (the EventSource covers most of that). Fix: post it from show() too.
- Only display:none is detected. If anything hides a pane another way, onScreen() fails open and polling continues (acknowledged in the draft).
- Its tests press Escape in the shell document. They still pass with P0-3's Escape handler, because nothing in the merged agents page takes focus on load (verified on the merged tree).

**corrections:**
- Optional: in the office dock IIFE, at the end of show(), add `var f = body.querySelector("iframe"); if (f) { try { f.contentWindow.postMessage({ aiuiFrameVisible: true }, window.location.origin); } catch (e) {} }`. Add a test that clicks #office-close, advances the clock 31 s, clicks #office-open, and asserts an office activity hit with the clock paused.

---

# Draft: P0-1 shell: rail edge, phone mount, open-pane

# P0-1 shell: rail edge, phone mount, aiui:open-pane (task-panel.js)

All paths are relative to `C:/Users/alama/Desktop/Lukas Work/IO`. `T` means `mcp-servers/tasks`.

Read first: `docs/plans/2026-10-05-ai-agents-workspace-design.md` ("Shell changes") and the evidence below. Every code block here was applied to a scratch copy of today's files and run. Each task's new tests fail against the code before it (counts given), pass after it, and the existing suites stay green (counts given). Scratch evidence: `C:/Users/alama/AppData/Local/Temp/claude/C--Users-alama-Desktop-Lukas-Work-IO/25f6c77a-8e01-460d-b899-203a222150ca/scratchpad/plan/p0-1-shell/` (probe scripts, `*.json` results, `auth_phone.html` and `auth_desk.html` captures, `plan.md` holding this exact text, and `mirror/` with the finished files).

## Evidence that shaped the code (live site, 2026-10-05, read-only, every non-GET request aborted by the probes)

1. Collapsed at 1920x1080, `#sidebar` is the rail: 0,0, 42x1080, `position: static`. The old function returns 260 (its fallback), and the pane opens at 260.
2. The toggle, recorded frame by frame (`toggle_probe.json`). Opening REMOVES the rail node and moves `id="sidebar"` onto a fixed z-50 panel, which widens from 0 to 124 (36 ms) to 245 (199 ms). Closing inserts a NEW rail (42px at once), and the panel loses the id and narrows to 0. After a close, our `[data-aiui-*]` entries stay inside the closed 0px panel.
3. Because of (2), the OLD walk returns 245 after a runtime collapse while the visible rail is 42 (`geo_probe.json`, "after Close Sidebar": old=245). It finds a 245px inner column inside the closed 0px panel. So `#sidebar` must be checked FIRST, not only "when no 120-520px column qualifies".
4. Live mutation record (`mut_probe.json`). On open, DOM changes land at 3 ms and 18 ms, then none during the slide. A re-measure triggered by a DOM change can therefore land mid-slide: the entries were back in the panel when it was already 124px wide. The pane must also observe the size of the current `#sidebar` node.
5. Breakpoint (`bp_probe.json`). At 767px wide there is no `#sidebar`, `#sidebar-toggle-button` is present, and the chat starts at x=0. At 768px the 42px rail is back (chat at 42), and the open panel is 245 fixed with the chat at 245. At 1024 collapsed, the rail is 42.
6. Phone at 390x844, signed in, at `/ai-agents` (`signed_probe.py`). The head rescue moves to `/`. `main#main-content`, `#chat-container` and `#chat-input` appear at 6.6 s. There are no sidebar links and no `[data-aiui-embed]`, so the pane never opens. The hamburger opens a drawer that is `#sidebar`, 245 wide and fixed. Closing the drawer slides it to left -245 with NO DOM mutation (transform only).
7. Signed out (`auth_probe.json`): 390x844 and 1920x1080, starting at `/auth`, `/` and `/ai-agents`, with a first-seen recorder from the start of navigation. `main#main-content`, `#main-content`, `#chat-container`, `#chat-input`, `.app` and `#sidebar-new-chat-button` NEVER appear, not even for a moment while `/` redirects to `/auth`. `a[href="#main-content"]` (the skip link) and `#svelte-announcer` ARE present on `/auth`. With a bogus token, `/ai-agents` also never shows `main#main-content` before landing on `/auth`. The phone signal chosen is `main#main-content`.
8. Served bytes today. The md5 of `/tasks/static/task-panel.js` and of the `/auth` HTML (CRLF stripped) equal the repo files: `500cee6d7c76cd983de7c8031fdf2afb` and `2d97bf322cf9c6585a6b285bf64a3843`. The live cache key is `task-panel.js?v=20260824-pane-dismiss`. The script is served with `Cache-Control: no-cache, no-store, must-revalidate`.

## Pinned constraints these tasks keep (checked by running the suites)

- `tests/test_feature_pages_embed.py` pins:
  - the `const appIsUp` and `wanted && appIsUp` literals (lines 170-175);
  - `[data-aiui-embed][data-open]`, `AIUI_FRAMES`, `NAV_EMBED_SELECTOR` and `aiuiFrameVisible`;
  - no `wrap.remove()` in `closeAiuiEmbed`;
  - `AIUI_URL_PATHS` equal to the NAV_ENTRIES urlPaths;
  - the head rescue in the `<head>` of `openwebui-overrides/index.html`.

  The cache key sits in `<body>` at line 300, and no test pins its value.
- `tests/test_nav_entries.py` pins `__aiuiEmbedPrevUrl`, `cfg.urlPath && location.pathname !== cfg.urlPath`, and the `a[href="/..."]` anchor set (`/workspace`, `/notes`, `/calendar`).
- `test_sidebar_injection.py:165-177` (the pane never covers the sidebar) and `test_pane_dismissal.py:107-141` stay green. Their fixtures have a 260px `#sidebar`, which the new first check accepts.
- Files are CRLF in the working tree (`core.autocrlf=true`). Use the Edit tool for `task-panel.js`. New files may be written with LF.

Baseline today, all green: `cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_sidebar_injection.py tests/browser/test_pane_dismissal.py tests/browser/test_direct_feature_url.py tests/test_feature_pages_embed.py tests/test_nav_entries.py -q` gives 123 passed (45 + 7 + 15 + 49 + 7).

### Task 1: The pane starts at Open WebUI's sidebar edge, rail or panel, and follows every toggle

**Files:**
- Create: `T/tests/browser/sidebar_collapsed_rail.html`, a fixture trimmed from the live collapsed DOM.
- Create: `T/tests/browser/test_pane_edge.py`.
- Modify: `T/static/task-panel.js` at these lines:
  - 1369-1383, `aiuiSidebarRightEdge`;
  - 1454-1462, `reposition` in `aiuiEmbedShell`;
  - 1511-1513, in `openAiuiEmbed`;
  - 1639-1640, the `scanSidebar` rAF callback.
- Modify: `openwebui-overrides/index.html` line 300 (the cache key).
- Test: `T/tests/browser/test_pane_edge.py`, plus the five existing suites above.

**Step 1: Write the failing test.** Create the fixture `T/tests/browser/sidebar_collapsed_rail.html` with exactly this content. Its structure comes from the live capture with no user content. Checked in a browser, it measures the rail at 0,0, 42x1080 and the Graph entry at 4,298, 33x32, the same as live.

```html
<!doctype html><html><head><meta charset="utf-8"><title>collapsed rail</title>
<!--
  Open WebUI v0.11.4 with the sidebar COLLAPSED, trimmed from the live DOM
  captured on 2026-10-05 at 1920x1080 (desk_collapsed.html). Tags, ids,
  aria labels, hrefs and data-state are the real ones; text, images, svg
  paths, the chat list and every user detail are removed. Tailwind is not
  loaded, so the geometry measured live is written as inline styles:

    #sidebar (the rail)       0,0    42 x 1080   static, z-index 10
    rail button.flex-col      4,4    33 x 1038
    collapsed panel           0,0     0 x 1080   fixed, z-index 50, aria-hidden
    open panel (#sidebar)     0,0   245 x 1080   fixed, z-index 50

  The toggle below copies what the live site did, recorded frame by frame:
  opening REMOVES the rail and moves id="sidebar" onto the panel, which widens
  0 -> 245px over about 200ms. Closing inserts a NEW rail with none of our
  entries in it, and the panel drops the id and narrows back to 0.
-->
<style>
  body { margin: 0; }
  .shell-row { display: flex; flex-direction: row; height: 100vh; }
  .rail { width: 42px; height: 100vh; box-sizing: border-box; padding: 4px;
          display: flex; flex-direction: column; justify-content: space-between;
          position: static; z-index: 10; flex-shrink: 0; }
  .rail > button { display: flex; flex-direction: column; flex: 1 1 0%;
                   justify-content: flex-start; width: 33px; padding: 0;
                   border: 0; background: none; }
  .rail .pb-1 { padding-bottom: 4px; }
  /* Tailwind's size-4 / size-5 and hidden, which the real icons carry. */
  svg { width: 16px; height: 16px; }
  img { width: 20px; height: 20px; }
  .hidden { display: none; }
  .rail .row-flex > * { display: flex; width: 32px; height: 32px; }
  .panel { position: fixed; top: 0; left: 0; height: 100vh; width: 0;
           overflow: hidden; z-index: 50; transition: width 200ms;
           pointer-events: none; }
  .panel[data-state="true"] { width: 245px; pointer-events: auto; }
  .panel-inner { width: 245px; height: 100vh; display: flex; flex-direction: column; }
  main.contents { display: contents; }
  #chat-container { flex: 1 1 0%; height: 100vh; min-width: 0; }
</style>
</head>
<body>
<div>
  <a href="#main-content" class="sr-only" style="position:absolute;left:-1px;top:-1px;width:1px;height:1px;overflow:hidden"></a>
  <div class="app relative">
    <div class="shell-row" id="shell-row">
      <button id="sidebar-new-chat-button" class="hidden" style="display:none"></button>
      <div role="navigation" aria-label="Chat history" aria-hidden="true"
           class="panel" data-state="false">
        <div class="panel-inner">
          <div class="sidebar" style="display:flex;justify-content:space-between">
            <a href="/" draggable="false"><img alt=""></a>
            <a href="/" style="flex:1 1 0%"><div id="sidebar-webui-name"></div></a>
            <div class="flex">
              <button aria-label="Open Sidebar" style="width:30px;height:30px"><div class=" self-center"><svg aria-hidden="true" class="size-4"></svg></div></button>
            </div>
          </div>
          <div style="display:flex;flex-direction:column;flex:1 1 0%">
            <div class="pb-1">
              <div class="px-1 flex"><a id="sidebar-new-chat-button" href="/" draggable="false" aria-label="New Chat"></a></div>
              <div class="px-1 flex"><button id="sidebar-search-button" draggable="false" aria-label="Search"></button></div>
              <div id="pinned-menu-items-list">
                <div class="px-1 flex" data-id="notes"><a draggable="false" id="sidebar-notes-button" href="/notes" aria-label="Notes"><div class="flex"><div></div></div></a></div>
                <div class="px-1 flex" data-id="workspace"><a draggable="false" id="sidebar-workspace-button" href="/workspace" aria-label="Workspace"><div class="flex"><div></div></div></a></div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <main id="main-content" class="contents">
        <div id="chat-container"></div>
      </main>
    </div>
  </div>
</div>

<template id="rail-template">
  <div class="rail" id="sidebar" role="navigation" aria-label="Chat history">
    <!-- A <button> in the real DOM. The HTML parser will not nest a button in a
         button, so it is written as a div and made a button when stamped. -->
    <div data-button class="flex flex-col flex-1 cursor-pointer">
      <div class="pb-1">
        <div class="flex">
          <button aria-label="Open Sidebar" style="width:34px;height:34px"><div class="self-center flex"><img alt=""><svg aria-hidden="true" class="size-4 hidden group-hover:flex"></svg></div></button>
        </div>
      </div>
      <div class="-gap-0.5 row-flex">
        <div><div class="flex"><a href="/" draggable="false" aria-label="New Chat"><div class="self-center flex"><svg aria-hidden="true" class="size-4"></svg></div></a></div></div>
        <div><div class="flex"><button draggable="false" aria-label="Search"><div class="self-center flex"><svg aria-hidden="true" class="size-4"></svg></div></button></div></div>
        <div><div class="flex"><a draggable="false" href="/notes" aria-label="Notes"><div class="self-center flex"><svg aria-hidden="true" class="size-4"></svg></div></a></div></div>
        <div><div class="flex"><a draggable="false" href="/workspace" aria-label="Workspace"><div class="self-center flex"><svg aria-hidden="true" class="size-4"></svg></div></a></div></div>
      </div>
    </div>
    <div><div><div class="flex justify-center items-center"><span role="button"><button type="button" aria-label="User menu" style="width:34px;height:34px"></button></span></div></div></div>
  </div>
</template>

<script>
  (function () {
    var row = document.getElementById("shell-row");
    var panel = row.querySelector(".panel");
    var panelToggle = panel.querySelector(".sidebar button");

    function stampRail() {
      var rail = document.getElementById("rail-template").content
        .firstElementChild.cloneNode(true);
      var stub = rail.querySelector("[data-button]");
      var big = document.createElement("button");
      for (var i = 0; i < stub.attributes.length; i++) {
        var a = stub.attributes[i];
        if (a.name !== "data-button") big.setAttribute(a.name, a.value);
      }
      while (stub.firstChild) big.appendChild(stub.firstChild);
      stub.replaceWith(big);
      row.insertBefore(rail, panel);
      // The rail is one big <button> in the real DOM, and pressing it (its
      // "Open Sidebar" icon is inside it) opens the sidebar. Its links do not.
      rail.querySelector("button.flex-col").addEventListener("click", function (e) {
        if (e.target.closest && e.target.closest("a")) return;
        openSidebar();
      });
    }
    function openSidebar() {
      var rail = document.getElementById("sidebar");
      if (rail && rail !== panel) rail.remove();
      panel.id = "sidebar";
      panel.setAttribute("data-state", "true");
      panel.setAttribute("aria-hidden", "false");
      panelToggle.setAttribute("aria-label", "Close Sidebar");
    }
    function closeSidebar() {
      panel.id = "";
      panel.setAttribute("data-state", "false");
      panel.setAttribute("aria-hidden", "true");
      panelToggle.setAttribute("aria-label", "Open Sidebar");
      stampRail();
    }
    panelToggle.addEventListener("click", function () {
      if (panel.getAttribute("data-state") === "true") closeSidebar();
      else openSidebar();
    });
    stampRail();
  })();
</script>
<script src="./task-panel.js"></script>
</body></html>
```

Create `T/tests/browser/test_pane_edge.py`. It follows the conventions of `test_sidebar_injection.py`: `importorskip`, the REAL `task-panel.js` copied beside the fixture, and a skip when chromium is missing.

```python
"""The pane starts where Open WebUI's sidebar really ends, and follows it.

Measured on the live site on 2026-10-05 (Open WebUI v0.11.4, 1920x1080, the
sidebar collapsed): the rail, <div id="sidebar">, is 42px wide and the pane
opened at x=260. aiuiSidebarRightEdge() accepted only a column 120 to 520px
wide, found none, and fell back to 260, which left an empty strip about 218px
wide between the rail and the page.

Collapsing is not a resize. Recorded frame by frame on the live site: opening
the sidebar REMOVES the rail and moves id="sidebar" onto a fixed 245px panel
that slides in over about 200ms; closing inserts a NEW rail, and the panel
narrows to 0 without the id, keeping our entries inside it.

sidebar_collapsed_rail.html is that DOM trimmed to structure, with the live
geometry written in as inline styles and the swap reproduced by its toggle.
The first test checks the fixture still has the measured shape, because every
other test here means nothing without it.
"""
import pathlib
import shutil

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

HERE = pathlib.Path(__file__).parent
STATIC = HERE.parents[1] / "static"
PANE = "[data-aiui-embed]"
OPEN_PANE = "[data-aiui-embed][data-open]"

#: openAiuiEmbed re-measures every 250ms for 3s after an open. A person
#: collapses the sidebar long after that, so the toggle tests wait it out;
#: otherwise they would pass on that poll alone and prove nothing.
AFTER_OPEN_POLL_MS = 3500
#: The live panel slides for about 200ms.
SLIDE_MS = 600


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001 - browser binary absent
            pytest.skip(f"chromium not installed: {exc}")
        yield b
        b.close()


@pytest.fixture()
def page(browser, tmp_path):
    """The REAL task-panel.js beside the fixture, at the measured window."""
    shutil.copy(STATIC / "task-panel.js", tmp_path / "task-panel.js")
    shutil.copy(HERE / "sidebar_collapsed_rail.html", tmp_path / "index.html")
    pg = browser.new_page(viewport={"width": 1920, "height": 1080})
    pg.goto((tmp_path / "index.html").as_uri())
    pg.wait_for_selector("#sidebar [data-aiui-agents]", timeout=8000)
    yield pg
    pg.close()


def _open_agents(page):
    page.locator("#sidebar [data-aiui-agents]").click()
    page.wait_for_selector(OPEN_PANE, timeout=4000)


def _pane_left(page):
    return page.locator(PANE).bounding_box()["x"]


def _sidebar_right(page):
    box = page.locator("#sidebar").bounding_box()
    return box["x"] + box["width"]


def test_the_fixture_has_the_shape_measured_live(page):
    rail = page.locator("#sidebar").bounding_box()
    assert (rail["x"], rail["width"], rail["height"]) == (0, 42, 1080)
    seed = page.locator("[data-aiui-graph]").bounding_box()
    assert (seed["x"], seed["y"], seed["width"], seed["height"]) == (4, 298, 33, 32)


def test_the_pane_starts_at_the_collapsed_rail(page):
    _open_agents(page)
    assert _pane_left(page) == 42, (
        f"the pane starts at {_pane_left(page)} but the rail ends at 42, "
        "leaving an empty strip between them")


def test_the_pane_never_covers_the_rail(page):
    _open_agents(page)
    entry = page.locator("#sidebar [data-aiui-agents]").bounding_box()
    assert _pane_left(page) >= entry["x"] + entry["width"]


def test_the_pane_follows_the_sidebar_when_it_opens(page):
    _open_agents(page)
    page.wait_for_timeout(AFTER_OPEN_POLL_MS)
    page.locator('#sidebar button[aria-label="Open Sidebar"]').click()
    page.wait_for_timeout(SLIDE_MS)
    assert page.locator(OPEN_PANE).count() == 1, "opening the sidebar closed the pane"
    assert _sidebar_right(page) == 245
    assert _pane_left(page) == 245, (
        f"the sidebar opened to 245px and the pane stayed at {_pane_left(page)}")


def test_the_pane_follows_the_sidebar_when_it_closes_again(page):
    _open_agents(page)
    page.wait_for_timeout(AFTER_OPEN_POLL_MS)
    page.locator('#sidebar button[aria-label="Open Sidebar"]').click()
    page.wait_for_timeout(SLIDE_MS)
    page.locator('#sidebar button[aria-label="Close Sidebar"]').click()
    page.wait_for_timeout(SLIDE_MS)
    assert _sidebar_right(page) == 42
    assert _pane_left(page) == 42, (
        f"the sidebar closed to the 42px rail and the pane stayed at "
        f"{_pane_left(page)}")


def test_the_pane_follows_a_sidebar_still_sliding_when_the_page_changes(page):
    """Recorded live: our entries were put back into the panel when it was
    already 124px into its 245px slide, so the re-measure that a DOM change
    triggers can land mid-slide. The pane must still end where the panel
    does, not where it happened to be at that moment."""
    _open_agents(page)
    page.wait_for_timeout(AFTER_OPEN_POLL_MS)
    page.evaluate("""() => new Promise((done) => {
      document.querySelector('#sidebar button[aria-label="Open Sidebar"]').click();
      setTimeout(() => {
        document.body.appendChild(document.createElement("i"));
        done();
      }, 60);
    })""")
    page.wait_for_timeout(SLIDE_MS)
    assert _pane_left(page) == 245, (
        f"the panel finished at 245px and the pane stopped at {_pane_left(page)}")
```

**Step 2: Run it to verify it fails.**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_pane_edge.py -q
```

Expected: `4 failed, 2 passed`. The failures:
- `test_the_pane_starts_at_the_collapsed_rail`: `assert 260 == 42`, the same 260 measured live.
- `test_the_pane_follows_the_sidebar_when_it_opens`: `assert 260 == 245`.
- `test_the_pane_follows_the_sidebar_when_it_closes_again`: `assert 260 == 42`.
- `test_the_pane_follows_a_sidebar_still_sliding_when_the_page_changes`: `assert 260 == 245`.

The two that pass are guards (the fixture shape, and the pane never covering the rail).

**Step 3: Minimal implementation.** Make four edits in `T/static/task-panel.js`. Each is anchored by a string that occurs exactly once today.

Edit 1a (lines 1369-1383, `aiuiSidebarRightEdge`: check `#sidebar` first, and keep the old walk and the 260 fallback for layouts without it). Replace exactly:

```js
    // Measure the left sidebar so the overlay starts exactly at its right edge
    // (and re-measures when the sidebar collapses / the window resizes).
    function aiuiSidebarRightEdge() {
      const seed = document.querySelector("[data-aiui-graph]") ||
                   document.querySelector('a[href="/workspace"]');
      let best = null, el = seed;
      while (el && el !== document.body) {
        const r = el.getBoundingClientRect();
        // The sidebar is anchored to the left, tall, and a few hundred px wide.
        if (r.left <= 8 && r.width >= 120 && r.width <= 520 && r.height > 200) best = el;
        el = el.parentElement;
      }
      if (best) return { edge: Math.round(best.getBoundingClientRect().right), el: best };
      return { edge: 260, el: null };
    }
```

with:

```js
    // Measure the left sidebar so the overlay starts exactly at its right edge
    // (and re-measures when the sidebar collapses / the window resizes).
    //
    // Open WebUI 0.11 puts id="sidebar" on whichever sidebar is showing: the
    // 42px icon rail when collapsed, the 245px panel when open. They are two
    // different nodes and only one carries the id at a time (recorded frame
    // by frame on the live site, 2026-10-05). The walk below accepts only a
    // column 120px or wider, so it never found the rail and the pane fell
    // back to 260px, leaving an empty strip about 218px wide beside it.
    function aiuiSidebarRightEdge() {
      const sb = document.getElementById("sidebar");
      if (sb) {
        const r = sb.getBoundingClientRect();
        if (r.left <= 8 && r.width >= 30 && r.width <= 520 && r.height > 200) {
          return { edge: Math.max(0, Math.round(r.right)), el: sb };
        }
      }
      // Layouts without a usable #sidebar: walk up from one of our entries.
      const seed = document.querySelector("[data-aiui-graph]") ||
                   document.querySelector('a[href="/workspace"]');
      let best = null, el = seed;
      while (el && el !== document.body) {
        const r = el.getBoundingClientRect();
        // The sidebar is anchored to the left, tall, and a few hundred px wide.
        if (r.left <= 8 && r.width >= 120 && r.width <= 520 && r.height > 200) best = el;
        el = el.parentElement;
      }
      if (best) return { edge: Math.round(best.getBoundingClientRect().right), el: best };
      return { edge: 260, el: null };
    }
```

Edit 1b (lines 1454-1462 in `aiuiEmbedShell`: the observer follows whichever node is `#sidebar` now. The old observer on `meas.el` is removed; `meas` is still used for the initial `left`). Replace exactly:

```js
      // Keep the pane glued to the sidebar edge on resize / collapse.
      const reposition = () => {
        if (isOpen()) wrap.style.left = aiuiSidebarRightEdge().edge + "px";
      };
      window.addEventListener("resize", reposition);
      if (meas.el && "ResizeObserver" in window) {
        new ResizeObserver(reposition).observe(meas.el);
      }
      wrap.__aiuiReposition = reposition;
```

with:

```js
      // Keep the pane glued to the sidebar edge on resize / collapse.
      //
      // Collapsing does not resize one sidebar: Open WebUI swaps the rail and
      // the panel as whole nodes and moves the id between them. scanSidebar
      // catches the swap (it re-places an open pane on every DOM change), but
      // that can land while the panel is still sliding open (live: 124 of
      // 245px), so this observer follows whichever node is the sidebar now
      // and reports the rest of the slide. One fixed on the node measured at
      // first open went blind after the first toggle.
      let watched = null;
      const ro = "ResizeObserver" in window
        ? new ResizeObserver(() => reposition()) : null;
      const reposition = () => {
        if (!isOpen()) return;
        const m = aiuiSidebarRightEdge();
        wrap.style.left = m.edge + "px";
        const sb = m.el || document.getElementById("sidebar");
        if (ro && sb !== watched) {
          if (watched) ro.unobserve(watched);
          if (sb) ro.observe(sb);
          watched = sb;
        }
      };
      window.addEventListener("resize", reposition);
      wrap.__aiuiReposition = reposition;
```

Edit 1c (lines 1511-1513 in `openAiuiEmbed`: place the pane through `reposition`, so the observer starts on open). Replace exactly:

```js
      wrap.setAttribute("data-open", cfg.href);
      wrap.style.display = "block";
      wrap.style.left = aiuiSidebarRightEdge().edge + "px";
```

with:

```js
      wrap.setAttribute("data-open", cfg.href);
      wrap.style.display = "block";
      wrap.__aiuiReposition();
```

Edit 1d (lines 1639-1640, the FIRST lines of the `scanSidebar` rAF callback. The anchor includes the comment line because `pending = false;` alone also occurs at line 1091). Replace exactly:

```js
        pending = false;
        // Don't early-return for non-admins: entries flagged allUsers must
```

with:

```js
        pending = false;
        // An open pane follows the sidebar through Open WebUI's re-renders.
        // Collapsing and expanding swap the rail and the panel as whole
        // nodes, which no resize event reports, and this runs on every DOM
        // change.
        const shown = document.querySelector("[data-aiui-embed][data-open]");
        if (shown && shown.__aiuiReposition) shown.__aiuiReposition();
        // Don't early-return for non-admins: entries flagged allUsers must
```

Edit 1e (`openwebui-overrides/index.html` line 300). Replace exactly:

```html
	<script src="/tasks/static/task-panel.js?v=20260824-pane-dismiss"></script></body>
```

with:

```html
	<script src="/tasks/static/task-panel.js?v=20261005-pane-edge"></script></body>
```

**Step 4: Run it to verify it passes.**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_pane_edge.py -q
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_pane_edge.py tests/browser/test_sidebar_injection.py tests/browser/test_pane_dismissal.py tests/browser/test_direct_feature_url.py tests/test_feature_pages_embed.py tests/test_nav_entries.py -q
```

Expected: `6 passed`, then `129 passed` (6 new + 123 existing). This ran 3 times on the finished code with no flaky failures.

Variant checks were done in scratch, and both pieces are load-bearing:
- Without the `scanSidebar` hook, `..._when_it_closes_again` fails (`assert 245 == 42`).
- Without the observer that follows `#sidebar`, `..._still_sliding_...` fails (`assert 141 == 245`).

**Step 5: Commit.**

```bash
git add mcp-servers/tasks/static/task-panel.js openwebui-overrides/index.html mcp-servers/tasks/tests/browser/sidebar_collapsed_rail.html mcp-servers/tasks/tests/browser/test_pane_edge.py
git commit -m "Shell pane starts at the collapsed rail and follows sidebar toggles" -m "Open WebUI 0.11 keeps id=sidebar on whichever sidebar shows: the 42px rail or the 245px panel. The pane now measures that first, so it opens at 42 instead of 260. It re-measures on DOM changes and on the sidebar node's size, so it follows open and close. Fixture trimmed from the live collapsed DOM. Cache key bumped." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: On a phone the agents pane opens (never over /auth) and leaves the top bar reachable

**Files:**
- Create: `T/tests/browser/shell_phone.html`, which holds the signed-in phone home and the signed-out `/auth` page, trimmed from the live captures, behind a small router.
- Create: `T/tests/browser/test_phone_shell.py`.
- Modify: `T/static/task-panel.js` in four places:
  - `aiuiSidebarRightEdge` (lines 1371-1383 today, as rewritten in Task 1);
  - the `cssText` line in `aiuiEmbedShell` (line 1442 today);
  - `reposition` (from Task 1);
  - the `appIsUp` block (lines 1673-1676 today).
- Modify: `openwebui-overrides/index.html` line 300 (the cache key again).
- Test: `T/tests/browser/test_phone_shell.py`, `test_pane_edge.py` and the five existing suites.

**Step 1: Write the failing test.** Create `T/tests/browser/shell_phone.html`:

```html
<!doctype html><html><head><meta charset="utf-8"><title>phone shell</title>
<!--
  Open WebUI v0.11.4 on a 390x844 phone, trimmed from two live captures taken
  on 2026-10-05: the signed-in home at "/" (phone_home.html) and the signed-out
  sign-in page at "/auth". Tags, ids, aria labels and hrefs are the real ones;
  text, images, svg paths and every user detail are removed. Tailwind is not
  loaded, so the geometry that matters is written as inline styles: the home's
  only bar is a <nav> at 0,0, 390 x 47.

  What makes these two pages different for task-panel.js, as measured live:
    home  : no a[href="/"], a[href="/notes"], a[href="/calendar"],
            a[href="/workspace"], no #sidebar; main#main-content present.
    /auth : none of those either, and no main#main-content; the skip link
            a[href="#main-content"] IS present, as it is on the home.

  The router below plays Open WebUI's: "/" is the home, "/auth" the sign-in
  page, anything else the bare 404 the real router renders for a pane URL.
-->
<style>
  body { margin: 0; }
  .hidden { display: none; }
  main.contents { display: contents; }
  svg { width: 16px; height: 16px; }
  .sr-only { position: absolute; left: -1px; top: -1px; width: 1px; height: 1px; overflow: hidden; }
</style>
</head>
<body>
<div id="root"></div>

<template id="page-home">
  <a href="#main-content" class="sr-only"></a>
  <div class="app relative">
    <div style="height:100vh;display:flex;flex-direction:row;overflow:auto">
      <button id="sidebar-new-chat-button" class="hidden"></button>
      <main id="main-content" class="contents">
        <audio id="audioElement"></audio>
        <div id="chat-container" style="height:100vh;width:100%;display:flex;flex-direction:column">
          <div style="width:100%;height:100%;display:flex;flex-direction:column">
            <div style="width:100%;height:100%;display:flex">
              <div style="height:100%;display:flex;flex-direction:column;flex:1 1 0%;min-width:0;position:relative">
                <button id="new-chat-button" class="hidden" aria-label="New Chat"></button>
                <nav class="sticky top-0 z-30 w-full drag-region" style="position:sticky;top:0;z-index:30;width:100%;height:47px;box-sizing:border-box;padding:6px 10px 4px;margin-bottom:-48px">
                  <div style="display:flex;align-items:center;width:100%">
                    <div class="mr-1 flex flex-none items-center self-center">
                      <div class="flex">
                        <button id="sidebar-toggle-button" aria-label="Open Sidebar" style="width:28px;height:28px;padding:0"><div class="self-center p-1.5"><svg aria-hidden="true" class="size-4"></svg></div></button>
                      </div>
                    </div>
                    <div style="flex:1 1 0%"></div>
                    <div style="display:flex;gap:8px">
                      <div class="flex"><button id="temporary-chat-button" aria-label="Temporary Chat" style="width:24px;height:24px"></button></div>
                      <div class="flex"><button aria-label="Controls" style="width:24px;height:24px"></button></div>
                    </div>
                  </div>
                </nav>
                <div id="chat-pane" style="display:flex;flex-direction:column;flex:1 1 auto;width:100%;overflow:auto">
                  <div id="message-input-container" style="margin-top:auto">
                    <div id="chat-input-container">
                      <div id="chat-input" class="tiptap ProseMirror" contenteditable="true" aria-label="How can I help you today?"></div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  </div>
  <div id="svelte-announcer"></div>
</template>

<template id="page-auth">
  <a href="#main-content" class="sr-only"></a>
  <div id="auth-page" style="width:100%;height:100vh;position:relative">
    <div id="auth-container" style="position:fixed;inset:0;display:flex;justify-content:center;z-index:50">
      <div id="auth-login-card" style="margin:auto;width:100%;max-width:448px">
        <form>
          <input type="email" id="email" name="email" autocomplete="email">
          <input type="password" id="password" name="password" autocomplete="current-password">
          <button type="submit"></button>
        </form>
      </div>
    </div>
  </div>
  <div id="svelte-announcer"></div>
</template>

<script>
  (function () {
    var root = document.getElementById("root");
    var path = location.pathname;
    if (path === "/" || path === "/auth") {
      var tpl = document.getElementById(path === "/" ? "page-home" : "page-auth");
      root.appendChild(tpl.content.cloneNode(true));
    } else {
      root.textContent = "404: Not Found";
    }
  })();
</script>
<script src="/task-panel.js"></script>
</body></html>
```

Create `T/tests/browser/test_phone_shell.py`. It uses the HTTP server pattern from `test_direct_feature_url.py`: every path answers 200 with the shell, and `/task-panel.js` is the real file. `/tasks/*` answers a stub, so the pane's iframe does not boot the shell inside itself.

```python
"""On a phone, /ai-agents opens, and never over the sign-in page.

Measured on the live site on 2026-10-05 at 390x844, signed in: the page at
/ai-agents was still the plain chat home after 60 s. The shell opens a pane
only once "the app is up", and it judged that by sidebar links. A phone has
none: Open WebUI drops the rail under 768px and shows one 47px top bar.

The other half is the guard that check exists for. A signed-out visitor is
sent to /auth, and a pane opened there would cover the sign-in form and spend
the request. So the new signal had to be present on the signed-in phone home
and absent on /auth. main#main-content is: checked live at 390x844 and
1920x1080, including while a signed-out "/" and a dead token were being
redirected to /auth, where it never appeared even for a moment.

shell_phone.html holds both pages, trimmed from those captures, behind a small
router. These run over HTTP because the rescue and pushState need a real
origin; file:// swallows both.
"""
import functools
import http.server
import pathlib
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

HERE = pathlib.Path(__file__).parent
STATIC = HERE.parents[1] / "static"
OPEN_PANE = "[data-aiui-embed][data-open]"
PHONE = {"width": 390, "height": 844}
DESK = {"width": 1920, "height": 1080}

#: What a pane's iframe loads. Only its presence matters here.
STUB = b"<!doctype html><meta charset='utf-8'><title>stub pane</title>"


class _Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib naming
        path = self.path.split("?")[0]
        if path == "/task-panel.js":
            body, ctype = (STATIC / "task-panel.js").read_bytes(), "application/javascript"
        elif path.startswith("/tasks/"):
            body, ctype = STUB, "text/html"
        else:
            # 200 with the shell for every other path, like the real server.
            body, ctype = (HERE / "shell_phone.html").read_bytes(), "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # keep pytest output clean
        pass


@pytest.fixture(scope="module")
def base_url():
    srv = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_Handler, directory=str(HERE)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001 - browser binary absent
            pytest.skip(f"chromium not installed: {exc}")
        yield b
        b.close()


@pytest.fixture()
def phone(browser):
    pg = browser.new_page(viewport=PHONE)
    yield pg
    pg.close()


def test_the_fixture_has_no_sidebar_links_like_the_live_phone(phone, base_url):
    """Guards the rest: this is the condition that kept the pane shut."""
    phone.goto(base_url + "/")
    phone.wait_for_selector("main#main-content", state="attached")
    for sel in ('a[href="/"]', 'a[href="/notes"]', 'a[href="/calendar"]',
                'a[href="/workspace"]', "#sidebar"):
        assert phone.locator(sel).count() == 0, sel
    bar = phone.locator("nav").bounding_box()
    assert (bar["x"], bar["y"], bar["width"], bar["height"]) == (0, 0, 390, 47)


def test_a_phone_opens_the_agents_pane(phone, base_url):
    phone.goto(base_url + "/ai-agents")
    phone.wait_for_selector(OPEN_PANE, timeout=8000)
    assert "/tasks/agents" in phone.get_attribute(f"{OPEN_PANE} iframe", "src")
    assert phone.evaluate("location.pathname") == "/ai-agents"


def test_the_phone_pane_is_full_width_under_the_top_bar(phone, base_url):
    phone.goto(base_url + "/ai-agents")
    phone.wait_for_selector(OPEN_PANE, timeout=8000)
    box = phone.locator(OPEN_PANE).bounding_box()
    assert (box["x"], box["y"], box["width"], box["height"]) == (0, 47, 390, 797)


def test_the_hamburger_stays_reachable_over_the_pane(phone, base_url):
    """A phone has no Escape key, and every link that would close the pane is
    under it. The hamburger is the way out, so the pane must not cover it."""
    phone.goto(base_url + "/ai-agents")
    phone.wait_for_selector(OPEN_PANE, timeout=8000)
    hit = phone.evaluate("""() => {
      const r = document.getElementById("sidebar-toggle-button").getBoundingClientRect();
      const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return !!(el && el.closest("#sidebar-toggle-button"));
    }""")
    assert hit, "the pane covers the hamburger, so a phone cannot leave it"


@pytest.mark.parametrize("viewport", [PHONE, DESK], ids=["phone", "desktop"])
def test_a_pane_never_opens_over_the_sign_in_page(browser, base_url, viewport):
    """The request waits, unspent, for the sign-in to finish."""
    pg = browser.new_page(viewport=viewport)
    try:
        pg.goto(base_url + "/auth")
        pg.evaluate(
            "() => sessionStorage.setItem('__aiuiOpenPath',"
            " JSON.stringify({path: '/ai-agents', at: Date.now()}))")
        pg.reload()
        pg.wait_for_selector("#auth-page", state="attached")
        pg.wait_for_timeout(1500)
        assert pg.locator(OPEN_PANE).count() == 0, "a pane opened over the sign-in form"
        assert pg.evaluate("() => sessionStorage.getItem('__aiuiOpenPath')"), \
            "the request was spent on the sign-in page"
    finally:
        pg.close()
```

**Step 2: Run it to verify it fails.**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_phone_shell.py -q
```

Expected: `3 failed, 3 passed`. The three failures are `test_a_phone_opens_the_agents_pane`, `test_the_phone_pane_is_full_width_under_the_top_bar` and `test_the_hamburger_stays_reachable_over_the_pane`. Each fails with `playwright._impl._errors.TimeoutError: Page.wait_for_selector: Timeout 8000ms exceeded.`, because the pane never opens, as measured live. The passing guards are the fixture shape and both `test_a_pane_never_opens_over_the_sign_in_page[phone|desktop]`.

**Step 3: Minimal implementation.** Make five edits in `T/static/task-panel.js`, then change the cache key. The anchors are as they read after Task 1.

Edit 2a (top of `aiuiSidebarRightEdge`: phones get edge 0 and a top offset under Open WebUI's top bar, and every other return gains `top: 0`). Replace exactly:

```js
    function aiuiSidebarRightEdge() {
      const sb = document.getElementById("sidebar");
      if (sb) {
        const r = sb.getBoundingClientRect();
        if (r.left <= 8 && r.width >= 30 && r.width <= 520 && r.height > 200) {
          return { edge: Math.max(0, Math.round(r.right)), el: sb };
        }
      }
```

with:

```js
    function aiuiSidebarRightEdge() {
      // Phones. Under 768px Open WebUI has no rail: its sidebar is a drawer
      // that slides over the page (measured live 2026-10-05: at 767px there
      // is no #sidebar and the hamburger, #sidebar-toggle-button, sits in a
      // 47px top bar; at 768px the 42px rail is back). Nothing holds the left
      // edge, so the pane takes the full width. It starts under that top bar
      // so the hamburger stays reachable: a phone has no Escape key, and
      // every link that would close the pane is underneath it.
      if (window.innerWidth < 768) {
        const btn = document.getElementById("sidebar-toggle-button");
        const bar = btn && (btn.closest("nav") || btn);
        const top = bar ? Math.max(0, Math.round(bar.getBoundingClientRect().bottom)) : 0;
        return { edge: 0, top: top, el: null };
      }
      const sb = document.getElementById("sidebar");
      if (sb) {
        const r = sb.getBoundingClientRect();
        if (r.left <= 8 && r.width >= 30 && r.width <= 520 && r.height > 200) {
          return { edge: Math.max(0, Math.round(r.right)), top: 0, el: sb };
        }
      }
```

Edit 2b (end of `aiuiSidebarRightEdge`). Replace exactly:

```js
      if (best) return { edge: Math.round(best.getBoundingClientRect().right), el: best };
      return { edge: 260, el: null };
    }
```

with:

```js
      if (best) return { edge: Math.round(best.getBoundingClientRect().right), top: 0, el: best };
      return { edge: 260, top: 0, el: null };
    }
```

Edit 2c (line 1442 today, the pane's initial `cssText` in `aiuiEmbedShell`). Replace exactly:

```js
        "position:fixed;top:0;right:0;bottom:0;left:" + meas.edge + "px;" +
```

with:

```js
        "position:fixed;top:" + meas.top + "px;right:0;bottom:0;left:" + meas.edge + "px;" +
```

Edit 2d (inside `reposition`, from Task 1). Replace exactly:

```js
        const m = aiuiSidebarRightEdge();
        wrap.style.left = m.edge + "px";
```

with:

```js
        const m = aiuiSidebarRightEdge();
        wrap.style.left = m.edge + "px";
        wrap.style.top = m.top + "px";
```

Edit 2e (lines 1673-1676 today, `appIsUp` in `scanSidebar`. It keeps the literals `const appIsUp` and `wanted && appIsUp` that `test_feature_pages_embed.py:170-175` pins. `onAuthRoute()` is the existing function at line 1016). Replace exactly:

```js
        // sidebar is the honest signal that the app rendered and the user is
        // in; until then the key just waits.
        const appIsUp = !!document.querySelector(
          'a[href="/"], a[href="/notes"], a[href="/calendar"], a[href="/workspace"]');
```

with:

```js
        // sidebar is the honest signal that the app rendered and the user is
        // in; until then the key just waits.
        //
        // Phones render no sidebar links at all (390px: one 47px top bar), so
        // on a phone /ai-agents never opened. The app's own
        // <main id="main-content"> is the phone signal: it appears once a
        // signed-in user's app has rendered, and never on /auth, not even
        // while a signed-out "/" or a dead token is being sent there (all
        // checked live, 2026-10-05). The skip link that points at it,
        // a[href="#main-content"], IS on /auth: match the element, not the
        // link.
        const appIsUp = !onAuthRoute() && !!document.querySelector(
          'a[href="/"], a[href="/notes"], a[href="/calendar"], a[href="/workspace"], ' +
          'main#main-content');
```

Edit 2f (`openwebui-overrides/index.html` line 300): change `task-panel.js?v=20261005-pane-edge` to `task-panel.js?v=20261005-phone-mount`.

**Step 4: Run it to verify it passes.**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_phone_shell.py -q
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_phone_shell.py tests/browser/test_pane_edge.py tests/browser/test_sidebar_injection.py tests/browser/test_pane_dismissal.py tests/browser/test_direct_feature_url.py tests/test_feature_pages_embed.py tests/test_nav_entries.py -q
```

Expected: `6 passed`, then `135 passed`.

Variant checks were done in scratch:
- With `top: 0` on phones, the full-width test and the hamburger test fail.
- With the skip-link selector `[href="#main-content"]` and no `onAuthRoute()`, both sign-in tests fail.

`onAuthRoute()` itself is belt and braces: the selector alone already keeps `/auth` shut, and no test isolates it.

**Step 5: Commit.**

```bash
git add mcp-servers/tasks/static/task-panel.js openwebui-overrides/index.html mcp-servers/tasks/tests/browser/shell_phone.html mcp-servers/tasks/tests/browser/test_phone_shell.py
git commit -m "Shell opens feature panes on phones, never over the sign-in page" -m "Phones render no sidebar links, so /ai-agents never opened at 390px. The signal is now main#main-content: it is present once a signed-in app renders, and absent on /auth even during the signed-out redirect (checked live). Under 768px the pane takes the full width below Open WebUI's top bar, so the hamburger stays reachable. Fixtures trimmed from the live phone home and /auth. Cache key bumped." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: `aiui:open-pane` listener, with the ask handed to the agents page after its frame loads

**Files:**
- Create: `T/tests/browser/test_open_pane_message.py`.
- Modify: `T/static/task-panel.js` in two places, both inside `injectSidebarBuildWebsiteEntry` so that `NAV_ENTRIES`, `AIUI_FRAMES`, `openAiuiEmbed` and `isAdmin` are in scope:
  - lines 1531-1533, the frame `load` handler in `openAiuiEmbed`;
  - an insertion before line 1544 (`// Mirrors the original App Builder cloning logic exactly, parameterized`).
- Modify: `openwebui-overrides/index.html` line 300 (the cache key again).
- Test: `T/tests/browser/test_open_pane_message.py` and everything above.

**Step 1: Write the failing test.** Create `T/tests/browser/test_open_pane_message.py`. The shell is the Task 1 fixture served over HTTP. `/tasks/*` is a stub page that records `aiui-agents-ask`, making the origin AND source checks the real agents page must make.

```python
"""A page in a pane can open another pane, and can hand AI Agents a question.

The agents page and the office had no way to reach another feature except
sending the whole window there, which loads a bare page outside Open WebUI.
The shell now listens for {type: "aiui:open-pane", path} and opens that pane
exactly as its sidebar entry would. With path "/ai-agents" and an `ask`, it
hands the question to the agents page once that page has loaded, as
{type: "aiui-agents-ask", ask}. The agents page only PREFILLS its composer
with it; nothing is ever sent for the person.

Only same-origin messages that come straight from one of the shell's own pane
frames count. Open WebUI renders chat artifacts in frames, and App Builder
shows app previews (/api/template-preview/, this same origin) in frames inside
its pane. Neither may drive the shell, and the last three tests pin that.

The shell is sidebar_collapsed_rail.html, the live v0.11.4 DOM. The pane
pages are stubs that record what they are handed, with the origin and source
checks the real agents page must make. These run over HTTP: file:// has an
opaque origin, and postMessage cannot target it.
"""
import functools
import http.server
import pathlib
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

HERE = pathlib.Path(__file__).parent
STATIC = HERE.parents[1] / "static"
OPEN_PANE = "[data-aiui-embed][data-open]"

STUB = b"""<!doctype html><html><head><meta charset="utf-8"><title>stub pane</title></head>
<body><script>
  window.__asks = [];
  window.addEventListener("message", function (e) {
    if (e.origin !== location.origin || e.source !== window.parent) return;
    if (e.data && e.data.type === "aiui-agents-ask") window.__asks.push(e.data.ask);
  });
</script></body></html>"""


class _Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib naming
        path = self.path.split("?")[0]
        if path == "/task-panel.js":
            body, ctype = (STATIC / "task-panel.js").read_bytes(), "application/javascript"
        elif path.startswith("/tasks/"):
            body, ctype = STUB, "text/html"
        else:
            body, ctype = (HERE / "sidebar_collapsed_rail.html").read_bytes(), "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # keep pytest output clean
        pass


@pytest.fixture(scope="module")
def server():
    srv = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_Handler, directory=str(HERE)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001 - browser binary absent
            pytest.skip(f"chromium not installed: {exc}")
        yield b
        b.close()


@pytest.fixture()
def page(browser, server):
    pg = browser.new_page(viewport={"width": 1920, "height": 1080})
    pg.goto(f"http://127.0.0.1:{server}/")
    pg.wait_for_selector("#sidebar [data-aiui-office]", timeout=8000)
    yield pg
    pg.close()


def _open(page, attr):
    page.locator(f"#sidebar [{attr}]").click()
    page.wait_for_selector(OPEN_PANE, timeout=4000)


def _frame(page, href):
    """The pane frame that loaded `href`, once it has loaded."""
    for _ in range(40):
        for f in page.frames:
            if f.url.split("?")[0].endswith(href):
                f.wait_for_function("() => Array.isArray(window.__asks)")
                return f
        page.wait_for_timeout(100)
    raise AssertionError(f"no frame for {href}: {[f.url for f in page.frames]}")


def _post(frame, msg, target="location.origin", to="parent"):
    frame.evaluate(f"m => {to}.postMessage(m, {target})", msg)


def _shown(page):
    return page.evaluate(
        "Array.from(document.querySelectorAll('[data-aiui-embed] iframe'))"
        ".filter(f => f.style.display !== 'none').map(f => f.getAttribute('src'))")


# --- what it is for -------------------------------------------------------

def test_a_pane_opens_another_pane(page):
    _open(page, "data-aiui-agents")
    _post(_frame(page, "/tasks/agents"), {"type": "aiui:open-pane", "path": "/graph"})
    page.wait_for_function("() => location.pathname === '/graph'", timeout=4000)
    shown = _shown(page)
    assert len(shown) == 1 and shown[0].startswith("/tasks/graph"), shown


def test_the_office_hands_the_agents_page_a_question(page):
    """The agents frame does not exist yet, so the question has to wait for
    it to load rather than be posted into a page with no listener."""
    _open(page, "data-aiui-office")
    _post(_frame(page, "/tasks/office"), {
        "type": "aiui:open-pane", "path": "/ai-agents",
        "ask": "  Ada, what changed today?  "})
    page.wait_for_function("() => location.pathname === '/ai-agents'", timeout=4000)
    agents = _frame(page, "/tasks/agents")
    agents.wait_for_function("() => window.__asks.length === 1", timeout=4000)
    assert agents.evaluate("() => window.__asks") == ["Ada, what changed today?"]


def test_an_agents_page_already_loaded_gets_the_question_too(page):
    _open(page, "data-aiui-agents")
    agents = _frame(page, "/tasks/agents")
    _open(page, "data-aiui-office")
    _post(_frame(page, "/tasks/office"), {
        "type": "aiui:open-pane", "path": "/ai-agents", "ask": "Mia, plan my week"})
    agents.wait_for_function("() => window.__asks.length === 1", timeout=4000)
    assert agents.evaluate("() => window.__asks") == ["Mia, plan my week"]
    assert page.locator("[data-aiui-embed] iframe[src^='/tasks/agents']").count() == 1, \
        "the agents page was rebuilt instead of reused"


# --- what it must ignore --------------------------------------------------

def test_a_question_goes_to_no_other_page(page):
    _open(page, "data-aiui-office")
    _post(_frame(page, "/tasks/office"),
          {"type": "aiui:open-pane", "path": "/graph", "ask": "hello"})
    page.wait_for_function("() => location.pathname === '/graph'", timeout=4000)
    graph = _frame(page, "/tasks/graph")
    page.wait_for_timeout(500)
    assert graph.evaluate("() => window.__asks") == []


def test_an_overlong_question_is_not_handed_over(page):
    _open(page, "data-aiui-office")
    _post(_frame(page, "/tasks/office"),
          {"type": "aiui:open-pane", "path": "/ai-agents", "ask": "x" * 2001})
    page.wait_for_function("() => location.pathname === '/ai-agents'", timeout=4000)
    agents = _frame(page, "/tasks/agents")
    page.wait_for_timeout(800)
    assert agents.evaluate("() => window.__asks") == []


@pytest.mark.parametrize("path", ["/admin/settings", "/tasks/graph", "graph", ""])
def test_a_path_that_is_not_a_nav_entry_is_ignored(page, path):
    _open(page, "data-aiui-agents")
    _post(_frame(page, "/tasks/agents"), {"type": "aiui:open-pane", "path": path})
    page.wait_for_timeout(500)
    assert page.evaluate("location.pathname") == "/ai-agents"
    assert [s.split("?")[0] for s in _shown(page)] == ["/tasks/agents"]


def test_a_same_origin_frame_that_is_not_a_pane_is_ignored(page):
    """Like a chat artifact: same origin, but not one of the shell's panes."""
    page.evaluate("""() => new Promise((done) => {
      const f = document.createElement("iframe");
      f.name = "stranger"; f.srcdoc = "<p>stranger</p>"; f.onload = done;
      document.body.appendChild(f);
    })""")
    # An about:srcdoc frame reports location.origin as "null" while really
    # sharing the parent's origin, so it names the parent's as the target.
    _post(page.frame(name="stranger"), {"type": "aiui:open-pane", "path": "/graph"},
          target="parent.location.origin")
    page.wait_for_timeout(500)
    assert page.locator(OPEN_PANE).count() == 0


def test_a_frame_inside_a_pane_is_ignored(page):
    """Like an app preview inside App Builder: same origin, nested in one of
    our panes, and still not allowed to drive the shell."""
    _open(page, "data-aiui-agents")
    _frame(page, "/tasks/agents").evaluate("""() => new Promise((done) => {
      const f = document.createElement("iframe");
      f.name = "nested"; f.srcdoc = "<p>nested</p>"; f.onload = done;
      document.body.appendChild(f);
    })""")
    _post(page.frame(name="nested"),
          {"type": "aiui:open-pane", "path": "/graph"},
          target="top.location.origin", to="top")
    page.wait_for_timeout(500)
    assert page.evaluate("location.pathname") == "/ai-agents"


def test_another_origin_is_ignored_even_in_a_pane_frame(page, server):
    """The pane frame itself, navigated to a different origin (localhost is
    not 127.0.0.1 to a browser)."""
    _open(page, "data-aiui-agents")
    page.evaluate(
        "port => { document.querySelector(\"[data-aiui-embed] iframe[src^='/tasks/agents']\")"
        ".src = 'http://localhost:' + port + '/tasks/agents'; }", server)
    page.wait_for_timeout(800)
    other = next(f for f in page.frames if f.url.startswith("http://localhost"))
    _post(other, {"type": "aiui:open-pane", "path": "/graph"}, target="'*'")
    page.wait_for_timeout(500)
    assert page.evaluate("location.pathname") == "/ai-agents"
```

**Step 2: Run it to verify it fails.**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_open_pane_message.py -q
```

Expected: `5 failed, 7 passed`. Today the message is ignored, so all five fail with `TimeoutError ... wait_for_function: Timeout 4000ms exceeded`:
- `test_a_pane_opens_another_pane`
- `test_the_office_hands_the_agents_page_a_question`
- `test_an_agents_page_already_loaded_gets_the_question_too`
- `test_a_question_goes_to_no_other_page`
- `test_an_overlong_question_is_not_handed_over`

The 7 that pass are guards. They can only be proven by weakening the listener, which was done in scratch (see Step 4).

**Step 3: Minimal implementation.**

Edit 3a (lines 1531-1533: remember that a pane frame has loaded). Replace exactly:

```js
        frame.addEventListener("load", () => {
          aiuiFrameVisible(frame, wrap.getAttribute("data-open") === cfg.href);
        });
```

with:

```js
        frame.addEventListener("load", () => {
          frame.__aiuiLoaded = true;
          aiuiFrameVisible(frame, wrap.getAttribute("data-open") === cfg.href);
        });
```

Edit 3b (insert before line 1544. The anchor line is kept as the last line). Replace exactly:

```js
    // Mirrors the original App Builder cloning logic exactly, parameterized
```

with:

```js
    // --- aiui:open-pane --------------------------------------------------
    // A page inside a pane asks the shell to open another pane, exactly as a
    // click on that sidebar entry would: the agents page opening the Graph,
    // the office opening AI Agents with a question. Without this they could
    // only send the whole window to a bare page outside Open WebUI.
    //
    // Accepted only from this origin AND straight from one of our own pane
    // frames. Open WebUI renders chat artifacts in frames, and App Builder
    // shows app previews in frames inside its pane (projects.html loads
    // /api/template-preview/ from this same origin); neither may drive the
    // shell. The path must be the urlPath of a known entry. Anything else is
    // ignored.
    //
    // An `ask` goes only to the AI Agents page, only once its frame has
    // loaded, and only PREFILLS its composer. Nothing is ever sent for the
    // person: a turn costs money and can run tools.
    const AIUI_ASK_MAX = 2000;

    function aiuiIsPaneFrame(source) {
      return !!source && Object.keys(AIUI_FRAMES).some(
        (k) => AIUI_FRAMES[k].contentWindow === source);
    }

    function aiuiHandAskToAgents(cfg, ask) {
      const frame = AIUI_FRAMES[cfg.href];
      if (!frame) return;
      const hand = () => {
        try {
          frame.contentWindow.postMessage(
            { type: "aiui-agents-ask", ask: ask }, location.origin);
        } catch (e) { /* frame gone: the question is dropped, never sent */ }
      };
      if (frame.__aiuiLoaded) hand();
      else frame.addEventListener("load", hand, { once: true });
    }

    window.addEventListener("message", async (ev) => {
      if (ev.origin !== location.origin) return;
      const d = ev.data;
      if (!d || d.type !== "aiui:open-pane" || typeof d.path !== "string") return;
      if (!aiuiIsPaneFrame(ev.source)) return;
      const cfg = NAV_ENTRIES.find((c) => c.embed && c.urlPath === d.path);
      if (!cfg) return;
      if (!cfg.allUsers && !(await isAdmin())) return;
      openAiuiEmbed(cfg);
      if (d.path === "/ai-agents" && typeof d.ask === "string") {
        const ask = d.ask.trim();
        if (ask && ask.length <= AIUI_ASK_MAX) aiuiHandAskToAgents(cfg, ask);
      }
    });

    // Mirrors the original App Builder cloning logic exactly, parameterized
```

Edit 3c (`openwebui-overrides/index.html` line 300): change `task-panel.js?v=20261005-phone-mount` to `task-panel.js?v=20261005-open-pane`.

**Step 4: Run it to verify it passes.**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_open_pane_message.py -q
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_open_pane_message.py tests/browser/test_phone_shell.py tests/browser/test_pane_edge.py tests/browser/test_sidebar_injection.py tests/browser/test_pane_dismissal.py tests/browser/test_direct_feature_url.py tests/test_feature_pages_embed.py tests/test_nav_entries.py -q
node --check mcp-servers/tasks/static/task-panel.js
```

Expected: `12 passed`, then `147 passed` (ran 3 times with no flaky failures), and `node --check` prints nothing.

The guards were proven in scratch against weakened copies:
- Without the source check, the two frame tests fail.
- Without the origin check, `test_another_origin_is_ignored_even_in_a_pane_frame` fails.
- Without the 2000-character cap, the overlong test fails.
- With the ask forwarded for any path, `test_a_question_goes_to_no_other_page` fails.

**Step 5: Commit.**

```bash
git add mcp-servers/tasks/static/task-panel.js openwebui-overrides/index.html mcp-servers/tasks/tests/browser/test_open_pane_message.py
git commit -m "Shell opens a pane on request from a pane page, and hands AI Agents a question" -m "An aiui:open-pane message from one of the shell's own pane frames (same origin, direct frame only) opens a known nav entry exactly as its sidebar click would. With path /ai-agents and an ask of at most 2000 characters, the shell posts aiui-agents-ask to the agents frame once it has loaded. The page only prefills; nothing is sent. Cache key bumped." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### After the three commits (not part of these tasks; listed so nobody assumes they happened)

1. Deploying is a separate step.
   - `task-panel.js` is baked into the tasks image: scp the file, then run `docker compose -f docker-compose.unified.yml up -d --build tasks`.
   - `openwebui-overrides/index.html` is a single-file bind mount into open-webui: scp it to `/tmp`, `mv` it into place, and `--force-recreate` open-webui (the inode lesson).
   - Before deploying, fetch and check divergence with `git branch -r --contains`. After deploying, verify the served bytes and the `?v=` key over HTTPS.
2. The real agents page still has to add its `aiui-agents-ask` listener (another Phase 0 task). When both have landed, add one integration test that loads the real `agents.html` in the pane instead of the stub.


**Open questions:**
- Protocol detail to align with the other drafters: an ask longer than 2000 characters after trimming is NOT forwarded (the pane still opens). It is not truncated, because a cut-off question is one the person never wrote. Confirm, or switch to truncation in Edit 3b and the overlong test.
- The shell listener adds a source check that the protocol text does not name: messages count only when they come straight from a pane iframe in AIUI_FRAMES. This is stricter than 'origin only', and it is what blocks chat artifacts and App Builder previews. Consequence for the office drafter: when the office is hosted inside the agents page it must message its host. A post to window.top from that nested frame is ignored. The protocol already says this, but the nested case must not fall back to window.top before the handshake.
- Deviation from the design doc, needs a nod: on phones (under 768px) the pane starts under Open WebUI's 47px top bar instead of covering the full screen. Without that, a phone user cannot leave the pane: there is no Escape key, the outside links are underneath it, and the back button does not close it. A fixed top:0 pane would be a trap. The design says only 'edge 0'.
- Deviation from the brief: #sidebar is checked FIRST, and accepted at 30-520px wide and taller than 200px, rather than 'only when no 120-520px column qualifies' with height > 400. The live evidence is that after a runtime collapse the old walk qualifies a 245px column inside the closed 0px panel (old = 245 beside a 42px rail).
- The desktop fallback stays 260 when no sidebar can be found at 768px and wider, so a missed measurement never covers the nav. Edge 0 applies only to phones, defined as innerWidth < 768 (measured live: 767 has no rail, 768 has the rail). If Open WebUI moves its breakpoint, this constant must follow.
- Not fixed (pre-existing, separate task): after a runtime collapse our entries stay in the closed 0px panel. The injector sees them as present and never adds them to the new rail, so the collapsed rail shows no AI Agents or Graph icons until a reload. Verified live (toggle_probe: 'in-panel' after close).
- Unverified: on phone routes other than '/' (for example /notes), whether #sidebar-toggle-button sits in a <nav>. If it does not, top falls back to the button's bottom or 0. Only '/' (where the rescue lands) was captured.
- Unverified: whether dragging the open sidebar's col-resize handle changes its width. The handle exists live, but a Playwright drag left the width at 245. The ResizeObserver-follow would cover a resize if it happens.
- The ask hand-off is tested against a stub agents page. The real agents.html still needs its aiui-agents-ask listener (another drafter). Once both land, add an integration test with the real page.
- Cost of the scanSidebar hook: while a pane is open, one getElementById plus getBoundingClientRect per animation frame that has DOM changes (rAF-throttled). This is negligible, but it does run during chat streaming under an open pane.
- Deploy notes for whoever ships this:
- task-panel.js is baked into the tasks image, so scp it before running up -d --build tasks.
- index.html is a single-file bind mount into open-webui and needs --force-recreate.
- Run a branch-divergence check first.
- Live bytes match the repo today.

# Draft: P0-2 office: links stay in app, one hue, a11y

# P0-2 Office: links stay in the app, one hue per agent, readable states

Context for an engineer with no history:
- `mcp-servers/tasks/static/office.html` is the Agent Office floor. It runs in two places:
  1. Hosted: inside the agents page dock (`/tasks/office?embed=1`). The `aiui-office-host` handshake sets `HOSTED = true`.
  2. Standalone: as its own shell pane at `/ai-agents/office`.
- Today every link is `target=_top`. Only `a.who-chat` and `a.chat-with` are intercepted, and only when hosted (office.html:1526-1547). So The Brain, Call a team meeting, the skill links and Edit agent each load a bare page over Open WebUI.
- Shared protocol, used exactly:
  1. The hosted office sends `aiui-office-ask`, `aiui-office-open {path}` or `aiui-office-edit {id}` to the agents page.
  2. The agents page forwards `aiui:open-pane {path}` to its parent, but only when `window.parent !== window`.
  3. The standalone office pane inside the shell sends `aiui:open-pane {path, ask?}` to `window.top`.
- "Inside the shell" means more than `window.top !== window`. It means `window.top.__aiuiTaskPanelLoaded === true`, the flag task-panel.js sets on its first lines (11-12).
  - Why: the existing test `test_a_frame_that_does_not_host_the_office_still_follows_the_link` frames the office in a plain `/bare` page and requires the link to be followed there.
- Run every command from `C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks`.
- The prefix `DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody` makes DB-tier tests fail fast. These office tests do not use the DB.
- Baseline measured today: test_office_page.py 72 passed, test_office_inline.py 31 passed, test_office_live.py 5 passed (108 in 94 s).
- Line numbers below are as they are TODAY. Tasks 2 and 3 run after Task 1, so lines will have shifted by then. Always find the place by the quoted anchor text; each anchor appears exactly once.

---

### Task 1: Office links stay inside the app (office.html click routing, agents.html host handlers)

**Files:**
- Modify: `mcp-servers/tasks/static/office.html`:
  - line 1026: "Open the chat" link
  - lines 1056-1057: skill link
  - line 1132: Edit agent link
  - lines 1526-1547: click handler
- Modify: `mcp-servers/tasks/static/agents.html`, lines 3133-3146: the office message listener's `aiui-office-ask` branch and the closing `})();` of the office IIFE.
- Test: `mcp-servers/tasks/tests/browser/test_office_inline.py`:
  - add two server branches at lines 69-77
  - add module constants before line 49
  - append tests at the end of the file (today 603 lines)

**Step 1: Write the failing test**

1a. In `tests/browser/test_office_inline.py`, insert the block below immediately ABOVE the line `# The page's own stylesheet has to be served, not stubbed. An earlier version` (line 49):

```python
# Stand-ins for the Open WebUI document, holding only what the contract needs:
# a recorder for the one message the shell answers, aiui:open-pane. The office
# pane variant also loads the REAL task-panel.js, because the office decides
# it is inside the shell by the flag that file sets on the top window, and a
# flag written here by hand would only prove what this fixture imagined.
_RECORD = (b'<script>window.__panes = [];'
           b'window.addEventListener("message", function (ev) {'
           b' if (ev.data && ev.data.type === "aiui:open-pane")'
           b'  window.__panes.push({ data: ev.data, origin: ev.origin });'
           b'});</script>')
SHELL_AROUND_OFFICE = (
    b'<!doctype html><title>shell</title>' + _RECORD +
    b'<script src="/tasks/static/task-panel.js"></script>'
    b'<iframe id="pane" src="/tasks/office" '
    b'style="width:100%;height:1400px;border:0"></iframe>')
SHELL_AROUND_AGENTS = (
    b'<!doctype html><title>shell</title>' + _RECORD +
    b'<iframe id="pane" src="/agents.html" '
    b'style="width:1500px;height:1000px;border:0"></iframe>')


```

1b. In the `server` fixture's `Handler.do_GET`, change these old lines (73-76):

```python
                body = (b'<!doctype html><title>bare</title>'
                        b'<iframe src="/tasks/office" '
                        b'style="width:100%;height:1400px;border:0"></iframe>')
            else:
```

to these new lines:

```python
                body = (b'<!doctype html><title>bare</title>'
                        b'<iframe src="/tasks/office" '
                        b'style="width:100%;height:1400px;border:0"></iframe>')
            elif path.startswith("/shell-agents"):
                body = SHELL_AROUND_AGENTS
            elif path.startswith("/shell"):
                body = SHELL_AROUND_OFFICE
            else:
```

The order matters: `/shell-agents` is tested before `/shell`.

1c. Append to the END of `tests/browser/test_office_inline.py`:

```python


# --- nothing in the office loads a bare page --------------------------------
#
# Design 2026-10-05, finding 5: every office link is target=_top and only the
# Chat pills were intercepted, so The Brain, Call a team meeting, the skill
# links and Edit agent each replaced the whole Open WebUI window with a bare
# page. Hosted by the agents page they are now messages to it. Framed straight
# into the shell (the Agent Office pane) they are aiui:open-pane messages to
# the shell. Anywhere else they are still followed, which
# test_a_frame_that_does_not_host_the_office_still_follows_the_link pins.

SKILLED = [
    {"id": "agent-iris-a103", "name": "Iris",
     "meta": {"role": "Drive librarian", "toolIds": ["gdrive"],
              "skillIds": ["find-my-file"]},
     "params": {}, "user_id": "me", "created_at": 1, "updated_at": 1},
    OFFICE_AGENTS[1],
]
SKILL_CATALOGUE = [{"name": "find-my-file", "description": "Find a file.",
                    "tools": ["gdrive"], "tags": ["files"]}]


def _as_owner(browser, server, agents=None, url="/agents.html"):
    """The agents page signed in as the owner of the office's agents.

    The default fixture answers /api/v1/auths/ with no id, which the page
    reads as no identity, so it has no agents of its own and nothing to edit.
    """
    roster = agents or OFFICE_AGENTS
    ctx = browser.new_context(viewport={"width": 1500, "height": 1000})
    pg = ctx.new_page()
    pg.set_default_timeout(8000)

    def route(r):
        u = r.request.url
        if "/api/v1/auths/" in u:
            body = {"id": "me", "email": "me@example.test"}
        elif "/models/list" in u:
            body = {"items": roster, "total": len(roster)}
        elif "/agents/activity" in u:
            body = {"activity": {}, "handoffs": []}
        elif "/agents/stats" in u:
            body = {"stats": {}}
        elif "/agents/skills" in u:
            body = {"skills": SKILL_CATALOGUE}
        else:
            body = {"items": [], "total": 0}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.route("**/tasks/agents/chat/**", route)
    pg.goto("http://127.0.0.1:%d%s" % (server.server_address[1], url))
    return ctx, pg


def test_the_embedded_office_does_not_offer_to_open_the_page_it_is_in(page):
    """"Open the chat" points at /tasks/agents, which is the page around the
    floor. Followed, it reloaded the page; it has nothing to do here."""
    frame = page.frame_locator("#office-body iframe")
    frame.locator(".floor-bar").wait_for()
    said = frame.locator(".floor-bar a").all_inner_texts()
    assert "Open the chat" not in said, said
    assert any("team meeting" in s for s in said), said


def test_the_meeting_button_fills_the_room_in_place(page):
    """Call a team meeting hands over "everyone answer: ". It is a question
    for the room, so a private conversation that happens to be open is left
    for the room first: in Iris's own thread only Iris would hear it."""
    page.evaluate("() => window.aiuiTalkTo('agent-iris-a103', 'Iris')")
    page.wait_for_timeout(200)
    frame = page.frame_locator("#office-body iframe")
    meeting = frame.locator(".floor-bar a.btn").first
    meeting.wait_for()
    page.evaluate("() => { window.__stillHere = true; }")
    meeting.click()
    page.wait_for_timeout(400)
    assert page.evaluate("() => window.__stillHere === true"), "the page reloaded"
    assert page.locator("#ap-agent").input_value() == ""
    assert page.locator(".ap-composer input[name=message]").input_value(
        ) == "everyone answer: "


def test_a_skill_opens_that_agents_conversation_with_the_question(browser, server):
    """The skill link says "Iris, find my file". It opens Iris's own
    conversation and leaves the question in the box, unsent."""
    ctx, pg = _as_owner(browser, server, agents=SKILLED)
    try:
        frame = pg.frame_locator("#office-body iframe")
        frame.locator('.who[data-id="agent-iris-a103"]').click()
        skill = frame.locator("#side a.skill").first
        skill.wait_for()
        pg.evaluate("() => { window.__stillHere = true; }")
        skill.click()
        pg.wait_for_timeout(400)
        assert pg.evaluate("() => window.__stillHere === true"), "the page reloaded"
        assert pg.locator("#ap-agent").input_value() == "agent-iris-a103"
        assert pg.locator(".ap-composer input[name=message]").input_value(
            ) == "find my file"
    finally:
        ctx.close()


def test_edit_agent_in_the_office_opens_the_form_on_this_page(browser, server):
    """Edit agent linked to /tasks/agents, which reloaded this page and
    opened nothing. The page around the floor has the form already."""
    ctx, pg = _as_owner(browser, server)
    try:
        pg.wait_for_selector('#my-agents .card[data-agent-id="agent-iris-a103"]',
                             state="attached")
        frame = pg.frame_locator("#office-body iframe")
        frame.locator('.who[data-id="agent-iris-a103"]').click()
        edit = frame.locator("#side a", has_text="Edit agent")
        edit.wait_for()
        pg.evaluate("() => { window.__stillHere = true; }")
        edit.click()
        pg.wait_for_timeout(400)
        assert pg.evaluate("() => window.__stillHere === true"), "the page reloaded"
        assert pg.locator("#agent-overlay").is_visible()
        assert pg.locator("#form-title").inner_text() == "Edit agent"
        assert pg.locator("#agent-name").input_value() == "Iris"
    finally:
        ctx.close()


def test_the_brain_opens_the_graph_pane_and_leaves_the_page_alone(browser, server):
    """Inside the shell the agents page asks the shell for its Graph pane,
    the same pane a click on the sidebar entry opens. The shell document is
    not replaced and the agents page stays where it is."""
    ctx, pg = _as_owner(browser, server, url="/shell-agents")
    try:
        office = pg.frame_locator("#pane").frame_locator("#office-body iframe")
        office.locator(".brain a").wait_for()
        pg.wait_for_timeout(300)
        office.locator(".brain a").click()
        pg.wait_for_timeout(400)
        origin = "http://127.0.0.1:%d" % server.server_address[1]
        got = pg.evaluate("() => window.__panes || null")
        assert got == [{"data": {"type": "aiui:open-pane", "path": "/graph"},
                        "origin": origin}], got
        assert pg.locator("#pane").evaluate(
            "f => f.contentWindow.location.pathname") == "/agents.html"
    finally:
        ctx.close()


def test_in_the_shell_a_chat_pill_asks_for_the_agents_pane(page, server):
    """The Agent Office pane on its own, inside the shell. Nobody hosts it,
    so its Chat pill asks the shell to open AI Agents with the question."""
    page.goto("http://127.0.0.1:%d/shell" % server.server_address[1])
    office = page.frame_locator("#pane")
    office.locator('.who-chat[data-id="agent-iris-a103"]').wait_for()
    assert page.evaluate("() => window.__aiuiTaskPanelLoaded === true")
    # Standalone, so the floor still offers the chat.
    assert office.locator(".floor-bar a", has_text="Open the chat").count() == 1
    page.evaluate("() => { window.__stillHere = true; }")
    office.locator('.who-chat[data-id="agent-iris-a103"]').click()
    page.wait_for_timeout(400)
    assert page.evaluate("() => window.__stillHere === true"), "the shell was replaced"
    origin = "http://127.0.0.1:%d" % server.server_address[1]
    assert page.evaluate("() => window.__panes") == [
        {"data": {"type": "aiui:open-pane", "path": "/ai-agents",
                  "ask": "Iris, "}, "origin": origin}]


def test_in_the_shell_the_brain_asks_for_the_graph_pane(page, server):
    page.goto("http://127.0.0.1:%d/shell" % server.server_address[1])
    office = page.frame_locator("#pane")
    office.locator(".brain a").wait_for()
    page.evaluate("() => { window.__stillHere = true; }")
    office.locator(".brain a").click()
    page.wait_for_timeout(400)
    assert page.evaluate("() => window.__stillHere === true"), "the shell was replaced"
    origin = "http://127.0.0.1:%d" % server.server_address[1]
    assert page.evaluate("() => window.__panes") == [
        {"data": {"type": "aiui:open-pane", "path": "/graph"}, "origin": origin}]


def test_on_its_own_the_agents_page_still_opens_the_graph(page):
    """Guard, passes before and after: /tasks/agents with no shell around it
    has no pane to open, so The Brain still reaches the graph page."""
    frame = page.frame_locator("#office-body iframe")
    frame.locator(".brain a").wait_for()
    page.wait_for_timeout(300)
    frame.locator(".brain a").click()
    page.wait_for_url("**/tasks/graph")
```

**Step 2: Run it to verify it fails**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_office_inline.py -q -k "embedded_office_does_not or meeting_button_fills or skill_opens or edit_agent_in or brain_opens or in_the_shell or on_its_own"
```

Expected: `7 failed, 1 passed`. Only the guard passes. Measured failure messages:
- `test_the_embedded_office_does_not_offer_to_open_the_page_it_is_in`: `AssertionError: ['Call a team meeting', 'Open the chat']`
- meeting, skill and edit tests: `AssertionError: the page reloaded`. The Page url is `/tasks/agents`.
- `test_the_brain_opens_the_graph_pane_and_leaves_the_page_alone`: `assert None == [{'data': {'path': '/graph', 'type': 'aiui:open-pane'}, ...}]`
- the two `in_the_shell` tests: `AssertionError: the shell was replaced`. The url is `/tasks/agents` and `/tasks/graph` respectively.

**Step 3: Minimal implementation**

3a. In `static/office.html`, change the "Open the chat" line (1026). Old:

```js
        '<a class="btn ghost" target="_top" href="/tasks/agents">Open the chat</a>' +
      '</span></div>';
```

New:

```js
        // Not in the card on the agents page: the chat it opens is the page
        // around this floor, so following it only reloaded that page.
        (document.documentElement.classList.contains("embed") ? "" :
          '<a class="btn ghost" target="_top" href="/tasks/agents">Open the chat</a>') +
      '</span></div>';
```

3b. In `static/office.html`, change the skill link (1056). Old:

```js
        return '<a class="tag skill" target="_top" href="/tasks/agents?ask=' +
```

New:

```js
        // The agent's id rides along, so the page around a hosted floor can
        // open this agent's own conversation instead of asking the room.
        return '<a class="tag skill" target="_top" data-id="' + esc(m.id) +
          '" href="/tasks/agents?ask=' +
```

3c. In `static/office.html`, change the Edit agent link (1132). Old:

```js
      '<a class="btn ghost" target="_top" href="/tasks/agents">Edit agent</a>' +
```

New:

```js
      '<a class="btn ghost edit-agent" target="_top" data-id="' + esc(m.id) +
        '" href="/tasks/agents">Edit agent</a>' +
```

3d. In `static/office.html`, replace the whole click handler (lines 1526-1547). It starts with `  document.addEventListener("click", function (ev) {` followed by `    if (!HOSTED) return;`, and ends with the `  });` just before `  document.getElementById("side").addEventListener("click", ...`.

Old:

```js
  document.addEventListener("click", function (ev) {
    if (!HOSTED) return;
    var a = ev.target.closest("a.who-chat, a.chat-with");
    if (!a) return;
    var ask = "";
    try { ask = decodeURIComponent((a.href.split("ask=")[1] || "")); }
    catch (e) { return; }                  // malformed: let the link do its job
    if (!ask) return;
    ev.preventDefault();
    // Same origin only. The office and the page around it are served by the
    // same host, and a wildcard would hand whatever is typed to any parent
    // that framed this page.
    //
    // The agent's id goes with it. The page around us opens that agent's own
    // conversation rather than putting the question to the room: "Chat" on a
    // robot means a private word with them, not a message everybody reads.
    window.parent.postMessage({
      type: "aiui-office-ask", ask: ask,
      agent: a.getAttribute("data-id") || "",
      name: (ask.split(",")[0] || "").trim()
    }, window.location.origin);
  });
```

New:

```js
  //: Each page this office links to, by the shell's own nav path for it
  //: (task-panel.js NAV_ENTRIES urlPath). A link to anything else is left
  //: alone wherever the office is.
  var PANE_OF = { "/tasks/agents": "/ai-agents", "/tasks/graph": "/graph",
                  "/tasks/office": "/ai-agents/office" };

  //: The Open WebUI shell, not merely some page that frames this one.
  //: task-panel.js sets this flag on the top window before it does anything
  //: else. A page that frames the office without it has nobody to answer
  //: aiui:open-pane, so there a link has to be followed.
  function inShell() {
    if (window.top === window) return false;
    try { return window.top.__aiuiTaskPanelLoaded === true; }
    catch (e) { return false; }            // a top we cannot read is not ours
  }

  // Every link here used to load a bare page over the whole of Open WebUI,
  // except the Chat pills. Now:
  //   hosted by the agents page: a message to it, which acts in place;
  //   the Agent Office pane in the shell: aiui:open-pane to the shell, which
  //     opens that pane exactly as its sidebar entry would;
  //   anywhere else: the link is followed, target=_top as written.
  // Nothing is ever sent. An ask only fills the composer.
  document.addEventListener("click", function (ev) {
    // A new tab or window was asked for: that is the link's job.
    if (ev.defaultPrevented || ev.button !== 0 ||
        ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
    var a = ev.target.closest("a[href]");
    if (!a) return;
    var path = PANE_OF[a.pathname];
    if (!path) return;
    var shell = !HOSTED && inShell();
    if (!HOSTED && !shell) return;
    var ask = "";
    var raw = a.href.split("ask=")[1];
    if (raw != null) {
      try { ask = decodeURIComponent(raw); }
      catch (e) { return; }                // malformed: let the link do its job
    }
    var id = a.getAttribute("data-id") || "";
    ev.preventDefault();
    // Same origin only, both ways. The office, the agents page and the shell
    // are served by the same host, and a wildcard would hand whatever is
    // typed to any page that framed this one.
    var origin = window.location.origin;
    if (shell) {
      var open = { type: "aiui:open-pane", path: path };
      if (ask) open.ask = ask;
      window.top.postMessage(open, origin);
      return;
    }
    if (ask) {
      // The agent's id goes with it. The page around us opens that agent's
      // own conversation rather than putting the question to the room:
      // "Chat" on a robot means a private word with them. Without an id
      // (the meeting button) it is a question for the room.
      window.parent.postMessage({
        type: "aiui-office-ask", ask: ask, agent: id,
        name: (ask.split(",")[0] || "").trim()
      }, origin);
    } else if (id && a.classList.contains("edit-agent")) {
      window.parent.postMessage({ type: "aiui-office-edit", id: id }, origin);
    } else {
      window.parent.postMessage({ type: "aiui-office-open", path: path }, origin);
    }
  });
```

Leave the `HOSTED` listener and the `aiui-office-ready` post above it unchanged. The incoming listener already checks `ev.origin === location.origin` and `ev.source === window.parent`.

3e. In `static/agents.html`, change the office IIFE's listener. Lines 3133-3146 run from the anchor `if (!msg || msg.type !== "aiui-office-ask" || typeof msg.ask !== "string") return;` to the `  })();` that closes the office IIFE, just before `</script>`. Its origin and source checks at 3117-3119 stay as they are.

Old:

```js
      if (!msg || msg.type !== "aiui-office-ask" || typeof msg.ask !== "string") return;
      // Clicking Chat on a robot opens that agent's own conversation. It used
      // to type "Ada, " into the shared room, which routed the answer to Ada
      // but left the words where every other agent read them.
      if (msg.agent && typeof window.aiuiTalkTo === "function") {
        window.aiuiTalkTo(msg.agent, msg.name || msg.agent);
        return;
      }
      var box = document.querySelector(".ap-composer input[name=message]");
      if (!box) return;
      box.value = msg.ask;
      box.focus();
    });
  })();
```

New. It contains no em or en dashes: `test_agents_page_access.py::test_no_em_dashes_in_the_new_copy` enforces that.

```js
      if (msg && msg.type === "aiui-office-open") { openPane(msg.path); return; }
      if (msg && msg.type === "aiui-office-edit") { editAgent(msg.id); return; }
      if (!msg || msg.type !== "aiui-office-ask" || typeof msg.ask !== "string") return;
      var talk = typeof window.aiuiTalkTo === "function" ? window.aiuiTalkTo : null;
      // Clicking Chat on a robot opens that agent's own conversation. It used
      // to type "Ada, " into the shared room, which routed the answer to Ada
      // but left the words where every other agent read them.
      if (msg.agent && typeof msg.agent === "string" && talk) {
        var name = typeof msg.name === "string" ? msg.name : "";
        talk(msg.agent, name || msg.agent);
        // A skill link says "Iris, find my file". In Iris's own conversation
        // her name is not needed, so only the question goes in the box. A
        // Chat pill says just "Iris, " and leaves the box empty.
        var rest = msg.ask;
        if (name && rest.indexOf(name + ",") === 0) rest = rest.slice(name.length + 1);
        rest = rest.trim();
        if (rest) prefill(rest);
        return;
      }
      // No agent: a question for the room, such as the meeting button's
      // "everyone answer: ". Asked in a private conversation only that one
      // agent would hear it, so the room comes back first.
      var field = document.getElementById("ap-agent");
      if (talk && field && field.value) talk("", "");
      prefill(msg.ask);
    });

    function prefill(text) {
      var box = document.querySelector(".ap-composer input[name=message]");
      if (!box) return;
      box.value = text;
      box.focus();
    }

    // Panes the floor may ask for, by the shell's own nav paths
    // (task-panel.js NAV_ENTRIES urlPath), and the bare page each one is.
    var PANES = { "/graph": "/tasks/graph", "/ai-agents/office": "/tasks/office",
                  "/ai-agents": "/tasks/agents" };

    // The Brain and the other links that leave this page. Inside the shell
    // the shell opens that pane, exactly as its sidebar entry does, so the
    // whole window is never replaced by a bare page. On its own, with no
    // shell around it, this page has no panes, so it goes to the page itself.
    function openPane(path) {
      if (typeof path !== "string" ||
          !Object.prototype.hasOwnProperty.call(PANES, path)) return;
      if (window.parent !== window) {
        window.parent.postMessage({ type: "aiui:open-pane", path: path },
                                  window.location.origin);
        return;
      }
      if (path !== "/ai-agents") window.location.assign(PANES[path]);
    }

    // Edit agent on the floor opens this page's own form. Yours only, the
    // same rule the cards follow: nobody else's agent has an Edit button
    // here, and the server would refuse the save.
    function editAgent(id) {
      var page = window.__aiuiAgents;
      if (!page || !page.state || typeof id !== "string" || !id) return;
      var agent = page.state.agents.filter(function (m) { return m.id === id; })[0];
      if (!agent || agent.user_id !== page.state.me) return;
      page.openForm(agent);
    }
  })();
```

The edit path reuses the existing card Edit flow: `openForm(agent)` at agents.html:2322, which is the function `data-act="edit"` calls at 2779. It is already exposed on `window.__aiuiAgents` at 2790-2793.

**Step 4: Run it to verify it passes**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_office_inline.py tests/browser/test_office_page.py tests/browser/test_office_live.py tests/test_agents_page_access.py -q
```

Expected, measured on a scratch copy:
- test_office_inline.py: 39 passed (31 old, 7 new, 1 guard)
- test_office_page.py: 72 passed
- test_office_live.py: 5 passed
- test_agents_page_access.py: 9 passed (the no-dash rule)

Also run the agents-page suites (measured: 386 passed before and after, about 6 minutes):

```bash
DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_agents_ask_prefill.py tests/browser/test_agents_page.py tests/browser/test_agents_page_fit.py tests/browser/test_agents_tools_live.py tests/browser/test_embedded_page_chrome.py tests/test_agent_chat_endpoint.py tests/test_agent_chat_page.py tests/test_agent_chat_render.py tests/test_agent_free_fallback.py tests/test_agent_name_header.py tests/test_agents_page_memory.py tests/test_feature_pages_embed.py -q
```

**Step 5: Commit**

```bash
git add mcp-servers/tasks/static/office.html mcp-servers/tasks/static/agents.html mcp-servers/tasks/tests/browser/test_office_inline.py
git commit -m "Office links stay inside the app

The Brain, Call a team meeting, the skill links and Edit agent each loaded a
bare page over the whole of Open WebUI. Hosted by the agents page they are now
messages it acts on in place: the meeting fills the room, a skill opens that
agent's conversation with the question in the box, Edit agent opens the form,
and The Brain asks the shell for its Graph pane. The standalone Agent Office
pane asks the shell with aiui:open-pane. Anywhere else the link is still
followed. Open the chat is gone from the card, where it reloaded its own page.
Nothing is ever sent.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: One hue per agent: robots default to the agent's name hue

**Files:**
- Modify: `mcp-servers/tasks/static/office.html`:
  - lines 553-569: comment, `paletteOf` and the first line of `pickColour`
  - lines 1109-1112: the swatch map in `drawSide`
- Test: `mcp-servers/tasks/tests/browser/test_office_page.py`:
  - lines 12-22: imports
  - append at the end of the file (today 1057 lines)

**Step 1: Write the failing test**

1a. In `tests/browser/test_office_page.py`, change the import block at lines 12-22. Old:

```python
import http.server
import json
import pathlib
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

STATIC = pathlib.Path(__file__).resolve().parents[2] / "static"
```

New. This follows the import pattern in `tests/browser/test_agent_chat_turn_targets.py:33-36`:

```python
import http.server
import json
import pathlib
import re
import sys
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

STATIC = pathlib.Path(__file__).resolve().parents[2] / "static"
sys.path.insert(0, str(STATIC.parent))
# The hue the cards and the chat thread give an agent. Read from the producer
# rather than re-implemented here, so the office is held to the real thing.
import agent_chat_render as render                        # noqa: E402
```

1b. Append to the END of `tests/browser/test_office_page.py`:

```python


# --- one colour per agent, everywhere ---------------------------------------
# DESIGN.md, the One Hue Per Agent Rule. The office picked one of its own six
# palettes from a hash of the agent's id, so Ada was green on her card and
# purple as a robot. Cards and the chat thread take the hue from the agent's
# NAME (agents.html avatarHue, ported as agent_chat_render._hue), and a robot
# now starts from that same hue. A colour the person picked still wins.

def _hue_of(fill):
    m = re.match(r"\s*hsl\(\s*(\d+)", fill or "")
    return int(m.group(1)) if m else None


def test_a_robot_is_the_colour_of_its_agents_card(page):
    for agent_id, name in (("agent-research-assistant-0001", "Ada"),
                           ("agent-iris-a103", "Iris")):
        fill = page.locator('.who[data-id="%s"] .bot-body' % agent_id
                            ).get_attribute("fill")
        assert _hue_of(fill) == render._hue(name), (name, fill, render._hue(name))


def test_a_colour_the_person_chose_still_wins(page):
    """Only the default changed. A swatch somebody picked is kept, and the
    agent nobody recoloured still wears its own hue."""
    page.evaluate("() => localStorage.setItem('aiuiOfficeColours',"
                  " JSON.stringify({'agent-iris-a103': 'orange'}))")
    page.reload()
    page.wait_for_selector(".who", state="visible")
    iris = page.locator('.who[data-id="agent-iris-a103"] .bot-body'
                        ).get_attribute("fill")
    ada = page.locator('.who[data-id="agent-research-assistant-0001"] .bot-body'
                       ).get_attribute("fill")
    assert iris == "#cc7f2b", iris          # the orange palette's body
    assert _hue_of(ada) == render._hue("Ada"), ada


def test_the_panel_offers_the_agents_own_colour_back(page):
    """A person who tried orange needs a way back to the colour the agent
    has everywhere else, and it is the one marked when nothing was picked."""
    page.locator('.who[data-id="agent-iris-a103"]').click()
    page.wait_for_timeout(150)
    own = page.locator('#side .swatch[data-hue="own"]')
    assert own.count() == 1
    assert own.get_attribute("aria-current") == "true"
    page.locator('#side .swatch[data-hue="orange"]').click()
    page.wait_for_timeout(200)
    assert page.locator('#side .swatch[data-hue="own"]'
                        ).get_attribute("aria-current") is None
    page.locator('#side .swatch[data-hue="own"]').click()
    page.wait_for_timeout(200)
    fill = page.locator('.who[data-id="agent-iris-a103"] .bot-body'
                        ).get_attribute("fill")
    assert _hue_of(fill) == render._hue("Iris"), fill
    saved = page.evaluate("() => localStorage.getItem('aiuiOfficeColours')")
    assert "agent-iris-a103" not in (saved or ""), saved
```

**Step 2: Run it to verify it fails**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_office_page.py -q -k "colour_of_its_agents_card or person_chose_still_wins or own_colour_back"
```

Expected: `3 failed`. Measured messages:
- `AssertionError: ('Ada', '#cc7f2b', 142)`: today Ada's robot is the orange palette, picked by an id hash.
- `AssertionError: #cc7f2b`: Ada again.
- `assert 0 == 1`: there is no own-colour swatch.

**Step 3: Minimal implementation**

3a. In `static/office.html`, change lines 553-569, from the comment `// The one this person picked, or a stable one from the id so the same agent` through `CHOSEN[id] = hue;`. Old:

```js
  // The one this person picked, or a stable one from the id so the same agent
  // is the same robot on every reload without anybody choosing.
  function paletteOf(id) {
    var picked = CHOSEN[id];
    if (picked) {
      for (var i = 0; i < PALETTES.length; i++) {
        if (PALETTES[i].hue === picked) return PALETTES[i];
      }
    }
    var n = 0;
    for (var j = 0; j < id.length; j++) n = (n * 31 + id.charCodeAt(j)) >>> 0;
    return PALETTES[n % PALETTES.length];
  }
  function colourOf(id) { return paletteOf(id).accent; }

  function pickColour(id, hue) {
    CHOSEN[id] = hue;
```

New:

```js
  //: The agent's own hue, from its NAME, by the hash its card uses
  //: (agents.html avatarHue) and the chat thread uses
  //: (agent_chat_render._hue). Keep the three identical: a robot picked by
  //: a hash of the id made Ada green on her card and purple on this floor.
  function nameHue(name) {
    var h = 0, str = String(name || "");
    for (var i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) % 360;
    return h;
  }
  //: A palette in that hue: the body is DESIGN.md's avatar colour,
  //: hsl(hue 45% 32%), and the accent is light enough to read as eyes on
  //: the dark face.
  function ownPalette(id) {
    var h = nameHue(nameOf(id));
    return { hue: "own", accent: "hsl(" + h + ", 70%, 66%)",
             body: "hsl(" + h + ", 45%, 32%)", body2: "hsl(" + h + ", 45%, 24%)" };
  }

  // The one this person picked, or the agent's own hue, so the same agent is
  // the same colour here as on its card and in the chat without anybody
  // choosing.
  function paletteOf(id) {
    var picked = CHOSEN[id];
    if (picked) {
      for (var i = 0; i < PALETTES.length; i++) {
        if (PALETTES[i].hue === picked) return PALETTES[i];
      }
    }
    return ownPalette(id);
  }
  function colourOf(id) { return paletteOf(id).accent; }

  function pickColour(id, hue) {
    // "own" is the way back: no choice stored, the agent's own hue again.
    if (hue === "own") delete CHOSEN[id];
    else CHOSEN[id] = hue;
```

`nameOf(id)` already exists. It is a hoisted function declaration that looks the agent up in `AGENTS`.

3b. In `static/office.html`, change the swatch map in `drawSide` (1109-1112). Old:

```js
        PALETTES.map(function (pal) {
          return '<button class="swatch" type="button" data-hue="' + pal.hue +
            '" title="' + pal.hue + '" aria-label="Make ' + esc(m.name || m.id) +
            ' ' + pal.hue + '" style="background:' + pal.body +
```

New:

```js
        // The agent's own colour first, the one it wears on its card.
        [ownPalette(m.id)].concat(PALETTES).map(function (pal) {
          var own = pal.hue === "own";
          return '<button class="swatch" type="button" data-hue="' + pal.hue +
            '" title="' + (own ? "Its own colour, as on its card" : pal.hue) +
            '" aria-label="' + (own
              ? "Give " + esc(m.name || m.id) + " its own colour"
              : "Make " + esc(m.name || m.id) + " " + pal.hue) +
            '" style="background:' + pal.body +
```

The rest of that expression stays as it is: `';border-color:' ...`, the `aria-current` line and `'></button>'`. The `aria-current` test `paletteOf(m.id).hue === pal.hue` now marks "own" when nothing is stored.

**Step 4: Run it to verify it passes**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_office_page.py tests/browser/test_office_inline.py -q
```

Expected:
- test_office_page.py: 75 passed (72 old, 3 new).
- test_office_inline.py: 39 passed.

The pinned colour tests still pass. They were measured green:
- `test_the_panel_offers_colours_to_pick`: 7 swatches, against a minimum of 6.
- `test_picking_a_colour_changes_that_agent`
- `test_it_only_changes_the_one_you_picked`
- `test_the_colour_is_remembered`
- `test_the_robot_carries_the_agents_colour`: Ada is hue 142 and Iris 227.
- `test_the_figure_wears_the_agents_colour`

**Step 5: Commit**

```bash
git add mcp-servers/tasks/static/office.html mcp-servers/tasks/tests/browser/test_office_page.py
git commit -m "Office robots wear the same colour as the agent's card

The office picked one of six palettes from a hash of the agent's id, so Ada
was green on her card and orange or purple as a robot. A robot now starts
from the hue of the agent's name, the same hash the card and the chat thread
use. A colour somebody picked is kept, and the panel offers the agent's own
colour back as the first swatch.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: State lights lit again, rooms outlined instead of striped, reduced motion

**Files:**
- Modify: `mcp-servers/tasks/static/office.html`:
  - lines 142-143: `.zone` border
  - after line 215: `@keyframes blink`; insert the `.dot` and `.st` rules
  - lines 436-437: add the reduced-motion block before `</style>`
- Test: `mcp-servers/tasks/tests/browser/test_office_page.py`: append at the end, after Task 2's block.

**Step 1: Write the failing test**

Append to the END of `tests/browser/test_office_page.py`. It uses the file's existing `_with_handoff` helper.

```python


# --- state you can read, edges without stripes, motion you can stop ---------
# 6e3dda3c4 deleted the .dot rules along with the old cards, so every state
# light on the page has been an empty box since: a robot's light, the live
# strip, the activity list and the header all drew nothing. DESIGN.md also
# rules out a coloured side stripe wider than 1px, and asks that motion stop
# for a person whose system asks for less of it.

def test_the_state_light_is_lit_in_the_states_colour(page):
    got = page.evaluate(
        "() => {"
        " const bg = s => getComputedStyle(document.querySelector(s)).backgroundColor;"
        " const d = document.querySelector('.who[data-id=\"agent-iris-a103\"] .dot');"
        " return {"
        "  working: bg('.who[data-id=\"agent-research-assistant-0001\"] .dot.working'),"
        "  ready: bg('.who[data-id=\"agent-iris-a103\"] .dot.ready'),"
        "  live: bg('#live .dot'),"
        "  round: getComputedStyle(d).borderRadius }; }")
    assert got["working"] == "rgb(34, 211, 238)", got    # --cyan
    assert got["ready"] == "rgb(52, 211, 153)", got      # --ok
    assert got["live"] != "rgba(0, 0, 0, 0)", got
    assert got["round"] == "50%", got


def test_a_room_is_outlined_not_striped(page):
    sides = page.locator("section.zone").evaluate_all(
        "els => els.map(e => { const s = getComputedStyle(e);"
        " return [s.borderLeftWidth, s.borderTopWidth, s.borderRightWidth,"
        "         s.borderBottomWidth, s.borderLeftColor === s.borderTopColor]; })")
    assert sides, sides
    for left, top, right, bottom, same in sides:
        assert left == top == right == bottom == "1px", sides
        assert same, sides


def test_reduced_motion_stops_every_loop(page):
    """breathe, bustle, blink, halo, the dot's pulse and the talk line's
    along: every one runs for ever, and none of them is the only place a
    state is said. The dot colour and the label still say it."""
    _with_handoff(page)
    page.emulate_media(reduced_motion="reduce")
    page.wait_for_timeout(100)
    names = page.evaluate(
        "() => {"
        " const a = (el, p) => getComputedStyle(el, p || null).animationName;"
        " const ada = document.querySelector("
        "   '.who[data-id=\"agent-research-assistant-0001\"]');"
        " const iris = document.querySelector('.who[data-id=\"agent-iris-a103\"]');"
        " return [a(iris.querySelector('.bot')), a(ada.querySelector('.bot')),"
        "         a(ada.querySelector('.bot-think')), a(ada, '::after'),"
        "         a(ada.querySelector('.dot')),"
        "         a(document.querySelector('.talk-line'))]; }")
    assert names == ["none"] * 6, names
```

**Step 2: Run it to verify it fails**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_office_page.py -q -k "state_light_is_lit or outlined_not_striped or reduced_motion"
```

Expected: `3 failed`. Measured messages:
- `{'live': 'rgba(0, 0, 0, 0)', 'ready': 'rgba(0, 0, 0, 0)', 'round': '0px', 'working': 'rgba(0, 0, 0, 0)'}`
- `[['3px', '1px', '1px', '1px', False], ['3px', '1px', '1px', '1px', False]]`
- `['breathe', 'bustle', 'blink', 'halo', 'none', 'along']`

**Step 3: Minimal implementation**

3a. In `static/office.html`, change the `.zone` border (lines 142-143). Old:

```css
    border: 1px solid var(--border-2);
    border-left: 3px solid var(--glow, var(--cyan));
```

New:

```css
    /* The department's colour on all four sides at 1px, not a 3px stripe
       down the left: DESIGN.md rules out side stripes as an accent. Mixed
       into the plain border so six rooms do not read as six neon frames. */
    border: 1px solid color-mix(in srgb, var(--glow, var(--cyan)) 55%, var(--border-2));
```

Each room keeps a different `borderLeftColor`, so `test_each_department_is_its_own_colour` still passes (measured).

3b. In `static/office.html`, change the line `@keyframes blink { 0%, 88%, 100% { opacity: 1 } 94% { opacity: .2 } }` (215) and the comment after it. Old:

```css
  @keyframes blink { 0%, 88%, 100% { opacity: 1 } 94% { opacity: .2 } }
  /* the state light, bottom-right, as in the mockup */
```

New. The `.dot` rules are restored verbatim from `git show 6e3dda3c4 -- mcp-servers/tasks/static/office.html`. The `.st` row rule is new, so the lit dot is not flush against "No runs yet" in the side panel; this was seen in a screenshot.

```css
  @keyframes blink { 0%, 88%, 100% { opacity: 1 } 94% { opacity: .2 } }
  /* The state light itself, wherever it is drawn: on a robot, in the live
     strip, the activity list and the header. 6e3dda3c4 removed these with
     the old cards, and every light on the page was an empty box after it. */
  .dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; flex: none; }
  .dot.ready { background: var(--ok); }
  .dot.working { background: var(--cyan); animation: pulse 1.4s ease-in-out infinite; }
  .dot.waiting { background: var(--warn); }
  .dot.failed { background: var(--bad); }
  .dot.idle { background: #3d4d6b; }
  @keyframes pulse { 0%,100% { opacity: 1 } 50% { opacity: .3 } }
  /* The panel's state line, which lost its rule in the same commit: lit
     again, its light would otherwise sit flush against the words. */
  .st { display: flex; align-items: center; gap: 6px; }
  /* the state light, bottom-right, as in the mockup */
```

`.who .dot` (12px, absolutely positioned) is more specific and keeps its size. It gains the round shape and the state fill.

3c. In `static/office.html`, change lines 436-437. Old:

```css
  html.embed .brain { margin-bottom: 8px; }
</style>
```

New:

```css
  html.embed .brain { margin-bottom: 8px; }

  /* Every loop on this floor runs for ever: breathe, bustle, blink, halo,
     the dot's pulse and the talk line. None is the only place a state is
     said (the dot colour and the label say it), so a person whose system
     asks for less motion gets none, and a walking robot steps instead. */
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
      animation: none !important;
      transition: none !important;
    }
  }
</style>
```

**Step 4: Run it to verify it passes**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_office_page.py tests/browser/test_office_inline.py tests/browser/test_office_live.py -q
```

Expected: 122 passed (78 + 39 + 5), measured on a scratch copy in 105 s.

`test_everyone_is_breathing` still passes because the reduced-motion rule applies only under the media query.

Then look at it in a browser at 1500x1000, standalone and in the agents-page dock. Measured on the scratch copy:
- dots are lit
- Ada's robot is green and her card is green
- Iris is blue on both
- rooms have a 1px outline
- the dock floor bar has no "Open the chat"

**Step 5: Commit**

```bash
git add mcp-servers/tasks/static/office.html mcp-servers/tasks/tests/browser/test_office_page.py
git commit -m "Office state lights are lit again and motion stops when asked

6e3dda3c4 removed the .dot rules with the old cards, so every state light in
the office drew an empty box. They are back. Rooms get a 1px outline in their
department colour instead of a 3px stripe down the left. Under
prefers-reduced-motion the breathing, bustle, blink, halo, pulse and talk line
animations stop; the dot colour and the label still say the state.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

**Open questions:**
- Shell detection goes beyond the shared protocol text: the office treats itself as shell-framed only when window.top.__aiuiTaskPanelLoaded === true, not merely when window.top !== window. This is needed to keep test_a_frame_that_does_not_host_the_office_still_follows_the_link green (/bare framing). The task-panel.js drafter must not rename or remove that flag.
- End to end through the real shell is not proven. The /shell tests load the real task-panel.js but only record the aiui:open-pane message, because the shell listener that opens the pane and posts aiui-agents-ask is another drafter's task. Once it lands:
  1. Re-run test_office_inline.py; the listener will act on the recorded messages.
  2. Test in a real browser on the server.
- Edit agent for an agent the viewer does not own is a silent no-op when hosted. The office shows Edit agent for every agent and does not know who 'me' is. In the standalone shell pane, Edit agent opens AI Agents without the form, because aiui:open-pane carries no id. Should the office hide Edit agent for agents the viewer does not own?
- Two behaviour choices to confirm with the owner and Ralph:
  1. The meeting button switches a private conversation back to Everyone before prefilling 'everyone answer: '.
  2. A skill link opens that agent's private conversation and prefills only the question, without the 'Name,' prefix.
- Phase 1 removes the office dock from the main surface. The new prefill, openPane and editAgent helpers live inside the dock IIFE (agents.html 2937-3146) and must move with the on-demand office iframe.
- Possible merge overlap: another Phase 0 drafter adds the aiui-agents-ask listener near the ?ask= script (agents.html 2807-2836). This plan edits 3133-3146 only.
- Robot bodies now use hsl(hue, 45%, 32%) per DESIGN.md. Cards still draw hsl(hue 58% 46%) to hsl(hue+26 58% 34%) gradients until the avatar task lands, so the hue matches but the lightness differs.
- office.html is Ralph's file (design risk 1). Tell him before this lands.

# Draft: P0-3 agents page: contrast, focus, dialogs, ask

# P0-3 agents page: contrast, focus, dialogs, ask

Scope: `mcp-servers/tasks/static/agents.html`, `agent-chat.css`, `agent-chat.js` (Phase 0 of docs/plans/2026-10-05-ai-agents-workspace-design.md: "Contrast token, focus rings, Escape and dialog roles", "Button font"), plus the receiving half of the shared `aiui-agents-ask` protocol.

Ground rules for whoever executes this:
- Run every test from `mcp-servers/tasks` with a dead DB URL, exactly like this:
  `cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest <files> -q`
- One failure is pre-existing on HEAD 8052d7b78 and is NOT yours: `tests/test_static_page_js.py::test_element_ids_are_unique[office.html]` (office.html contains the literal id `"' + esc(m.id) + '"` twice). Every count below includes it as "1 failed".
- The three static files are CRLF and contain only ASCII except the "More actions" button's three middle dots. Add no em or en dashes and no other non-ASCII (`tests/test_agents_page_access.py::test_no_em_dashes_in_the_new_copy` enforces the dashes).
- Do not touch `templates.py` or any `.env`.
- Every code block below was applied to copies of today's files and run: red counts and green counts are measured, not predicted.

---

### Task 1: Muted contrast, the page font, and one focus ring

**Files:**
- Create: `mcp-servers/tasks/tests/browser/test_agents_page_a11y.py`
- Modify: `mcp-servers/tasks/static/agents.html` line 16 (`--muted`), line 23 (`* { box-sizing ... }`), lines 136-137 (`.search-wrap input`), lines 541-548 (`.modal input[...]`), line 674 (`.saved-what`)
- Modify: `mcp-servers/tasks/static/agent-chat.css` lines 27-30 (`.agents-main`), line 128 (`.aquote`), line 169 (`.afail`), lines 253-257 (`.ap-composer input`)
- Test: the new file, plus the existing suites listed in Step 4

**Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/browser/test_agents_page_a11y.py` with exactly this content. It follows `test_office_inline.py`: a module-scoped `browser`, a module-scoped `server` that serves the REAL `agent-chat.css` and `agent-chat.js` (vendored scripts empty), a per-test `page` with `pg.route("**/api/**", ...)` stubs, and the `window.__aiuiAgents.ready` wait from `test_agents_page_fit.py`.

```python
"""Contrast, focus and dialogs on the agents page.

Measured on 2026-10-05 in Chromium against this page with its real
stylesheet and panel script:

- --muted (#74747e) was 3.87:1 on --surface-2, and the composer placeholder
  was the browser's own #757575, 3.88:1.
- Every .btn, the search boxes and the checkboxes computed to Arial.
- Tab reached the search box and the composer with outline: none and nothing
  in its place, and every button with the browser's ring in rgb(16, 16, 16)
  on a near black page.
- The agent form had no dialog role and left focus on the button behind it.
- Connections opened from inside the form drew UNDER it (both overlays at
  z-index 50, the form later in the markup), and Escape closed neither.

Rendered, not read: contrast and focus are computed styles, and a rule that
loses on specificity reads exactly like one that wins.
"""
import http.server
import json
import pathlib
import re
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

STATIC = pathlib.Path(__file__).resolve().parents[2] / "static"

ME = "user-me"
#: DESIGN.md Switchboard Periwinkle, as getComputedStyle reports it.
ACCENT = "rgb(124, 140, 255)"

AGENTS = [
    {"id": "agent-ada-0001", "name": "Ada", "user_id": ME,
     "base_model_id": "gpt-4o-mini",
     "params": {"system": "You are Ada. Project manager."},
     "meta": {"role": "Project manager", "toolIds": []},
     "access_grants": [], "is_active": True, "write_access": True,
     "created_at": 1, "updated_at": 1,
     "user": {"id": ME, "name": "Me", "email": "me@example.com"}},
]

BASE_MODELS = [
    {"id": "gpt-4o-mini", "name": "gpt-4o-mini", "user_id": None,
     "base_model_id": None, "params": {}, "meta": {},
     "access_grants": [], "is_active": True, "write_access": False,
     "created_at": 0, "updated_at": 0, "user": None},
]

#: The connected apps umbrella unconnected, so the form carries its "Connect
#: an app" link: the one real way Connections opens ON TOP of the form.
TOOLS = {"tools": [
    {"id": "gmail", "label": "Gmail", "connected": True, "connect_url": None},
    {"id": "server:mcp-proxy", "label": "Your connected apps",
     "connected": False, "connect_url": ""},
]}

SKILLS = {"skills": [
    {"name": "inbox-triage", "tags": ["email"], "tools": [],
     "description": "Sort unread mail into what needs a reply today."},
]}


def _api_envelope(rows):
    out = []
    for row in rows:
        info = {k: v for k, v in row.items() if k != "params"}
        out.append({"id": row["id"], "name": row["name"], "object": "model",
                    "created": row.get("created_at", 0), "owned_by": "openai",
                    "preset": True, "connection_type": None,
                    "actions": [], "filters": [], "tags": [], "info": info})
    return {"data": out}


def _rgb(css):
    css = css.strip()
    if css.startswith("#"):
        h = css[1:]
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return tuple(int(float(v)) for v in re.findall(r"[\d.]+", css)[:3])


def _contrast(fg, bg):
    """WCAG 2 contrast ratio between two CSS colours."""
    def lum(colour):
        lin = []
        for v in _rgb(colour):
            v /= 255
            lin.append(v / 12.92 if v <= 0.03928
                       else ((v + 0.055) / 1.055) ** 2.4)
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    a, b = lum(fg), lum(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:                            # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        yield b
        b.close()


# The real stylesheet and the real panel script, as test_office_inline.py
# serves them. The composer's focus style lives in agent-chat.css and the
# clear confirm opens and closes in agent-chat.js, so a fixture that answered
# either with a placeholder would test an unstyled, half wired page.
@pytest.fixture(scope="module")
def server():
    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):                                    # noqa: N802
            path = self.path.split("?")[0]
            name = path.rsplit("/", 1)[-1]
            kind = "text/html"
            if name in ("agent-chat.css", "agent-chat.js"):
                body = (STATIC / name).read_bytes()
                kind = ("text/css" if name.endswith(".css")
                        else "text/javascript")
            elif name.endswith(".js"):
                # Vendored htmx, marked and DOMPurify. Not under test, and
                # an empty body keeps htmx from swapping stub JSON into the
                # thread.
                body, kind = b"", "text/javascript"
            elif path.startswith("/tasks/office"):
                # The dock frames the office. A blank page keeps this file
                # about the agents page.
                body = b"<!doctype html><title>office</title>"
            else:
                body = (STATIC / "agents.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


@pytest.fixture
def page(browser, server):
    pg = browser.new_page(viewport={"width": 1500, "height": 1000})
    pg.set_default_timeout(5000)

    def route(r):
        url = r.request.url
        if "/api/v1/auths/" in url:
            body = {"id": ME, "email": "me@example.com"}
        elif "/agents/activity" in url:
            body = {"activity": {}}
        elif url.rstrip("/").endswith("/api/tasks/agents/memory"):
            body = {"counts": {}}
        elif "/agents/seed" in url:
            body = {"seeded": False, "created": 0}
        elif "/agents/skills" in url:
            body = SKILLS
        elif "/agents/tools" in url:
            body = TOOLS
        elif "/api/v1/models/list" in url:
            body = {"items": AGENTS, "total": len(AGENTS)}
        elif "/api/models" in url or url.rstrip("/").endswith("/api/v1/models"):
            body = _api_envelope(AGENTS + BASE_MODELS)
        else:
            body = {"ok": True}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.goto("http://127.0.0.1:%d/agents.html" % server.server_address[1])
    pg.wait_for_function("() => window.__aiuiAgents && window.__aiuiAgents.ready")
    pg.wait_for_selector('[data-agent-id="agent-ada-0001"]')
    yield pg
    pg.close()


def _active(page):
    return page.evaluate(
        "() => { const e = document.activeElement;"
        " return { id: e.id, cls: typeof e.className === 'string'"
        " ? e.className : '', act: e.dataset ? (e.dataset.act || '') : '' }; }")


def _open_form(page):
    page.locator("#new-agent").click()
    page.wait_for_selector("#agent-form", state="visible")


# --- contrast and the page font ----------------------------------------------

def test_muted_text_passes_aa_on_every_surface(page):
    """DESIGN.md: Muted is #8b8b95, at least 5.30:1 on every surface."""
    tokens = page.evaluate(
        "() => { const s = getComputedStyle(document.documentElement);"
        " return Object.fromEntries(['--muted', '--bg', '--surface',"
        " '--surface-2'].map(k => [k, s.getPropertyValue(k).trim()])); }")
    for surface in ("--bg", "--surface", "--surface-2"):
        ratio = _contrast(tokens["--muted"], tokens[surface])
        assert ratio >= 4.5, "%s on %s (%s) is %.2f:1" % (
            tokens["--muted"], surface, tokens[surface], ratio)


def test_muted_text_on_screen_is_readable(page):
    """The token is only half of it: what a person reads is the computed
    colour on the computed background. The composer placeholder ignored the
    token entirely and used the browser's own grey."""
    got = page.evaluate(
        "() => { const i = document.querySelector("
        "'.ap-composer input[name=message]');"
        " const sub = document.getElementById('ap-sub');"
        " return { ph: getComputedStyle(i, '::placeholder').color,"
        " field: getComputedStyle(i).backgroundColor,"
        " sub: getComputedStyle(sub).color,"
        " panel: getComputedStyle(document.querySelector('.agent-panel'))"
        ".backgroundColor }; }")
    assert got["ph"] == "rgb(139, 139, 149)", got
    assert _contrast(got["ph"], got["field"]) >= 4.5, got
    assert _contrast(got["sub"], got["panel"]) >= 4.5, got


def test_no_control_falls_back_to_arial(page):
    """DESIGN.md: buttons inherit the family; the Arial fallback is a bug.
    Controls in the hidden dialogs count too: their style is computed all
    the same."""
    odd = page.evaluate(
        "() => { const want = getComputedStyle(document.body).fontFamily;"
        " return [...document.querySelectorAll("
        "'button, input, select, textarea')]"
        ".filter(e => getComputedStyle(e).fontFamily !== want)"
        ".map(e => (e.id || e.className || e.tagName) + ': '"
        " + getComputedStyle(e).fontFamily); }")
    assert odd == [], odd


# --- focus ---------------------------------------------------------------------

#: What the focused element draws, and the first ancestor that would cut its
#: ring off at the side (overflow other than visible, measured on the padding
#: box, which is where the clip is).
FOCUSED_JS = """() => {
  const e = document.activeElement;
  const s = getComputedStyle(e);
  const r = e.getBoundingClientRect();
  let clip = null;
  for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) {
    if (getComputedStyle(p).overflowX === 'visible') continue;
    const c = p.getBoundingClientRect();
    const left = c.left + p.clientLeft, right = left + p.clientWidth;
    if (r.left - 4 < left - 0.5 || r.right + 4 > right + 0.5) {
      clip = p.id || p.className; break;
    }
  }
  return { what: e.tagName + '#' + e.id + '.' +
             (typeof e.className === 'string' ? e.className : ''),
           tag: e.tagName, id: e.id,
           ring: [s.outlineStyle, s.outlineWidth, s.outlineColor,
                  s.outlineOffset],
           after: getComputedStyle(e, '::after').backgroundColor, clip };
}"""


def test_every_stop_on_the_tab_path_draws_the_periwinkle_ring(page):
    """One ring for everything (DESIGN.md: 2px periwinkle, 2px offset), and
    not cut off by the scrolling column it sits in."""
    page.locator("body").click(position={"x": 5, "y": 5})
    seen = []
    for _ in range(16):
        page.keyboard.press("Tab")
        f = page.evaluate(FOCUSED_JS)
        if f["tag"] in ("BODY", "IFRAME"):
            continue
        if f["id"] == "ap-resize":
            # Its mark fades in over 0.12s, and a computed style read mid
            # transition reports the starting colour.
            page.wait_for_timeout(250)
            f = page.evaluate(FOCUSED_JS)
        seen.append(f)
    assert len(seen) >= 8, [f["what"] for f in seen]
    for f in seen:
        if f["id"] == "ap-resize":
            # A full height drag strip between the columns. Its focus mark is
            # the 2px accent rule it already draws, which is a replacement,
            # not an outline: none with nothing in its place.
            assert f["after"] == ACCENT, f
            continue
        assert f["ring"] == ["solid", "2px", ACCENT, "2px"], f
        assert f["clip"] is None, f


def test_a_focused_composer_looks_different_from_an_idle_one(page):
    box = page.locator(".ap-composer input[name=message]")
    idle = box.evaluate(
        "e => [getComputedStyle(e).borderTopColor,"
        " getComputedStyle(e).outlineStyle]")
    box.focus()
    now = box.evaluate(
        "e => { const s = getComputedStyle(e); return [s.borderTopColor,"
        " s.outlineStyle, s.outlineWidth, s.outlineColor, s.outlineOffset]; }")
    assert idle[0] != ACCENT and idle[1] == "none", idle
    assert now == [ACCENT, "solid", "2px", ACCENT, "2px"], now


def test_the_skill_search_is_a_styled_field_not_a_white_box(page):
    _open_form(page)
    page.locator("#skills-toggle").click()
    got = page.locator("#skill-search").evaluate(
        "e => { const s = getComputedStyle(e); return [s.backgroundColor,"
        " s.borderTopColor, s.color, s.fontSize]; }")
    # --surface-2, --border-2, --text, and the other fields' 13px.
    assert got == ["rgb(23, 23, 26)", "rgb(46, 46, 54)",
                   "rgb(237, 237, 238)", "13px"], got


@pytest.mark.parametrize("field", ["#agent-name", "#agent-instructions",
                                   "#agent-base", "#skill-search"])
def test_a_focused_form_field_shows_the_ring_and_the_border(page, field):
    """Reached by keyboard, the way a person tabbing through the form gets
    there, so :focus-visible applies to the select as it would for them."""
    _open_form(page)
    page.locator("#skills-toggle").click()
    page.locator(field).focus()
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Tab")
    assert _active(page)["id"] == field[1:], _active(page)
    got = page.locator(field).evaluate(
        "e => { const s = getComputedStyle(e); return [s.outlineStyle,"
        " s.outlineWidth, s.outlineColor, s.borderTopColor]; }")
    assert got == ["solid", "2px", ACCENT, ACCENT], (field, got)
```

**Step 2: Run it to verify it fails**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_agents_page_a11y.py -q
```

Expected: `10 failed`. Measured messages:
- `test_muted_text_passes_aa_on_every_surface`: `AssertionError: #74747e on --bg (#0a0a0b) is 4.28:1`
- `test_muted_text_on_screen_is_readable`: `assert 'rgb(117, 117, 117)' == 'rgb(139, 139, 149)'`
- `test_no_control_falls_back_to_arial`: `['agent-search: Arial', 'open-connections: Arial', 'new-agent: Arial', ...]` (25 more)
- `test_every_stop_on_the_tab_path_draws_the_periwinkle_ring`: `'ring': ['auto', '1px', 'rgb(16, 16, 16)', '1px']` (the first stop, `a.back`)
- `test_a_focused_composer_looks_different_from_an_idle_one`: `['rgb(36, 36, 42)', 'none', '0px', 'rgb(237, 237, 238)', '0px']`
- `test_the_skill_search_is_a_styled_field_not_a_white_box`: `['rgb(255, 255, 255)', 'rgb(118, 118, 118)', 'rgb(0, 0, 0)', '13.3333px']`
- `test_a_focused_form_field_shows_the_ring_and_the_border[#agent-name]`, `[#agent-instructions]`, `[#agent-base]`: `['none', '0px', ...]`; `[#skill-search]`: `['auto', '1px', 'rgb(16, 16, 16)', 'rgb(118, 118, 118)']`

**Step 3: Minimal implementation**

1.1 `static/agents.html` line 16. Old:
```css
    --muted:        #74747e;
```
New:
```css
    /* #74747e was 3.87:1 on --surface-2. This is 5.30:1 there and better
       on the other two surfaces (DESIGN.md, Muted). */
    --muted:        #8b8b95;
```

1.2 `static/agents.html` line 23 (unique). Old:
```css
  * { box-sizing: border-box; }
```
New:
```css
  * { box-sizing: border-box; }
  /* Form controls do not inherit the page font on their own, so every .btn
     and both search boxes rendered in Arial. Element selectors only, so a
     class that sets its own size still wins. */
  button, input, select, textarea { font: inherit; }
  /* The browser's own placeholder grey (#757575) is 3.88:1 on the composer.
     opacity: 1 because Firefox fades placeholder text on top of its colour. */
  ::placeholder { color: var(--muted); opacity: 1; }
```

1.3 `static/agents.html` lines 136-137 (`.search-wrap input`). Old:
```css
    border-radius: var(--radius); color: var(--text); font-size: 13px;
    outline: none; transition: border-color 0.15s, width 0.15s;
```
New:
```css
    border-radius: var(--radius); color: var(--text); font-size: 13px;
    transition: border-color 0.15s, width 0.15s;
```

1.4 `static/agents.html` lines 541-548. Old:
```css
  /* password too: the Connections panel asks for API tokens, and a
     browser default white box in a dark modal looks broken. */
  .modal input[type=text], .modal input[type=password],
  .modal textarea, .modal select {
    width: 100%; box-sizing: border-box; background: var(--surface-2);
    border: 1px solid var(--border-2); border-radius: var(--radius);
    padding: 10px 12px; color: var(--text); font-size: 13px; outline: none;
    font-family: inherit; }
```
New:
```css
  /* password too: the Connections panel asks for API tokens, and a
     browser default white box in a dark modal looks broken. search for the
     same reason: the skill search in the agent form was exactly that box. */
  .modal input[type=text], .modal input[type=password],
  .modal input[type=search], .modal textarea, .modal select {
    width: 100%; box-sizing: border-box; background: var(--surface-2);
    border: 1px solid var(--border-2); border-radius: var(--radius);
    padding: 10px 12px; color: var(--text); font-size: 13px;
    font-family: inherit; }
```

1.5 `static/agents.html` line 674 (the last rule before `</style>`). Old:
```css
  .saved-what { color: var(--muted, #8b8b96); font-size: 12px; margin-top: 3px; }
```
New:
```css
  .saved-what { color: var(--muted, #8b8b95); font-size: 12px; margin-top: 3px; }

  /* One focus ring for everything a keyboard can reach (DESIGN.md: 2px
     periwinkle, 2px offset). Last in the sheet so it wins ties, and nothing
     above sets outline: none any more. The browser ring it replaces was
     rgb(16, 16, 16) on a near black page. tabindex="-1" is left out: those
     take focus from script, like a dialog as it opens, and a ring round a
     whole dialog says nothing. */
  a[href]:focus-visible, button:focus-visible, input:focus-visible,
  select:focus-visible, textarea:focus-visible, summary:focus-visible,
  [tabindex]:not([tabindex="-1"]):focus-visible {
    outline: 2px solid var(--accent); outline-offset: 2px;
  }
  /* Fields turn their border periwinkle as well. Repeated under .modal
     because .modal input[type=text] sets the border at a higher
     specificity than a bare input selector. */
  input:focus-visible, select:focus-visible, textarea:focus-visible,
  .modal input:focus-visible, .modal select:focus-visible,
  .modal textarea:focus-visible {
    border-color: var(--accent);
  }
```
(`.ap-resize:focus-visible { outline: none; }` at agent-chat.css:309 stays: it outranks this rule on purpose and keeps its 2px accent bar, agent-chat.css:306-308. The test checks that bar.)

1.6 `static/agent-chat.css` lines 27-30. Old:
```css
.agents-main {
  min-width: 0; min-height: 0; overflow-y: auto;
  padding-right: 4px; scrollbar-gutter: stable;
}
```
New:
```css
.agents-main {
  min-width: 0; min-height: 0; overflow-y: auto;
  /* Both sides, not just the right. This column clips, and the focus ring
     (2px, offset 2px) on the search box and the buttons flush with its left
     edge was cut off. */
  padding: 0 4px; scrollbar-gutter: stable;
}
```
(Do not write the word `.agents-main` inside that comment: `test_agent_chat_page.py::test_the_page_itself_does_not_scroll` looks for `overflow-y: auto` within 200 characters after the FIRST `.agents-main` in the file.) Measured: without this padding the new tab test fails with `'clip': 'agents-main', 'id': 'agent-search'`.

1.7 `static/agent-chat.css` line 128. Old: `  font-size: 12px; line-height: 1.45; color: var(--muted, #8b8b96);` New: `  font-size: 12px; line-height: 1.45; color: var(--muted, #8b8b95);`

1.8 `static/agent-chat.css` line 169. Old: `         font-size: 12.5px; color: var(--muted, #8b8b96); line-height: 1.5; }` New: `         font-size: 12.5px; color: var(--muted, #8b8b95); line-height: 1.5; }`

1.9 `static/agent-chat.css` lines 253-257. Old:
```css
.ap-composer input {
  flex: 1; min-width: 0; padding: 9px 12px; border-radius: var(--radius);
  background: var(--surface-2); color: inherit;
  border: 1px solid var(--border); outline: none; font: inherit;
}
```
New:
```css
.ap-composer input {
  flex: 1; min-width: 0; padding: 9px 12px; border-radius: var(--radius);
  background: var(--surface-2); color: inherit;
  border: 1px solid var(--border); font: inherit;
}
/* A focused composer has to look different from an idle one (DESIGN.md).
   :focus rather than :focus-visible: this is where people type, so the ring
   shows however focus arrived, a click, Tab or the page putting it there. */
.ap-composer input:focus {
  border-color: var(--accent);
  outline: 2px solid var(--accent); outline-offset: 2px;
}
```

**Step 4: Run it to verify it passes**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_agents_page_a11y.py -q
```
Expected: `10 passed` (about 5 s).

Then every existing suite that reads or renders these three files:
```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/test_agent_chat_page.py tests/test_static_page_js.py tests/test_agents_page_access.py tests/test_agents_page_memory.py tests/browser/test_agents_ask_prefill.py tests/browser/test_agents_page_fit.py tests/browser/test_agents_page.py tests/browser/test_office_inline.py tests/browser/test_agents_tools_live.py tests/browser/test_embedded_page_chrome.py tests/browser/test_agent_chat_turn_targets.py -q
```
Expected: `1 failed, 273 passed` (about 3 min 15 s). The one failure must be `test_element_ids_are_unique[office.html]`, which fails identically on HEAD today. Anything else failing is yours.

**Step 5: Commit**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO" && git add mcp-servers/tasks/static/agents.html mcp-servers/tasks/static/agent-chat.css mcp-servers/tasks/tests/browser/test_agents_page_a11y.py && git commit -m "Agents page: readable muted text, the page font on every control, one focus ring

Muted goes from #74747e (3.87:1 on the raised surface) to #8b8b95 (5.30:1),
placeholders use it, buttons and fields stop rendering in Arial, and every
focusable control draws the 2px periwinkle ring. The composer, the form
fields and the skill search show focus for the first time.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Dialog roles, focus in and out, and one Escape handler

**Files:**
- Modify: `mcp-servers/tasks/static/agents.html` (line numbers are TODAY's, before Task 1 shifted them; anchor by the strings): the Task 1 focus block end (z-index rule), lines 903-904 (`#connections-panel`), line 915 (`#agent-form`), lines 2388-2391 (end of `openForm`, `closeForm`), lines 2665-2681 (`openConnections` and its two close handlers), lines 2784-2787 (the Escape handler)
- Modify: `mcp-servers/tasks/static/agent-chat.js` lines 145-147 (its own Escape listener)
- Test: append to `mcp-servers/tasks/tests/browser/test_agents_page_a11y.py`; append to `mcp-servers/tasks/tests/test_agent_chat_page.py` after line 172

**Step 1: Write the failing test**

Append to the end of `tests/browser/test_agents_page_a11y.py`:

```python


# --- dialogs -------------------------------------------------------------------

@pytest.mark.parametrize("dialog, title", [("#agent-form", "New agent"),
                                           ("#connections-panel", "Connections"),
                                           ("#ap-clear-modal",
                                            "Clear this conversation?")])
def test_each_dialog_is_announced_as_one(page, dialog, title):
    el = page.locator(dialog)
    assert el.get_attribute("role") == "dialog", dialog
    assert el.get_attribute("aria-modal") == "true", dialog
    label = el.get_attribute("aria-labelledby")
    assert label, dialog
    assert page.locator("#" + label).inner_text().strip() == title


def test_opening_the_form_moves_focus_in_and_cancel_hands_it_back(page):
    page.locator("#new-agent").focus()
    page.keyboard.press("Enter")
    page.wait_for_selector("#agent-form", state="visible")
    assert _active(page)["id"] == "agent-name", _active(page)
    page.locator("#agent-cancel").click()
    assert page.locator("#agent-overlay").is_hidden()
    assert _active(page)["id"] == "new-agent", _active(page)


def test_escape_closes_the_form_and_returns_to_the_edit_button(page):
    edit = page.locator('[data-agent-id="agent-ada-0001"] [data-act="edit"]')
    edit.click()
    page.wait_for_selector("#agent-form", state="visible")
    assert _active(page)["id"] == "agent-name", _active(page)
    page.keyboard.press("Escape")
    assert page.locator("#agent-overlay").is_hidden(), "Escape left the form open"
    assert _active(page)["act"] == "edit", _active(page)


def test_connections_opened_from_the_form_sits_on_top_of_it(page):
    _open_form(page)
    page.locator("#agent-form a.umbrella-connect").click()
    page.wait_for_selector("#connections-panel", state="visible")
    top = page.evaluate(
        "() => { const p = document.getElementById('connections-panel')"
        ".getBoundingClientRect();"
        " const e = document.elementFromPoint(p.left + p.width / 2, p.top + 12);"
        " if (!e) return null;"
        " if (e.closest('#connections-panel')) return 'connections';"
        " if (e.closest('#agent-form')) return 'agent-form';"
        " return e.tagName; }")
    assert top == "connections", top


def test_escape_closes_only_the_top_most_dialog(page):
    """Connections over the form. One Escape closes Connections and keeps
    the half written agent; the next closes the form."""
    _open_form(page)
    page.fill("#agent-name", "Jack")
    page.locator("#agent-form a.umbrella-connect").click()
    page.wait_for_selector("#connections-panel", state="visible")
    assert page.evaluate(
        "() => !!document.activeElement.closest('#connections-panel')"), (
        "focus stayed behind the panel")

    page.keyboard.press("Escape")
    assert page.locator("#connections-overlay").is_hidden()
    assert page.locator("#agent-overlay").is_visible(), "one Escape closed both"
    assert page.input_value("#agent-name") == "Jack"
    # Closing re-reads the tools and redraws the link that opened the panel,
    # so focus lands on its replacement once that is done.
    page.wait_for_function(
        "() => document.activeElement.classList.contains('umbrella-connect')")

    page.keyboard.press("Escape")
    assert page.locator("#agent-overlay").is_hidden()
    assert _active(page)["id"] == "new-agent", _active(page)


def test_escape_closes_the_clear_confirm_and_returns_to_clear(page):
    """Already true before the Escape handlers were merged: kept as a pin,
    because the merge moved this case out of agent-chat.js."""
    page.locator("#ap-clear").click()
    page.wait_for_selector("#ap-clear-modal", state="visible")
    assert _active(page)["id"] == "ap-clear-cancel", _active(page)
    page.keyboard.press("Escape")
    assert page.locator("#ap-clear-overlay").is_hidden()
    assert _active(page)["id"] == "ap-clear", _active(page)


def test_escape_closes_an_open_card_menu_and_returns_to_its_button(page):
    more = page.locator('[data-agent-id="agent-ada-0001"] [data-act="more"]')
    more.click()
    menu = page.locator('[data-agent-id="agent-ada-0001"] .more-menu')
    assert menu.is_visible()
    page.keyboard.press("Escape")
    assert menu.is_hidden()
    assert _active(page)["act"] == "more", _active(page)
```

Append to the end of `tests/test_agent_chat_page.py` (after line 172; `re`, `_page()` and `_script()` already exist there):

```python


def test_escape_is_handled_in_one_place():
    """Two Escape handlers, each closing "its" dialog, close two layers on
    one press. agents.html has the page's one handler, which closes only the
    top-most layer; agent-chat.js has none."""
    assert '"Escape"' not in _script(), (
        "agent-chat.js still handles Escape itself")
    assert _page().count('"Escape"') == 1, "expected exactly one Escape check"
```

**Step 2: Run it to verify it fails**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_agents_page_a11y.py tests/test_agent_chat_page.py -q
```
Expected: `7 failed, 29 passed`. Measured failures:
- `test_each_dialog_is_announced_as_one[#agent-form-New agent]` and `[#connections-panel-Connections]`: `assert None == 'dialog'`
- `test_opening_the_form_moves_focus_in_and_cancel_hands_it_back`: `assert 'new-agent' == 'agent-name'`
- `test_escape_closes_the_form_and_returns_to_the_edit_button`: `assert '' == 'agent-name'` (focus never left the Edit button)
- `test_connections_opened_from_the_form_sits_on_top_of_it`: `assert 'agent-form' == 'connections'`
- `test_escape_closes_only_the_top_most_dialog`: `focus stayed behind the panel`
- `test_escape_is_handled_in_one_place`: `agent-chat.js still handles Escape itself`

The `[#ap-clear-modal...]` case, the clear confirm pin and the menu pin pass already: they guard behaviour this task moves.

**Step 3: Minimal implementation**

2.1 `static/agents.html`, right after the block Task 1 added at the end of `<style>`. Old:
```css
  .modal textarea:focus-visible {
    border-color: var(--accent);
  }
```
New:
```css
  .modal textarea:focus-visible {
    border-color: var(--accent);
  }
  /* Connections opens from inside the agent form too (its "Connect an app"
     link). Both overlays sat at z-index 50, so the form, later in the
     markup, drew over the panel it had just opened. Escape closes
     Connections first, so it has to be the one on top. */
  #connections-overlay { z-index: 51; }
```

2.2 `static/agents.html` lines 903-904. Old:
```html
      <div class="modal" id="connections-panel">
        <h2>Connections</h2>
```
New:
```html
      <div class="modal" id="connections-panel" role="dialog" aria-modal="true"
           aria-labelledby="connections-title" tabindex="-1">
        <h2 id="connections-title">Connections</h2>
```
(`tabindex="-1"` lets the panel itself take focus while its list is still loading; Task 1's ring rule excludes `tabindex="-1"`, so no ring is drawn round the dialog.)

2.3 `static/agents.html` line 915. Old:
```html
      <div class="modal" id="agent-form">
```
New:
```html
      <div class="modal" id="agent-form" role="dialog" aria-modal="true"
           aria-labelledby="form-title">
```
(`#form-title` is the existing `<h2 id="form-title">New agent</h2>` at line 916.)

2.4 `static/agents.html` lines 2388-2391 (last line of `openForm`, then `closeForm`). Old:
```js
      document.getElementById("agent-overlay").hidden = false;
    }

    function closeForm() { document.getElementById("agent-overlay").hidden = true; }
```
New:
```js
      openDialog("agent-overlay", document.getElementById("agent-name"));
    }

    function closeForm() { closeDialog("agent-overlay"); }

    // The agent form and Connections behave the way the clear confirm already
    // does (agent-chat.js, showClear): focus moves in when one opens and goes
    // back to whatever opened it when it closes. Kept per overlay, because
    // Connections can open on top of the form and each has its own way back.
    var dialogOpener = {};

    function openDialog(id, first) {
      var overlay = document.getElementById(id);
      if (!overlay) return;
      if (overlay.hidden) dialogOpener[id] = document.activeElement;
      overlay.hidden = false;
      var target = first || overlay.querySelector('[role="dialog"]');
      if (target && typeof target.focus === "function") target.focus();
    }

    // Says whether there was anything to close, so the Escape handler can
    // stop at the first layer it actually closed.
    function closeDialog(id) {
      var overlay = document.getElementById(id);
      if (!overlay || overlay.hidden) return false;
      overlay.hidden = true;
      var back = dialogOpener[id];
      dialogOpener[id] = null;
      if (back && back.isConnected && typeof back.focus === "function") {
        back.focus();
      }
      return true;
    }
```
(`closeForm()` is also called after a successful save at line 2517; that path now returns focus too, and silently skips it when the save re-rendered the Edit button that opened the form.)

2.5 `static/agents.html` lines 2665-2681 (inside `wireForm`). Old:
```js
        connOverlay.hidden = false;
        loadConnections();
      }

      document.getElementById("open-connections").addEventListener(
        "click", openConnections);
      document.getElementById("connections-close").addEventListener(
        "click", function () {
          connOverlay.hidden = true;
          refreshToolsKeepingChoices();
        });
      connOverlay.addEventListener("click", function (ev) {
        if (ev.target === connOverlay) {
          connOverlay.hidden = true;
          refreshToolsKeepingChoices();
        }
      });
```
New:
```js
        openDialog("connections-overlay");
        loadConnections();
      }

      // Closing re-reads the tools, which redraws the form's "Connect an app"
      // link: the very link that opened this panel when it sat on top of the
      // form. Focus went back to that link before the redraw replaced it, so
      // once the redraw lands it goes to the replacement, or failing that the
      // form's first field, rather than being dropped on the page body.
      function keepFocusInForm() {
        var form = document.getElementById("agent-overlay");
        if (!form || form.hidden || form.contains(document.activeElement)) return;
        var again = form.querySelector("a.umbrella-connect")
          || document.getElementById("agent-name");
        if (again) again.focus();
      }

      function closeConnections() {
        if (!closeDialog("connections-overlay")) return false;
        refreshToolsKeepingChoices().then(keepFocusInForm, keepFocusInForm);
        return true;
      }

      document.getElementById("open-connections").addEventListener(
        "click", openConnections);
      document.getElementById("connections-close").addEventListener(
        "click", closeConnections);
      connOverlay.addEventListener("click", function (ev) {
        if (ev.target === connOverlay) closeConnections();
      });
```
(The embedded branch of `openConnections` above it, which posts `aiui:open-connections` to the shell, is unchanged.)

2.6 `static/agents.html` lines 2784-2787. Old:
```js
      // Escape closes the overflow, same as clicking away.
      document.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape") closeMenus(null);
      });
```
New:
```js
      // The page's one Escape handler. Each press closes the top-most thing
      // that is open and nothing under it: an overflow menu, then the clear
      // confirm, then Connections (which can sit on top of the agent form),
      // then the agent form. One layer per press, so Escape in Connections
      // never throws away an agent somebody is halfway through writing.
      // Delete and Forget all are not here: they ask through window.confirm,
      // which handles its own keys.
      document.addEventListener("keydown", function (ev) {
        if (ev.key !== "Escape") return;
        var menu = document.querySelector(".more-menu:not([hidden])");
        if (menu) {
          var opener = menu.parentNode.querySelector('[data-act="more"]');
          closeMenus(null);
          if (opener) opener.focus();
          ev.preventDefault();
          return;
        }
        var clear = document.getElementById("ap-clear-overlay");
        if (clear && !clear.hidden) {
          // agent-chat.js owns this one, and its Cancel is the way out that
          // already hands focus back to Clear.
          document.getElementById("ap-clear-cancel").click();
          ev.preventDefault();
          return;
        }
        if (closeConnections() || closeDialog("agent-overlay")) {
          ev.preventDefault();
        }
      });
```
(The shell's own Escape listener, task-panel.js:1464-1466, is on the top document; a keydown inside this iframe never reaches it, so closing a dialog here cannot also close the pane.)

2.7 `static/agent-chat.js` lines 145-147. Old:
```js
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && overlay && !overlay.hidden) { showClear(false); }
  });
```
New:
```js
  // No Escape handler here. agents.html has the page's one Escape handler,
  // which closes only the top-most layer, and for this dialog it presses
  // Cancel, so focus comes back to Clear through showClear above.
```

**Step 4: Run it to verify it passes**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_agents_page_a11y.py tests/test_agent_chat_page.py -q
```
Expected: `36 passed`.

Then the full set (now including the a11y file):
```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/test_agent_chat_page.py tests/test_static_page_js.py tests/test_agents_page_access.py tests/test_agents_page_memory.py tests/browser/test_agents_ask_prefill.py tests/browser/test_agents_page_fit.py tests/browser/test_agents_page_a11y.py tests/browser/test_agents_page.py tests/browser/test_office_inline.py tests/browser/test_agents_tools_live.py tests/browser/test_embedded_page_chrome.py tests/browser/test_agent_chat_turn_targets.py -q
```
Expected: `1 failed, 293 passed`, the failure being `test_element_ids_are_unique[office.html]` (pre-existing). The existing Delete and Forget all tests (`test_delete_asks_first`, `test_the_confirm_names_the_agent_being_deleted`, `test_forget_all_asks_before_it_empties_the_memory`, `test_forgetting_everything_asks_first`) must stay green: they pin `window.confirm`, which this task does not touch.

**Step 5: Commit**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO" && git add mcp-servers/tasks/static/agents.html mcp-servers/tasks/static/agent-chat.js mcp-servers/tasks/tests/browser/test_agents_page_a11y.py mcp-servers/tasks/tests/test_agent_chat_page.py && git commit -m "Agents page: the agent form and Connections are real dialogs, and Escape closes the top one

Both get role=dialog, aria-modal and a labelled title. Focus moves inside on
open and goes back to the button that opened them on close. One Escape
handler closes the top-most layer only: a card menu, the clear confirm,
Connections, then the agent form. Connections opened from inside the form
now draws above it instead of underneath. Delete and Forget all still ask
through window.confirm.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Accept a question from the shell (aiui-agents-ask)

Shared protocol, receiving side only (rule 2): the shell posts `{type: "aiui-agents-ask", ask}` to this page's `contentWindow` with targetOrigin `location.origin` after the pane's iframe has loaded. This page accepts it only when `event.source === window.parent` and `event.origin === location.origin` (and only when it is framed at all), and prefills through the SAME function `?ask=` now uses. It never sends. The shell side (task-panel.js) belongs to another task.

**Files:**
- Modify: `mcp-servers/tasks/static/agents.html` lines 2819-2835 (the `?ask=` IIFE inside the `<script>` that starts at line 2807)
- Test: `mcp-servers/tasks/tests/browser/test_agents_ask_prefill.py` line 23 (add a constant after it), lines 42-47 (the handler body), append after line 139

**Step 1: Write the failing test**

1. In `tests/browser/test_agents_ask_prefill.py`, after line 23 (`STATIC = pathlib.Path(__file__).resolve().parents[2] / "static"`), add:
```python

#: The Open WebUI shell, cut down to what these tests need from it: a top
#: document that frames the agents page as a pane, the way task-panel.js does.
#: ?frame= points the pane somewhere else, so one server can also play a
#: shell on a different origin (localhost framing 127.0.0.1).
SHELL = (b'<!doctype html><meta charset="utf-8"><title>shell</title>'
         b'<body style="margin:0">'
         b'<iframe id="pane" style="width:1300px;height:900px;border:0">'
         b'</iframe><script>document.getElementById("pane").src = '
         b'new URLSearchParams(location.search).get("frame")'
         b' || "/agents.html";</script></body>')
```

2. In the `server` fixture, lines 42-47. Old:
```python
        def do_GET(self):                                    # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
```
New:
```python
        def do_GET(self):                                    # noqa: N802
            body = SHELL if self.path.startswith("/shell") else html
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
```

3. Append to the end of the file (after line 139):
```python


# --- the shell handing the pane a question ----------------------------------
#
# task-panel.js opens the agents pane and then posts
# {type: "aiui-agents-ask", ask} to its iframe, with targetOrigin set to its
# own origin (the shared aiui:open-pane protocol, 2026-10-05). The page fills
# the box by the same path ?ask= uses, and only for a message from the window
# that framed it, on its own origin. It never sends.

BOX = ".ap-composer input[name=message]"

#: target None means the shell's own origin, which is what task-panel.js
#: uses. "*" is only for the cross-origin case: with a named target the
#: browser would drop the message before the page ever saw it, and the test
#: would pass without the page checking anything.
POST_TO_PANE = (
    "([ask, target]) => document.getElementById('pane').contentWindow"
    ".postMessage({type: 'aiui-agents-ask', ask: ask},"
    " target || location.origin)")

#: Records every message type the pane receives, so a test that expects the
#: box to stay empty can also prove the message did arrive and was refused.
LISTEN = ("() => { window.__got = [];"
          " addEventListener('message', e => window.__got.push("
          "e.data && e.data.type)); }")


def _shell(browser, server, host="127.0.0.1", frame=None):
    pg = browser.new_page(viewport={"width": 1400, "height": 950})
    pg.set_default_timeout(6000)
    sent = []

    def route(r):
        if r.request.method == "POST":
            sent.append(r.request.url)
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps({"items": [], "total": 0}))

    pg.route("**/api/**", route)
    pg.route("**/tasks/**", route)
    url = "http://%s:%d/shell" % (host, server.server_address[1])
    if frame:
        url += "?frame=" + urllib.parse.quote(frame, safe="")
    pg.goto(url)
    pg.frame_locator("#pane").locator(BOX).wait_for(state="attached")
    pg.wait_for_timeout(350)
    pg.frame_locator("#pane").locator("body").evaluate(LISTEN)
    pg.sent = sent
    return pg


def _pane(pg):
    return pg.frame_locator("#pane")


def _arrived(pg):
    return _pane(pg).locator("body").evaluate("() => window.__got")


def test_the_shell_can_hand_the_pane_a_question(browser, server):
    pg = _shell(browser, server)
    try:
        pg.evaluate(POST_TO_PANE, ["Ada, weekly review", None])
        pg.wait_for_timeout(200)
        assert _pane(pg).locator(BOX).input_value() == "Ada, weekly review"
        assert _pane(pg).locator(BOX).evaluate(
            "e => e === document.activeElement"), (
            "the box was filled but not focused, unlike ?ask=")
    finally:
        pg.close()


def test_a_question_from_the_shell_is_not_sent(browser, server):
    pg = _shell(browser, server)
    try:
        pg.evaluate(POST_TO_PANE, ["Ada, weekly review", None])
        pg.wait_for_timeout(300)
        assert "aiui-agents-ask" in _arrived(pg)
        assert not [u for u in pg.sent if "chat/send" in u], pg.sent
    finally:
        pg.close()


def test_a_message_that_is_not_from_the_parent_is_ignored(browser, server):
    """The pane posting to itself stands in for any other frame on the same
    origin: right origin, wrong source."""
    pg = _shell(browser, server)
    try:
        _pane(pg).locator("body").evaluate(
            "() => window.postMessage({type: 'aiui-agents-ask',"
            " ask: 'typed by someone else'}, location.origin)")
        pg.wait_for_timeout(200)
        assert "aiui-agents-ask" in _arrived(pg), "the message never arrived"
        assert _pane(pg).locator(BOX).input_value() == ""
    finally:
        pg.close()


def test_a_parent_on_another_origin_is_ignored(browser, server):
    """Right source, wrong origin: a page on localhost framing the agents
    page on 127.0.0.1 must not be able to type into it."""
    port = server.server_address[1]
    pg = _shell(browser, server, host="localhost",
                frame="http://127.0.0.1:%d/agents.html" % port)
    try:
        pg.evaluate(POST_TO_PANE, ["typed by another site", "*"])
        pg.wait_for_timeout(200)
        assert "aiui-agents-ask" in _arrived(pg), "the message never arrived"
        assert _pane(pg).locator(BOX).input_value() == ""
    finally:
        pg.close()


def test_a_standalone_page_ignores_the_message(browser, server):
    """Not framed, there is no shell, and window.parent is the page itself,
    so a source check alone would let the page's own posts through."""
    pg = _open(browser, server)
    try:
        pg.evaluate(
            "() => window.postMessage({type: 'aiui-agents-ask',"
            " ask: 'nobody asked'}, location.origin)")
        pg.wait_for_timeout(200)
        assert pg.input_value(BOX) == ""
    finally:
        pg.close()


@pytest.mark.parametrize("ask", [42, None, "   "])
def test_a_question_that_is_not_text_is_ignored(browser, server, ask):
    pg = _shell(browser, server)
    try:
        pg.evaluate(POST_TO_PANE, [ask, None])
        pg.wait_for_timeout(200)
        assert "aiui-agents-ask" in _arrived(pg)
        assert _pane(pg).locator(BOX).input_value() == ""
    finally:
        pg.close()


def test_an_overlong_question_is_cut_to_the_shells_limit(browser, server):
    pg = _shell(browser, server)
    try:
        pg.evaluate(POST_TO_PANE, ["x" * 2500, None])
        pg.wait_for_timeout(200)
        assert len(_pane(pg).locator(BOX).input_value()) == 2000
    finally:
        pg.close()
```

**Step 2: Run it to verify it fails**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_agents_ask_prefill.py -q
```
Expected: `2 failed, 12 passed`. Measured: `test_the_shell_can_hand_the_pane_a_question` fails with `assert '' == 'Ada, weekly review'`; `test_an_overlong_question_is_cut_to_the_shells_limit` with `assert 0 == 2000`. The negative tests pass today because nothing listens; their `_arrived` checks prove each message really reached the frame (the localhost to 127.0.0.1 cross-origin case was verified to deliver in this environment).

**Step 3: Minimal implementation**

`static/agents.html` lines 2819-2835. Old:
```js
  (function () {
    try {
      var ask = new URLSearchParams(location.search).get("ask");
      if (!ask) return;
      var box = document.querySelector(".ap-composer input[name=message]");
      if (!box) return;
      box.value = ask;
      box.focus();
      // Taken out of the address bar once it is in the box. Left there, F5
      // would put it back after the person cleared it, and a URL copied out
      // of the bar would carry somebody else's question.
      var url = location.pathname + location.hash;
      history.replaceState(null, "", url);
    } catch (e) {
      console.warn("[agents] could not read the asked question", e);
    }
  })();
```
New:
```js
  (function () {
    // The one way into the box, whoever is asking: the ?ask= link below and
    // the shell's aiui-agents-ask message both come through here.
    function prefillAsk(text) {
      var box = document.querySelector(".ap-composer input[name=message]");
      if (!box) return false;
      box.value = text;
      box.focus();
      return true;
    }

    try {
      var ask = new URLSearchParams(location.search).get("ask");
      if (ask && prefillAsk(ask)) {
        // Taken out of the address bar once it is in the box. Left there, F5
        // would put it back after the person cleared it, and a URL copied out
        // of the bar would carry somebody else's question.
        var url = location.pathname + location.hash;
        history.replaceState(null, "", url);
      }
    } catch (e) {
      console.warn("[agents] could not read the asked question", e);
    }

    // The shell (task-panel.js) opening this pane with a question:
    // {type: "aiui-agents-ask", ask}. Only from the window that framed this
    // page and only from this origin. Without both, any page that framed
    // this one, or any frame beside it, could type into the composer. It
    // fills and stops, like ?ask=: nothing is ever sent for the person.
    window.addEventListener("message", function (ev) {
      if (window.parent === window) return;
      if (ev.source !== window.parent) return;
      if (ev.origin !== location.origin) return;
      var msg = ev.data;
      if (!msg || msg.type !== "aiui-agents-ask") return;
      if (typeof msg.ask !== "string" || !msg.ask.trim()) return;
      prefillAsk(msg.ask.slice(0, 2000));
    });
  })();
```
(The receiver does not trim: the shell already trims, and `?ask=` never trimmed, so `"Iris, "` keeps its trailing space either way. It caps at 2000 to match the shell.)

**Step 4: Run it to verify it passes**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_agents_ask_prefill.py -q
```
Expected: `14 passed` (the 5 original `?ask=` tests included, about 11 s).

Then the full set:
```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/test_agent_chat_page.py tests/test_static_page_js.py tests/test_agents_page_access.py tests/test_agents_page_memory.py tests/browser/test_agents_ask_prefill.py tests/browser/test_agents_page_fit.py tests/browser/test_agents_page_a11y.py tests/browser/test_agents_page.py tests/browser/test_office_inline.py tests/browser/test_agents_tools_live.py tests/browser/test_embedded_page_chrome.py tests/browser/test_agent_chat_turn_targets.py -q
```
Expected: `1 failed, 302 passed` (about 3 min 25 s), the failure being the pre-existing `test_element_ids_are_unique[office.html]`.

**Step 5: Commit**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO" && git add mcp-servers/tasks/static/agents.html mcp-servers/tasks/tests/browser/test_agents_ask_prefill.py && git commit -m "Agents page: take a question from the shell without sending it

The page now accepts {type: aiui-agents-ask, ask} from the window that
frames it, on its own origin only, and fills the composer through the same
function the ?ask= link uses. It never sends. Messages from other frames,
other origins, or a page that is not framed at all are ignored.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### After all three tasks (not a code step, but required before anyone says done)
- Look at it in a browser at 1920x1080 and 390x844: the composer ring, the agent form with a focused field, Connections opened from the form. Measured screenshots from the patched copies matched expectations at 1500x1000 (ring on composer and search box, skill search no longer a white box, Connections above the form).
- Run Impeccable's checker on the changed files and re-measure contrast, per the design doc's Testing section.
- Deploy is not part of this plan. tasks bakes /app/static into its image: copy the three files to the host, rebuild, then compare host, container and HTTPS bytes.


**Open questions:**
- Merge order with other P0 drafters: the model-default task edits openForm (agents.html 2342-2372) just above this plan's anchor at 2388-2391; the office-links task edits the office listener at 3114-3145 (aiui-office-open / aiui-office-edit). Anchors are distinct strings, but whoever lands second should re-run Task 2's tests. An aiui-office-edit handler that calls openForm(agent) will now move focus into the form and return it to the office iframe on close, which seems right.
- Pre-existing violations of the 'every message listener checks origin and source' rule, not fixed here: the aiui:connections-changed listener (agents.html 1382-1387) checks neither, and openConnections posts aiui:open-connections with targetOrigin '*' (agents.html 2662). Adding a parent-source check there would break test_agents_tools_live.py, which posts that message from the page itself (lines 306 and 616). Fix in a separate task?
- No focus trap: aria-modal is set and focus moves in and back, as DESIGN.md asks, but Tab can still leave an open dialog for the page underneath. Add a trap now or in Phase 1?
- Other hard-coded fallbacks outside this scope remain: var(--accent, #6366f1) at agents.html 214-215 and 670, and .saved uses var(--card, #17171c) and var(--text, #e7e7ea) where --card does not exist. Text sizes 10.5/11/11.5/12.5/13.5px still break the five-sizes rule; that is Phase 1 work.
- The receiver caps an ask at 2000 characters and ignores blank or non-string asks, but does not trim; the shell is specified to trim. Confirm the shell drafter trims, otherwise leading whitespace from a link would reach the box.
- End-to-end proof of aiui-agents-ask needs the shell side (task-panel.js) from another task and a real Open WebUI page; the tests here use a minimal stand-in shell.

# Draft: P0-4 model default and grouping

## P0-4: a new agent starts on the platform default, the model list puts Recommended first, and models that cannot chat are left out

Today the agent form fills `#agent-base` from Open WebUI's `GET /api/models`. For a new agent it then picks the first option. In production that first option is the "Webhook Automation" pipe. The server's default is `AGENT_DEFAULT_MODEL`, which is `nvidia/nemotron-3-super-120b-a12b:free` (read from the tasks container on 2026-10-05), but nothing sends it to the browser.

The fix has two tasks:
1. Server: `GET /api/tasks/agents/tools` also returns `default_model`. The form already loads this endpoint in `loadTools()`.
2. Browser: `openForm` builds a "Recommended" optgroup and an "All models" optgroup. Recommended holds the default, then the models this user's own agents use. A new agent starts on the first recommended model. Models that cannot chat are left out by exact id, next to the existing `CALLBACK_MODELS` filter.

Run every command from `C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks` in Git Bash. Files check out with CRLF line endings, and the Edit tool handles that.

---

### Task 1: The tools endpoint sends the platform default model

**Files:**
- Modify: `mcp-servers/tasks/routes_agents.py` lines 645-648 (`@router.get("/tools")` / `list_tools`)
- Test: `mcp-servers/tasks/tests/test_agent_tools_endpoint.py`. Append after the last line, line 122 (`assert "connections.html" not in routes_agents.CONNECT_URL`).

Why here and not in `tools_for_email`: `routes_agent_turn.py:108-109` also calls `tools_for_email` to give every agent turn its tool list. Only the form needs the default, so it goes on the route.

**Step 1: Write the failing test.** Append this to the end of `tests/test_agent_tools_endpoint.py`. The file already imports `AsyncMock`, `patch` and `routes_agents`. The HTTP client follows the ASGI pattern in `tests/test_agent_memory_routes.py:254-262`.

```python


# --- which model a new agent starts on --------------------------------------
# Measured 2026-10-05: GET /api/models lists the Webhook Automation pipe first,
# and the form put a new agent on whatever came first. The form already loads
# GET /api/tasks/agents/tools, so that response is where it learns the
# platform default (AGENT_DEFAULT_MODEL, read by _default_model).

def _tools_client(monkeypatch, installed=("documents",)):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from auth import CurrentUser, current_user

    app = FastAPI()
    app.include_router(routes_agents.router, prefix="/api/tasks")
    app.dependency_overrides[current_user] = (
        lambda: CurrentUser(email="asker@example.com"))
    monkeypatch.setattr(routes_agents, "_installed_tool_ids",
                        AsyncMock(return_value=list(installed)))
    monkeypatch.setattr(routes_agents, "_connected_providers",
                        AsyncMock(return_value=set()))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def test_the_form_is_told_the_platform_default_model(monkeypatch):
    """Over HTTP, on the exact path agents.html fetches, because that is the
    layer the browser reaches."""
    monkeypatch.setenv("AGENT_DEFAULT_MODEL", "some/default-model:free")
    r = await _tools_client(monkeypatch).get("/api/tasks/agents/tools")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["default_model"] == "some/default-model:free"
    # The tools are still there, unchanged, beside it.
    assert [t["id"] for t in body["tools"]][0] == "documents"


async def test_the_default_is_the_fallback_when_nothing_is_set(monkeypatch):
    monkeypatch.delenv("AGENT_DEFAULT_MODEL", raising=False)
    r = await _tools_client(monkeypatch).get("/api/tasks/agents/tools")
    assert r.json()["default_model"] == "nvidia/nemotron-3-super-120b-a12b:free"


async def test_the_listing_every_agent_turn_reads_does_not_change(monkeypatch):
    """tools_for_email also feeds every agent turn its tool list
    (routes_agent_turn._every_tool_for). The default belongs to the form's
    response only, so that listing keeps exactly the shape it had."""
    monkeypatch.setenv("AGENT_DEFAULT_MODEL", "some/default-model:free")
    with patch.object(routes_agents, "_installed_tool_ids",
                      new=AsyncMock(return_value=["documents"])), \
         patch.object(routes_agents, "_connected_providers",
                      new=AsyncMock(return_value=set())):
        out = await routes_agents.tools_for_email("x@example.com")
    assert set(out) == {"tools"}
```

**Step 2: Run it to verify it fails.**
```bash
DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/test_agent_tools_endpoint.py -q -p no:cacheprovider
```
Expected result: `2 failed, 11 passed`.
- Both `test_the_form_is_told_the_platform_default_model` and `test_the_default_is_the_fallback_when_nothing_is_set` fail with `KeyError: 'default_model'`.
- `test_the_listing_every_agent_turn_reads_does_not_change` passes before and after. It is a guard, not a red test.

**Step 3: Minimal implementation.** In `routes_agents.py`, replace these old lines (645-648):
```python
@router.get("/tools")
async def list_tools(user: CurrentUser = Depends(current_user)) -> dict:
    """What the agent form may offer the signed-in caller right now."""
    return await tools_for_email(user.email)
```
with these new lines:
```python
@router.get("/tools")
async def list_tools(user: CurrentUser = Depends(current_user)) -> dict:
    """What the agent form may offer the signed-in caller right now, and the
    model a new agent should start on.

    default_model rides here rather than in tools_for_email, because that
    listing also feeds every agent turn its tools and has no use for it.
    Without it the form started a new agent on whatever /api/models listed
    first, which on production is the Webhook Automation pipe.
    """
    out = await tools_for_email(user.email)
    return {**out, "default_model": _default_model()}
```
`_default_model()` already exists at lines 80-88 and reads the env var at call time.

**Step 4: Run it to verify it passes.**
```bash
DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/test_agent_tools_endpoint.py -q -p no:cacheprovider
```
Expected: `13 passed`. Then run the neighbours:
```bash
DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/test_agent_tools_endpoint.py tests/test_agent_seed.py tests/test_agent_tool_reach.py tests/test_agents_page_access.py -q -p no:cacheprovider
```
Expected: `38 passed`. The baseline today is 35, so this adds 3.

**Step 5: Commit.**
```bash
git add mcp-servers/tasks/routes_agents.py mcp-servers/tasks/tests/test_agent_tools_endpoint.py
git commit -m "Agents tools endpoint says which model a new agent starts on

GET /api/tasks/agents/tools now carries default_model (AGENT_DEFAULT_MODEL),
so the agent form can start a new agent on the platform default instead of
whatever /api/models lists first. tools_for_email is unchanged because every
agent turn reads it too.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The form starts a new agent on the default, groups Recommended first, and leaves out models that cannot chat

**Files:**
- Modify: `mcp-servers/tasks/static/agents.html`
  - line 1015 (`var state = ...`)
  - lines 1942-1943 (inside `loadTools`)
  - line 2219 (`var CALLBACK_MODELS = ...`)
  - lines 2349-2356 (the option builder in `openForm`)
  - lines 2367-2368 (the marked-option label)
- Test: `mcp-servers/tasks/tests/browser/test_agents_page.py`. Insert a new section after line 1420 (the end of `test_the_warning_clears_when_you_pick_something_else`) and before line 1423 (`# --- tools: everything, or only what you pick ---`).

**Step 1: Write the failing test.** Paste this block between line 1420 and the `# --- tools: everything, or only what you pick` comment.

It uses the file's own fixtures and helpers: `page`, `MODELS`, `_api_models_envelope`, `_open_form` and `_fill`. Routes added later win over the fixture's `**/api/**` catch-all. A `page.reload()` re-runs the real bootstrap, including `loadTools()`. `**/api/models*` does not match `/api/v1/models/list`, and `test_agents_tools_live.py:339` already uses that same glob.

```python


# --- which model a new agent starts on ---------------------------------------

# Measured 2026-10-05 on GET /api/models in production: 133 base models, and
# the first one is the Webhook Automation pipe, so that is what a new agent
# started on. The platform default (AGENT_DEFAULT_MODEL) was
# nvidia/nemotron-3-super-120b-a12b:free, which 11 of the 12 agents on the
# platform run on. The rows below keep production's order for the ones that
# matter: a pipe first, then models that cannot answer a chat turn at all,
# with the default and a real chat model further down.

DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"


def _base_row(model_id, name):
    return {"id": model_id, "name": name, "user_id": None,
            "base_model_id": None, "params": {}, "meta": {},
            "access_grants": [], "is_active": True, "write_access": False,
            "created_at": 1, "updated_at": 1, "user": None}


# One id per kind that NON_CHAT_MODELS names, plus the two callback pipes.
NOT_FOR_AN_AGENT = [
    "webhook_automation.webhook-automation", "webhook_pipe", "gpt-image-1",
    "chatgpt-image-latest", "sora-2", "gpt-4o-mini-transcribe",
    "gpt-realtime", "gpt-audio", "omni-moderation-latest",
    "gpt-3.5-turbo-instruct", "io.io", "auto_router.auto",
]

PROD_ORDER = [
    _base_row("webhook_automation.webhook-automation", "Webhook Automation"),
    _base_row("fusion_pipe.fusion", "Fusion"),
    _base_row("auto_smart.auto-smart", "Auto (Smart)"),
    _base_row("gpt-image-1", "gpt-image-1"),
    _base_row("chatgpt-image-latest", "chatgpt-image-latest"),
    _base_row("sora-2", "sora-2"),
    _base_row("gpt-4o-mini-transcribe", "gpt-4o-mini-transcribe"),
    _base_row("gpt-realtime", "gpt-realtime"),
    _base_row("gpt-audio", "gpt-audio"),
    _base_row("omni-moderation-latest", "omni-moderation-latest"),
    _base_row("gpt-3.5-turbo-instruct", "gpt-3.5-turbo-instruct"),
    _base_row("gpt-5.5", "gpt-5.5"),
    _base_row("webhook_pipe", "webhook_pipe"),
    _base_row("io.io", "IO"),
    _base_row(DEFAULT_MODEL, DEFAULT_MODEL),
] + MODELS


def _reload_with(page, default_model=None, models=PROD_ORDER):
    """Re-run the page's own bootstrap against a different /api/models and
    /agents/tools. Routes added later win over the fixture's catch-all, and
    the default only arrives through loadTools(), which runs on page load."""
    tools = {"tools": [{"id": "documents", "label": "Documents",
                        "connected": True, "connect_url": ""}]}
    if default_model is not None:
        tools["default_model"] = default_model
    page.route("**/api/tasks/agents/tools*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(tools)))
    page.route("**/api/models*", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps(_api_models_envelope(models))))
    page.reload()
    page.wait_for_function(
        "() => window.__aiuiAgents && window.__aiuiAgents.ready")


def _groups(page):
    """[(label, [option values])] for every optgroup in the model select."""
    return page.locator("#agent-base optgroup").evaluate_all(
        "gs => gs.map(g => [g.label,"
        " Array.from(g.querySelectorAll('option')).map(o => o.value)])")


def _offered(page):
    return page.locator("#agent-base option").evaluate_all(
        "els => els.map(e => e.value)")


def test_a_new_agent_starts_on_the_platform_default(page):
    _reload_with(page, default_model=DEFAULT_MODEL)
    _open_form(page)
    assert page.locator("#agent-base").input_value() == DEFAULT_MODEL, (
        "a new agent started on whatever the list had first")


def test_a_new_agent_saves_with_the_platform_default(page):
    """The value has to reach the request, not just the dropdown."""
    _reload_with(page, default_model=DEFAULT_MODEL)
    _fill(page, name="Startsright", instructions="Something.")
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    assert json.loads(page.sent[-1]["body"])["base_model_id"] == DEFAULT_MODEL


def test_recommended_comes_first_with_the_default_and_your_own_models(page):
    """Recommended is data, not taste: the platform default, then every model
    one of YOUR agents already runs on. gpt-4o-mini is in it because your
    agents in MODELS use it. gpt-5.5 is used only by somebody else's agent,
    so it stays under All models."""
    _reload_with(page, default_model=DEFAULT_MODEL)
    page.evaluate(
        "() => { const s = window.__aiuiAgents.state.agents"
        ".find(x => x.id === 'agent-shared-c3d4');"
        " s.base_model_id = 'gpt-5.5'; }")
    _open_form(page)
    groups = _groups(page)
    assert [g[0] for g in groups] == ["Recommended", "All models"], groups
    assert groups[0][1] == [DEFAULT_MODEL, "gpt-4o-mini"], groups[0]
    assert "gpt-5.5" in groups[1][1], groups[1]
    assert DEFAULT_MODEL not in groups[1][1], "the default is listed twice"
    assert "gpt-4o-mini" not in groups[1][1], "a model is listed twice"


def test_models_that_cannot_answer_a_chat_are_not_offered(page):
    _reload_with(page, default_model=DEFAULT_MODEL)
    _open_form(page)
    offered = _offered(page)
    for model_id in NOT_FOR_AN_AGENT:
        assert model_id not in offered, (model_id, offered)


def test_the_exclusion_is_by_id_and_keeps_every_chat_model(page):
    """An earlier guard learned this: filtering by a name pattern would take
    Auto (Smart) with it. The list is exact ids, so the pipes that DO chat
    and an ordinary model all stay."""
    _reload_with(page, default_model=DEFAULT_MODEL)
    _open_form(page)
    offered = _offered(page)
    for model_id in ("auto_smart.auto-smart", "fusion_pipe.fusion",
                     "gpt-5.5", "gpt-4o-mini", DEFAULT_MODEL):
        assert model_id in offered, (model_id, offered)


def test_without_a_server_default_a_new_agent_starts_on_a_model_you_use(page):
    """An older tasks service sends no default_model. The form must still
    not fall back to the pipe that happens to be listed first."""
    _reload_with(page, default_model=None)
    _open_form(page)
    assert page.locator("#agent-base").input_value() == "gpt-4o-mini"
    assert _groups(page)[0] == ["Recommended", ["gpt-4o-mini"]]


def test_a_default_that_is_not_on_offer_is_not_forced(page):
    """A default the account cannot see, or one that cannot chat, is left
    out rather than shown as a choice that would fail."""
    _reload_with(page, default_model="gpt-image-1")
    _open_form(page)
    assert "gpt-image-1" not in _offered(page)
    assert page.locator("#agent-base").input_value() == "gpt-4o-mini"


def test_editing_keeps_the_agents_own_model_not_the_default(page):
    """Green before this change as well: a guard that the default never
    overrides an existing agent's model."""
    _reload_with(page, default_model=DEFAULT_MODEL)
    page.locator('[data-agent-id="agent-mine-a1b2"] [data-act="edit"]').click()
    page.wait_for_selector("#agent-form", state="visible")
    assert page.locator("#agent-base").input_value() == "gpt-4o-mini"


def test_an_agent_already_on_a_non_chat_model_shows_it_marked(page):
    """No agent is on one today (12 agents, two models, measured), but the
    form must not silently move one that is: it shows the model, marked."""
    _reload_with(page, default_model=DEFAULT_MODEL)
    page.evaluate(
        "() => { const a = window.__aiuiAgents.state.agents"
        ".find(x => x.id === 'agent-mine-a1b2');"
        " a.base_model_id = 'gpt-image-1';"
        " window.__aiuiAgents.openForm(a); }")
    page.wait_for_selector("#agent-form", state="visible")
    assert page.locator("#agent-base").input_value() == "gpt-image-1"
    assert "gpt-image-1 (cannot run an agent)" in (
        page.locator("#agent-base").inner_text())
```

**Step 2: Run it to verify it fails.**
```bash
DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_agents_page.py -q -p no:cacheprovider -k "platform_default or recommended_comes or cannot_answer or exclusion_is_by_id or without_a_server_default or not_on_offer or editing_keeps_the_agents_own or non_chat_model_shows"
```
Expected result: `7 failed, 2 passed, 125 deselected`. These are the failure messages I saw:

| Test | Failure |
|---|---|
| `test_a_new_agent_starts_on_the_platform_default` | `a new agent started on whatever the list had first ... + webhook_automation.webhook-automation` |
| `test_a_new_agent_saves_with_the_platform_default` | `'webhook_auto...ok-automation' == 'nvidia/nemot...20b-a12b:free'` |
| `test_recommended_comes_first_with_the_default_and_your_own_models` | `assert [] == ['Recommended', 'All models']` |
| `test_models_that_cannot_answer_a_chat_are_not_offered` | `'webhook_automation.webhook-automation' not in [...]` |
| `test_without_a_server_default_a_new_agent_starts_on_a_model_you_use` | `'webhook_auto...ok-automation' == 'gpt-4o-mini'` |
| `test_a_default_that_is_not_on_offer_is_not_forced` | `'gpt-image-1' not in [...]` |
| `test_an_agent_already_on_a_non_chat_model_shows_it_marked` | `'gpt-image-1 (cannot run an agent)' in 'Webhook Automation\nFusion...'` |

The two that pass today are guards: `test_the_exclusion_is_by_id_and_keeps_every_chat_model` and `test_editing_keeps_the_agents_own_model_not_the_default`.

**Step 3: Minimal implementation.** Make five edits in `static/agents.html`. Each anchor is unique today (I grep-counted each one as 1). Keep plain hyphens only: the page must contain no em or en dashes (`tests/test_agents_page_access.py:88`).

Edit 3a. State, line 1015. Old:
```js
    var state = { me: null, email: null, agents: [], models: [], query: "" };
```
New:
```js
    // defaultModel is the platform default, sent by GET /api/tasks/agents/tools
    // (AGENT_DEFAULT_MODEL on the server). Null until that answers, or when an
    // older service does not send it.
    var state = { me: null, email: null, agents: [], models: [], query: "",
                  defaultModel: null };
```

Edit 3b. `loadTools`, lines 1942-1943. Old:
```js
          var body = await r.json();
          if (body && Array.isArray(body.tools)) tools = body.tools;
```
New:
```js
          var body = await r.json();
          if (body && Array.isArray(body.tools)) tools = body.tools;
          if (body && typeof body.default_model === "string"
              && body.default_model) {
            state.defaultModel = body.default_model;
          }
```

Edit 3c. The exclusion list, line 2219. Old:
```js
    var CALLBACK_MODELS = ["auto_router.auto", "io.io"];
```
New:
```js
    var CALLBACK_MODELS = ["auto_router.auto", "io.io"];

    // Models that cannot answer a chat turn at all, so an agent on one can
    // never run. Exact ids, never a name pattern: a pattern is how Auto
    // (Smart) nearly went missing once. Every id here was on GET /api/models
    // in production on 2026-10-05, and none had ever run an agent turn
    // (tasks.agent_run, same day). A new one shows up under All models until
    // somebody adds it here, which is the safe way round.
    var NON_CHAT_MODELS = [
      // Automation entry points, not chat. The webhook handler calls the
      // first one with a wrapped payload; the second is a Pipelines pipe.
      "webhook_automation.webhook-automation", "webhook_pipe",
      // Image and video generation.
      "gpt-image-1", "gpt-image-1-mini", "gpt-image-1.5", "gpt-image-2",
      "gpt-image-2-2026-04-21", "gpt-image-2.5-flare",
      "gpt-image-2.5-flare-2026-09-08", "gpt-image-2.5-sunburst",
      "gpt-image-2.5-sunburst-2026-09-08", "chatgpt-image-latest",
      "sora-2", "sora-2-pro",
      // Speech to text.
      "gpt-transcribe", "gpt-live-transcribe", "gpt-4o-transcribe",
      "gpt-4o-transcribe-diarize", "gpt-4o-mini-transcribe",
      "gpt-4o-mini-transcribe-2025-03-20",
      "gpt-4o-mini-transcribe-2025-12-15",
      // Realtime voice sessions.
      "gpt-realtime", "gpt-realtime-1.5", "gpt-realtime-2",
      "gpt-realtime-2025-08-28", "gpt-realtime-2.1", "gpt-realtime-2.1-mini",
      "gpt-realtime-mini", "gpt-realtime-mini-2025-12-15",
      "gpt-realtime-translate",
      // Audio models, which need audio in or out on every request.
      "gpt-audio", "gpt-audio-1.5", "gpt-audio-2025-08-28", "gpt-audio-mini",
      "gpt-audio-mini-2025-10-06", "gpt-audio-mini-2025-12-15",
      // Moderation classifiers.
      "omni-moderation-latest", "omni-moderation-2024-09-26",
      // Completions only, with no chat endpoint.
      "gpt-3.5-turbo-instruct", "gpt-3.5-turbo-instruct-0914"
    ];
```

Edit 3d. `openForm`, lines 2349-2356. Keep the existing "Auto (Free) and IO are pipes..." comment above it unchanged. Old:
```js
      state.models.filter(function (m) {
        return !isAgent(m) && CALLBACK_MODELS.indexOf(m.id) === -1;
      }).forEach(function (m) {
        var o = document.createElement("option");
        o.value = m.id; o.textContent = m.name || m.id;
        base.appendChild(o);
      });
      if (agent && agent.base_model_id) {
```
New:
```js
      // Models that cannot chat at all are left out the same way.
      var offered = state.models.filter(function (m) {
        return !isAgent(m) && CALLBACK_MODELS.indexOf(m.id) === -1
          && NON_CHAT_MODELS.indexOf(m.id) === -1;
      });
      var offeredIds = offered.map(function (m) { return m.id; });
      // Recommended is data, not taste: the platform default first, then
      // every model one of your own agents already runs on. Only models that
      // are on offer, and each one once.
      var recommended = [];
      function recommend(id) {
        if (id && offeredIds.indexOf(id) !== -1
            && recommended.indexOf(id) === -1) {
          recommended.push(id);
        }
      }
      recommend(state.defaultModel);
      state.agents.forEach(function (a) {
        if (a.user_id === state.me) recommend(a.base_model_id);
      });
      function addGroup(label, models) {
        if (!models.length) return;
        var g = document.createElement("optgroup");
        g.label = label;
        models.forEach(function (m) {
          var opt = document.createElement("option");
          opt.value = m.id; opt.textContent = m.name || m.id;
          g.appendChild(opt);
        });
        base.appendChild(g);
      }
      addGroup("Recommended", recommended.map(function (id) {
        return offered[offeredIds.indexOf(id)];
      }));
      addGroup("All models", offered.filter(function (m) {
        return recommended.indexOf(m.id) === -1;
      }));
      // A new agent starts on the first recommended model: the platform
      // default when it is on offer, otherwise one your agents already use.
      // It used to start on whatever /api/models listed first, which on
      // production is the Webhook Automation pipe.
      if (!agent && recommended.length) base.value = recommended[0];
      if (agent && agent.base_model_id) {
```
Notes on 3d:
- Option text is set through `textContent`, as before, so model names stay text. No `innerHTML` is added.
- The existing edit path is unchanged: `base.value = agent.base_model_id`, plus the marked option inserted with `base.insertBefore(o, base.firstChild)`. That still works when the select's first child is an optgroup.
- `duplicate()` calls `openForm(null)` and then sets `base.value` to the source agent's model, so it still carries the model across.

Edit 3e. The marked-option label, lines 2367-2368. Old:
```js
            + (CALLBACK_MODELS.indexOf(agent.base_model_id) !== -1
                 ? " (cannot run an agent)" : " (not available)");
```
New:
```js
            + (CALLBACK_MODELS.indexOf(agent.base_model_id) !== -1
               || NON_CHAT_MODELS.indexOf(agent.base_model_id) !== -1
                 ? " (cannot run an agent)" : " (not available)");
```

**Step 4: Run it to verify it passes.**
1. The new tests:
   ```bash
   DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_agents_page.py -q -p no:cacheprovider -k "platform_default or recommended_comes or cannot_answer or exclusion_is_by_id or without_a_server_default or not_on_offer or editing_keeps_the_agents_own or non_chat_model_shows"
   ```
   Expected: `9 passed, 125 deselected`.
2. The whole file:
   ```bash
   DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_agents_page.py -q -p no:cacheprovider
   ```
   Expected: `134 passed`, about 2 minutes. The baseline today is 125.
3. Every other browser suite that loads agents.html:
   ```bash
   DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_agents_page_fit.py tests/browser/test_agents_tools_live.py tests/browser/test_agents_ask_prefill.py tests/browser/test_office_inline.py tests/browser/test_embedded_page_chrome.py -q -p no:cacheprovider
   ```
   Expected: `85 passed`, the same as the baseline today.
4. The source-level checks, including the no-dash test:
   ```bash
   DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/test_agents_page_access.py tests/test_agents_page_memory.py tests/test_agent_chat_page.py tests/test_agent_name_header.py -q -p no:cacheprovider
   ```
   Expected: all pass. None of these files pins the model dropdown code (grep-checked).

**Step 5: Commit.**
```bash
git add mcp-servers/tasks/static/agents.html mcp-servers/tasks/tests/browser/test_agents_page.py
git commit -m "New agents start on the platform default model, Recommended first

The model list now has a Recommended group (the server's default model, then
every model your own agents already use) and an All models group. A new agent
starts on the first recommended model instead of the first model Open WebUI
lists, which in production is the Webhook Automation pipe. Models that cannot
answer a chat (image, video, transcription, realtime, audio, moderation,
completions only, and the two webhook pipes) are left out by exact id, beside
the existing callback pipe filter. Editing an agent keeps its own model, and
an agent already on a left-out model shows it marked as unable to run.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Live check after deploy (not part of either commit)
The tasks image bakes in `/app/static`, so `scp` both changed files to the server before `up -d --build tasks`.

Then check:
1. `curl -fsS -H "Authorization: Bearer <token>" https://ai-ui.coolestdomain.win/api/tasks/agents/tools` returns a `default_model` key. Today the keys are only `['tools']` (verified).
2. In a browser, open AI agents, then New agent. The Model select shows `nvidia/nemotron-3-super-120b-a12b:free` under "Recommended", and "Webhook Automation" is not in the list.

### Evidence for the exclusion list (40 ids)
**Verified on 2026-10-05:**
1. All 40 ids are in the live `GET /api/models` response (137 rows: 134 base models and 3 agents).
2. None of them is the base model of any of the 12 agents on the platform. A SELECT on `public.model` shows 11 agents on `nvidia/nemotron-3-super-120b-a12b:free` and 1 on `gpt-5.5`.
3. None appears in `tasks.agent_run.model`. The models that have ever run an agent are nemotron-3-super, nemotron-3-ultra, nemotron-3.5-lightning, cohere/north-mini-code, nex-n2.5-mini, nex-n2.5-pro and gpt-5.5.
4. `auto_smart.auto-smart` (Auto (Smart)) is not in the list.
5. After filtering, 93 of the 134 base models are still offered.

**By category:**
1. **`webhook_automation.webhook-automation` (verified):**
   - Its source is `open-webui-functions/webhook_pipe.py`. The docstring says webhook-handler calls it with `model="webhook_automation.webhook-automation"` for automation payloads.
   - In `/api/models` its row has `pipe.type=pipe`, and it is the first row, which is the bug.
2. **`webhook_pipe` (verified):** its `/api/models` row has `pipeline.type=pipe`, `connection_type=external` and `urlIdx=1`, so it comes from the Pipelines container.
3. **Image (inferred):** `gpt-image-*` and `chatgpt-image-latest` are OpenAI Images API models.
4. **Video (inferred):** `sora-2` and `sora-2-pro` are video generation models.
5. **Transcription (inferred):** `*-transcribe*` and `gpt-live-transcribe` are speech-to-text models.
6. **Realtime (inferred):** `gpt-realtime*` are Realtime API (websocket/WebRTC) models.
7. **Audio (inferred):** `gpt-audio*` need audio input or output.
8. **Moderation (inferred):** `omni-moderation-*` are moderation endpoint models.
9. **Completions only (inferred):** `gpt-3.5-turbo-instruct` and `-0914` are legacy completions-only models.

Categories 3-9 are inferred from what OpenAI documents for these model families. I did not probe them, because a probe is a paid POST and live access was GET only.

**TTS and embeddings:** the live list has none (no `tts`, `embed`, `whisper`, `dall-e`, `davinci` or `babbage` ids), so the list adds none.

**Open questions:**
- Models that are probably unusable as agents but not proven, so not excluded: Responses-API-only families (gpt-5-codex, gpt-5.1-codex*, gpt-5.2-codex, gpt-5.3-codex, o1-pro*, gpt-5-pro*, gpt-5.x-pro*, o4-mini-deep-research*), which may fail through Open WebUI's chat completions; and *-search-preview / gpt-5-search-api, which may not support tool calls. Proving it needs a paid POST per model, which was out of scope (GET only). Add them to NON_CHAT_MODELS only after a real probe.
- gpt-live-1 is in the live list and I cannot identify it. It is kept under All models.
- The exclusion list is hard-coded in the page, so a new image or realtime model appears under All models until someone adds its id. The alternative is to have the server send the list beside default_model. I did not do that, to keep this change minimal.
- Saving onto a non-chat model is not refused; only callback pipes are refused. No agent is on one today (verified), and the form now shows such a model marked '(cannot run an agent)'. Decide whether save() should refuse it as it does for CALLBACK_MODELS.
- Recommended includes any model one of your agents uses, even one that is in MODEL_WARNINGS (Auto (Smart), arena-model). The existing warning still shows when it is selected. Decide whether warned models should stay out of Recommended.

# Draft: P0-5 hide stored PASS in history

### Task 1: Stop redrawing stored PASS answers and the routing footer in thread history

**Why (verified 2026-10-05):** `GET https://ai-ui.coolestdomain.win/tasks/agents/chat/thread` for the session owner's room returns 12 agent bubbles. 4 of them are byte-identical to `agent_chat_render.agent_bubble(name, STORED_SMART_PASS)`. `STORED_SMART_PASS` is the 65-character stored text ``"PASS\n\n*Auto (Smart): routed to the paid general model `gpt-5.5`.*"``, already copied from production into `tests/test_agent_chat_room.py:260-261`. I rebuilt that room's messages from the served HTML and replayed them through today's `thread()`, and the output matched the served bytes exactly. The patched `thread()` below draws 8 bubbles, 0 PASS and 0 footers, with the same 8 turns.

**The rule, with the code it comes from:**
- The round already decides what a pass is with `agent_routing.is_pass`. `routes_agent_chat.py:192-195` wraps it, and `:532` stops a NEW pass from being stored. `is_pass` (`agent_routing.py:437-464`) removes `ROUTE_FOOTER` first, then label lines, then compares what is left to `PASS`. History therefore makes the same call on the whole stored text: if `is_pass(content)` is true, no bubble is drawn.
- `ROUTE_FOOTER` (`agent_routing.py:424-426`) only matches the footer when it is the last line and follows a newline (the pattern ends in `\s*\Z`). `is_pass` prepends `"\n"` so it still finds a footer that has nothing before it. History does the same, and strips the result only when a footer was found. All other text is drawn exactly as stored.
- An `awaiting` approval on the same message is still drawn. The round deliberately lets through a pass that came back with a tool call (`_is_pass(answer) and not out.get("pending")`, `routes_agent_chat.py:532`), and `_question_events` stores it with `awaiting` (`routes_agent_chat.py:272-275`). The Yes and No buttons are the point. Only the word PASS goes.
- When nothing is left to show, `thread()` still falls back to `empty_thread()`. This is the existing contract (`agent_chat_render.py:358-362`).

**Files:**
- Modify: `mcp-servers/tasks/agent_chat_render.py` at line 14 (`from urllib.parse import quote`) and lines 344-403 (`def thread`, with its docstring at 345-363 and the assistant branch at 387-395)
- Test: `mcp-servers/tasks/tests/test_agent_chat_render.py` (append after the last line, 305)
- Test: `mcp-servers/tasks/tests/test_agent_chat_room.py` (insert between line 355, the end of `test_the_conversation_is_still_there_after_a_restart`, and line 358, `def test_a_second_person_gets_their_own_room`)

**Step 1: Write the failing tests**

1a. Append the block below to the end of `mcp-servers/tasks/tests/test_agent_chat_render.py`, after line 305 (`    assert GENERIC_FAILURE_REASON in html`).
- It uses the file's own module import `render` and its `CALLS` constant (line 10).
- The message dicts have the shape `routes_agent_chat._run_round` saves (`routes_agent_chat.py:565-567`).
- The user dict has the shape `agent_chat_send` saves (`routes_agent_chat.py:756`).

```python


# --- a stored PASS is protocol, not an answer ------------------------------
#
# PASS is a word in a protocol between routes_agent_chat and the model, and a
# person should never read it (see the comment under `_is_pass(answer)` in
# routes_agent_chat._run_round). The round stopped storing new ones, but rows
# saved before that still hold them, and thread() redrew every one of them as
# a bubble on each load. The shapes below are what the round really stored:
# the dict is _run_round's `messages.append`, and the two contents are a bare
# PASS (the "Ada / PASS" bubble of 2026-09-24) and the Auto (Smart) pass
# copied from production into test_agent_chat_room.py as STORED_SMART_PASS.
# The owner's room still drew that exact 65-character text four times on
# 2026-10-05.

SMART_FOOTER = "\n\n*Auto (Smart): routed to the paid general model `gpt-5.5`.*"
STORED_SMART_PASS = "PASS" + SMART_FOOTER


def _stored(name, content, **extra):
    """One answer, in the shape routes_agent_chat._run_round saves it."""
    m = {"role": "assistant", "agent_id": "agent-" + name.lower(),
         "agent_name": name, "content": content, "replying_to": None}
    m.update(extra)
    return m


def test_a_stored_pass_is_not_drawn_on_the_way_back():
    html = render.thread([
        {"role": "user", "content": "anything new?", "turn_id": "aaa111aaa111"},
        _stored("Ada", "PASS"),
        _stored("Kai", STORED_SMART_PASS),
        _stored("Mia", "Two invoices are due on Friday."),
    ])
    assert html.count('class="am agent"') == 1, "a pass came back as a bubble"
    assert "Two invoices are due on Friday." in html
    assert "PASS" not in html
    assert ">Ada<" not in html and ">Kai<" not in html
    # The question stays, in its own turn. Only the passes go.
    assert html.count('class="aturn"') == 1
    assert "anything new?" in html


def test_a_stored_answer_is_drawn_without_its_route_footer():
    """The footer is the routing pipe talking (auto_smart_pipe.py _footer),
    not the agent. It comes off the last line only, the way is_pass reads
    it, so everything the agent said stays."""
    html = render.thread([
        {"role": "user", "content": "what is due?", "turn_id": "aaa111aaa111"},
        _stored("Mia", "Two invoices are due on Friday." + SMART_FOOTER),
    ])
    assert html.count('class="am agent"') == 1
    assert "Two invoices are due on Friday." in html
    assert "routed to" not in html
    assert "gpt-5.5" not in html


def test_an_answer_that_starts_with_pass_is_still_drawn():
    """Kai's stored reply (STORED_PASS_THEN_ANSWER in test_agent_chat_room.py)
    starts with PASS and then says what it did. is_pass calls that an answer,
    so the thread draws it, word for word."""
    kai = ("PASS\n\n(create-me-a-shoe-website-fe02: I inspected the files. I "
           "read public/index.html and the root index.html, but both read "
           "results were shortened by the tool.)")
    html = render.thread([
        {"role": "user", "content": "check the site", "turn_id": "aaa111aaa111"},
        _stored("Kai", kai),
    ])
    assert html.count('class="am agent"') == 1
    assert "I inspected the files." in html


def test_a_stored_pass_that_asked_permission_keeps_its_question():
    """The round does not treat a pass that came back with a tool call as a
    pass (`_is_pass(answer) and not out.get("pending")`), so _question_events
    stores it with `awaiting`. The Yes and No are what matter, so they stay;
    only the word goes."""
    html = render.thread([
        {"role": "user", "content": "send it", "turn_id": "aaa111aaa111"},
        _stored("Ada", "PASS", awaiting={"ask_id": "q-9", "calls": CALLS}),
    ])
    assert 'id="await-q-9"' in html
    assert "PASS" not in html
    assert 'class="atext md"' not in html, "the pass was drawn above the question"


def test_a_conversation_of_only_passes_falls_back_to_the_empty_state():
    """Nothing left to show is the empty state, as with round bookkeeping
    (test_round_bookkeeping_still_draws_as_nothing)."""
    assert (render.thread([_stored("Ada", STORED_SMART_PASS)])
            == render.empty_thread())
```

1b. In `mcp-servers/tasks/tests/test_agent_chat_room.py`, insert the test below between line 355 and line 358, with two blank lines on each side.
- Line 355 is the end of `test_the_conversation_is_still_there_after_a_restart`: `    assert mod.store.get_session(EMAIL).chat_id == "chat-1"`.
- Line 358 is `def test_a_second_person_gets_their_own_room(monkeypatch):`.

This test goes through the real route (`agent_chat_thread`, `routes_agent_chat.py:1048-1061`) and `_hydrate`. It uses the file's own `_app`, fake store rows, `_hdr`, `ADA`, `MIA`, and the module-level `STORED_SMART_PASS` (line 260).

Old text (unique in the file today; use it as the anchor):
```python
    assert "remember this" in thread
    assert mod.store.get_session(EMAIL).chat_id == "chat-1"


def test_a_second_person_gets_their_own_room(monkeypatch):
```
New:
```python
    assert "remember this" in thread
    assert mod.store.get_session(EMAIL).chat_id == "chat-1"


def test_a_stored_pass_is_not_redrawn_when_the_room_loads(monkeypatch):
    """The other half of test_a_pass_with_a_router_footer_is_still_a_pass.
    Recognising the shape stopped NEW passes being stored. The ones stored
    before that are still in the row, and the thread route drew every one as
    a bubble reading PASS over the route footer: four in the owner's room on
    2026-10-05."""
    app, mod, _, rows = _app(monkeypatch)
    rows[EMAIL] = {
        "id": "chat-1", "user_email": EMAIL, "title": "anything new?",
        "summary": "", "pending": {},
        "messages": [
            {"role": "user", "content": "anything new?",
             "turn_id": "aaa111aaa111"},
            {"role": "assistant", "agent_id": ADA["id"], "agent_name": "Ada",
             "content": STORED_SMART_PASS, "replying_to": None},
            {"role": "assistant", "agent_id": MIA["id"], "agent_name": "Mia",
             "content": "Two invoices are due on Friday.\n\n*Auto (Smart): "
                        "routed to the paid general model `gpt-5.5`.*",
             "replying_to": None},
        ]}
    mod.store._SESSIONS.clear()
    thread = TestClient(app).get("/tasks/agents/chat/thread",
                                 headers=_hdr()).text
    assert thread.count('class="am agent"') == 1
    assert "PASS" not in thread
    assert "routed to" not in thread
    assert "Two invoices are due on Friday." in thread


def test_a_second_person_gets_their_own_room(monkeypatch):
```

**Step 2: Run them to verify they fail**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/test_agent_chat_render.py tests/test_agent_chat_room.py::test_a_stored_pass_is_not_redrawn_when_the_room_loads -q -p no:cacheprovider --tb=line
```
Expected, as measured against today's code: `5 failed, 28 passed`.
- `test_a_stored_pass_is_not_drawn_on_the_way_back`: `AssertionError: a pass came back as a bubble` / `assert 3 == 1`
- `test_a_stored_answer_is_drawn_without_its_route_footer`: `assert 'routed to' not in '<div class=...'`
- `test_a_stored_pass_that_asked_permission_keeps_its_question`: `assert 'PASS' not in '<div class=...'`
- `test_a_conversation_of_only_passes_falls_back_to_the_empty_state`: the left side is an `am agent` bubble reading `PASS ... *Auto (Smart): routed to ...*`, and the right side is the `aempty` placeholder.
- `test_a_stored_pass_is_not_redrawn_when_the_room_loads`: `assert 2 == 1`

`test_an_answer_that_starts_with_pass_is_still_drawn` passes today on purpose. It guards against the fix hiding real answers that happen to start with PASS.

**Step 3: Minimal implementation**

All changes are in `mcp-servers/tasks/agent_chat_render.py`. `agent_routing` imports only `re`, so the new import cannot create a cycle.

3a. Import. Old (line 14):
```python
from urllib.parse import quote
```
New:
```python
from urllib.parse import quote

import agent_routing
```

3b. Add the helper directly above `thread`. Old (line 344):
```python
def thread(messages: list[dict], private: bool = False) -> str:
```
New:
```python
def _shown(content: str) -> str:
    """What a stored answer shows when the thread is drawn again, or "".

    Two things a round stored are not the agent talking. A PASS is a word in
    a protocol between routes_agent_chat and the model, never something a
    person should read. The round stopped storing new ones (the
    `_is_pass(answer)` branch in _run_round), but rows saved before that
    still hold them, and the owner's room drew four on 2026-10-05, each one
    a PASS over an Auto (Smart) footer. And that footer is the routing pipe
    saying which model it picked (auto_smart_pipe.py _footer).

    Both come from agent_routing, so the thread and the round cannot
    disagree about what a pass is: the pass check reads the whole stored
    text, exactly as the round does, and the footer comes off the last line
    only, the one place ROUTE_FOOTER matches. Any other text is drawn
    exactly as it was stored.
    """
    if agent_routing.is_pass(content):
        return ""
    body, found = agent_routing.ROUTE_FOOTER.subn("", "\n" + content)
    return body.strip() if found else content


def thread(messages: list[dict], private: bool = False) -> str:
```

3c. Describe the rule in `thread`'s docstring. Old (lines 350-351):
```python
    agent, or one that could not answer, said out loud while the round ran
    and then gone on reload leaves a conversation that no longer makes sense.
```
New:
```python
    agent, or one that could not answer, said out loud while the round ran
    and then gone on reload leaves a conversation that no longer makes sense.
    An answer is drawn as _shown leaves it: a stored PASS not at all, and
    anything else without the routing footer. A PASS that stopped to ask
    permission still draws its Yes and No.
```

3d. Use the helper in the assistant branch. Old (lines 388-395):
```python
            name = str(m.get("agent_name") or "Agent")
            if content:
                # The stored decision, not a fresh one. After a reload the
                # messages are in order and nothing looks ambiguous any more,
                # so recomputing would silently drop a quote that was on
                # screen a moment ago.
                out.append(agent_bubble(name, content,
                                        m.get("replying_to")))
```
New:
```python
            name = str(m.get("agent_name") or "Agent")
            shown = _shown(content)
            if shown:
                # The stored decision, not a fresh one. After a reload the
                # messages are in order and nothing looks ambiguous any more,
                # so recomputing would silently drop a quote that was on
                # screen a moment ago.
                out.append(agent_bubble(name, shown,
                                        m.get("replying_to")))
```
Leave the `awaiting` block just below (lines 396-400) unchanged. That is what keeps the approval on screen when the message text was a pass.

**Step 4: Run it to verify it passes**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/test_agent_chat_render.py tests/test_agent_chat_room.py::test_a_stored_pass_is_not_redrawn_when_the_room_loads -q -p no:cacheprovider
```
Expected: `33 passed`.

Then run every suite that calls `thread()` or `agent_bubble()`, plus the browser test. The counts below were measured on a patched copy of HEAD 8052d7b78.
```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/test_agent_chat_render.py tests/test_agent_chat_room.py tests/test_agent_chat_round.py tests/test_agent_app_card.py tests/test_agent_chat_approval.py tests/test_agent_chat_queue.py tests/test_agent_chat_endpoint.py -q -p no:cacheprovider
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_agent_chat_turn_targets.py -q -p no:cacheprovider
```
Expected: `211 passed` for the first command.
- Per file, run one at a time: render 32, room 22, round 34, app_card 12, approval 24, queue 41, endpoint 46.
- Today the same files give 27 for render and 21 for room; the others are unchanged.
- It takes about 9 minutes, mostly endpoint (3.5 min), approval, queue and round. That is normal, not a hang, so give it a timeout of at least 15 minutes or run it in the background.

Expected for the browser test: `4 passed`, before and after. The browser file never calls `thread()`; it uses `turn_open`, `turn_close`, `stream_block`, `agent_bubble`, `into_turn` and `turn_status`, so this change does not affect it.

**Step 5: Commit**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO" && git add mcp-servers/tasks/agent_chat_render.py mcp-servers/tasks/tests/test_agent_chat_render.py mcp-servers/tasks/tests/test_agent_chat_room.py && git commit -F - <<'EOF'
Agent chat: a stored PASS is not redrawn when the thread loads

The round stopped storing new passes, but rows saved before that still
hold them, and the thread route drew each one as a bubble reading PASS over
the Auto (Smart) routing footer: four in the owner's room on 2026-10-05.
thread() now uses agent_routing.is_pass, the same check the round uses, to
skip them, and takes the routing footer off the end of any other stored
answer. An approval stored on a pass still shows its Yes and No.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

**After deploy (for whoever ships the tasks service):** `GET https://ai-ui.coolestdomain.win/tasks/agents/chat/thread` for the owner's room should return 8 `class="am agent"` bubbles (12 today), 8 turns, and no `routed to`. The change is a Python module in the tasks image, so it ships by scp of `agent_chat_render.py` followed by a tasks rebuild.


**Open questions:**
- Live path not covered: a new non-pass answer from an Auto (Smart) agent is still drawn live WITH the footer (agent_bubble is called with the raw answer at routes_agent_chat.py:279, 569, 611, 1033, 1039), and the footer disappears only on reload. If live should match history, a one-line follow-up moves the footer strip into agent_bubble itself. I left it out because P0-5 is scoped to history. Exposure checked today: 0 such answers in the owner's room.
- Live/replay mismatch: a PASS that came with a pending tool call is drawn live as a 'PASS' bubble above the Yes/No (routes_agent_chat.py:277-280), and now disappears on reload. The fix would be to guard with `if answer and not _is_pass(answer)` in _question_events. That is out of scope here and has not been measured in production.
- Stored PASS messages still go into every agent's history (_history_for_round -> clean_history_for_agent strips only label lines), so models keep reading old PASS turns. This is not a display issue and is not addressed here.
- agent_runner.with_note appends the daily-cap note after the content, so a footer followed by that note is not the last line, and ROUTE_FOOTER (anchored with \Z) leaves it in place. This is consistent with is_pass, but such a footer would still show. No instance seen.

# Draft: P0-6 stop polling while the pane is hidden

## P0-6: Stop polling while the agents pane is hidden

Summary for the engineer:

1. The shell (task-panel.js) never removes a pane. It hides it in two ways. Closing sets the whole pane `[data-aiui-embed]` to `display:none` (task-panel.js:1417). Opening another feature sets the agents `<iframe>` alone to `display:none` (task-panel.js:1517). `document.hidden` only follows the browser tab, so it sees neither.
2. Today the pollers are:
   - agents.html:1734-1736, every 5 s, with only a `document.hidden` check;
   - office.html:1588, `setInterval(resync, 30000)`, with no visibility check at all.

   Both hit `/api/tasks/agents/activity`.
3. The fix asks one question at every tick: is any frame between this page and the top window `display:none`? It walks `window.frameElement` up to `window.top` and checks `getClientRects().length`. It also keeps the `document.hidden` check. Because it is checked at each tick and not stored as a flag, a lost message cannot stop polling for good. If the walk reaches an ancestor it cannot read, it fails open and keeps polling.
4. To resume at once, the fix reuses the message the shell already sends: `{aiuiFrameVisible: boolean}` (task-panel.js:1405-1410, sent on close, open and frame load). Only projects.html listens to it today. No change to task-panel.js, and no new protocol.
5. The agents page passes `{aiuiFrameVisible: true}` on to its office frame. The shell cannot see that frame, because it is nested one level deeper.
6. The rule for the listeners is the same as everywhere else: `event.origin === location.origin` and `event.source === window.parent`.
7. The files check out with CRLF line endings. Use the Edit tool with the exact old text below; it keeps the line endings. There are no em or en dashes anywhere in the new text.

---

### Task 1: The agents page stops its 5 s activity poll while its pane is hidden

**Files:**
- Create: `mcp-servers/tasks/tests/browser/test_agents_hidden_pane.py`
- Modify: `mcp-servers/tasks/static/agents.html` lines 1728-1737 as they are today (`var activityTimer = null;` through the closing `}` of `watchActivity`)
- Test: `mcp-servers/tasks/tests/browser/test_agents_hidden_pane.py`

**Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/browser/test_agents_hidden_pane.py`. It follows the conventions of `test_office_inline.py`: a module-scoped `browser`, a `ThreadingHTTPServer` handler that serves the real static files, and `page.route` stubs for `/api/**`. It also reuses `shell_with_chrome.html` and the real `task-panel.js`, the same way `test_pane_dismissal.py` does.

```python
"""A hidden AI Agents pane stops asking the server what its agents are doing.

The shell keeps a pane loaded after it is closed, so that reopening it is
instant. Closing sets the whole pane to display:none, and opening another
feature sets this page's frame to display:none. document.hidden sees neither,
because it only follows the browser tab. So a pane opened once went on
polling /api/tasks/agents/activity every 5 seconds, and the office inside it
every 30, for as long as the tab lived. The cost is measured in
docs/plans/2026-10-05-ai-agents-workspace-design.md.

The shell here is the real task-panel.js over shell_with_chrome.html, and the
pane is hidden by the shell's own code (Escape, and opening another feature),
never by the test setting display:none itself. The pages inside are the real
agents.html and office.html with their real stylesheet and vendor scripts.

The clock is Playwright's fake one, paused once the pane has loaded. That
makes the office's 30 second tick a call rather than a wait, and it means a
request seen while the clock stands still can only have come from the page
noticing it is back on screen, never from a timer that happened to be due.
"""
import http.server
import json
import pathlib
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

HERE = pathlib.Path(__file__).parent
STATIC = HERE.parents[1] / "static"
OPEN_PANE = "[data-aiui-embed][data-open]"
AGENTS_OPEN = '[data-aiui-embed][data-open="/tasks/agents"]'

AGENTS = [
    {"id": "agent-ada-0001", "name": "Ada",
     "meta": {"role": "Project manager", "toolIds": []},
     "params": {}, "user_id": "me", "created_at": 1, "updated_at": 1},
]

KINDS = {".js": "text/javascript", ".css": "text/css", ".html": "text/html"}


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:                            # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        yield b
        b.close()


@pytest.fixture(scope="module")
def server():
    shell = (HERE / "shell_with_chrome.html").read_bytes()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):                                    # noqa: N802
            path = self.path.split("?")[0]
            kind = "text/html"
            rel = path[len("/tasks/static/"):]
            if path == "/task-panel.js":
                body, kind = (STATIC / "task-panel.js").read_bytes(), KINDS[".js"]
            elif path.startswith("/tasks/static/") and (STATIC / rel).is_file():
                # Served for real, vendor scripts included. A stubbed asset
                # hid a broken layout through a whole deploy once already.
                body = (STATIC / rel).read_bytes()
                kind = KINDS.get((STATIC / rel).suffix, kind)
            elif path.startswith("/tasks/agents"):
                body = (STATIC / "agents.html").read_bytes()
            elif path.startswith("/tasks/office"):
                body = (STATIC / "office.html").read_bytes()
            elif path.startswith("/tasks/"):
                # Another feature's pane. What it shows does not matter here,
                # only that opening it hides the agents frame.
                body = b"<!doctype html><title>another feature</title>"
            else:
                body = shell
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


@pytest.fixture
def shell(browser, server):
    """The shell with the AI Agents pane open and its office drawn, the clock
    paused, and every activity request recorded with the page that made it."""
    ctx = browser.new_context(viewport={"width": 1500, "height": 1000})
    ctx.clock.install()
    pg = ctx.new_page()
    pg.set_default_timeout(8000)
    hits = []

    def route(r):
        url = r.request.url
        if "/agents/stream" in url:
            # 204 tells an EventSource to stop for good, so the office's live
            # feed cannot start re-reads of its own in the middle of a count.
            r.fulfill(status=204, body="")
            return
        if "/agents/activity" in url:
            made_by = r.request.frame.url
            hits.append("office" if "/tasks/office" in made_by else "agents")
            body = {"activity": {}, "handoffs": []}
        elif "/models/list" in url:
            body = {"items": AGENTS, "total": len(AGENTS)}
        elif "/agents/stats" in url:
            body = {"stats": {}}
        elif "/agents/skills" in url:
            body = {"skills": []}
        else:
            body = {"items": [], "total": 0}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.route("**/tasks/agents/chat/**", lambda r: r.fulfill(
        status=200, content_type="text/html", body=""))
    pg.goto("http://127.0.0.1:%d/" % server.server_address[1])
    pg.wait_for_selector("[data-aiui-agents]")
    pg.locator("[data-aiui-agents]").click()
    pg.wait_for_selector(AGENTS_OPEN)
    pg.frame_locator("[data-aiui-embed] iframe").first.locator(
        "#office-body iframe").wait_for(state="attached")
    agents = next(f for f in pg.frames if "/tasks/agents" in f.url)
    agents.wait_for_function(
        "() => window.__aiuiAgents && window.__aiuiAgents.ready")
    office = next(f for f in pg.frames if "/tasks/office" in f.url)
    office.wait_for_selector(".who", state="attached")
    pg.clock.pause_at(pg.evaluate("Date.now()") + 1000)
    yield pg, hits
    ctx.close()


def _hide(pg, how):
    if how == "closed":
        # Escape is the shell's own way out: closeAiuiEmbed sets the whole
        # pane to display:none and keeps it loaded.
        pg.keyboard.press("Escape")
        pg.wait_for_selector(OPEN_PANE, state="detached")
    else:
        # Another feature opened in the same pane: the agents frame alone
        # goes to display:none.
        pg.locator("[data-aiui-graph]").click()
        pg.wait_for_selector('[data-aiui-embed][data-open="/tasks/graph"]')


def _advance(pg, ms):
    """Move the paused clock on, then give the requests it started real time
    to reach the route handler."""
    pg.clock.run_for(ms)
    pg.wait_for_timeout(500)


@pytest.mark.parametrize("how", ["closed", "switched"])
def test_a_hidden_agents_pane_stops_polling(shell, how):
    pg, hits = shell
    # On screen it polls every 5 seconds. This keeps the zero below from
    # passing because nothing polls at all.
    start = hits.count("agents")
    _advance(pg, 11000)
    assert hits.count("agents") > start, "the agents page never polled on screen"

    _hide(pg, how)
    pg.wait_for_timeout(300)
    before = hits.count("agents")
    _advance(pg, 31000)
    assert hits.count("agents") == before, (
        "the agents page went on polling /api/tasks/agents/activity while the "
        "shell had it hidden (%s): %d new requests"
        % (how, hits.count("agents") - before))


@pytest.mark.parametrize("how", ["closed", "switched"])
def test_showing_the_pane_again_catches_up_at_once(shell, how):
    pg, hits = shell
    _hide(pg, how)
    _advance(pg, 11000)             # ticks skipped while hidden
    before = hits.count("agents")
    # The clock stays paused from here, so no timer can fire.
    pg.locator("[data-aiui-agents]").click()
    pg.wait_for_selector(AGENTS_OPEN)
    pg.wait_for_timeout(1000)
    assert hits.count("agents") > before, (
        "reopening the pane left the activity dots stale until the next tick")
```

**Step 2: Run it to verify it fails**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_agents_hidden_pane.py -q
```

Expected: `4 failed`, about 10 s. The messages:
- `AssertionError: the agents page went on polling /api/tasks/agents/activity while the shell had it hidden (closed): 6 new requests` (and the same for `switched`)
- `AssertionError: reopening the pane left the activity dots stale until the next tick` (twice, `assert N > N`)

**Step 3: Minimal implementation**

In `mcp-servers/tasks/static/agents.html`, replace these exact lines (1728-1737 today, anchored by `var activityTimer = null;`):

```js
    var activityTimer = null;

    function watchActivity() {
      if (activityTimer) clearInterval(activityTimer);
      // Only while the tab is actually being looked at. The box has 3.8GB and
      // no reason to answer a poll nobody is reading.
      activityTimer = setInterval(function () {
        if (!document.hidden) loadActivity();
      }, 5000);
    }
```

with:

```js
    var activityTimer = null;
    //: A tick that found the page off screen. Coming back on screen makes it
    //: up at once, rather than leaving the dots up to 5 seconds stale.
    var activityMissed = false;

    // On screen means the tab is showing AND no frame between this page and
    // the top window is display:none. The shell keeps a closed pane loaded so
    // that it reopens instantly: closing sets the pane to display:none, and
    // opening another feature sets this frame to display:none. document.hidden
    // sees neither, because it only follows the browser tab, so a pane opened
    // once went on polling for as long as the tab lived. Asked at every tick
    // rather than kept as a flag, so a message that never arrives cannot
    // stop the dots for good.
    function onScreen() {
      if (document.hidden) return false;
      try {
        for (var w = window; w !== w.top; w = w.parent) {
          var f = w.frameElement;
          // Framed by another origin: nothing more can be known, so poll.
          if (!f) return true;
          if (!f.getClientRects().length) return false;
        }
      } catch (e) { /* an ancestor we may not read: poll as before */ }
      return true;
    }

    function watchActivity() {
      if (activityTimer) clearInterval(activityTimer);
      // Only while somebody can see it. The box has 3.8GB and no reason to
      // answer a poll nobody is reading.
      activityTimer = setInterval(function () {
        if (onScreen()) { activityMissed = false; loadActivity(); }
        else activityMissed = true;
      }, 5000);
    }

    function catchUpActivity() {
      if (!activityMissed || !onScreen()) return;
      activityMissed = false;
      loadActivity();
    }
    document.addEventListener("visibilitychange", catchUpActivity);
    // The shell says when this pane is back on screen (aiuiFrameVisible in
    // task-panel.js). Only from the window that framed this page, and only
    // from this origin.
    window.addEventListener("message", function (ev) {
      if (ev.origin !== window.location.origin) return;
      if (ev.source !== window.parent) return;
      if (ev.data && ev.data.aiuiFrameVisible === true) catchUpActivity();
    });
```

Nothing else changes. `render()` still calls `loadActivity()` directly at line 1769 after a list load, which only happens after a user action or at boot.

**Step 4: Run it to verify it passes**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_agents_hidden_pane.py -q
```

Expected: `4 passed` in about 10 s.

Then the existing suites that touch agents.html:

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_agents_page.py tests/browser/test_agents_ask_prefill.py tests/browser/test_agents_page_fit.py tests/browser/test_agents_tools_live.py tests/browser/test_office_inline.py tests/test_agents_page_access.py tests/test_agents_page_memory.py tests/test_agent_chat_page.py tests/test_static_page_js.py -q
```

Expected: 253 passed and 1 failed (226 from the eight agents and office files, plus 27 from `test_static_page_js.py`).
- The one failure, `test_element_ids_are_unique[office.html]` ("office.html reuses element ids: [\"' + esc(m.id) + '\"]"), was already failing on main before this change. Its regex matches a JS string.
- `test_inline_javascript_parses[agents.html]` must pass.

**Step 5: Commit**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO" && git add mcp-servers/tasks/static/agents.html mcp-servers/tasks/tests/browser/test_agents_hidden_pane.py && git commit -m "$(cat <<'EOF'
AI agents page: stop the activity poll while its pane is hidden

The shell keeps a closed pane loaded with display:none, and hides a pane it
switched away from the same way. document.hidden sees neither, so the page
went on asking /api/tasks/agents/activity every 5 seconds for as long as the
tab lived. Each tick now also checks that no frame up to the top window is
display:none, and the shell's existing aiuiFrameVisible message makes up a
skipped tick the moment the pane is shown again.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: The office stops its 30 s re-read while hidden, and catches up when shown

**Files:**
- Modify: `mcp-servers/tasks/static/office.html`:
  - insert before line 1301 as it is today (`  async function loadStats() {`, right after `connectLive()` ends);
  - line 1588 (`    setInterval(resync, 30000);`).
- Modify: `mcp-servers/tasks/static/agents.html` lines 3060-3061 as they are today (`if (open) open.addEventListener("click", show);` / `if (close) close.addEventListener("click", hide);`, inside the office dock IIFE). Insert after them.
- Test: append to `mcp-servers/tasks/tests/browser/test_agents_hidden_pane.py`.

**Step 1: Write the failing test**

Append this to the end of `mcp-servers/tasks/tests/browser/test_agents_hidden_pane.py`. It reuses the `shell` fixture, `_hide`, `_advance` and `AGENTS_OPEN` from Task 1.

```python


# --- the office inside it ----------------------------------------------------
# The floor is a frame inside the agents page, so inside the shell it is two
# frames down, and it has its own 30 second re-read.

@pytest.mark.parametrize("how", ["closed", "switched"])
def test_the_office_in_a_hidden_pane_stops_polling(shell, how):
    pg, hits = shell
    start = hits.count("office")
    _advance(pg, 31000)
    assert hits.count("office") > start, "the office never polled on screen"

    _hide(pg, how)
    pg.wait_for_timeout(300)
    before = hits.count("office")
    _advance(pg, 31000)
    assert hits.count("office") == before, (
        "the office went on polling while the shell had the pane hidden (%s)"
        % how)


@pytest.mark.parametrize("how", ["closed", "switched"])
def test_the_office_catches_up_when_the_pane_is_shown(shell, how):
    pg, hits = shell
    _hide(pg, how)
    _advance(pg, 31000)             # its tick skipped while hidden
    before = hits.count("office")
    pg.locator("[data-aiui-agents]").click()
    pg.wait_for_selector(AGENTS_OPEN)
    pg.wait_for_timeout(1000)
    assert hits.count("office") > before, (
        "reopening the pane left the office floor stale until its next tick")


def test_the_office_hidden_inside_the_page_stops_polling(shell):
    """The page's own Hide button on the office. The pane is on screen, so
    only the office's frame is display:none, one frame further down."""
    pg, hits = shell
    agents = pg.frame_locator("[data-aiui-embed] iframe").first
    agents.locator("#office-close").click()
    agents.locator("#office-dock").wait_for(state="hidden")
    pg.wait_for_timeout(300)
    agents_before, office_before = hits.count("agents"), hits.count("office")
    _advance(pg, 31000)
    assert hits.count("office") == office_before, (
        "the office went on polling while the agents page had it hidden")
    assert hits.count("agents") > agents_before, (
        "hiding the office stopped the agents page's own poll as well")
```

**Step 2: Run it to verify it fails**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_agents_hidden_pane.py -q
```

Expected: `5 failed, 4 passed`, about 20 s. The 4 Task 1 tests stay green. The messages:
- `the office went on polling while the shell had the pane hidden (closed)` and `(switched)`
- `reopening the pane left the office floor stale until its next tick` (twice)
- `the office went on polling while the agents page had it hidden`

**Step 3: Minimal implementation**

3a. In `mcp-servers/tasks/static/office.html`, replace the exact line `  async function loadStats() {` (line 1301 today; it is unique) with:

```js
  //: On screen: the tab is showing and no frame between this floor and the
  //: top window is display:none. Inside the agents pane the floor is two
  //: frames down (shell, agents page, office), and the shell keeps a closed
  //: pane loaded with display:none, which document.hidden never sees. The
  //: agents page's own Hide button is caught the same way.
  function onScreen() {
    if (document.hidden) return false;
    try {
      for (var w = window; w !== w.top; w = w.parent) {
        var f = w.frameElement;
        // Framed by another origin: nothing more can be known, so poll.
        if (!f) return true;
        if (!f.getClientRects().length) return false;
      }
    } catch (e) { /* an ancestor we may not read: poll as before */ }
    return true;
  }

  //: The poll is the live feed's fallback, so it runs only while somebody can
  //: see the floor. A skipped tick is made up as soon as whoever framed this
  //: page (the shell, or the agents page) says it is back on screen.
  var RESYNC_MISSED = false;
  function pollWhenOnScreen() {
    if (onScreen()) { RESYNC_MISSED = false; resync(); }
    else RESYNC_MISSED = true;
  }
  function catchUp() {
    if (!RESYNC_MISSED || !onScreen()) return;
    RESYNC_MISSED = false;
    resync();
  }
  document.addEventListener("visibilitychange", catchUp);
  window.addEventListener("message", function (ev) {
    if (ev.origin !== window.location.origin) return;
    if (ev.source !== window.parent) return;
    if (ev.data && ev.data.aiuiFrameVisible === true) catchUp();
  });

  async function loadStats() {
```

3b. In `mcp-servers/tasks/static/office.html`, replace the exact line (1588 today; it is unique):

```js
    setInterval(resync, 30000);
```

with:

```js
    setInterval(pollWhenOnScreen, 30000);
```

Leave the `hello` handler (`es.addEventListener("hello", function () { resync(); });`) and the 1 s working-timer tick as they are. See the open questions.

3c. In `mcp-servers/tasks/static/agents.html`, replace these exact lines (3060-3061 today):

```js
    if (open) open.addEventListener("click", show);
    if (close) close.addEventListener("click", hide);
```

with:

```js
    if (open) open.addEventListener("click", show);
    if (close) close.addEventListener("click", hide);

    // The shell tells this page when its pane is back on screen. The floor is
    // a frame inside this page that the shell cannot see, so it is told here,
    // or it would wait up to 30 seconds to re-read what it skipped while
    // hidden. Only from the window that framed this page.
    window.addEventListener("message", function (ev) {
      if (ev.origin !== window.location.origin) return;
      if (ev.source !== window.parent) return;
      if (!ev.data || ev.data.aiuiFrameVisible !== true) return;
      var frame = body.querySelector("iframe");
      if (!frame) return;
      try {
        frame.contentWindow.postMessage({ aiuiFrameVisible: true },
                                        window.location.origin);
      } catch (e) { /* not loaded yet: it catches up on its own tick */ }
    });
```

`body` here is the IIFE's existing `var body = document.getElementById("office-body");` (line 2963). This anchor is deliberately not inside the existing `aiui-office-ask` listener (3114-3145), which the office-links task edits.

**Step 4: Run it to verify it passes**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_agents_hidden_pane.py -q
```

Expected: `9 passed` in about 20 s. It was stable across 3 repeat runs.

Then every suite that reads agents.html, office.html or task-panel.js:

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO/mcp-servers/tasks" && DATABASE_URL=postgresql://nobody@127.0.0.1:1/nobody python -m pytest tests/browser/test_agents_ask_prefill.py tests/browser/test_agents_page.py tests/browser/test_agents_page_fit.py tests/browser/test_agents_tools_live.py tests/browser/test_direct_feature_url.py tests/browser/test_embedded_page_chrome.py tests/browser/test_office_inline.py tests/browser/test_office_live.py tests/browser/test_office_page.py tests/browser/test_pane_dismissal.py tests/browser/test_sidebar_injection.py tests/test_agent_chat_endpoint.py tests/test_agent_chat_page.py tests/test_agent_chat_render.py tests/test_agent_free_fallback.py tests/test_agent_name_header.py tests/test_agents_page_access.py tests/test_agents_page_memory.py tests/test_feature_pages_embed.py tests/test_nav_entries.py tests/browser/test_agents_hidden_pane.py tests/test_static_page_js.py -q
```

Expected: `1 failed, 604 passed` in about 8.5 minutes. That is:
- 568 existing tests, which pass on main today;
- 9 new tests;
- 27 from `test_static_page_js`.

The 1 failure is the pre-existing `test_element_ids_are_unique[office.html]`.

**Step 5: Commit**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO" && git add mcp-servers/tasks/static/office.html mcp-servers/tasks/static/agents.html mcp-servers/tasks/tests/browser/test_agents_hidden_pane.py && git commit -m "$(cat <<'EOF'
Agent office: stop the 30 second re-read while it is hidden

The office's fallback poll ran every 30 seconds with no visibility check at
all, including inside a closed agents pane, two frames down, and behind the
agents page's own Hide button. It now runs only while no frame up to the top
window is display:none and the tab is showing. The agents page passes the
shell's aiuiFrameVisible message on to the office frame, so a skipped re-read
is made up as soon as the pane is shown again. The live feed is unchanged.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

Deploy is out of scope. tasks bakes `/app/static` into its image (see MEMORY: lesson_tasks_static_is_baked_not_mounted), so a deploy means copying the files to the host, rebuilding, then checking the bytes on the host, in the container and over HTTPS.

**Open questions:**
- The office EventSource (/api/tasks/agents/stream) stays connected while hidden. It is a held connection with a 20 s ping, not a poll, so it was left alone, and it keeps the floor current, which is why a missed re-read is cheap. Closing it while hidden and reopening it on show would be easy, because 'hello' already triggers a resync. Phase 2 plans to move activity onto SSE anyway. Decide whether that belongs here.
- The office's 1 s working-timer tick (office.html:1590) was left running. It makes no request, and gating it would cost a getClientRects walk every second, which is more work than the tick does when no agent is working.
- onScreen() only detects display:none, which is all the shell uses today (task-panel.js:1417, 1517). If the P0 phone-mount or pane-edge work starts hiding panes another way (visibility, transform, off-screen), the walk will not see it. In that case it fails open: polling simply continues as before.
- Merge order with the other Phase 0 drafts: the office-links task edits agents.html 3107-3145 and office.html 1505-1550, and the ?ask= task adds another source === window.parent listener in agents.html. This plan's anchors (agents.html 1728-1737 and 3060-3061, office.html 1301 and 1588) avoid those regions, and every anchor is a unique string, so it survives line shifts.
- Not verified live: no deploy was done. The office's EventSource 'hello' resync is still ungated, so a reconnect while hidden costs one request, on purpose: correctness over a rare call.
