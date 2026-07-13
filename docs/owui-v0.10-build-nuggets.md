# Open WebUI v0.10.2 — opportunities for the App Builder

Date: 2026-07-13
Status: **deferred** (documented for a future project; not built in the
2026-07-13 prompt/resume pass)

The OWUI upgrade (v0.8.10 → v0.10.2, live since 2026-07-09) adds several features
that could improve the App Builder. They are all **sizeable architectural
changes**, not drop-in wins, so they were deliberately kept out of the bug-fix
pass and captured here for the team to pick up as their own projects.

## How the build feature integrates with OWUI today

The App Builder is essentially a **self-hosted web app bolted onto OWUI**, not a
native OWUI feature. Its entire coupling to OWUI is three things:

- **Injection:** `docker-compose.unified.yml` mounts a patched
  `openwebui-overrides/index.html` that injects one boot script,
  `/tasks/static/task-panel.js`. That script deep-clones OWUI's sidebar row to
  add "App Builder / Video / Cron" nav entries and borrows OWUI's login JWT.
- **Everything else is re-implemented under `/tasks/*`:** the gallery
  (`projects.html`), the preview/editor (`preview.html` + a home-grown iframe +
  `picker.js` visual-edit), templates, task tracking, cron, and even the built
  apps' own LLM proxy (`/api/chat-proxy`).
- It uses **none** of OWUI's native Artifacts, Knowledge Bases/RAG, Model
  builder, Functions/Tools, Pipelines, Channels, or prompt suggestions.

This is exactly why the v0.8→v0.10 image bump broke the UI (the index-override
trap, see the memory note): the coupling is fragile because it's a DOM-injection
graft rather than a native integration.

## Top 5 opportunities (ranked by leverage)

1. **Expose the build agent as a native MCP / OpenAPI tool server + native tool
   calling (v0.10.0).** Highest architectural payoff. The stack already connects
   a tool server to mcp-proxy (`docker-compose.unified.yml`). Registering the
   `aiuibuilder` build/enhance/preview endpoints as a native tool makes "build me
   an app" work from any chat, model, or channel — cutting the reliance on the
   fragile `index.html` override + DOM-cloned sidebar that broke on this upgrade.

2. **Ship a first-class "App Builder" Model via the model builder (v0.10.0).**
   Instead of DOM-cloning a sidebar entry, define a Model (system prompt = build
   persona, attached tools = the tool server from #1, attached knowledge = the
   templates catalog) that users pick from OWUI's model dropdown. Native,
   upgrade-safe, and context compaction supports long enhance loops. Removes the
   single biggest source of upgrade breakage.

3. **Native Artifacts for inline app preview** (docs; v0.9.5 CSP hardening for
   iframe artifacts, v0.10.0 client-side structured rendering). Best quick UX
   win: render a generated single-page app inline beside the prompt, shrinking
   the custom `preview.html` iframe. Caveat: Artifacts is single-file/in-chat, so
   it **complements** rather than replaces the multi-file preview + `picker.js`
   visual-edit workflow for complex apps.

4. **OWUI Knowledge Bases + RAG** (v0.9.6–v0.10.0: pgvector-native hybrid search,
   external KB connections, directory sync, a filesystem tool over knowledge).
   Replace the chatbot template's paste-in `<knowledge>` textarea
   (`templates.py`) with real Knowledge collections so built chatbots get genuine
   retrieval, and give the build agent a best-practices/templates KB. The stack
   already runs pgvector.

5. **Native scheduled automations + task primitive (v0.9.0).** Overlaps the
   home-grown Cron Jobs and Task Panel (run history, manual triggers, account
   re-checks before each run). Backing them with OWUI-native automations shrinks
   custom code and maintenance.

Honorable mentions: **Channels** (v0.9.5) for an in-OWUI `#app-builder` channel
with streaming builds (parity with the Discord/Slack builder), and **Notes**
(v0.10.0) for storing and resuming build briefs/history.

## Recommendation

Pursue **#1 (native tool server) + #2 (App Builder Model)** together as the next
build-feature project — they remove the upgrade-fragility that just cost the team
a blank-UI incident, and unlock "build from any chat/channel." Treat #3–#5 as
incremental follow-ups. Each is its own spec → plan → implementation cycle.
