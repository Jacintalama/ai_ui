# LiteLLM adoption: probed, works, declined on memory

Date: 2026-07-23
Status: **Decided — do not adopt now.** Revisit on the triggers below.
Decision: Jacint, after the Phase 0 probe returned its numbers.

## The question

`fusion_engine.py` hand-rolls three request contracts in `PROVIDER_REGISTRY`
because providers disagree on request shape:

| contract | models | shape |
|---|---|---|
| `openai_new` | gpt-5, gpt-5.5, o3 | `max_completion_tokens`, no temperature |
| `openai_legacy` | gpt-4o, gpt-4.1 | `max_tokens` + temperature |
| `anthropic` | 5 Claude models | `max_tokens`, system pulled out of messages |

That is ~35 lines in `call_model`, plus four more files in this service
(`routes_tasks`, `video_codegen`, `video_plan`, `video_refine`) making their own
raw httpx calls. LiteLLM exists to own exactly this mapping across 100+
providers. Deep research (2026-07-23, 25/25 claims confirmed) said the library
form would replace it with no new infrastructure.

## Phase 0 probe: what was actually measured

Run in a throwaway container from the **real** `proxy-server-tasks:latest`
image, so Python 3.11 on Linux, not the dev laptop. Production untouched.

**Gate 1 — does it install alongside our pins?** PASS. Clean install (exit 0)
next to `fastapi`, `pydantic>=2`, `httpx>=0.28`, `anthropic 0.118`. litellm
1.93.0.

> A first attempt on the Windows dev machine failed with
> `metadata-generation-failed`. That was a **false signal** — local Python is
> 3.13.5 and the service runs 3.11. Always probe LLM deps in the real image.

**Gate 2 — does it send the right wire format for OUR models?** PASS, 10/10.
Method: local mock HTTP server, LiteLLM pointed at it via `api_base`, capture
the body actually put on the wire. No API keys, no network.

```
gpt-5 / gpt-5.5 / o3          -> keys=['max_completion_tokens']        OK
gpt-4o / gpt-4.1              -> keys=['max_tokens','temperature']     OK
all 5 claude-*                -> keys=['max_tokens','system']          OK
```

LiteLLM distinguishes the gpt-5 family from gpt-4o by name, and handles our
2026 Claude ids (`claude-fable-5`, `claude-opus-4-8`) correctly via the
`anthropic/` provider prefix. Prefixing is required — do not rely on bare-name
guessing if this is revisited.

Scope note: the `openai_new` cases did not pass a temperature (matching what our
code does), so this proves LiteLLM **sends** the right params, not that it would
**drop** a temperature if given one. Irrelevant to the swap, since our code
controls what it passes.

**Gate 3 — what does it cost?**

```
site-packages   304 MB -> 493 MB   (+189 MB image)
RSS on import     7 MB -> 196 MB   (+189 MB resident, permanent)
```

Pulls in `openai`, `tiktoken`, `tokenizers`, `aiohttp`, `Jinja2` — a large
expansion for a service that deliberately uses raw httpx and does not even
install the `openai` package.

**It would fit.** Stated plainly because an earlier draft of this doc overstated
it as a hard blocker: the `tasks` container runs at **105 MiB against a 1 GiB
limit**, so +189 MB lands near 294 MiB, under 30% of its own cap. The host had
499 MB free / 1821 MB available. Nothing here makes adoption impossible.

## Why declined

Not "it does not fit" — **the trade is bad.**

We would spend +189 MB resident and take on `openai` + `tiktoken` + `tokenizers`
+ `aiohttp` in a deliberately lean service, in order to delete 35 lines that are
correct today and pinned by 16 wire-format tests. Nothing is broken. There is no
bug to fix. The only real return is *future* maintenance we are not yet paying.

The memory does carry a specific risk worth recording even though it fits: this
box already OOMs under pressure (the in-container tasks test tier gets SIGKILLed
at exit 137, see the OOM-chunking lesson), and the tasks service is the one that
spawns Claude Code CLI subprocesses for every build. Making that particular
container ~2.8x its idle size is not free, and the host's *free* RAM fluctuated
358-508 MB during this session.

So: viable, measured, and declined on value rather than on feasibility.

## What would change the answer

Revisit when any of these becomes true:

1. **A third provider is added** (Gemini, Mistral, a local model). Hand-rolling a
   fourth contract is where the maintenance actually starts to hurt.
2. **The box gets more RAM.** 189 MB is affordable with real headroom.
3. **Cost visibility becomes a priority.** There is zero spend attribution today
   across ~10 call sites. That needs the *proxy* form (+ Postgres), not the
   library, and would be its own decision.
4. **A model contract breaks in production.** If a new model ships a fourth
   shape and it bites us, the maintenance argument wins on evidence.

If revisited, prefer the **separate container** form over the library: the same
189 MB, but isolated behind a hard memory limit where it cannot OOM a build, and
it is the only path to the cost-tracking and guardrail features.

## What was NOT done

No production code changed. No dependency added. No tests touched. The 16
existing Fusion wire-format tests still verify the hand-rolled contracts, which
remains the strongest reason the current code is safe to keep.
