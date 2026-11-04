# Skills From Connections Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Suggest skills from what a person has connected, and show a Connect button for a skill whose app is not connected, in the main chat and in the AI agent chat.

**Architecture:** A pure module `skill_fit.py` decides which apps a skill needs and which of those a person lacks. The tasks service uses it in the `/agents/make` preview and two new read routes. The main chat already turns `#aiui-connect:<app>` links into buttons; the Agents page gets a notice above its message box and `agent-chat.js` rewrites those links to open its Connections panel.

**Tech Stack:** FastAPI, pytest (asyncio auto), Open WebUI tool (httpx), plain browser JS, node for JS unit tests, Playwright for the page.

Design: `docs/plans/2026-11-04-skills-from-connections-design.md`.

All commands run from `mcp-servers/tasks/` unless stated.

---

## PR A: matching, make preview, suggest route, chat tool

### Task 1: skill_fit.needs and missing

**Files:**
- Create: `mcp-servers/tasks/skill_fit.py`
- Test: `mcp-servers/tasks/tests/test_skill_fit.py`

**Step 1: failing tests**

```python
import skill_fit as F

def sk(name, tools=()):
    return {"name": name, "tools": list(tools), "description": "", "tags": []}

def test_google_tools_are_needs_and_others_are_not():
    assert F.needs(sk("inbox-triage", ["gmail"])) == ["gmail"]
    assert F.needs(sk("x", ["calendar", "gmail"])) == ["calendar", "gmail"]
    assert F.needs(sk("x", ["documents", "remember"])) == []

def test_tracker_skills_need_a_tracker():
    assert F.needs(sk("backlog-groom", ["server:mcp-proxy"])) == ["tracker"]
    assert F.needs(sk("research-and-cite", ["server:mcp-proxy"])) == []

def test_missing_reads_the_persons_connections():
    s = sk("inbox-triage", ["gmail"])
    assert F.missing(s, set()) == ["gmail"]
    assert F.missing(s, {"gmail"}) == []
    t = sk("daily-standup", ["server:mcp-proxy"])
    assert F.missing(t, {"gmail"}) == ["tracker"]
    assert F.missing(t, {"github"}) == []
```

**Step 2:** `python -m pytest tests/test_skill_fit.py -q` → FAIL (no module).

**Step 3: implement**

```python
GOOGLE = ("gmail", "calendar", "gdrive")
TRACKERS = ("trello", "github", "clickup")
TRACKER_SKILLS = frozenset({...the ten from the design...})
LABELS = {"gmail": "Gmail", "calendar": "Google Calendar",
          "gdrive": "Google Drive",
          "tracker": "a task tracker (Trello, GitHub or ClickUp)"}
CONNECT_ID = {"gmail": "gmail", "calendar": "calendar", "gdrive": "gdrive",
              "tracker": "trello"}

def needs(skill) -> list: google tools in skill order, then "tracker" if name in TRACKER_SKILLS
def missing(skill, connected) -> list: needs not satisfied by `connected`
```

**Step 4:** tests pass. **Step 5:** commit.

### Task 2: split and connect_lines

**Test:**

```python
def test_split_keeps_order_and_groups_gaps():
    pool = {"a": sk("a", ["gmail"]), "b": sk("b"), "c": sk("c", ["gmail"]),
            "d": sk("daily-standup", ["server:mcp-proxy"])}
    pool["daily-standup"] = pool.pop("d")
    ready, gaps = F.split(["a", "b", "c", "daily-standup"], pool, set())
    assert ready == ["b"]
    assert gaps == {"gmail": ["a", "c"], "tracker": ["daily-standup"]}

def test_connect_lines_name_the_skills_and_give_a_link():
    lines = F.connect_lines({"gmail": ["a", "c"]})
    assert lines == ["Connect Gmail to add: a, c",
                     "[Connect Gmail](#aiui-connect:gmail)"]
```

Unknown names in `split` are ignored. `connect_lines` order: gmail, calendar, gdrive, tracker.
Button text for the tracker is "Connect a task tracker". Commit.

### Task 3: suggest over a pool, with connections

**Files:** Modify `agent_skills.py` (`suggest`), test `tests/test_agent_skills_suggest.py`.

`suggest(text, limit=SUGGEST_LIMIT, pool=None)`: `pool` defaults to `load_all()`. Test with a pool holding one user skill named "invoice-chaser" whose description matches "invoices" → it is suggested. Existing tests unchanged.

### Task 4: make preview uses connections

**Files:** Modify `routes_agents.py` (`_skills_for`, `proposal_text`, `make_agent`), test `tests/test_make_agent_route.py`.

- `_skills_for(asked, role, instructions, connected, pool)` returns `(kept, unknown, suggested, gaps)`.
  - Suggested: `ranked = agent_skills.suggest(text, limit=10, pool=pool)`; `top = ranked[:3]`; `ready = [n for n in ranked if not missing][:3]`; gaps from `top` only.
  - Named: kept as now; gaps = what the kept ones lack (they stay kept).
- `make_agent` reads `connected = await _connected_providers(email)` and `pool = user_skills.merge(agent_skills.load_all(), await user_skills.mine(email))`.
- `proposal_text(..., gaps=None)` adds `skill_fit.connect_lines(gaps)` after the Skills lines. For named skills the line reads "inbox-triage needs Gmail." style through the same helper (wording: "Connect Gmail so these work: ..." when kept).
- Response gains `needs_connect: [{"app","label","skills","connect"}]`.

Tests (stub `_connected_providers` and `user_skills.mine` in the fixture):
1. Inbox assistant, nothing connected: `skills` has no gmail skill; message has "Connect Gmail to add:" and "#aiui-connect:gmail".
2. Same with `{"gmail"}`: inbox-triage in `skills`, no Connect line.
3. Named `["inbox-triage"]`, nothing connected: kept, message says Connect Gmail so these work.
4. Existing tests still pass (fixture default connected = {"gmail","calendar","gdrive"} so their expectations hold).

### Task 5: GET /agents/skills/suggest

**Files:** `routes_agents.py`, test `tests/test_skill_suggest_route.py`.

Returns `{"ready": [{"app","label","skills"}], "mine": [...], "connect": [{"app","label","skills","connect"}], "message": str}`.
- ready: per connected app in (gmail, calendar, gdrive, tracker) the pool skills that need it and are fully satisfied.
- connect: per unconnected app the skills it would make ready (all their other needs met or also this app), first 5 names plus a count.
- mine: the person's own skill names.
- message: plain lines plus `[Connect X](#aiui-connect:id)` links; ends "Ask me to add any of these to an agent."
Must be registered BEFORE `/skills/find`? (both literal; order irrelevant) but before any `/{agent_id}` GET route of the same depth. Test via TestClient that `/api/tasks/agents/skills/suggest` returns 200 JSON, not another route.

### Task 6: chat tool and Jev note

**Files:** `open-webui-functions/agent_builder_tool.py`, `agent_jev.py`, tests in `tests/test_make_agent_route.py` and the Jev notes test if one asserts text.

`suggest_skills(self, __user__={})`: GET `/agents/skills/suggest`, return `message`. Docstring: use when asked which skills to use or what their connected apps can do; show the reply as written, keeping the Connect links. Jev note for agent_builder gains "or which skills fit the apps they connected".

Run full tasks suite, commit, push branch, open PR A.

## PR B: Agents page

### Task 7: GET /agents/skills/needs

`?skills=a,b` → `{"needs": [{"app","label","skills","connect"}]}` for the signed-in person. Unknown names ignored. Tests with stubs.

### Task 8: agent-chat.js turns connect links into buttons

In `renderMarkdown` after sanitising: every `a[href^="#aiui-connect:"]` gets `href="#connections"` and class `btn aiui-connect`. Node test loads the real `static/agent-chat.js` section? It is an IIFE bound to `document`; test instead the exported helper `window.aiuiConnectifyLinks(el)` added for this, run in node with a tiny DOM stub, or in the browser test of Task 9.

### Task 9: notice above the message box

`agents.html`: a `<div id="ap-needs" hidden>` before `.ap-composer`. In the "Who you are talking to" IIFE, when `current.id` changes: find the agent in `window.__aiuiAgents.state.agents`, read `meta.skillIds`, GET `/api/tasks/agents/skills/needs?skills=...`, draw one line per app: "inbox-triage needs Gmail." and `<a href="#connections" class="btn">Connect Gmail</a>`. Hidden for the room and when nothing is missing. Fails quiet (hidden) on error.

Browser test (Playwright, existing `tests/browser` pattern) against the real `agents.html` with routes stubbed: talking to an agent with inbox-triage and no Gmail shows the notice and clicking Connect opens `#connections-overlay`.

Run suites, commit, push, open PR B.

## Live checks (after approval and deploy)

1. Preview "Inbox assistant" for the test account with Gmail connected, and for a fresh view with Gmail missing (stub by asking for a tracker skill: test account has no Trello).
2. `/agents/skills/suggest` message for the test account.
3. Agents page: switch to an agent holding daily-standup; notice says a task tracker is needed; Connect opens the panel.
