# User Knowledge Graph, Phase 1 (chats -> graph page) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use `- [ ]` checkboxes.

**Goal:** Every OWUI user gets a **Graph** page showing a per-user, force-directed knowledge graph built from their own chats, with a Build/Refresh button.

**Architecture:** New module in the `tasks` service. A `knowledge_graph_node` table (per-user). `POST /graph/mine/build` reads the user's OWUI conversations, an LLM clusters them into topics -> sub-topics -> leaf summaries, stored as nodes. `GET /graph/mine` returns `{nodes, links}`. `GET /tasks/graph` serves a self-contained page rendering the force graph (renderer adapted from `static/projects.html`). A "Graph" entry is injected into the OWUI sidebar (via the existing frontend injector) pointing at the page.

## Global Constraints
- Per-user isolation: every query + node row scoped to `current_user().email` (from `x-user-email`, lowercased). Never leak another user's nodes.
- Bounds (cost/RAM on the 3.8GB box): read at most **30** most-recent chats; cap stored nodes at **800** per user (truncate + surface a note, never silent-drop). Build is on-demand only.
- Reuse existing patterns: `auth.current_user`; OpenAI via `fusion_engine._openai_key()` + httpx to `OPENAI_API_BASE`; DB via the tasks `session()` / asyncpg.
- OWUI chats live in `public."chat"` (cols: `id`, `user_id`, `title`, `chat` JSON, `updated_at`); map email -> `user_id` via `public."user"`.
- No em-dashes in code/UI copy. No secrets in code. Attribute commits to Ralph only. Don't touch `.env` or `templates.py`.
- Deploy: commit, push changed files, rebuild `tasks`, smoke.

---

### Task 1: Knowledge-graph store + read endpoint

**Files:** Create `mcp-servers/tasks/routes_knowledge_graph.py`; Test `mcp-servers/tasks/tests/test_knowledge_graph.py`; wire `graph_mine_router` into `main.py`.

**Interfaces produced:** `router` (prefix `/graph/mine`), `GET /graph/mine` -> `{nodes:[{id,kind,label,parent_id}], links:[{source,target}]}` for the signed-in user; a `_ensure_table()` that `CREATE TABLE IF NOT EXISTS knowledge_graph_node (id uuid pk, user_email text, kind text, label text, summary text, parent_id uuid null, source_ref text, created_at timestamptz default now())`.

- [ ] **Step 1: failing test** for a pure `build_links(nodes)` helper (turns parent_id into `{source,target}` links, skips roots) and `cap_nodes(nodes, 800)` (truncates + sets a `truncated` flag). Assert real behavior.
- [ ] **Step 2:** run it, confirm fail.
- [ ] **Step 3:** implement `build_links`, `cap_nodes`, `_ensure_table`, and `GET /graph/mine` (reads this user's rows -> nodes + links).
- [ ] **Step 4:** run tests -> pass.
- [ ] **Step 5:** wire `app.include_router(graph_mine_router)` in `main.py`; add `GET /graph/mine/healthz`. Commit.

### Task 2: Build-from-chats pipeline

**Files:** Modify `routes_knowledge_graph.py`; Test `tests/test_knowledge_graph_build.py`.

**Interfaces:** `POST /graph/mine/build` -> reads <=30 recent `public.chat` rows for the user, concatenates titles+message snippets, calls the LLM with a strict JSON instruction to return `{topics:[{label, subtopics:[{label, leaves:[{label, summary}]}]}]}`, parses it, replaces the user's nodes (root -> topics -> subtopics -> leaves), returns counts.

- [ ] **Step 1: failing test** for `parse_cluster_json(text)` (strips code fences, validates shape, returns topics tree) and `tree_to_nodes(user, tree)` (flattens to node rows with parent_id + root). Include a malformed-JSON case -> raises ValueError.
- [ ] **Step 2:** run, confirm fail.
- [ ] **Step 3:** implement `parse_cluster_json`, `tree_to_nodes`, the LLM call (reuse `_openai_key()` + httpx, model `gpt-4o`, temperature 0, bounded input), and `POST /graph/mine/build` (delete old nodes for user in a txn, insert new, cap at 800).
- [ ] **Step 4:** run tests -> pass.
- [ ] **Step 5:** commit.

### Task 3: Graph page + sidebar entry

**Files:** Create `mcp-servers/tasks/static/graph.html`; add `GET /tasks/graph` (FileResponse) in `main.py`; modify `mcp-servers/gdrive/integrations-ui.js` (inject a "Graph" sidebar item).

**Interfaces:** `GET /tasks/graph` serves the page; page calls `GET /graph/mine` to draw and `POST /graph/mine/build` on the Build button. Force renderer adapted from `static/projects.html` (self-contained, no external CDN).

- [ ] **Step 1:** create `graph.html`: header + legend (Topic/Sub-topic/Leaf) + Build/Refresh button + a canvas/SVG force graph. Adapt the simulation from `projects.html`. Fetch `/graph/mine`; empty-state prompts "Build" .
- [ ] **Step 2:** add `GET /tasks/graph` in `main.py` returning `FileResponse("static/graph.html")`.
- [ ] **Step 3:** in `integrations-ui.js`, inject a **Graph** sidebar entry (reuse the menu-injection approach) linking to `/tasks/graph`. Bump the version log.
- [ ] **Step 4:** manual check: page loads, Build creates nodes, graph renders.
- [ ] **Step 5:** commit.

### Task 4: Deploy + live smoke

- [ ] Push changed `tasks` files, rebuild `tasks`; scp `integrations-ui.js` (bind mount).
- [ ] Smoke: `GET /graph/mine/healthz` 200; as a real user, open the Graph page, click Build, confirm nodes render and are scoped to that user.
- [ ] Record result; do not claim done until the live graph renders per user.

## Notes for implementer
- Keep the LLM prompt strict-JSON and bounded; on parse failure, return a clean error (don't crash the endpoint).
- The build must be idempotent per user (replace, not append).
- If node count would exceed 800, keep the top topics/subtopics and note the truncation in the response + page.
