# Local Docker stack (Part 1). Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or
> superpowers:subagent-driven-development) to implement this plan task by task.

**Goal:** One command brings up a local copy of the platform at
`http://localhost:8090`: Postgres, Redis, Open WebUI, the API gateway, tasks,
Caddy and a scripted fake model. It has its own secrets, no production data,
a local admin and three agents (Mia, Ada, Dev), so every change can be tried
locally before it goes live.

**Architecture:**
- A standalone `docker-compose.dev.yml`, not an override of the 30-service
  production compose.
- Agent turns always go tasks → Open WebUI `/api/chat/completions`
  (`agent_runner.py:211-217`), signed with a JWT minted from
  `WEBUI_SECRET_KEY` (`owui_token.py:37-66`). So the fake model is simply
  Open WebUI's only OpenAI connection.
- The fake model is a small FastAPI app that answers non-streaming
  (`"stream": False`, `agent_runner.py:737`) with fixed timings, and plays
  scenes chosen by keywords.

**Tech stack:** Docker Compose 5.5 (Docker Desktop 29.7, already installed),
FastAPI and uvicorn, pytest, httpx, Playwright, Git Bash.

**Facts this plan relies on** (gathered 2026-10-12, with file:line):
1. **tasks**
   - Port 8210, health check `/healthz`.
   - Migrations run at boot from `migrations/*.sql`, against the same
     `openwebui` database, schema `tasks`.
   - Needs `DATABASE_URL`, `AIUI_FERNET_KEY` (it crashes at import without
     it, `crypto_utils.py:11-17`), `WEBUI_SECRET_KEY`, `OPENWEBUI_URL`.
   - Model settings: `AGENT_DEFAULT_MODEL`, `AGENT_FREE_MODELS`,
     `AGENT_REFLECT_MODEL`, `GATEWAY_MODEL`, `AGENT_PAID_DAILY_CAP`.
2. **Gateway**
   - Verifies the HS256 JWT with the same `WEBUI_SECRET_KEY`.
   - Forwards `/api/tasks*` and `/tasks/*` to tasks, and the rest to Open
     WebUI.
   - Env: `WEBUI_SECRET_KEY`, `DATABASE_URL`, `OPEN_WEBUI_URL`, `TASKS_URL`.
3. **Caddy** uses the repo `Caddyfile` on `:80`. Production-only upstreams
   fail only on their own paths. Plain `caddy:2-alpine` is enough.
4. **Open WebUI v0.11.4**
   - The image tag must not change (the override `index.html` hardcodes its
     asset hashes).
   - Needs `WEBUI_SECRET_KEY`, `DATABASE_URL` and pgvector, and Redis when
     `ENABLE_REDIS=true`.
   - The first sign-up becomes admin.
   - Connection config saved in the DB beats env after first boot, so use a
     fresh volume.
5. **Seeding**
   - `POST /api/tasks/agents/seed` creates Ada and Mia once per email. A
     failed seed is never retried (`routes_agents.py:224-226`): seed only
     after Open WebUI lists the fake model.
   - The base model id must be in Open WebUI's live model list.
   - A base model that does not end in `:free` skips paid escalation and the
     free fallback list.
6. **Postgres:** `pgvector/pgvector:pg16`, database `openwebui`, init script
   `scripts/init-db-hetzner.sql` (the `vector` extension and the `mcp_proxy`
   schema).
7. **Things that do not exist on Windows or locally,** so they are dropped:
   - the `/etc/proxy-server/agent_ssh_key` mount;
   - `mcp-proxy`, pipelines, video, the bots.

**Rules:**
- Never copy or read the values of the production `.env`.
- `.env.dev` is generated and gitignored.
- Run commands in Git Bash from the repo root.
- Commit after each task. Each message ends with a blank line and then
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never push or deploy anything to production in this plan.

---

### Task 1: The fake model service (`dev/fake-llm`)

**Files:**
- Create: `dev/fake-llm/app.py`, `dev/fake-llm/requirements.txt`,
  `dev/fake-llm/Dockerfile`.
- Test: `dev/fake-llm/test_app.py`.

**Behaviour:**
1. `GET /v1/models` returns the model `fake-agent`, owned by `local`.
2. `POST /v1/chat/completions` reads the last user message and the first
   system message (the agent's instructions, which carry its name). It
   waits `FAKE_DELAY_MS` (default 1500), or the scene's own delay, and
   answers in OpenAI format.
   - With `stream` true it returns SSE chunks; Open WebUI may forward streams.
   - With `stream` false it returns one JSON body.
3. **Scenes,** chosen by a keyword in the last user message (case
   insensitive):
   - none: `"<Name> here. You said: <text>"` after the default delay;
   - `scene:slow`: answers after 5000 ms;
   - `scene:tool`: on the first call returns an assistant `tool_calls` entry
     for a tool in the request's `tools` list (the first one), with arguments
     `{}`; when the next request carries a `tool` role message, answers
     `"<Name> used a tool."`;
   - `scene:fail`: HTTP 500 with an OpenAI error body;
   - `scene:pass`: answers `PASS` (the room protocol).
4. `GET /healthz` returns `{"ok": true}`.

**Step 1: Failing tests** (`dev/fake-llm/test_app.py`, using `httpx` with
the ASGI transport, with `FAKE_DELAY_MS=0` set in a fixture):

```python
import os, json, pytest, httpx
os.environ["FAKE_DELAY_MS"] = "0"
from app import app

@pytest.fixture
def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")

def _body(text, system="You are Ada, the project manager.", **kw):
    return {"model": "fake-agent", "messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": text}], **kw}

async def test_models_lists_the_fake(client):
    r = await client.get("/v1/models")
    assert [m["id"] for m in r.json()["data"]] == ["fake-agent"]

async def test_a_plain_answer_names_the_agent(client):
    r = await client.post("/v1/chat/completions", json=_body("hello"))
    msg = r.json()["choices"][0]["message"]
    assert msg["role"] == "assistant" and msg["content"].startswith("Ada here.")

async def test_tool_scene_calls_the_first_offered_tool(client):
    tools = [{"type": "function", "function": {"name": "search_drive", "parameters": {}}}]
    r = await client.post("/v1/chat/completions", json=_body("scene:tool find it", tools=tools))
    calls = r.json()["choices"][0]["message"]["tool_calls"]
    assert calls[0]["function"]["name"] == "search_drive"
    assert r.json()["choices"][0]["finish_reason"] == "tool_calls"

async def test_tool_result_turns_into_an_answer(client):
    body = _body("scene:tool find it")
    body["messages"] += [
        {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function",
          "function": {"name": "search_drive", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "ok"}]
    r = await client.post("/v1/chat/completions", json=body)
    assert r.json()["choices"][0]["message"]["content"] == "Ada used a tool."

async def test_fail_scene_is_a_500(client):
    r = await client.post("/v1/chat/completions", json=_body("scene:fail"))
    assert r.status_code == 500 and "error" in r.json()

async def test_pass_scene(client):
    r = await client.post("/v1/chat/completions", json=_body("scene:pass hi"))
    assert r.json()["choices"][0]["message"]["content"] == "PASS"

async def test_streaming_ends_with_done(client):
    r = await client.post("/v1/chat/completions", json=_body("hello", stream=True))
    assert r.text.rstrip().endswith("data: [DONE]")
```

Add `pytest.ini` beside it with `asyncio_mode = auto`.

**Step 2:** run `cd dev/fake-llm && python -m pytest -q`. Expect
`ModuleNotFoundError: app`.

**Step 3:** implement `app.py` (FastAPI, about 120 lines).
- The name is the first capitalised word after "You are" in the system
  message, falling back to "Agent".
- Ids come from `uuid4`. Timestamps come from `time.time()`.
- `requirements.txt`: `fastapi`, `uvicorn`, `httpx`, `pytest`,
  `pytest-asyncio`.
- `Dockerfile`: `python:3.11-slim`, pip install, then
  `CMD uvicorn app:app --host 0.0.0.0 --port 9000`.

**Step 4:** tests pass (7 passed).

**Step 5:** commit "Local dev: a scripted fake model for repeatable agent
runs".

---

### Task 2: Compose file, env template and secret generation

**Files:**
- Create: `docker-compose.dev.yml`, `.env.dev.example`,
  `scripts/dev_env.py`.
- Modify: `.gitignore` (add `.env.dev`).
- Test: `scripts/test_dev_env.py`.

**`scripts/dev_env.py`** writes `.env.dev` if it is missing, and never
overwrites it unless `--force` is passed.
- Random values: `WEBUI_SECRET_KEY` (`secrets.token_urlsafe(48)`),
  `POSTGRES_PASSWORD`, `AIUI_FERNET_KEY`
  (`cryptography.fernet.Fernet.generate_key()`).
- Fixed values:
  - `DEV_ADMIN_EMAIL=admin@local.test`;
  - `DEV_ADMIN_PASSWORD` (random);
  - `LOCAL_MODEL=fake`;
  - `OPENROUTER_API_KEY=` (empty).
- It prints the path and the key names only, never the values.

**Tests** (`scripts/test_dev_env.py`, pytest, `tmp_path`):
- it creates a file with all the keys, and the Fernet key is valid;
- a second run does not change it;
- `--force` changes it;
- stdout contains no value.

**`docker-compose.dev.yml`.** Project name `aiui-dev`, so it never touches
production volume names. Services:

```yaml
name: aiui-dev
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment: { POSTGRES_DB: openwebui, POSTGRES_USER: openwebui, POSTGRES_PASSWORD: "${POSTGRES_PASSWORD}" }
    volumes:
      - pg:/var/lib/postgresql/data
      - ./scripts/init-db-hetzner.sql:/docker-entrypoint-initdb.d/01-init.sql:ro
    healthcheck: { test: ["CMD-SHELL", "pg_isready -U openwebui"], interval: 5s, retries: 30 }
  redis:
    image: redis:7-alpine
    healthcheck: { test: ["CMD", "redis-cli", "ping"], interval: 5s, retries: 30 }
  fake-llm:
    build: ./dev/fake-llm
    environment: { FAKE_DELAY_MS: "1500" }
  open-webui:
    image: ghcr.io/open-webui/open-webui:v0.11.4
    depends_on: { postgres: { condition: service_healthy }, redis: { condition: service_healthy }, fake-llm: { condition: service_started } }
    environment:
      WEBUI_SECRET_KEY: "${WEBUI_SECRET_KEY}"
      DATABASE_URL: "postgresql://openwebui:${POSTGRES_PASSWORD}@postgres:5432/openwebui"
      VECTOR_DB: pgvector
      PGVECTOR_DB_URL: "postgresql://openwebui:${POSTGRES_PASSWORD}@postgres:5432/openwebui"
      ENABLE_REDIS: "true"
      REDIS_URL: redis://redis:6379/0
      WEBUI_URL: http://localhost:8090
      ENABLE_SIGNUP: "true"
      ENABLE_OLLAMA_API: "false"
      ENABLE_OPENAI_API: "true"
      OPENAI_API_BASE_URLS: http://fake-llm:9000/v1
      OPENAI_API_KEYS: local
      ENABLE_LOGIN_FORM: "true"
    volumes:
      - owui:/app/backend/data
      - ./openwebui-overrides/index.html:/app/build/index.html:ro
  tasks:
    build: ./mcp-servers/tasks
    depends_on: { postgres: { condition: service_healthy }, open-webui: { condition: service_started } }
    environment:
      DATABASE_URL: "postgresql://openwebui:${POSTGRES_PASSWORD}@postgres:5432/openwebui"
      WEBUI_SECRET_KEY: "${WEBUI_SECRET_KEY}"
      AIUI_FERNET_KEY: "${AIUI_FERNET_KEY}"
      OPENWEBUI_URL: http://open-webui:8080
      AGENT_DEFAULT_MODEL: fake-agent
      AGENT_FREE_MODELS: fake-agent
      AGENT_REFLECT_MODEL: fake-agent
      GATEWAY_MODEL: fake-agent
      AGENT_PAID_DAILY_CAP: "0"
      VIDEO_ENABLED: "false"
      CLAUDE_WORKSPACE: /workspace/ai_ui
    volumes:
      - ./:/workspace/ai_ui
  api-gateway:
    build: ./api-gateway
    depends_on: [tasks, open-webui]
    environment:
      WEBUI_SECRET_KEY: "${WEBUI_SECRET_KEY}"
      DATABASE_URL: "postgresql://openwebui:${POSTGRES_PASSWORD}@postgres:5432/openwebui"
      OPEN_WEBUI_URL: http://open-webui:8080
      TASKS_URL: http://tasks:8210
  caddy:
    image: caddy:2-alpine
    depends_on: [api-gateway]
    ports: ["127.0.0.1:8090:80"]
    volumes: [./Caddyfile:/etc/caddy/Caddyfile:ro]
volumes: { pg: {}, owui: {} }
```

**Before writing it, check every env var name and build context against
`docker-compose.unified.yml`** (`PGVECTOR_DB_URL` versus
`PGVECTOR_CONNECTION_STRING`, and the gateway and tasks build contexts). Use
the production names exactly.

**Test:** `docker compose --env-file .env.dev -f docker-compose.dev.yml config
--quiet` exits 0.

**Commit:** "Local dev: a standalone compose file and generated secrets".

---

### Task 3: Bring it up, and prove each layer

**Files:**
- Create: `scripts/dev_up.sh`, `scripts/dev_check.py`.

**`dev_up.sh`** with subcommands:
- `up`:
  1. start Docker Desktop if `docker info` fails, and wait;
  2. run `python scripts/dev_env.py`;
  3. `docker compose --env-file .env.dev -f docker-compose.dev.yml up -d --build`;
  4. wait for health;
  5. run the seed (Task 4) and `dev_check.py`.
- `down`: stop the stack, keeping its data.
- `reset`: `down -v`, after a confirmation prompt. It removes only
  `aiui-dev` volumes.
- `logs <svc>`.

**`dev_check.py`** prints one line per layer, PASS or FAIL, and exits
non-zero on any FAIL:
1. `GET http://localhost:8090/tasks/healthz` returns 200 `{"status":"ok"}`.
2. `GET http://localhost:8090/` returns 200 and contains `task-panel.js`
   (the override is mounted).
3. Open WebUI sign-in as the dev admin returns a token.
4. `GET /api/models` with that token lists `fake-agent`.
5. `GET /api/tasks/agents/tools` with the token returns 200.

**Steps:**
1. Run `bash scripts/dev_up.sh up`.
2. Fix what fails, one layer at a time, using
   superpowers:systematic-debugging. Expected trouble:
   - Open WebUI's first boot takes minutes;
   - the env var names;
   - the gateway's database queries on `mcp_proxy`, which are caught.
3. Record every fix in the compose file with a comment saying why.

**Done when:** `dev_check.py` prints 5 PASS twice in a row, after a
`down`/`up`.

**Commit:** "Local dev: one command up, with a layer-by-layer check".

---

### Task 4: Seed an admin and three agents

**Files:**
- Create: `scripts/dev_seed.py`.
- Test: covered by `dev_check.py`, extended with step 6.

**Behaviour** (all against `http://localhost:8090`):
1. If `POST /api/v1/auths/signin` with the dev admin fails, call
   `POST /api/v1/auths/signup` (the first user becomes admin).
2. Wait until `/api/models` lists `fake-agent`, so a seed is never burnt.
3. Call `POST /api/tasks/agents/seed`. It creates Ada and Mia once.
4. Create Dev through the same endpoint the "New agent" form uses (find it
   in `routes_agents.py`):
   - name Dev, role Developer;
   - instructions "You are Dev, a software developer. Answer briefly.";
   - base model `fake-agent`.

   Skip this when an agent named Dev already exists.
5. Print the agent names, never the password.

**dev_check step 6:** the owner's agent list contains Ada, Mia and Dev.

**Run it twice:** the second run creates nothing new.

**Commit:** "Local dev: a local admin and Mia, Ada and Dev".

---

### Task 5: End-to-end proof: a real agent turn on the fake model

**Files:**
- Create: `scripts/dev_e2e.py` (Playwright).
- It writes screenshots to `dev/out/` (gitignored).

**Steps:**
1. Sign in through the browser at `http://localhost:8090` as the dev admin.
2. Open `/ai-agents` and wait for the roster rows Ada, Mia and Dev.
3. Pick Ada and type "hello from local". Sending is allowed here: it is
   local and free.
4. Wait for an agent bubble containing "Ada here. You said: hello from
   local". Time from send to bubble should be about 1.5 s plus overhead;
   print it.
5. Open the Agent Office and check that Ada's robot exists. Screenshot the
   chat and the office.
6. Repeat with `scene:tool` and `scene:fail` and print what the thread
   shows. Record the outcomes; they are the input for Part 2.

**Done when:** steps 1 to 5 pass, and the screenshots show the local page
with the fake answer.

**Commit:** "Local dev: an end-to-end agent turn against the fake model".

---

### Task 6: Real-model switch

1. `LOCAL_MODEL=real` in `.env.dev` makes `dev_up.sh` start Open WebUI with
   `OPENAI_API_BASE_URLS=https://openrouter.ai/api/v1` and
   `OPENAI_API_KEYS=${OPENROUTER_API_KEY}`.
2. The agent default becomes `nvidia/nemotron-3-super-120b-a12b:free`, with
   `AGENT_PAID_DAILY_CAP=0`.
3. Use a compose profile or a second small override file
   (`docker-compose.dev.real.yml`). Saved Open WebUI connection config beats
   env after first boot, so the switch documents a `reset` (or editing the
   connection in the admin panel).
4. Verify only that the config renders with `docker compose ... config`.
   Running a real turn spends nothing on a free model, but needs a key: skip
   it unless one is provided.
5. Commit: "Local dev: switch to a real free model when wanted".

---

### Task 7: The "local first" rule, and the docs

1. Write `docs/LOCAL_DEV.md`, one page:
   - prerequisites;
   - `bash scripts/dev_up.sh up|down|reset|logs`;
   - the URL and the dev admin (read from `.env.dev`);
   - the scenes table;
   - what is not in the local stack (bots, MCP servers, video, n8n);
   - troubleshooting.
2. Add to the repo `CLAUDE.md`, under "Deploying to Hetzner", a section
   "Local first":
   1. Change the code.
   2. Run the unit and browser tests.
   3. `bash scripts/dev_up.sh up`, then check the change in a browser at
      `http://localhost:8090`, and run `scripts/dev_e2e.py` when agents are
      involved.
   4. Only then deploy with the hash-checked method.
   5. Say in the deploy notes what was checked locally.
3. Commit: "Docs: test in local Docker first, then deploy".

---

### Task 8: Review and hand-off

1. Code review (superpowers:code-reviewer) of the Part 1 diff. Check:
   - no secret is printed or committed;
   - project names cannot collide with production;
   - production compose and `.env` are untouched.
2. Fix important findings.
3. Push to `fork/main` after a fetch and rebase. Nothing is deployed to the
   server, because Part 1 is local only.
