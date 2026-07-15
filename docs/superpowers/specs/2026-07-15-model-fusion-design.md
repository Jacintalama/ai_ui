# Model Fusion (multi-model answer synthesis)

Date: 2026-07-15
Status: Approved direction (Ralph). Model availability verified live on prod.

## Goal

Add a "Fusion" capability to the Open WebUI chat: the user picks a Fusion
model from the normal model dropdown, sends a prompt, and gets ONE synthesized
answer produced by sending the prompt to a PANEL of real models in parallel and
having a JUDGE model combine them (consensus, contradictions, gaps, unique
insights). Fusion trades cost/latency for higher-confidence answers on hard
tasks (research, architecture, code review, security analysis).

Restricted to models actually available AND working in our system.

## Verified model inventory (probed live 2026-07-15)

Anthropic (key already in the tasks container) - all return 200:
`claude-opus-4-8`, `claude-sonnet-5`, `claude-fable-5`,
`claude-haiku-4-5-20251001`, `claude-opus-4-5`.

OpenAI (key present in the server `.env`, valid) - all return 200 when called
with the NEW contract (`max_completion_tokens`, no `temperature`):
`gpt-5`, `gpt-5.5`, `gpt-4o`, `gpt-4.1`, `o3`. (gpt-5/o3 are reasoning models -
give panel calls a generous token budget or they return empty.)

Two facts this surfaced, baked into the design below:
1. The OpenAI key lives in `.env` but is NOT injected into the tasks container.
   The fusion engine needs `OPENAI_API_KEY` added to the tasks service env.
2. Newer OpenAI models require `max_completion_tokens` and reject
   `temperature`; Claude uses the standard contract. The provider registry
   encodes the per-model call contract.

## Architecture

```
OWUI chat dropdown: "Fusion (Quality)" / "Fusion (Budget)"
   | user picks one, sends a prompt
   v
pipelines container: fusion_pipe.py  (THIN manifold pipe, ~100 lines)
   | POST http://tasks:8210/api/fusion/complete  (streaming), internal-secret auth
   v
tasks-service: fusion_engine.py  (all logic; versioned + unit-tested in git)
   1. resolve preset -> panel[model_ids] + judge model
   2. fan out the prompt to every panel model IN PARALLEL
        OpenAI models  -> OpenAI API (max_completion_tokens contract)
        Claude models  -> Anthropic API (standard contract)
   3. collect answers; a model that errors/times out is dropped, not fatal
   4. judge model synthesizes -> ONE final answer, STREAMED back
   v
pipe streams the judge tokens back to OWUI -> user sees one answer forming
```

The pipe carries no LLM logic: it authenticates, proxies to `/api/fusion`, and
streams the response through. Everything else is in our repo.

## Components

- `fusion_engine.py` (tasks-service):
  - `PROVIDER_REGISTRY: dict[model_id -> ModelSpec]` where ModelSpec =
    `{provider: "openai"|"anthropic", api_model: str, contract: "openai_new"|"anthropic"}`.
    Only registry models are usable anywhere - this is the single "only models
    available to our system" gate. Seeded with the verified models above.
  - `PRESETS: dict` - `quality` and `budget` (defaults below), each
    `{panel: [model_id...], judge: model_id}`. Validated against the registry
    at import (unknown model -> startup error).
  - `async call_model(model_id, messages, *, max_tokens) -> str` - dispatches
    to the right provider with the right contract; raises on failure.
  - `async fan_out(messages, panel) -> list[PanelAnswer]` - `asyncio.gather`
    over the panel with per-model timeout; failures captured as
    `PanelAnswer(model, ok=False, error=...)` and excluded from the merge.
  - `build_judge_prompt(user_question, answers) -> messages` - instructs the
    judge to compare consensus / contradictions / missing info / unique
    insights and produce ONE final answer; the panel answers are passed as
    labeled context, framed as data (not instructions).
  - `async fuse(messages, preset) -> AsyncIterator[str]` - fan_out, then stream
    the judge completion. Yields text chunks.
- `routes_fusion.py` (tasks-service):
  - `POST /api/fusion/complete` - internal-secret header auth (never public),
    body `{preset: str, messages: list}`, returns a streaming text response.
  - `GET /api/fusion/models` - lists exposed Fusion presets and the real
    models each resolves to (for the pipe's manifold list + debugging).
- `fusion_pipe.py` (pipelines container): a manifold Pipeline exposing
  `Fusion (Quality)` and `Fusion (Budget)`. Reads the tasks base URL + internal
  secret from Valves/env. On a chat request, POSTs the messages to
  `/api/fusion/complete` with the matching preset and streams the reply.

## Default presets (verified models)

- `quality`: panel = [`gpt-5.5`, `claude-opus-4-8`], judge = `claude-opus-4-8`.
- `budget`: panel = [`gpt-4o`, `claude-haiku-4-5-20251001`], judge = `gpt-4o`.

Overridable via pipe Valves (admin) OR engine env: `FUSION_QUALITY_PANEL`,
`FUSION_QUALITY_JUDGE`, `FUSION_BUDGET_PANEL`, `FUSION_BUDGET_JUDGE` as
comma-lists of registry model ids. Any id not in the registry is rejected with
a clear error - you can only choose models we have working keys for.

## Error handling & guardrails

- A panel model fails (timeout/API error): dropped; the judge runs on the
  survivors. If EVERY panel model fails: return a clean error, no crash.
- Judge fails: fall back to returning the single most-complete panel answer
  verbatim with a short "(fusion judge unavailable)" note.
- Cost/latency: hard cap panel size at 4; overall wall-clock timeout
  (`FUSION_TIMEOUT_S`, default 120); the pipe shows a "consulting N models..."
  status while the panel runs, then streams the judge.
- Panel token budget generous enough for reasoning models (gpt-5/o3) so they
  do not return empty.
- Auth: `/api/fusion/*` requires the internal secret; the pipe holds it via env,
  never in the file. Not routed publicly by Caddy.

## Testing

Pytest in our repo, no real LLM calls:
- registry/preset validation (unknown model rejected at import; valve override
  parsing accepts only registry ids).
- `call_model` builds the correct per-provider body (openai_new uses
  `max_completion_tokens`, no `temperature`; anthropic uses standard fields).
- `fan_out`: parallel; one-fails-is-dropped; all-fail returns the clean-error
  path; per-model timeout honored.
- `build_judge_prompt`: contains the consensus/contradictions/gaps/unique
  instruction and frames panel answers as data.
- `fuse`: streams judge output in order; judge-fails fallback returns a panel
  answer.
- route: `/api/fusion/complete` rejects a bad/missing internal secret; streams
  on success (engine mocked).

## Deploy

- Add `OPENAI_API_KEY=${OPENAI_API_KEY:-}` to the tasks service in
  `docker-compose.unified.yml` (the value already exists in `.env`).
- Install `fusion_pipe.py` into the pipelines container and register it; set its
  Valves (tasks URL `http://tasks:8210`, internal secret).
- Rebuild tasks; reload pipelines. Verify `Fusion (Quality)` and
  `Fusion (Budget)` appear in the OWUI model dropdown and a real prompt returns
  a synthesized answer that reflects both a GPT and a Claude panel member.

## Out of scope (future follow-ups)

- A per-user panel-builder UI ("Add model" as a custom page). v1 uses presets +
  admin valves.
- Adding Gemini/DeepSeek (one registry entry + key each when we add them).
- Showing the raw panel answers side-by-side before the merge.
