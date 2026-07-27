# Design: Per-user Knowledge Graph ("Brain") page in Open WebUI

Date: 2026-07-27
Status: Approved (design), Phase 1 in progress
Owner: Ralph Benitez

## Goal

Give every Open WebUI user a personal **Graph** page: a force-directed knowledge
graph of what the AI knows about *them*, built from their own content. Different
for every user. Inspired by the "Brain / Graph" dashboards in agent apps
(sources -> topics -> sub-topics -> leaves).

## Sources (user's choice)

Build each user's graph from:
1. **Chats** (the user's own conversations) - Phase 1
2. **Uploaded docs / Knowledge** (OWUI files + Knowledge collections) - Phase 2
3. **Saved memories** (OWUI per-user memory) - Phase 3

Explicitly NOT sourced from external Gmail/Drive.

## Architecture

- **Store** (tasks Postgres, `tasks` schema): `graph_node` table, per-user, isolated:
  `id, user_email, kind, label, summary, parent_id, source_ref, created_at`.
  `kind` in (`root`, `topic` (L1), `subtopic` (L2), `leaf`). Links are the
  parent_id relationships (parent-child), like the reference graph.
- **Build pipeline** (`POST /graph/build`): pull the user's content (bounded:
  last N chats / M docs / K memories), send to the LLM (OpenAI key already in
  the tasks/OWUI env) to cluster into topics -> sub-topics -> leaf summaries,
  then replace that user's nodes. On-demand only (a Build/Refresh button), never
  automatic, to bound token + RAM cost on the 3.8GB box.
- **Read** (`GET /graph`): returns `{nodes:[...], links:[...]}` for the user.
- **Page** (`GET /graph/view`): tasks service serves an HTML page rendering a
  force-directed graph (self-contained: vendored/inlined force layout, no
  external CDN, to respect any CSP), with a legend, Build/Refresh, and node
  click -> detail. Token-authed like the visual editor deep-link.
- **Entry point**: a **"Graph"** item in the OWUI sidebar (or the "+" menu)
  that opens the page for the signed-in user.

## Identity / per-user

The page/endpoints resolve the signed-in OWUI user (email) and scope every
query + store row to that user. Reading the user's chats maps email -> user_id
via OWUI's `user` table, then reads the `chat` table for that user_id.

## Bounds (cost + resource safety)

- Build caps: last 30 chats, 50 docs, 100 memories (tunable valves).
- Max nodes per user: ~800 (truncate + note if exceeded - no silent drop).
- Build is on-demand (button), not on every message.
- One LLM clustering call path, reusing the in-container OpenAI key.

## Phases

- **Phase 1 (MVP):** store + `POST /graph/build` from **chats** + `GET /graph`
  + the Graph page (force graph, Build/Refresh) + sidebar entry. End-to-end per
  user. This spec's build target.
- **Phase 2:** add uploaded docs / Knowledge as sources.
- **Phase 3:** add saved memories (enable OWUI memory) + memory nodes.
- **Phase 4:** polish - search, node -> summary/Q&A, incremental rebuild.

## Testing

- Unit (offline): the cluster-response parser (LLM JSON -> nodes), node-tree
  builder, and bounds/truncation logic - no network.
- Live smoke: build a graph for a test user from a few chats; confirm nodes
  render in the page.

## Deploy

Backend lives in the `tasks` service (Postgres + OpenAI key + serves pages).
Follow CLAUDE.md deploy rules: commit, push changed files, rebuild `tasks`,
smoke `/tasks/graph/healthz`. Do not touch `.env` or `templates.py`.
