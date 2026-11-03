# Main chat: skills on new agents, build progress, MCP tool list. Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** From the main chat, a new agent gets role-fitting skills, a build
started there reports its own end, and "what tools do you have" lists every
MCP server's tools.

**Architecture:** Three independent pieces, one branch and one PR each.
(1) `/agents/make` gains `skills`, validated against the catalogue and
suggested by keyword match when none are named; the chat tool passes them
through. (2) `integrations-ui.js` watches a build link in a reply and appends
one closing message when the build settles. (3) mcp-proxy gains
`POST /meta/list_tools`, built from the same live per-server fetch as
`GET /{server_id}`.

**Tech Stack:** FastAPI + pytest (tasks, mcp-proxy), vanilla JS tested by
running extracted functions under node, Open WebUI tool rows in
`public.tool`.

Design: `docs/plans/2026-11-03-main-chat-skills-progress-tools-design.md`.

Facts this plan rests on (all read 2026-11-03):
- Agent skills are `meta.skillIds`, a list of catalogue names
  (`agent_skills._ids_from`). The Agents page writes it only when non-empty
  (`static/agents.html:2747`). `/agents/make` never writes it.
- `agent_skills.search` scores 8 for a word in the name, 4 in a tag, 1 in the
  description. Measured: "Bookkeeper Keep the books straight." scores 1 at
  best (incidental); "Inbox assistant Triage my inbox and draft replies"
  scores inbox-triage 24, draft-reply 8. So suggestions need a floor of 4.
- The live `public.tool` rows `agent_builder`, `code`, `video`, `skills`
  match the repo files by md5.
- A new build is inserted with `status="running"`. `GET /api/tasks/<uuid>`
  is reachable from the browser through the gateway and returns
  `status`, `built_app_slug`, `result`; the owner may read it.
- The proxy's live per-server listing is `fetch_server_tools(server)`
  (local tier reads `TOOLS_CACHE`, others fetch). `/meta/stats` counts a
  stale index (ClickUp 172, though ClickUp serves 0 now), so it is NOT used.
- `integrations-ui.js` is a single-file bind mount into `open-webui`; replace
  it in place (`cat > file`), never `mv`, or the container keeps the old inode.

---

## PR 1: skills on new agents (branch `feat/agent-skills-from-chat`)

### Task 1: `agent_skills.suggest`

**Files:** Modify `mcp-servers/tasks/agent_skills.py` (after `search`).
Test: `mcp-servers/tasks/tests/test_agent_skills_suggest.py` (new).

Step 1, failing test:

```python
"""Skills suggested for an agent from its role and instructions."""
import agent_skills


def test_an_inbox_agent_is_offered_the_inbox_skills():
    got = agent_skills.suggest("Inbox assistant. Triage my inbox and draft "
                               "replies to customers")
    assert got[0] == "inbox-triage"
    assert "draft-reply" in got
    assert len(got) <= agent_skills.SUGGEST_LIMIT


def test_an_incidental_word_is_not_a_reason_to_add_a_skill():
    """Measured: the best any skill scores for a bookkeeper is 1, a word
    somewhere in a description. Adding those would hand an agent unrelated
    instructions on every turn."""
    assert agent_skills.suggest("Bookkeeper. Keep the books straight.") == []


def test_nothing_to_go_on_suggests_nothing():
    assert agent_skills.suggest("") == []
    assert agent_skills.suggest(None) == []
```

Step 2: `python -m pytest tests/test_agent_skills_suggest.py -q` from
`mcp-servers/tasks`. Expected: FAIL, `AttributeError: ... 'suggest'`.

Step 3, implementation:

```python
#: How many skills an agent made from a description is offered. Every chosen
#: skill's instructions ride along on every turn (MAX_TOTAL_CHARS), so a few
#: that fit the role beat a pile that might.
SUGGEST_LIMIT = 3

#: The lowest score that counts as a reason. 4 is a word in a tag, 8 in the
#: name; 1 is a word somewhere in a description, which for a bookkeeper
#: matched watch-for-changes and faq-from-questions (measured 2026-11-03).
SUGGEST_FLOOR = 4


def suggest(text, limit: int = SUGGEST_LIMIT) -> list:
    """Skill names that fit an agent described by `text`, best first."""
    wanted = _words(text)
    if not wanted:
        return []
    scored = [(n, s["name"]) for s in load_all().values()
              for n in [_score(s, wanted)] if n >= SUGGEST_FLOOR]
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [name for _n, name in scored[:max(1, int(limit))]]
```

Step 4: rerun, expect PASS. Step 5: commit
`Skills: suggest the ones an agent's own description names`.

### Task 2: `/agents/make` takes, checks and saves skills

**Files:** Modify `mcp-servers/tasks/routes_agents.py` (`MakeAgentIn`,
`_proposal_key`, `proposal_text`, `_make_agent_body`, `make_agent`).
Test: add to `mcp-servers/tasks/tests/test_make_agent_route.py`.

Step 1, failing tests (append after `test_the_rules_are_the_pages_rules`):

```python
def _make(client, body):
    code = client.post("/api/tasks/agents/make", json=body).json()["confirm"]
    return client.post("/api/tasks/agents/make", json=dict(body, confirm=code))


def test_named_skills_are_shown_and_saved(client, owui):
    body = dict(MAKE_JACK, skills=["inbox-triage", "draft-reply"])
    shown = client.post("/api/tasks/agents/make", json=body).json()
    assert "Skills: inbox-triage, draft-reply" in shown["message"]
    r = _make(client, body)
    assert r.status_code == 200, r.text
    assert r.json()["skills"] == ["inbox-triage", "draft-reply"]
    assert owui["created"][0]["meta"]["skillIds"] == ["inbox-triage", "draft-reply"]


def test_a_skill_that_does_not_exist_is_left_out_and_said(client, owui):
    body = dict(MAKE_JACK, skills=["inbox-triage", "fly-a-plane"])
    shown = client.post("/api/tasks/agents/make", json=body).json()
    assert "fly-a-plane" in shown["message"]
    assert "Skills: inbox-triage" in shown["message"]
    _make(client, body)
    assert owui["created"][0]["meta"]["skillIds"] == ["inbox-triage"]


def test_no_skills_named_means_ones_that_fit_the_role(client, owui):
    body = {"name": "Ivy", "role": "Inbox assistant", "access": "read",
            "instructions": "Triage my inbox and draft replies to customers."}
    shown = client.post("/api/tasks/agents/make", json=body).json()
    assert shown["skills"][0] == "inbox-triage"
    assert "suggested" in shown["message"].lower()
    _make(client, body)
    assert owui["created"][0]["meta"]["skillIds"] == shown["skills"]


def test_an_empty_list_means_no_skills(client, owui):
    body = dict(MAKE_JACK, skills=[])
    _make(client, body)
    assert "skillIds" not in owui["created"][0]["meta"]


def test_changing_the_skills_after_the_preview_needs_a_new_preview(client, owui):
    code = client.post("/api/tasks/agents/make",
                       json=dict(MAKE_JACK, skills=["inbox-triage"])).json()["confirm"]
    r = client.post("/api/tasks/agents/make",
                    json=dict(MAKE_JACK, skills=["draft-reply"], confirm=code))
    assert r.json()["created"] is False
    assert owui["created"] == []
```

`test_an_agent_is_made_with_the_agents_pages_own_body` stays as it is:
"Bookkeeper / Keep the books straight." suggests nothing (Task 1), so its
meta has no `skillIds`, which is exactly what it asserts.

Step 2: run `python -m pytest tests/test_make_agent_route.py -q`. Expected:
the five new tests FAIL (no `skills` in the reply or the message).

Step 3, implementation in `routes_agents.py`:

- `MakeAgentIn`: add
  ```python
      #: Skill names from the catalogue. None means "suggest ones that fit
      #: the role"; [] means none.
      skills: list[str] | None = None
  ```
- New helper above `make_agent`:
  ```python
  def _skills_for(asked, role: str, instructions: str) -> tuple[list, list, bool]:
      """(kept, unknown, suggested). Names are checked against the
      catalogue, never trusted: a model that invents a skill gets it left
      out and told so, not an agent that carries a name nothing answers to."""
      if asked is None:
          return agent_skills.suggest(" ".join([role or "", instructions])), [], True
      known = agent_skills.load_all()
      kept, unknown = [], []
      for raw in asked:
          name = str(raw or "").strip()
          if not name or name in kept or name in unknown:
              continue
          (kept if name in known else unknown).append(name)
      return kept, unknown, False
  ```
- `_proposal_key(email, name, instructions, role, access, skills)`: append
  `",".join(skills)` to the joined fields.
- `proposal_text(...)` gains `skills, unknown, suggested` and adds, after the
  Access line:
  ```python
      "Skills: %s%s" % (", ".join(skills) or "none",
                        " (suggested from its role; tell me to add or drop any)"
                        if suggested and skills else ""),
  ```
  and, when `unknown`, a line
  `"Not skills here, so left out: %s" % ", ".join(unknown)`.
- `_make_agent_body(..., skills)`: `if skills: meta["skillIds"] = list(skills)`.
- `make_agent`: compute `skills, unknown, suggested = _skills_for(body.skills,
  role or "", instructions)` after the problem checks; pass `skills` to the
  key, the preview (`"skills": skills` in the preview dict too) and the body;
  return `"skills": skills` on create.

Step 4: rerun the file. Expected: all PASS.
Step 5: commit `Agents made from the chat get skills that fit their role`.

### Task 3: the chat tool passes skills

**Files:** Modify `open-webui-functions/agent_builder_tool.py`
(`create_agent`). Test: `mcp-servers/tasks/tests/test_make_agent_route.py`.

Step 1, failing test (and update the existing whole-body assert in
`test_the_chat_tool_makes_an_agent_as_the_person_asking` to include
`"skills": None`):

```python
async def test_the_chat_tool_sends_the_skills_it_was_given():
    tool = _tool()
    sent = []

    async def call(method, path, email, json_body=None):
        sent.append(json_body)
        return True, {"created": False, "message": "preview"}
    tool._call = call
    await tool.create_agent("Ivy", "x", skills="inbox-triage, draft-reply",
                            __user__={"email": "r@example.com"})
    await tool.create_agent("Ivy", "x", skills="none", __user__={"email": "r@example.com"})
    await tool.create_agent("Ivy", "x", __user__={"email": "r@example.com"})
    assert [b["skills"] for b in sent] == [["inbox-triage", "draft-reply"], [], None]
```

Step 2: run, expect FAIL (`unexpected keyword argument 'skills'`).

Step 3: add `skills: str = ""` to `create_agent`, parse with
```python
        wanted = (skills or "").strip()
        if not wanted:
            names = None
        elif wanted.lower() in ("none", "no", "no skills"):
            names = []
        else:
            names = [s.strip() for s in wanted.split(",") if s.strip()]
```
send `"skills": names`, and append to the made sentence
`" Skills: " + ", ".join(data["skills"]) + "."` when `data.get("skills")`.
Docstring addition: `skills` is a comma separated list of skill names; leave
it empty and the service suggests skills that fit the role, which appear in
the preview; "none" gives the agent none; pass the same value again with the
confirm code.

Step 4: run the file, expect PASS. Step 5: commit
`The chat's agent builder sends the skills`.

### Task 4: PR 1

Full tasks suite for touched areas:
`python -m pytest tests/test_make_agent_route.py tests/test_agent_skills_suggest.py tests/test_agent_skills.py -q`.
Push branch to `fork`, open PR against `main`. Deploy is a separate,
approved step: `routes_agents.py` + `agent_skills.py` into tasks, then the
`agent_builder` row from the repo file, md5 checked.

---

## PR 2: the MCP tool list (branch `feat/proxy-list-tools`)

### Task 5: `tool_listing.by_server`

**Files:** Create `mcp-proxy/tool_listing.py`. Test:
`mcp-proxy/tests/test_tool_listing.py`.

Step 1, failing test:

```python
"""What "list the tools you have" answers with."""
from tool_listing import by_server


def test_each_server_with_its_tool_names_and_a_count():
    got = by_server([
        ("trello", "Trello", [{"name": "list_boards"}, {"name": "get_lists"}]),
        ("github", "GitHub", [{"name": "search_repositories"}]),
    ])
    assert got["servers"] == [
        {"server_id": "github", "name": "GitHub", "tool_count": 1,
         "tools": ["search_repositories"]},
        {"server_id": "trello", "name": "Trello", "tool_count": 2,
         "tools": ["get_lists", "list_boards"]},
    ]
    assert got["tool_count"] == 3 and got["server_count"] == 2


def test_a_server_that_answered_with_an_error_says_so_and_counts_nothing():
    """ClickUp answers [{"error": ...}] while its container crash loops
    (2026-11-03). Listing that as a tool would offer one that cannot run."""
    got = by_server([("clickup", "ClickUp", [{"error": "Could not fetch tools"}])])
    assert got["servers"] == [{"server_id": "clickup", "name": "ClickUp",
                               "tool_count": 0, "tools": [],
                               "note": "not answering right now"}]
    assert got["tool_count"] == 0
```

Step 2: `cd mcp-proxy && python -m pytest tests/test_tool_listing.py -q`,
expect FAIL (module missing).

Step 3:

```python
"""The answer to "what tools do you have", one server at a time.

Pure, so it is testable without a network. The endpoint in main.py does the
fetching, with the same live per-server call GET /{server_id} makes."""


def by_server(entries) -> dict:
    servers = []
    for server_id, name, tools in entries:
        names = sorted(str(t["name"]) for t in tools or []
                       if isinstance(t, dict) and t.get("name"))
        row = {"server_id": server_id, "name": name or server_id,
               "tool_count": len(names), "tools": names}
        if not names:
            row["note"] = "not answering right now"
        servers.append(row)
    servers.sort(key=lambda s: s["server_id"])
    return {"server_count": len(servers),
            "tool_count": sum(s["tool_count"] for s in servers),
            "servers": servers}
```

Step 4: rerun, PASS. Step 5: commit.

### Task 6: `POST /meta/list_tools` and its spec entry

**Files:** Modify `mcp-proxy/main.py`: endpoint after `meta_call_tool`, spec
entry inside the `META_TOOLS_MODE` block next to `/meta/call_tool`.

Endpoint:

```python
@app.post("/meta/list_tools")
async def meta_list_tools(request: Request):
    """Every server this caller may use, with its tool names. The same access
    check and the same live fetch as GET /{server_id}, for all of them."""
    user = await extract_user_from_headers_optional(request)
    require_identified(user.email if user else None)
    allowed = []
    for server_id, config in ALL_SERVERS.items():
        if await user_has_tenant_access_async(user.email, server_id, user.entra_groups):
            allowed.append((server_id, config))
    fetched = await asyncio.gather(*(fetch_server_tools(c) for _s, c in allowed),
                                   return_exceptions=True)
    return by_server([(sid, cfg.display_name,
                       tools if isinstance(tools, list) else [])
                      for (sid, cfg), tools in zip(allowed, fetched)])
```

Spec entry (operationId `list_tools`, POST, no body): summary "List every
tool you can use, grouped by server", description "Use this when the person
asks what tools, integrations or MCP servers are available. Returns each
server and its tool names."

No unit test drives `main.py` (no test in this package imports it). Verify
live after deploy instead: the assistant's spec gains `list_tools`, and a
call as the test account returns Trello 25 and GitHub 20, the counts
`GET /trello` and `GET /github` give.

### Task 7: PR 2

`cd mcp-proxy && python -m pytest tests -q`. Push, open PR.

---

## PR 3: build progress in the chat (branch `feat/chat-build-progress`)

### Task 8: the pure functions, tested under node

**Files:** Modify `mcp-servers/gdrive/integrations-ui.js`: a new section
`// ===== Build watcher =====` before `linkifyConnectButtons();`.
Test: `mcp-servers/tasks/tests/test_chat_build_watcher.py` (new).

The test extracts the section between `===== Build watcher =====` and
`===== End build watcher =====`, writes it with a small harness to a temp
file and runs `node`; skipped when node is absent.

Functions and their contract:
- `aiuiBuildIdsIn(content)`: ids from
  `/tasks/static/preview.html?task=<uuid>` in the text, unique, in order.
- `aiuiBuildDoneMarker(id)`: `<!-- aiui:build-done <id> -->`.
- `aiuiBuildIsClosed(chain, id)`: some message content holds that marker.
- `aiuiBuildOutcome(task, origin)`: `null` while `status` is running or
  planning; otherwise the closing text plus the marker. completed:
  `"<slug> is built.\nOpen it here: <origin>/tasks/preview-app/<slug>/"`;
  awaiting_input: `"<slug> is waiting on an answer.\n<result>\nAnswer it here: <origin>/tasks/static/preview.html?task=<id>"`;
  anything else: `"<slug> did not finish building.\n<result>"`. Mirrors
  `_public_build_status` and `_preview_url` in `routes_aiuibuilder.py`.

Test cases: an id found once though linked twice; no id in an ordinary
reply; a closed build is closed; each of the four status shapes; a
missing slug reads "The app".

Step 2: run, expect FAIL (section markers missing). Step 3: write the
functions. Step 4: PASS. Step 5: commit.

### Task 9: the watcher

Same file, same section. `aiuiWatchBuilds()` runs from the existing scan
(`aiuiScanAgentNameHeaders`, throttled, once per chat id per 5 s):
fetch the chat, find build ids in assistant messages that are not closed,
and for each one not already polling start `aiuiPollBuild(chatId, id)`:
every 10 s `GET /api/tasks/<id>`; show `aiuiTypingLine`-style line
"Building <slug>..." (own element id `aiui-build-line`); stop after 60
minutes. When `aiuiBuildOutcome` is not null: re-fetch the chat, re-check it
is not closed (another tab may have closed it), append the message under
the current tail only if the tail is a done assistant message (otherwise
try again on the next tick), save `{history}`, soft reload. Model on the
appended message: the tail's model, so the header stays the same.

Structural tests in the same test file: the watcher saves `{ history: `
only; it never calls `location.reload()`; it is started from the scan.

### Task 10: verification and PR 3

1. Node tests and `tests/test_agent_name_header.py` (same file) pass.
2. Live, after an approved deploy: start one small build from the main
   chat as the test account, see the build line, then the closing message
   with a working link; reload and see it once, not twice.
3. Push, open PR.
