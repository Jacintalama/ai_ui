# "Save as your skill" button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After the main chat makes an n8n workflow (or switches one on) or an Automation, put a "Save as your skill" button under the reply that asks the chat to draft a skill from it.

**Architecture:** A per-request context variable (`skill_offer.py`) collects what each tool call really made; `agent_tools.execute_tool_call` reports every call to it; the main chat route (`routes_agent_turn._chat_inner`, route_only) adds the link to the last reply. `integrations-ui.js` turns `#aiui-say:<id>` into a button that sends a fixed text through `aiuiSendToChat`.

**Tech Stack:** Python 3.11, FastAPI, pytest (asyncio auto), Playwright for the browser test, plain ES5 in `integrations-ui.js`.

**Spec:** `docs/superpowers/specs/2026-11-26-save-as-your-skill-design.md`

## Global Constraints

- Link text exactly: `[Save as your skill](#aiui-say:save-skill)`
- Message sent on click exactly: `Write a skill from what you just set up for me, and show it to me before saving.`
- Button after sending reads `✓ Asked` and is disabled; if the box was not empty it reads `Send or clear your message first, then press again`.
- Main chat on Auto only (`route_only`). Fails open everywhere: any error leaves the reply as it was.
- Never added to a reply that is waiting for a yes (`_held(turn)`), never twice.
- The page sends only texts from its own list (`AIUI_SAY_TEXTS`); unknown ids stay plain links.

## Review Focus

- A create that n8n refused but answered 200 with `{"ok": false, ...}` → no button.
- `create_automation` returning "Nothing was made: ..." → no button.
- A turn that made something and then stopped to ask about a second write → no button on the held reply.
- The answer already contains the link (model copied it) → not added again.
- Several tool calls in one turn (create then activate) → one button.

---

### Task 1: `skill_offer.py` — what counts as made

**Files:**
- Create: `mcp-servers/tasks/skill_offer.py`
- Test: `mcp-servers/tasks/tests/test_save_as_your_skill.py`

**Interfaces:**
- Produces:
  - `LINK: str` = `"[Save as your skill](#aiui-say:save-skill)"`
  - `collecting() -> contextlib.AbstractContextManager[list[str]]` — opens a fresh list for this request; inside it `note()` appends.
  - `note(tool: str, status: str, result: str) -> None` — `tool` is the called tool name (already unwrapped from `call_tool`), `status` an `agent_activity.STEP_*`. Appends `tool` when it counts. Never raises; no-op outside `collecting()`.
  - `counts(tool: str, status: str, result: str) -> bool` — the pure rule.
  - `with_link(answer: str) -> str` — answer + `"\n\n" + LINK`, unless LINK already in it.

- [ ] **Step 1: Write the failing tests**

```python
OK = json.dumps({"ok": True, "item": {"id": "w1"}})
BAD = json.dumps({"ok": False, "error": "n8n refused it"})

@pytest.mark.parametrize("tool", ["my-n8n_create_workflow", "create_workflow",
                                  "my-n8n_activate_workflow"])
def test_a_workflow_that_was_made_counts(tool):
    assert skill_offer.counts(tool, agent_activity.STEP_OK, OK)

def test_a_refused_or_failed_workflow_does_not_count():
    assert not skill_offer.counts("my-n8n_create_workflow", agent_activity.STEP_OK, BAD)
    assert not skill_offer.counts("my-n8n_create_workflow", agent_activity.STEP_FAILED, OK)
    assert not skill_offer.counts("my-n8n_create_workflow", agent_activity.STEP_OK, "not json")

def test_an_automation_counts_only_when_it_was_made():
    assert skill_offer.counts("create_automation", agent_activity.STEP_OK,
                              "Made the automation Leads. Ada will do that ...")
    assert not skill_offer.counts("create_automation", agent_activity.STEP_OK,
                                  "Nothing was made: name taken")

def test_other_tools_never_count():
    for t in ("my-n8n_list_my_workflows", "my-n8n_update_workflow",
              "my-n8n_deactivate_workflow", "create_schedule", "send_email"):
        assert not skill_offer.counts(t, agent_activity.STEP_OK, OK)

def test_note_collects_only_inside_collecting():
    skill_offer.note("create_workflow", agent_activity.STEP_OK, OK)   # no error
    with skill_offer.collecting() as made:
        skill_offer.note("create_workflow", agent_activity.STEP_OK, OK)
        skill_offer.note("send_email", agent_activity.STEP_OK, OK)
    assert made == ["create_workflow"]

def test_the_link_is_added_once():
    once = skill_offer.with_link("Done.")
    assert once == "Done.\n\n" + skill_offer.LINK
    assert skill_offer.with_link(once) == once
```

- [ ] **Step 2: Run to verify they fail**

Run (from `mcp-servers/tasks`): `python -m pytest tests/test_save_as_your_skill.py -q`
Expected: FAIL, `ModuleNotFoundError: skill_offer`.

- [ ] **Step 3: Implement `skill_offer.py`** with a `contextvars.ContextVar[list | None]` (default None). The n8n rule: tool `== name or endswith("_" + name)` for `create_workflow`/`activate_workflow`, status `STEP_OK`, result parses to a dict with `ok is True`. Automation rule: same name match for `create_automation`, `STEP_OK`, result `.startswith("Made the automation")`.

- [ ] **Step 4: Run to verify they pass** — same command, expected PASS.

- [ ] **Step 5: Commit** `git add mcp-servers/tasks/skill_offer.py mcp-servers/tasks/tests/test_save_as_your_skill.py && git commit -m "Save as your skill: what counts as made"`

### Task 2: Report every call, add the link in the main chat

**Files:**
- Modify: `mcp-servers/tasks/agent_tools.py` (`execute_tool_call`, ~line 876)
- Modify: `mcp-servers/tasks/routes_agent_turn.py` (`_chat_inner`, ~line 2299)
- Test: `mcp-servers/tasks/tests/test_save_as_your_skill.py` (append)

**Interfaces:**
- Consumes: `skill_offer.collecting`, `skill_offer.note`, `skill_offer.with_link` (Task 1); `agent_tools.called_tool_name(name, params)`.
- Produces: `routes_agent_turn._with_skill_offer(out: dict, made: list[str]) -> dict`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_execute_tool_call_reports_what_it_ran(monkeypatch):
    # native path stubbed: _load_native_tool_source returns source,
    # _run_native returns "Made the automation X. ..."
    with skill_offer.collecting() as made:
        await agent_tools.execute_tool_call(
            {"function": {"name": "create_automation", "arguments": "{}"}}, "a@b.c")
    assert made == ["create_automation"]

def test_the_offer_goes_on_the_last_reply():
    out = rt._reply([{"agent": None, "answer": "Made it.", "notes": []}])
    got = rt._with_skill_offer(out, ["create_automation"])
    assert got["turns"][-1]["answer"].endswith(skill_offer.LINK)
    assert skill_offer.LINK in got["rendered_web"]

def test_no_offer_when_nothing_was_made_or_the_reply_waits():
    out = rt._reply([{"agent": None, "answer": "Hi.", "notes": []}])
    assert rt._with_skill_offer(out, []) == out
    held = rt._reply([{"agent": None, "answer": "Shall I?", "notes": [],
                       "pending": {"calls": [{"id": "1"}], "agent_id": "x"}}])
    assert rt._with_skill_offer(held, ["create_workflow"]) == held

def test_the_offer_fails_open():
    assert rt._with_skill_offer({"turns": "broken"}, ["create_workflow"]) == {"turns": "broken"}

async def test_the_main_chat_adds_it_after_a_made_workflow(monkeypatch):
    # stub rt._chat_turns (the old _chat_inner body) to call skill_offer.note(...)
    # with an ok create_workflow and return _reply([...]); body.route_only=True
    out = await rt._chat_inner(_Body("yes", route_only=True), SECRET)
    assert out["turns"][-1]["answer"].endswith(skill_offer.LINK)

async def test_the_panel_gets_no_offer(monkeypatch):
    # same stub, route_only=False -> no LINK
```

- [ ] **Step 2: Run to verify they fail** — `python -m pytest tests/test_save_as_your_skill.py -q`, expected FAIL (`_with_skill_offer` missing, nothing noted).

- [ ] **Step 3: Implement**
  - `agent_tools.py`: rename the current body to `_execute_tool_call_inner(...)` (same signature); new `execute_tool_call` makes the `ToolOutcome` if None, awaits the inner, then in a `try/except Exception` calls `skill_offer.note(called_tool_name(name, params), outcome.status, result)` where `name`/`params` are read with the same shape checks (a helper `_name_and_params(tool_call) -> tuple[str, dict]`, never raising). Returns the inner result unchanged.
  - `routes_agent_turn.py`: rename current `_chat_inner` body to `_chat_turns`; new `_chat_inner(body, secret)`: when `route_only`, `with skill_offer.collecting() as made: out = await _chat_turns(...)` then `return _with_skill_offer(out, made)`; else return `_chat_turns(...)`.
  - `_with_skill_offer`: no-op if `not made`; take the last turn; skip if `_held(turn)` or empty answer; replace its answer with `skill_offer.with_link(answer)` and rebuild with `_reply(turns, out.get("queue"), out.get("marker", ""), out.get("status", ""))`; any exception → return `out` (log warning).

- [ ] **Step 4: Run the new tests and the neighbours**
  `python -m pytest tests/test_save_as_your_skill.py tests/test_main_chat_named_only.py tests/test_agent_tools*.py tests/test_triage_*.py -q` — expected PASS (DB-tier setup errors only).

- [ ] **Step 5: Commit** `git commit -am "Save as your skill: the main chat offers it after a workflow or automation is made"` (add the test file).

### Task 3: The button in the page

**Files:**
- Modify: `mcp-servers/gdrive/integrations-ui.js` (new section `// ===== The assistant's say links =====` right before `function wireAiuiConnectLinks()`; `wireAiuiConnectLinks.scan` also wires `a[href*="#aiui-say:"]`)
- Test: `mcp-servers/tasks/tests/browser/test_save_as_your_skill_button.py`

**Interfaces:**
- Consumes: `aiuiSendToChat(text, done)` (existing, same file).
- Produces: `AIUI_SAY_MARKER = '#aiui-say:'`, `AIUI_SAY_TEXTS = {'save-skill': '<the exact message>'}`, `wireAiuiSayLink(anchor)`; container class `aiui-say-inline`.

- [ ] **Step 1: Write the failing browser test** (pattern of `test_publish_button_opens_app_builder.py`: cut the section from `"  // ===== The assistant's say links ====="` to `"  function wireAiuiConnectLinks()"`, define a stub `function aiuiSendToChat(t, done) { window.__sent.push(t); done(window.__ok); }` before it):
  - `test_the_link_becomes_a_button_that_sends_the_fixed_text`: button text `Save as your skill`; click → `__sent == [EXACT_MESSAGE]`; button text `✓ Asked`, disabled.
  - `test_a_full_message_box_is_not_overwritten`: `__ok = false` → button text `Send or clear your message first, then press again`, still enabled.
  - `test_an_id_not_on_the_list_stays_a_plain_link`: `#aiui-say:other`, `#aiui-say:`, `#aiui-say:__proto__`, `#aiui-say:toString` → no `.aiui-say-inline`, one `<a>`.
  - The existing `test_publish_button_opens_app_builder.py` must still pass (its section now includes the new one; it only references functions at click time).

- [ ] **Step 2: Run to verify it fails** — `python -m pytest tests/browser/test_save_as_your_skill_button.py -q`, expected FAIL (marker not found).

- [ ] **Step 3: Implement** the section, mirroring `wireAiuiOpenLink` (hasOwnProperty check, `data-aiui-wired`, same button style), and add the say-link loop to `scan`.

- [ ] **Step 4: Run** `python -m pytest tests/browser/test_save_as_your_skill_button.py tests/browser/test_publish_button_opens_app_builder.py tests/browser/test_connect_then_carry_on.py -q` — expected PASS.

- [ ] **Step 5: Commit** `git commit -m "Save as your skill: the button in the main chat"`.

### Task 4: Ship and check live

- [ ] Full suite locally (`python -m pytest tests/ -q -p no:cacheprovider`): 0 failed, errors only `ERROR at setup`.
- [ ] Check how `integrations-ui.js` reaches the browser (which container serves it, whether a deploy of `mcp-servers/` updates it); after deploy, the live copy's md5 equals the repo file.
- [ ] PR, CI green (DB tier no worse than main), merge, deploy job green, healthz ok, `.deploy-state` sha = main.
- [ ] Live, test account: ask the main chat to make an Automation (webhook start, an existing agent, a harmless instruction), approve it, see **Save as your skill** under the reply; press it; see the draft "Here is the skill I would save. Nothing has been saved yet." Answer no.
- [ ] Clean up: the automation, the chat, new `public.memory` rows, the run's `tasks.agent_memory` notes, the token.
