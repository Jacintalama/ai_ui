# n8n uses AIUI connections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An n8n workflow runs one AIUI tool with the person's own connected account through `POST /api/tasks/tools/run`, AIUI wires that step into workflows it builds, and GitHub can review a pull request.

**Architecture:** A `tools` scope on the existing automation keys (`iok_`), a new route that runs one catalogue tool through the same `mytools._call` the chat uses, and a link step that stores an AIUI key in the person's n8n as a credential. Writes from a workflow are allowed only for steps the person approved when AIUI built the workflow.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy async + raw SQL migrations, httpx, pytest (`asyncio_mode = auto`).

**Spec:** `docs/superpowers/specs/2026-11-19-n8n-uses-aiui-connections-design.md`

## Global Constraints

- Run tests from `mcp-servers/tasks/` with `../../.venv/Scripts/python.exe -m pytest` (system python lacks sqlalchemy). ~130 `ERROR at setup` from `db_session` are pre-existing.
- No vendor credential (Trello token, GitHub token, Google token) ever leaves AIUI. The only secret sent to n8n is an AIUI `iok_` key.
- Existing keys keep exactly what they could do: `scopes = {agents}`.
- A `tools` key never runs any `n8n` tool or `link_aiui`.
- Arguments and results of `tools/run` are never logged.
- Every external call has try/except and a timeout.
- Public URL from env `AIUI_PUBLIC_URL`, default `https://ai-ui.coolestdomain.win`, never from the request.
- Migrations are additive and idempotent (`db.py` re-runs every one on each startup); a `.down.sql` goes in `migrations/rollbacks/`.
- Never touch `.env` or `templates.py`. Merging is deploying.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- A step that runs fine at build time but whose tool is a write the person never approved (n8n edited by hand afterwards): expect 403 with the "not approved in AIUI" sentence, not a silent run. Test in Task 3.
- `update_workflow` that REMOVES an AIUI write step: the approval stays (approvals only grow; revoking the key is the reset). Expect no crash and no shrink. Test in Task 4.
- A revoked key that is still stored in n8n: expect 401, and `link_aiui` (which remembers the credential on the key row) must not hand back a credential whose key is revoked; it makes a new one. Test in Task 4.
- A Google service that is down or times out: expect 502 with "Google Drive did not answer", never a 500 trace. Test in Task 3.
- `args` that is not an object (n8n sends a string when the person writes JSON in a text field): expect 422 "args must be a JSON object", not a 500. Test in Task 3.

---

### Task 1: GitHub `review_pull_request`

**Files:**
- Modify: `mcp-servers/tasks/mytools.py` (`GITHUB_TOOLS`, `_github_prepare`, the 422 translation)
- Modify: `mcp-servers/tasks/app_triage.py:135-143` (GitHub `can`, `tools`)
- Test: `mcp-servers/tasks/tests/test_github_reviews_a_pull_request.py`

**Interfaces:**
- Produces: tool `review_pull_request`, POST `/repos/{owner}/{repo}/pulls/{pull_number}/reviews`, args `owner`, `repo`, `pull_number` (integer), `event` (required), `body` (optional at the schema; required by prepare for `REQUEST_CHANGES`/`COMMENT`), `writes=True`, keep `("id", "state", "html_url", "submitted_at")`.

- [ ] **Step 1: Write the failing tests** (reuse the `github` fixture and `_run` helper shape from `tests/test_github_opens_a_pull_request_as_you.py`)

```python
def test_review_pull_request_is_on_the_github_server():
    assert "review_pull_request" in {t.name for t in mytools.GITHUB_TOOLS}

def test_approving_posts_event_approve(github):
    calls, answers = github
    answers[("POST", "/repos/o/r/pulls/7/reviews")] = _Resp(200, {"id": 1, "state": "APPROVED"})
    out = _run("review_pull_request", {"owner": "o", "repo": "r", "pull_number": 7, "event": "APPROVE"})
    assert out["ok"] is True
    sent = [c for c in calls if c["method"] == "POST"][-1]
    assert sent["url"].endswith("/repos/o/r/pulls/7/reviews")
    assert sent["json"]["event"] == "APPROVE"

def test_request_changes_without_a_body_is_refused_before_github(github):
    calls, _ = github
    out = _run("review_pull_request", {"owner": "o", "repo": "r", "pull_number": 7, "event": "REQUEST_CHANGES"})
    assert out["ok"] is False and "say what" in out["error"].lower()
    assert not [c for c in calls if c["method"] == "POST"]

def test_an_unknown_event_is_refused(github):
    out = _run("review_pull_request", {"owner": "o", "repo": "r", "pull_number": 7, "event": "MERGE"})
    assert out["ok"] is False and "APPROVE" in out["error"]

def test_approving_your_own_pull_request_says_so_plainly(github):
    _, answers = github
    answers[("POST", "/repos/o/r/pulls/7/reviews")] = _Resp(422, {"message": "Unprocessable Entity",
        "errors": ["Can not approve your own pull request"]})
    out = _run("review_pull_request", {"owner": "o", "repo": "r", "pull_number": 7, "event": "APPROVE"})
    assert out["error"] == ("GitHub does not let you approve your own pull request. "
                            "Someone else has to review it.")

def test_review_is_a_write():
    tool = {t.name: t for t in mytools.GITHUB_TOOLS}["review_pull_request"]
    assert mytools._writes(tool) is True
    import agent_tools
    assert agent_tools.is_write_tool("review_pull_request") is True

def test_triage_says_github_can_review_and_rests_on_the_tool():
    import app_triage
    gh = {a.key: a for a in app_triage.APPS}["github"]
    assert "review_pull_request" in gh.tools
    assert "approve" in gh.can
```

(If `App` uses another attribute name than `key`, or `APPS` is a dict, adapt the lookup; the assertions stay.)

- [ ] **Step 2: Run, expect FAIL**

Run: `../../.venv/Scripts/python.exe -m pytest tests/test_github_reviews_a_pull_request.py -q`
Expected: failures on the missing tool.

- [ ] **Step 3: Implement.** Add the tool to `GITHUB_TOOLS` after `comment_on_pull_request`. In `_github_prepare`, for `review_pull_request`: upper-case `event`; refuse if not in `("APPROVE", "REQUEST_CHANGES", "COMMENT")` with "event must be APPROVE, REQUEST_CHANGES or COMMENT."; refuse `REQUEST_CHANGES`/`COMMENT` with no non-blank `body` with "Say what should change: a review that requests changes or comments needs a body." Translate a 422 whose body text contains "own pull request" into the exact sentence in the test, at the place `_call` turns a vendor error into `_err` (find where `MAX_VENDOR_NOTE` is used). If `agent_tools.is_write_tool` returns False for it, add `review` to `_WRITE_VERBS`. Update `app_triage` GitHub `can` to "read repositories and pull requests, make a branch, save a file as a commit, open a pull request, approve, review or comment on one, and open or comment on issues" and add `list_repo_pull_requests`, `read_pull_request`, `review_pull_request` to `tools`.

- [ ] **Step 4: Run the new test file and `tests/test_triage_recommends_apps.py tests/test_github_*.py`; expect PASS.**

- [ ] **Step 5: Commit** `"GitHub can approve, request changes on, or comment on a pull request"`.

---

### Task 2: Keys get scopes, approved writes and a remembered n8n credential

**Files:**
- Create: `mcp-servers/tasks/migrations/070_automation_key_scopes.sql`, `mcp-servers/tasks/migrations/rollbacks/070_automation_key_scopes.down.sql`
- Modify: `mcp-servers/tasks/models.py:216-230` (`AutomationKey`)
- Modify: `mcp-servers/tasks/automation_keys.py`
- Modify: `mcp-servers/tasks/static/agents.html` (Automation panel: show what a key can do)
- Test: `mcp-servers/tasks/tests/test_automation_key_scopes.py`

**Interfaces:**
- Produces:
  - Columns: `scopes TEXT[] NOT NULL DEFAULT '{agents}'`, `allowed_writes TEXT[] NOT NULL DEFAULT '{}'`, `n8n_credential_id TEXT NULL`.
  - `SCOPE_AGENTS = "agents"`, `SCOPE_TOOLS = "tools"`.
  - `async def create(email: str, label: str, scopes: tuple[str, ...] = (SCOPE_AGENTS,)) -> dict` (row + `key`).
  - `async def owner_for(key) -> dict | None` returning `{"id", "email", "scopes": list, "allowed_writes": list, "n8n_credential_id"}` for a live key, None otherwise; never raises. Seam `_owner_for_hash_seam`.
  - `async def email_for(key) -> str | None`: unchanged signature; None unless the key has `agents` scope.
  - `async def allow_writes(email: str, key_id: str, steps: list[str]) -> None` (adds `"app.tool"` entries, de-duplicated; seam `_allow_writes_seam`).
  - `async def remember_n8n_credential(email: str, key_id: str, credential_id: str) -> None` (seam).
  - `async def n8n_key(email: str) -> dict | None`: the person's newest live key with `tools` scope and a non-null `n8n_credential_id` (seam).
  - `_row` gains `scopes`.
  - `_create_row(email, label, key_hash, prefix, scopes=("agents",))` (keyword default keeps existing test fakes working).

- [ ] **Step 1: Write the failing tests** (seam style of `tests/test_automation_run.py`)

```python
async def test_a_key_made_on_the_agents_page_runs_agents_only(monkeypatch):
    seen = {}
    async def create(email, label, key_hash, prefix, scopes=("agents",)):
        seen["scopes"] = scopes
        return {"id": "k1", "label": label, "prefix": prefix, "scopes": list(scopes)}
    monkeypatch.setattr(ak, "_create", create)
    row = await ak.create("a@x", "n8n")
    assert seen["scopes"] == ("agents",) and row["key"].startswith("iok_")

async def test_a_tools_only_key_cannot_run_an_agent(monkeypatch):
    monkeypatch.setattr(ak, "_owner_for_hash_seam", AsyncMock(return_value={
        "id": "k", "email": "a@x", "scopes": ["tools"], "allowed_writes": [], "n8n_credential_id": None}))
    monkeypatch.setattr(ak, "_email_for_hash_seam", AsyncMock(return_value=None))
    key = ak.make_key()
    assert await ak.email_for(key) is None
    assert (await ak.owner_for(key))["email"] == "a@x"

async def test_owner_for_never_raises(monkeypatch):
    monkeypatch.setattr(ak, "_owner_for_hash_seam", AsyncMock(side_effect=RuntimeError("down")))
    assert await ak.owner_for(ak.make_key()) is None

def test_migration_070_is_additive_and_defaults_existing_keys_to_agents():
    sql = (pathlib.Path(ak.__file__).parent / "migrations" / "070_automation_key_scopes.sql").read_text()
    assert "ADD COLUMN IF NOT EXISTS scopes" in sql and "DEFAULT '{agents}'" in sql
    assert "ADD COLUMN IF NOT EXISTS allowed_writes" in sql
    assert "ADD COLUMN IF NOT EXISTS n8n_credential_id" in sql
    assert "DROP" not in sql.upper().split("--")[0]
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement.** Migration with header comment in the style of 059/069 (why, additive, idempotent). Real `_email_for_hash` adds `AutomationKey.scopes.any("agents")` to its filter (Postgres `'agents' = ANY(scopes)`). Real `_owner_for_hash` stamps `last_used_at` like `_email_for_hash`. `allow_writes` uses `array(SELECT DISTINCT unnest(allowed_writes || $3))` scoped by `user_email` AND `id`. Agents page: in the Automation key list, show "Runs agents" / "Runs tools (n8n)" from `scopes` next to the prefix; keys made there still send no scopes.

- [ ] **Step 4: Run new tests plus `tests/test_automation_run.py`; expect PASS** (the existing fakes take the new keyword default).

- [ ] **Step 5: Commit** `"An automation key says what it may do; existing keys run agents only"`.

---

### Task 3: `POST /api/tasks/tools/run`

**Files:**
- Create: `mcp-servers/tasks/routes_tool_run.py`
- Modify: `mcp-servers/tasks/main.py` (import and `app.include_router(tool_run_router, prefix="/api/tasks")` beside line 201)
- Test: `mcp-servers/tasks/tests/test_tool_run_route.py`

**Interfaces:**
- Consumes: `automation_keys.owner_for`, `mytools.PROVIDER_TOOLS`, `mytools._call`, `mytools._secrets_for`, `mytools._writes`, `routes_automation._slots` (shared semaphore).
- Produces:
  - `router = APIRouter(prefix="/tools")`; `POST /run`, body `RunToolIn{app: str, tool: str, args: Any = {}}`.
  - `GOOGLE_READS: dict[str, tuple[str, frozenset[str]]]` = `{"gdrive": (GDRIVE_URL, {"gdrive_search_files", "gdrive_list_files", "gdrive_read_file"}), "gmail": (GMAIL_URL, {"gmail_search_emails", "gmail_read_email"}), "calendar": (CALENDAR_URL, {"calendar_list_events"})}`, URLs from env `GDRIVE_URL`/`GMAIL_URL`/`CALENDAR_URL`, defaults `http://mcp-gdrive:8000`, `http://mcp-gmail:8000`, `http://mcp-calendar:8000`.
  - `NEVER_FROM_A_KEY = frozenset({"n8n"})` (apps) and `{"link_aiui"}` (tools).
  - `def step_name(app: str, tool: str) -> str` returning `f"{app}.{tool}"` (Task 4 uses it).
  - Status codes: 401 no/revoked/unknown key; 403 key lacks `tools` ("This key cannot run tools. Ask AIUI to link your n8n again."); 403 n8n app or `link_aiui`; 403 unapproved write ("This step was not approved in AIUI. Ask AIUI to add it to the workflow, and it will ask you first."); 404 unknown app (lists apps) or tool (lists that app's tools); 409 not connected (the `_call` sentence: "You have not connected your <Label> account yet. ..."); 422 `args` not an object ("args must be a JSON object"); 422 `_call` returned `ok: False` (its `error` as detail); 502 Google service down/timeout ("Google Drive did not answer. Try again in a minute."); 200 the tool result.

- [ ] **Step 1: Write the failing tests** with `TestClient` on a `FastAPI()` that includes the router, `owner_for` patched, `mytools._call` and `_secrets_for` patched, Google via a patched `httpx.AsyncClient`:

```python
def test_no_key_is_401(client): assert client.post("/tools/run", json={"app": "github", "tool": "list_my_repos"}).status_code == 401
def test_an_agents_only_key_is_403(client, owner): owner(scopes=["agents"]); assert _post(client, "github", "list_my_repos").status_code == 403
def test_a_read_runs_and_returns_the_tool_result(client, owner, call): owner(); call.returns({"ok": True, "result": [1]}); r = _post(client, "github", "list_my_repos"); assert r.status_code == 200 and r.json()["result"] == [1]
def test_an_unapproved_write_is_403_and_never_called(client, owner, call): owner(); r = _post(client, "github", "review_pull_request", {"owner": "o", "repo": "r", "pull_number": 1, "event": "APPROVE"}); assert r.status_code == 403 and "not approved in AIUI" in r.text and not call.calls
def test_an_approved_write_runs(client, owner, call): owner(allowed_writes=["github.review_pull_request"]); call.returns({"ok": True}); assert _post(client, "github", "review_pull_request", {...}).status_code == 200
def test_n8n_tools_are_never_run_from_a_key(client, owner): owner(allowed_writes=["n8n.delete_workflow"]); assert _post(client, "n8n", "delete_workflow", {"workflow_id": "1"}).status_code == 403
def test_link_aiui_is_never_run_from_a_key(client, owner): owner(); assert _post(client, "n8n", "link_aiui").status_code == 403
def test_unknown_tool_is_404_and_lists_the_apps_tools(client, owner): owner(); r = _post(client, "github", "merge_everything"); assert r.status_code == 404 and "list_my_repos" in r.text
def test_not_connected_is_409(client, owner, secrets): owner(); secrets({}); r = _post(client, "trello", "list_boards"); assert r.status_code == 409 and "not connected your Trello" in r.text
def test_a_tool_refusal_is_422_with_its_words(client, owner, call): owner(); call.returns({"ok": False, "error": "No such board."}); r = _post(client, "trello", "list_boards"); assert r.status_code == 422 and "No such board." in r.text
def test_args_that_are_not_an_object_are_422(client, owner): owner(); r = client.post("/tools/run", headers=AUTH, json={"app": "github", "tool": "list_my_repos", "args": "{}"}); assert r.status_code == 422 and "JSON object" in r.text
def test_a_sheet_is_read_through_drive_as_the_owner(client, owner, google): owner(); google.returns(200, {"content": "a,b"}); r = _post(client, "gdrive", "gdrive_read_file", {"file_id": "x"}); assert r.status_code == 200 and google.calls[-1]["headers"]["X-User-Email"] == "a@x" and google.calls[-1]["url"].endswith("/gdrive_read_file")
def test_a_google_write_is_404(client, owner): owner(); assert _post(client, "gdrive", "gdrive_create_file").status_code == 404
def test_google_down_is_502(client, owner, google): owner(); google.raises(httpx.ConnectError("x")); r = _post(client, "gdrive", "gdrive_read_file", {"file_id": "x"}); assert r.status_code == 502 and "did not answer" in r.text
def test_arguments_and_results_are_not_logged(client, owner, call, caplog): owner(); call.returns({"ok": True, "result": "SECRET-RESULT"}); _post(client, "github", "list_my_repos", {"q": "SECRET-ARG"}); assert "SECRET" not in caplog.text
```

(`owner(**kw)` patches `automation_keys.owner_for` to return `{"id": "k", "email": "a@x", "scopes": ["tools"], "allowed_writes": [], "n8n_credential_id": "c"} | kw`; write the fixtures in the test file.)

- [ ] **Step 2: Run, expect FAIL** (module missing).

- [ ] **Step 3: Implement `routes_tool_run.py`.** Order: key → scope → app/tool known (mytools providers, then `GOOGLE_READS`) → never-list → write gate (`mytools._writes(tool)` and `step_name` not in `allowed_writes`) → for mytools: `_secrets_for` empty → 409, else `async with routes_automation._slots: await mytools._call(app, tool, email, args)` → 200 or 422. For Google: POST `<url>/<tool>` with `X-User-Email`, timeout 60 s, 401/403 from the service → 409 "You have not connected Google ...", other non-2xx → 422 with the service `detail` if a string, connect/timeout → 502. Log one line per run: hashed email (first 12 hex of sha256), app, tool, status. Module docstring in the house style: why the route exists and the approval rule.

- [ ] **Step 4: Run the test file; expect PASS. Also `python -c "import main"` from `mcp-servers/tasks` must not raise.**

- [ ] **Step 5: Commit** `"n8n can run one AIUI tool with the person's own connection"`.

---

### Task 4: Linking AIUI into n8n, and the AIUI step in built workflows

**Files:**
- Create: `mcp-servers/tasks/aiui_link.py`
- Modify: `mcp-servers/tasks/n8n_nodes.py` (shape `aiui_tool`)
- Modify: `mcp-servers/tasks/mytools.py` (`Tool.act` field; dispatch in `_call` right after the host guard, before `tool.run`; `link_aiui` in `N8N_TOOLS`; `_n8n_check` calls `aiui_link.check_steps`; after a successful `create_workflow`/`update_workflow`, `await aiui_link.approve_steps(email, nodes)`, failing open with a warning)
- Test: `mcp-servers/tasks/tests/test_aiui_link.py`

**Interfaces:**
- Consumes: `automation_keys.create(..., scopes=("tools",))`, `revoke`, `n8n_key`, `remember_n8n_credential`, `allow_writes`; `routes_tool_run.step_name`; `mytools._writes`, `mytools.PROVIDER_TOOLS`.
- Produces:
  - `PUBLIC_URL = os.environ.get("AIUI_PUBLIC_URL", "https://ai-ui.coolestdomain.win").rstrip("/")`; `RUN_URL = PUBLIC_URL + "/api/tasks/tools/run"`.
  - `CREDENTIAL_NAME = "AIUI"`; `KEY_LABEL = "n8n (made by AIUI)"`.
  - `def step_target(node: dict) -> tuple[str, str] | None`: for an `n8n-nodes-base.httpRequest` node whose `parameters.url` equals `RUN_URL`, the `(app, tool)` read from its JSON body (`parameters.jsonBody`, a string or dict); else None.
  - `def check_steps(nodes: list) -> None`: raises the same exception type `_n8n_check` raises, with a refusal carrying the right shape, for an AIUI step with no `credentials.httpHeaderAuth.id`.
  - `async def approve_steps(email: str, nodes: list) -> list[str]`: write steps (per `mytools._writes`) among AIUI steps, added to the person's `n8n_key` via `allow_writes`; returns them.
  - `async def link(email: str, auth, args: dict) -> dict`: the `link_aiui` action (below).
  - `Tool.act: Optional[Callable[[str, Any, Dict[str, Any]], Awaitable[dict]]] = None` (email, vendor auth, args).
  - `link_aiui` tool: no args except optional `again: boolean`, `writes=True`, summary "Link AIUI to your n8n, so a workflow can use the apps you connected in AIUI. Makes an AIUI key and saves it in your n8n as a credential called AIUI. Asks first.", `act=aiui_link.link`.
  - `n8n_nodes` shape `aiui_tool`: `type="n8n-nodes-base.httpRequest"`, `type_version=4.2`, parameters `{"method": "POST", "url": RUN_URL, "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth", "sendBody": True, "specifyBody": "json", "jsonBody": "{\"app\": \"github\", \"tool\": \"list_my_repos\", \"args\": {}}"}`, summary saying: use for any app the person connected in AIUI instead of n8n's own vendor node; set `credentials: {"httpHeaderAuth": {"id": <from link_aiui>, "name": "AIUI"}}`; call `link_aiui` first if there is no id.

`link` behaviour: if not `again` and `n8n_key(email)` returns a live key → return `{"ok": True, "credential": {"id", "name": "AIUI"}, "made": False}`. Else make a `tools` key; POST `auth.base_url + "/api/v1/credentials"` with `auth.headers`, JSON `{"name": "AIUI", "type": "httpHeaderAuth", "data": {"name": "Authorization", "value": "Bearer " + key}}`, timeout 20 s; on non-2xx or exception revoke the new key and return `_err` "Your n8n did not accept a new credential (<status>). Its API key needs permission to create credentials." (never the key); on success `remember_n8n_credential`, and when `again`, copy the previous key's `allowed_writes` onto the new key (so workflows already approved keep working) and then revoke the previous key; return `{"ok": True, "credential": {...}, "made": True}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_aiui_step_shape_is_in_the_catalogue_and_points_at_our_url():
    shape = n8n_nodes.shape("aiui_tool")   # or the catalogue's own lookup
    assert shape.parameters["url"] == aiui_link.RUN_URL
def test_step_target_reads_app_and_tool(): assert aiui_link.step_target(_step("github", "review_pull_request")) == ("github", "review_pull_request")
def test_step_target_ignores_other_http_nodes(): assert aiui_link.step_target(_http("https://example.com")) is None
def test_a_step_with_no_credential_is_refused_with_the_right_shape(): (pytest.raises on check_steps; message contains "httpHeaderAuth" and "link_aiui")
async def test_link_makes_a_tools_key_and_an_n8n_credential(fake_keys, fake_n8n): out = await aiui_link.link("a@x", AUTH, {}); assert fake_keys.made_scopes == ("tools",) and fake_n8n.posted["type"] == "httpHeaderAuth" and fake_n8n.posted["data"]["value"].startswith("Bearer iok_") and out["made"] is True and "iok_" not in json.dumps(out)
async def test_link_reuses_a_live_credential(fake_keys, fake_n8n): fake_keys.existing("c9"); out = await aiui_link.link("a@x", AUTH, {}); assert out["credential"]["id"] == "c9" and not fake_n8n.posted
async def test_link_revokes_its_key_when_n8n_refuses(fake_keys, fake_n8n): fake_n8n.status = 403; out = await aiui_link.link("a@x", AUTH, {}); assert out["ok"] is False and fake_keys.revoked == [fake_keys.last_id] and "iok_" not in out["error"]
async def test_link_again_replaces_and_revokes_the_old_key(fake_keys, fake_n8n): fake_keys.existing("c9", key_id="old"); out = await aiui_link.link("a@x", AUTH, {"again": True}); assert out["made"] and "old" in fake_keys.revoked and fake_keys.allowed_for_new == fake_keys.allowed_for_old
async def test_link_after_the_key_was_revoked_makes_a_new_one(fake_keys, fake_n8n): (n8n_key returns None because revoked keys are not live) -> made is True
async def test_building_a_workflow_approves_its_write_steps(fake_keys): got = await aiui_link.approve_steps("a@x", [_step("github", "review_pull_request"), _step("github", "list_my_repos"), _http("https://x")]); assert got == ["github.review_pull_request"]
async def test_removing_a_step_does_not_shrink_or_crash(fake_keys): assert await aiui_link.approve_steps("a@x", []) == [] and fake_keys.allowed_calls == []
def test_link_aiui_is_an_n8n_tool_and_a_write(): t = {t.name: t for t in mytools.N8N_TOOLS}["link_aiui"]; assert mytools._writes(t) and t.act is aiui_link.link
async def test_create_workflow_success_calls_approve_steps(monkeypatch): (patch _secrets_for, AsyncClient to answer 200 for POST /api/v1/workflows, patch aiui_link.approve_steps with AsyncMock; run mytools._call("n8n", create_workflow, ...) with one aiui step plus a manual trigger and a connection; assert approve_steps awaited with that email and nodes)
async def test_approve_steps_failing_does_not_fail_the_build(monkeypatch): (approve_steps raises; _call still returns ok True)
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement** per the interfaces above. `aiui_link` imports `mytools` lazily inside functions (mytools imports `aiui_link` at top) to avoid a cycle.

- [ ] **Step 4: Run `tests/test_aiui_link.py` and every existing n8n test (`tests/test_*n8n*.py tests/test_a_workflow_*`, `tests/test_a_credential_only_goes_to_its_own_vendor.py`); expect PASS.**

- [ ] **Step 5: Commit** `"AIUI links itself into a person's n8n and builds steps that use their connections"`.

---

### Task 5: Docs, full suite, PR

**Files:**
- Create: `docs/n8n-aiui-steps.md` (what the person asks in chat, what gets made, the route reference with every status code from Task 3, how to revoke)
- Modify: `docs/n8n-run-agent.md` (one line pointing to the new doc for single steps)
- Modify: `CLAUDE.md` (a short "n8n uses AIUI connections (2026-11-19)" paragraph under Automation: the route, scopes, the approval rule, `link_aiui`, the never-list)

- [ ] **Step 1:** Write the docs.
- [ ] **Step 2:** Full suite: `../../.venv/Scripts/python.exe -m pytest tests/ -q`. Expected: no new failures beyond the pre-existing `ERROR at setup` set; compare the failing-file list against `origin/main` run the same way.
- [ ] **Step 3:** Run the DB tier for migration 070 in the container after deploy (Task 6), not locally.
- [ ] **Step 4:** Commit, push branch, open the PR with the design link, a note to Ralph that `n8n_nodes.py` and `_n8n_check` gained an entry in his style, and the test summary. Do not merge without the user's word.

---

### Task 6: After merge (user approves the merge): live check

- [ ] **Step 1:** `curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz`; in the container `psql`: `SELECT scopes, count(*) FROM tasks.automation_key GROUP BY 1` shows only `{agents}`.
- [ ] **Step 2:** `curl -s -o /dev/null -w "%{http_code}" -X POST https://ai-ui.coolestdomain.win/api/tasks/tools/run` → `401`.
- [ ] **Step 3:** With Ralph's OK only (his is the only connected n8n): from the main chat as the test account, link AIUI, build "manual trigger → AIUI step github.list_my_repos", run it once in n8n, see repos in the execution. Then delete the workflow and the "AIUI" credential in n8n, and revoke the key on the Agents page. Report each step's evidence.
