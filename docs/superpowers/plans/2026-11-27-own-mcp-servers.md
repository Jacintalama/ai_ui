# Add your own MCP server: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person adds their own MCP server in Connections, and its tools work for them, and only them, in the main chat, agents, cron jobs and Discord.

**Architecture:** tasks owns the servers (table, encrypted address and token, MCP calls). mcp-proxy adds each caller's own tools to what that caller can search, describe and call on its three `/meta/*` routes, by asking tasks with an internal secret. Own tools are never put in `TOOLS_CACHE`.

**Tech Stack:** Python 3, FastAPI, asyncpg, httpx, respx (tests), pytest (`asyncio_mode = auto`), fastembed (already loaded in mcp-proxy), plain JS in `integrations-ui.js`, Playwright browser tests.

**Spec:** `docs/superpowers/specs/2026-11-26-own-mcp-servers-design.md`

## Global Constraints

- Tool name: `own-<slug>_<tool>`; slug `[a-z0-9]` from the name, max 20, unique per person (`acme`, `acme2`); `<tool>` with anything outside `[A-Za-z0-9_-]` as `_`; whole name max 64.
- Limits: 5 servers per person, first 40 tools per server, description cut at 600 characters, input schema at most 8 KB (a larger one: the tool is not used).
- Address: `https://` only, checked before `host_guard.problem`; `host_guard.problem` again before EVERY call; `follow_redirects=False`.
- Timeouts: Test and Save 15 s; a call 20 s. Result text cut at 20,000 characters. A server's own error text at most 160 characters, with the token removed.
- Never in a response, log or error: the token or the full address. Cards show the host only.
- Proxy-facing tasks routes need `X-Internal-Secret` equal to `INTERNAL_CALLBACK_SECRET`, compared with `hmac.compare_digest`; missing config denies.
- Read only = server's `annotations.readOnlyHint is True` AND `agent_tools.is_write_tool(<tool>) is False`. Unknown = write.
- `OWN_MCP=0` (mcp-proxy env): search, describe and call answer exactly as today.
- Someone with no own servers sees no change, Jev's note included (byte for byte).
- Repo rules: never touch or commit `.env`; never deploy local `templates.py`; never edit compose on the box; commit messages in my voice, no AI attribution, no em or en dashes.

## Review Focus

1. **A server that answers `tools/list` with junk** (no `tools` key, a tool with no name, a name that is all symbols, 500 tools, a 1 MB schema): Test says what is wrong or uses what it can, never a 500. Test owned by Task 1.
2. **Two tools that clean to the same name** (`get.item` and `get_item`): the second is dropped and listed as not used, the first still works. Task 1.
3. **A token that appears in the server's error body or in the URL path** (some vendors put the key in the URL): the sentence the person sees contains neither. Task 2.
4. **tasks down or slow while someone searches**: built-tool search answers as today within its normal time (own-tools fetch timeout 3 s, then `{}`). Task 5.
5. **A server removed while its tools are still in the proxy's 60 s cache**: a call answers "not found" from tasks, never runs against a stale row. Task 4.

---

### Task 1: The rules, `own_mcp.py` (pure, no I/O)

**Files:**
- Create: `mcp-servers/tasks/own_mcp.py`
- Test: `mcp-servers/tasks/tests/test_own_mcp_rules.py`

**Interfaces:**
- Produces:
  - `MAX_SERVERS = 5`, `MAX_TOOLS = 40`, `DESC_CHARS = 600`, `SCHEMA_BYTES = 8192`, `NAME_CHARS = 64`, `PREFIX = "own-"`
  - `address_problem(url: str) -> str`: "" when `https://` with a host, else a sentence that does not repeat the address.
  - `slug_for(label: str, taken: set[str]) -> str`: "" when the label has no `[a-z0-9]`.
  - `tool_name(slug: str, tool: str) -> str`
  - `snapshot(slug: str, listed: Any) -> tuple[list[dict], list[str]]`: (used tools `[{"name", "tool", "description", "input_schema", "read_only"}]`, names not used with a reason). `name` is the catalogue name, `tool` the server's own name.
  - `catalogue(slug: str, label: str, tools: list[dict]) -> list[dict]`: each `{"name", "description", "request_body", "server_id": "own-<slug>", "server_name": label, "read_only"}`.
  - `remember(email: str, tools: list[dict]) -> None` and `read_only(email: str, name: str) -> bool`: in-process cache, at most 500 emails, oldest dropped; a name not remembered is `False`.
  - `jev_note(servers: list[dict]) -> str`: "" for no servers, else `" and their own servers: Acme (create_invoice, list_customers, ...)"`, at most 8 tool names per server, "..." only when cut.

- [ ] **Step 1: Write the failing tests**

```python
def test_only_https_with_a_host_is_accepted():
    assert own_mcp.address_problem("https://mcp.example.com/mcp") == ""
    for bad in ("http://mcp.example.com/mcp", "ftp://x", "https://", "mcp.example.com", ""):
        said = own_mcp.address_problem(bad)
        assert said and "mcp.example.com" not in said

def test_a_slug_is_short_lowercase_and_unique_per_person():
    assert own_mcp.slug_for("Acme Billing!", set()) == "acmebilling"
    assert own_mcp.slug_for("Acme", {"acme"}) == "acme2"
    assert own_mcp.slug_for("Acme", {"acme", "acme2"}) == "acme3"
    assert len(own_mcp.slug_for("x" * 50, set())) == 20
    assert own_mcp.slug_for("!!!", set()) == ""

def test_a_tool_name_is_cleaned_and_capped():
    assert own_mcp.tool_name("acme", "create.invoice") == "own-acme_create_invoice"
    assert len(own_mcp.tool_name("a" * 20, "t" * 100)) == 64

def test_the_snapshot_keeps_40_and_says_why_the_rest_are_not_used():
    listed = {"tools": [{"name": f"t{i}", "inputSchema": {}} for i in range(45)]}
    used, skipped = own_mcp.snapshot("acme", listed)
    assert len(used) == 40 and len(skipped) == 5

def test_junk_from_a_server_never_raises():                  # Review Focus 1
    for junk in (None, {}, {"tools": "x"}, {"tools": [{}, {"name": "!!!"}, 7]}):
        used, skipped = own_mcp.snapshot("acme", junk)
        assert isinstance(used, list) and isinstance(skipped, list)
    big = {"tools": [{"name": "big", "inputSchema": {"d": "x" * 9000}}]}
    assert own_mcp.snapshot("acme", big)[0] == []

def test_two_tools_that_clean_to_one_name_keep_the_first():  # Review Focus 2
    used, skipped = own_mcp.snapshot("acme", {"tools": [{"name": "get.item"}, {"name": "get_item"}]})
    assert [t["tool"] for t in used] == ["get.item"] and len(skipped) == 1

def test_read_only_needs_the_hint_and_a_read_verb():
    listed = {"tools": [
        {"name": "list_customers", "annotations": {"readOnlyHint": True}},
        {"name": "create_invoice", "annotations": {"readOnlyHint": True}},
        {"name": "list_items"}]}
    used, _ = own_mcp.snapshot("acme", listed)
    assert [t["read_only"] for t in used] == [True, False, False]

def test_descriptions_are_cut_at_600():
    used, _ = own_mcp.snapshot("acme", {"tools": [{"name": "t", "description": "d" * 900}]})
    assert len(used[0]["description"]) <= 600

def test_read_only_is_per_person_and_unknown_is_a_write():
    own_mcp.remember("a@x.com", [{"name": "own-acme_list", "read_only": True}])
    assert own_mcp.read_only("a@x.com", "own-acme_list") is True
    assert own_mcp.read_only("b@x.com", "own-acme_list") is False
    assert own_mcp.read_only("a@x.com", "own-acme_other") is False

def test_the_jev_note_is_empty_without_servers_and_caps_at_8():
    assert own_mcp.jev_note([]) == ""
    note = own_mcp.jev_note([{"label": "Acme", "tools": [{"tool": f"t{i}"} for i in range(10)]}])
    assert note.startswith(" and their own servers: Acme (") and note.count(",") == 7 and "..." in note
```

- [ ] **Step 2: Run, expect FAIL** `cd mcp-servers/tasks && python -m pytest tests/test_own_mcp_rules.py -q` (ModuleNotFoundError: own_mcp)
- [ ] **Step 3: Implement `own_mcp.py`** with the signatures above. `read_only` per tool uses `agent_tools.is_write_tool(tool)`; schema size is `len(json.dumps(schema))`; `request_body` in `catalogue` is `{"content": {"application/json": {"schema": input_schema}}}`, the shape `describe_tools` already returns for built tools.
- [ ] **Step 4: Run, expect PASS** (same command)
- [ ] **Step 5: Commit** `git add mcp-servers/tasks/own_mcp.py mcp-servers/tasks/tests/test_own_mcp_rules.py && git commit -m "Own MCP servers: the naming, limits and read-only rules"`

---

### Task 2: Talking to a person's server, `own_mcp_client.py`

**Files:**
- Create: `mcp-servers/tasks/own_mcp_client.py`
- Test: `mcp-servers/tasks/tests/test_own_mcp_client.py`

**Interfaces:**
- Consumes: `own_mcp.address_problem`, `host_guard.problem(url) -> str`
- Produces:
  - `class Refused(Exception)`: `str(e)` is the sentence for the person.
  - `async def list_tools(url: str, token: str, *, key: tuple[str, str] | None = None, timeout: float = 15.0) -> Any`: the raw `tools/list` result. Raises `Refused`.
  - `async def call(key: tuple[str, str], url: str, token: str, tool: str, arguments: dict, label: str, timeout: float = 20.0) -> str`: the joined text. Raises `Refused`.
  - `forget(key: tuple[str, str]) -> None`: drops a cached session (used on Remove).
  - Session cache keyed by `(email, server_id)`, TTL 3600 s, at most 500 entries.
- Protocol: JSON-RPC over POST with `Accept: application/json, text/event-stream`; read `Mcp-Session-Id`; parse either JSON or the last `data:` line of SSE; send `notifications/initialized`. One re-initialize on 401, 404 or 409. Carry a small parser of its own; do not import mcp-proxy code (separate build contexts).

- [ ] **Step 1: Write the failing tests** (respx; `host_guard.problem` monkeypatched to "" except where a test says otherwise)

```python
async def test_http_is_refused_before_any_request(respx_mock): ...
    # list_tools("http://mcp.example.com/mcp", "") raises Refused; respx saw 0 calls

async def test_a_private_answer_is_refused(monkeypatch):
    # host_guard.problem returns "that address is on a private network"; Refused, 0 calls

async def test_a_redirect_is_not_followed(respx_mock):
    # POST answers 302 Location: http://10.0.0.5/ ; Refused whose text has "somewhere else"
    # and does not contain "10.0.0.5"; respx saw exactly 1 call

async def test_the_token_goes_as_a_bearer_and_never_into_a_sentence(respx_mock):  # Review Focus 3
    # token "sk-SECRET123"; server answers 400 with body "bad key sk-SECRET123 for /mcp/sk-SECRET123"
    # Refused text: no "sk-SECRET123", len(vendor part) <= 160; request header Authorization == "Bearer sk-SECRET123"

async def test_the_address_never_appears_in_a_sentence(respx_mock):
    # url "https://mcp.example.com/k/abc123/mcp" timing out -> text "did not answer in 20 seconds", no "abc123"

async def test_sse_and_json_answers_both_parse(respx_mock): ...
async def test_a_result_is_text_only_and_cut_at_20000(respx_mock):
    # content [{"type":"text","text":"a"*30000},{"type":"image","data":"..."}] -> len <= 20000 + note, "image" named
async def test_an_isError_result_comes_back_as_a_refusal_sentence(respx_mock): ...
async def test_sessions_are_per_person_per_server(respx_mock):
    # two keys ("a@x.com","s1") and ("b@x.com","s1") on the same url -> two initialize calls
async def test_a_404_session_re_initializes_once(respx_mock): ...
```

- [ ] **Step 2: Run, expect FAIL** `python -m pytest tests/test_own_mcp_client.py -q`
- [ ] **Step 3: Implement** with the signatures above. Sentences in the `mytools` voice, all naming `label`: "Your {label} server did not answer in 20 seconds.", "Your {label} server tried to send us somewhere else, so I did not follow it.", "Your {label} server said: {clip}". Token removal: replace every occurrence of the token, then cut at 160. Log server id and email only.
- [ ] **Step 4: Run, expect PASS**
- [ ] **Step 5: Commit** `git commit -m "Own MCP servers: a client that never follows a redirect or repeats a secret"`

---

### Task 3: Storage and the person's routes

**Files:**
- Create: `mcp-servers/tasks/migrations/075_own_mcp_servers.sql` (the spec's SQL, plus `fails INT NOT NULL DEFAULT 0` for section 9, my call)
- Create: `mcp-servers/tasks/migrations/rollbacks/075_own_mcp_servers.sql` (`DROP TABLE IF EXISTS tasks.own_mcp_servers;`)
- Create: `mcp-servers/tasks/own_mcp_store.py` (asyncpg, `_connect` like `routes_connections`)
- Create: `mcp-servers/tasks/routes_own_mcp.py`
- Modify: `mcp-servers/tasks/main.py` (beside line 221): `app.include_router(own_mcp_router)` and `app.include_router(own_mcp_router, prefix="/api/tasks")`
- Test: `mcp-servers/tasks/tests/test_own_mcp_routes.py` (store monkeypatched to an in-memory dict; no DB tier needed)

**Interfaces:**
- Consumes: Task 1 and Task 2.
- Produces (`own_mcp_store`):
  - `async def list_for(email: str) -> list[dict]`: rows with `id, slug, label, host, tools, check_ok, checked_at, fails` (never secrets)
  - `async def secrets_of(email: str, server_id: str) -> dict | None`: `{"url", "token"}` decrypted, `None` when not this person's
  - `async def by_slug(email: str, slug: str) -> dict | None`
  - `async def add(email, slug, label, host, url, token, tools) -> str`, `async def set_tools(email, server_id, tools) -> bool`, `async def record_check(email, server_id, ok: bool) -> None` (fails+1, `check_ok=false` at 3; ok resets), `async def remove(email, server_id) -> bool`
- Routes (`APIRouter(prefix="/own-mcp")`, `Depends(current_user)`):
  - `GET /own-mcp/servers` -> `{"servers": [{"id","label","host","tool_count","not_used","read_only_count","check_ok","checked_at"}]}`
  - `POST /own-mcp/servers/test` body `{label, url, token}` -> `{"ok": true, "tools": [{"name","read_only"}], "not_used": [...]}` or `{"ok": false, "problem": "<sentence>"}` (HTTP 200 both)
  - `POST /own-mcp/servers` -> same check, 400 with the sentence on failure or at 5 servers, else `{"id", ...card}`; calls `own_mcp.remember`
  - `POST /own-mcp/servers/{id}/refresh`, `DELETE /own-mcp/servers/{id}`: 404 when not the caller's

- [ ] **Step 1: Write the failing tests**

```python
async def test_test_shows_the_tools_and_stores_nothing(...): ...
async def test_save_checks_again_and_stores_the_address_encrypted(...):
    # the stored row's secrets_encrypted decrypts to {"url","token"}; no column holds the url
async def test_no_route_returns_the_token_or_the_full_address(...):
    # every JSON body from all five routes: "sk-SECRET123" not in it, "/k/abc123/mcp" not in it, host is
async def test_a_sixth_server_is_refused_with_a_sentence(...): ...
async def test_someone_elses_id_is_404_on_refresh_and_delete(...): ...
async def test_a_bad_label_or_address_is_refused_before_any_request(...): ...
async def test_three_failed_checks_mark_the_server_not_answering(...):
    # record_check False x3 -> check_ok False; True -> fails 0, check_ok True
async def test_the_router_is_reachable_on_both_prefixes(): ...
    # app.routes contain "/own-mcp/servers" and "/api/tasks/own-mcp/servers"
```

- [ ] **Step 2: Run, expect FAIL** `python -m pytest tests/test_own_mcp_routes.py -q`
- [ ] **Step 3: Implement** the migration, store and routes. `host` is `urllib.parse.urlsplit(url).hostname`. Remove also calls `own_mcp_client.forget`.
- [ ] **Step 4: Run, expect PASS**; also `python -m pytest tests/test_app_smoke.py -q`
- [ ] **Step 5: Commit** `git commit -m "Own MCP servers: the table and the routes a person uses"`

---

### Task 4: The two routes only mcp-proxy calls

**Files:**
- Modify: `mcp-servers/tasks/routes_own_mcp.py`
- Test: `mcp-servers/tasks/tests/test_own_mcp_internal.py`

**Interfaces:**
- Consumes: Tasks 1 to 3.
- Produces:
  - `GET /own-mcp/tools` (headers `X-Internal-Secret`, `X-User-Email`) -> `{"tools": own_mcp.catalogue(...) for each server}`; calls `own_mcp.remember`.
  - `POST /own-mcp/call` body `{"tool_name": str, "arguments": dict}` -> `{"result": "<text>"}` or `{"result": "<sentence>", "failed": true}`, HTTP 200; 404 `{"detail": "Tool '<name>' not found"}` when the name is not in the caller's current rows.
  - `def _require_proxy(secret: str) -> None` using `hmac.compare_digest`, 403 on mismatch or missing config.

- [ ] **Step 1: Write the failing tests**

```python
async def test_both_routes_refuse_without_the_secret_even_with_an_email(...):
    # no header, wrong header, INTERNAL_CALLBACK_SECRET unset -> 403 each, store never read
async def test_tools_lists_only_the_callers_servers(...): ...
async def test_call_runs_the_tool_on_the_callers_row(...):
    # own_mcp_client.call awaited with key (email, id), the server's own tool name "create.invoice"
async def test_call_on_a_removed_server_is_not_found(...):           # Review Focus 5
async def test_call_on_another_persons_tool_name_is_not_found(...):
async def test_call_re_checks_the_address_each_time(...):
    # host_guard.problem now says private -> sentence, client.call not awaited
async def test_a_failed_call_counts_toward_not_answering(...): ...
```

- [ ] **Step 2: Run, expect FAIL** `python -m pytest tests/test_own_mcp_internal.py -q`
- [ ] **Step 3: Implement.** The call path: `own-<slug>_...` -> `by_slug(email, slug)` -> find the tool by catalogue name in that row's `tools` -> `secrets_of` -> `own_mcp_client.call`. A `Refused` is a sentence with `failed: true` and `record_check(False)`.
- [ ] **Step 4: Run, expect PASS**
- [ ] **Step 5: Commit** `git commit -m "Own MCP servers: the list and run routes, for the proxy only"`

---

### Task 5: mcp-proxy adds the caller's own tools

**Files:**
- Create: `mcp-proxy/own_tools.py`
- Modify: `mcp-proxy/main.py` routes `meta_search_tools` (864), `meta_describe_tools` (932), `meta_call_tool` (991)
- Modify: `docker-compose.unified.yml` mcp-proxy `environment` (service at line 809): `INTERNAL_CALLBACK_SECRET=${INTERNAL_CALLBACK_SECRET:-}`, `TASKS_URL=http://tasks:8210`, `OWN_MCP=${OWN_MCP:-1}`
- Test: `mcp-proxy/tests/test_own_tools.py`

**Interfaces:**
- Consumes: Task 4's two routes.
- Produces (`own_tools`):
  - `def enabled() -> bool` (`OWN_MCP` not in "0","false","no")
  - `async def for_caller(email: str) -> dict[str, dict]`: name -> catalogue entry; 60 s per email, 200 emails max, 3 s timeout, `{}` on any failure or when disabled.
  - `def rank(query: str, tools: dict, limit: int) -> list[dict]`: results in the `search_tools` shape (`tool_name, server_id, display_name, description, relevance_score`). Uses `tool_embeddings.generate_embedding` and cosine; embeddings of tool text cached by `tool_embeddings.text_hash`, at most 2,000; keyword scoring (0.8 name, 0.5 description) when no model.
  - `def merge(built: list[dict], own: list[dict], limit: int) -> list[dict]`: by `relevance_score`, stable, cut at `limit`.
  - `def caller_is_tasks(request) -> bool`: `X-Internal-Secret` matches, `hmac.compare_digest`.
  - `async def call(email: str, name: str, arguments: dict) -> dict`: forwards to tasks `/own-mcp/call`.
  - `REFUSE_DIRECT = "This tool can change things in your {server} server, so I only run it where I can ask you first. Switch to Auto (Free) and ask again."`
- Route changes, all after `require_identified`:
  - search: fetch own tools; if `allowed_servers` is empty and there are own tools, return their ranking instead of the early "No server access configured"; otherwise `merge` into both the semantic and the keyword-fallback results.
  - describe: a name starting `own-` is answered from `for_caller` only, else `{"tool_name", "error": "Tool not found"}`; never reaches `TOOLS_CACHE`.
  - call: a name starting `own-` is handled before `TOOLS_CACHE.get`: not the caller's -> 404 exactly like a missing built tool; not `read_only` and not `caller_is_tasks` -> `{"result": REFUSE_DIRECT...}` without calling tasks; else `own_tools.call`.

- [ ] **Step 1: Write the failing tests** (FastAPI TestClient on `main.app`, `own_tools.for_caller` and `get_user_tenants_async` monkeypatched, `search_tools_by_query` stubbed)

```python
def test_no_built_server_id_starts_with_own():
    assert not [s for s in tenants.ALL_SERVERS if str(s).startswith("own-")]
def test_person_b_never_finds_person_a_s_tools(...):
    # for_caller returns A's tools only for "a@x.com"; B searching "create invoice acme" -> none of them
def test_describe_and_call_of_someone_elses_tool_match_a_missing_tool(...):
    # B's answers for "own-acme_create_invoice" == answers for "own-nothing_here" (status and body)
def test_an_unidentified_caller_is_refused_before_own_tools_are_asked(...): for_caller not awaited
def test_own_tools_are_found_with_no_built_servers(...): allowed_servers empty -> own results returned
def test_own_and_built_results_are_merged_by_score(...): ...
def test_a_write_own_tool_from_open_webui_is_refused_and_never_forwarded(...):
    # no X-Internal-Secret -> REFUSE_DIRECT with "Acme"; own_tools.call not awaited
def test_a_read_only_own_tool_runs_from_open_webui(...): ...
def test_a_write_own_tool_runs_for_the_tasks_loop(...): with the secret -> forwarded
def test_the_switch_restores_todays_answers(...):
    # OWN_MCP=0: search/describe/call bodies for a built tool and for "own-x_y" equal the no-feature run
def test_tasks_down_leaves_built_search_unchanged(respx_mock):        # Review Focus 4
    # tasks /own-mcp/tools times out -> for_caller {} within ~3 s; built results identical
def test_built_tools_answer_exactly_as_today(...): describe and call of "github_list_repos" unchanged
```

- [ ] **Step 2: Run, expect FAIL** `cd mcp-proxy && python -m pytest tests/test_own_tools.py -q`
- [ ] **Step 3: Implement** `own_tools.py` and the three route edits (a few lines each, calling into `own_tools`).
- [ ] **Step 4: Run, expect PASS**; then the whole proxy suite `python -m pytest tests -q`
- [ ] **Step 5: Commit** `git add mcp-proxy/own_tools.py mcp-proxy/main.py mcp-proxy/tests/test_own_tools.py docker-compose.unified.yml && git commit -m "mcp-proxy: a caller's own MCP tools, for that caller only"`

---

### Task 6: The tasks loop says it is the tasks loop, and asks first by the server's own marking

**Files:**
- Modify: `mcp-servers/tasks/agent_tools.py`: the `/meta/*` posts at lines 409, 422, 1044, 1050 add `X-Internal-Secret` when `INTERNAL_CALLBACK_SECRET` is set (one helper `_proxy_headers(user_email) -> dict`); `is_write_call(method_name, params=None, email=None)` (line 279)
- Modify: `mcp-servers/tasks/agent_runner.py:1050`: `is_write_call(name, probe, email=user_email)`
- Test: `mcp-servers/tasks/tests/test_own_mcp_asks_first.py`

**Interfaces:**
- Consumes: `own_mcp.read_only(email, name)`.
- Produces: `is_write_call(..., email=...)`: for an inner `tool_name` starting `own-`, returns `not own_mcp.read_only(email, inner)`; with no email it is `True`. Everything else unchanged.

- [ ] **Step 1: Write the failing tests**

```python
def test_an_own_tool_marked_read_only_by_its_owner_does_not_ask(): ...
def test_the_same_name_for_someone_else_asks(): ...
def test_an_own_tool_with_no_email_asks(): assert is_write_call("call_tool", {"tool_name": "own-acme_list"}) is True
def test_built_tools_are_judged_as_before():
    assert is_write_call("call_tool", {"tool_name": "web-search_web_search"}, email="a@x.com") is False
    assert is_write_call("call_tool", {"tool_name": "clickup_create_task"}, email="a@x.com") is True
async def test_the_loop_sends_the_secret_on_every_meta_call(respx_mock, monkeypatch): ...
async def test_without_a_secret_configured_the_header_is_absent(respx_mock, monkeypatch): ...
```

- [ ] **Step 2: Run, expect FAIL** `python -m pytest tests/test_own_mcp_asks_first.py -q`
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run, expect PASS**; then `python -m pytest tests/ -q -k "agent_tools or agent_runner or write_call or approval"` (expect only the known `ERROR at setup` DB-tier errors)
- [ ] **Step 5: Commit** `git commit -m "Agents: own MCP tools ask first unless their server marked them read-only"`

---

### Task 7: Jev knows a person's own servers

**Files:**
- Modify: `mcp-servers/tasks/agent_jev.py`: `tools_request(text, tools, context="", notes=None)` (line 691) and `pick_tools(email, text, tools, context="", notes=None)` (line 736); `notes` overrides `TOOL_NOTES` per tool.
- Modify: `mcp-servers/tasks/routes_agent_turn.py:332` (`_auto_tools`): when `server:mcp-proxy` is in `tools`, build `notes={"server:mcp-proxy": TOOL_NOTES["server:mcp-proxy"] + own_mcp.jev_note(rows)}` only if `jev_note` is non-empty, from `own_mcp_store.list_for(email)` (failure: no override).
- Modify: `scripts/jev_checks_calibrate.py`: a case set `own` run with the extended note.
- Test: `mcp-servers/tasks/tests/test_own_mcp_jev_note.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_the_question_is_byte_for_byte_unchanged_without_own_servers():
    assert agent_jev.tools_request("hi", ["server:mcp-proxy"]) == agent_jev.tools_request("hi", ["server:mcp-proxy"], notes=None)
    # and equal to a golden string captured before this change
def test_a_person_with_own_servers_gets_the_longer_note(...): "their own servers: Acme (" in the t0 instructions
async def test_a_store_failure_leaves_the_note_alone(...): ...
```

- [ ] **Step 2: Run, expect FAIL**, **Step 3: Implement**, **Step 4: Run, expect PASS**
- [ ] **Step 5: Re-measure the cut on the server** `scripts/jev_checks_calibrate.py own 2` on: "create an invoice in Acme", "list my Acme customers" (need it); "what's on my Trello board" (built app, longer note); "what is 15% of 80", "write me a poem" (need nothing). Record the scores in the commit message. If nothing is wrong at the current `PURPOSE_TOOLS` cut, leave it; if it moves, add a separate cut used only when the note was extended, with its test.
- [ ] **Step 6: Commit** `git commit -m "Jev: a person's own MCP servers are in the gateway's note, for them only"`

---

### Task 8: Health, from the connection sweep

**Files:**
- Modify: `mcp-servers/tasks/connection_sweep.py`: `sweep_once` also re-lists own servers due by the same `due(...)` rule, calling `own_mcp_store.set_tools` and `record_check`.
- Test: `mcp-servers/tasks/tests/test_own_mcp_sweep.py`

- [ ] **Step 1: Failing tests**: a server that answers updates its tools and resets `fails`; one that fails 3 sweeps reads `check_ok=false` and keeps its tools; `CONNECTION_SWEEP=0` touches none; one server raising never stops the others.
- [ ] **Step 2: FAIL**, **Step 3: Implement**, **Step 4: PASS**
- [ ] **Step 5: Commit** `git commit -m "Own MCP servers: the sweep re-lists them and marks one that stopped answering"`

---

### Task 9: The Connections card

**Files:**
- Modify: `mcp-servers/gdrive/integrations-ui.js`: a last card in the grid, **Add your own MCP server**, opening a form (Name, Address, Token as a password field, Test, Save); one card per saved server (label, host, "N tools", "Not answering since <time>" when `check_ok` is false, Refresh tools, Remove with a confirm). Calls `/api/tasks/own-mcp/servers*` with `authHeaders()`. Every server-supplied string through `textContent`.
- Test: `mcp-servers/tasks/tests/browser/test_own_mcp_card_in_a_browser.py` (lift functions by name as `test_the_connections_cards_in_a_browser.py` does; `page.route` stubs the API)

- [ ] **Step 1: Failing tests**: the add card is last; Test shows tool names and which are read-only; a refusal shows the server's sentence, not JSON; Save adds a card that shows the host and never the path or token; a tool or label of `<img src=x onerror="window.__pwned=1">` stays text; Remove asks first and removes the card; a not-answering server says so; the existing grid tests still pass.
- [ ] **Step 2: FAIL**, **Step 3: Implement** (match the existing cards; no `transition: all`; focus-visible on the new buttons)
- [ ] **Step 4: PASS**: `python -m pytest tests/browser/test_own_mcp_card_in_a_browser.py tests/browser/test_the_connections_cards_in_a_browser.py -q`
- [ ] **Step 5: Commit** `git commit -m "Connections: add your own MCP server"`

---

### Task 10: Ship and prove it live

- [ ] **Step 1: Wide run** of every test file touching agent_tools, agent_runner, agent_jev, routes_agent_turn, connection_sweep, Connections and mcp-proxy; all pass except known DB-tier setup errors. Then `bash scripts/dev_up.sh up` and check the card at `http://localhost:8090`.
- [ ] **Step 2: Security review** of the branch diff (security-reviewer agent): isolation, SSRF, secrets in output.
- [ ] **Step 3: PR** (mattpocock-skills:pr body), merge by branch (`head.ref == feat/own-mcp-servers`, check the sha), let the Deploy job ship it; run migration 075 in the tasks container; confirm `docker exec mcp-proxy printenv OWN_MCP INTERNAL_CALLBACK_SECRET` is set (value not printed: `| wc -c`), `/tasks/healthz` green.
- [ ] **Step 4: Live, company account (ralphbenitez32 platform account, never thunder500)**:
  - read path: add `https://mcp.deepwiki.com/mcp` (public, no token); ask the main chat on Auto about a public repo; the answer uses `own-deepwiki_*`.
  - isolation: a second account's search for the same words returns none of them.
  - addresses: `http://...`, `https://localhost/mcp`, `https://10.0.0.5/mcp`, `https://localtest.me/mcp` each refused on Test with a sentence.
  - write path: a throwaway server with one read and one write tool on a public https host, removed afterwards: an agent on Ask asks before the write; a read-only cron job refuses it; a non-Auto model in Open WebUI gets the "Switch to Auto" sentence.
- [ ] **Step 5: Evidence** on Trello tDLDwreQ, mark complete and archive in the same breath; line saved for the EOD.
