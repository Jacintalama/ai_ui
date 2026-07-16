# AI coding & app-builder market scan (mid-2026) + IO opportunities

Date: 2026-07-15
Status: research complete; nothing here is built yet (proposal for review)
Builds on: `docs/app-builder-feature-research-2026-07-14.md` (that doc covered
the four prompt-to-app builders only). This one widens the lens to coding
agents, frontier models, and agent infrastructure, and updates "where IO
stands" after the versions / AutoFix / pre-build-questions / Fusion merge.

## Method (and how much to trust it)

Ran a deep-research harness: 5 search angles, 19 sources fetched, 94 candidate
claims, top 25 put through 3-vote adversarial verification. Result: 16
confirmed, 9 refuted. Refuted claims are NOT used below.

Trust caveats (read before acting on any number):
- Most sources are blogs/aggregators. Their load-bearing facts are corroborated
  by primary sources (Supabase docs, Google docs, Veracode, Wiz, OpenAI's own
  pricing page), but exact figures are secondary snapshots.
- The model market turns over weekly. Treat all model rankings as directional,
  not fixed. "GPT-5.6 Sol" shipped ~6 days before this snapshot.
- Agent-infrastructure coverage (MCP adoption, sandboxes, memory, multi-agent
  orchestration) came back thin — treat that section as under-evidenced and see
  Open Questions.

## What shipped since the 2026-07-14 doc (IO's position moved)

The 2026-07-14 doc listed versions, AutoFix, and pre-build questions as
confirmed gaps. They are now shipped (in main `d052b641b`), alongside Fusion:
- App version timeline + non-destructive rollback (git-backed, now on Web +
  Discord + Slack).
- AutoFix loop (headless Playwright smoke -> narrow "fix only this" pass, max 2,
  fail-open).
- Structured pre-build clarifying questions (buttons, <=3, skippable).
- Model Fusion (panel of GPT + Claude models -> judge synthesis; Quality/Budget
  presets) in the OWUI chat.

So IO has closed most of the "table stakes" gaps flagged a day earlier. The
research below is framed against this newer, stronger baseline.

IO also already has: multi-surface builds (Web/Discord/Slack/Voice) with
answer-and-resume; publish + custom-domain/apex serving; connect-your-own
Supabase (OAuth link + per-app config, with a build gate until linked);
walkthrough video of the built app; cron/scheduled agents; no credit meter.

> **CORRECTION 2026-07-16.** This line originally also claimed "full code +
> infra ownership". That claim was wrong and is withdrawn. Verified against the
> code and against live prod on 2026-07-16:
>
> - **There is no export.** No download, zip, GitHub sync or clone route exists
>   for app source. An end user cannot get their app's code out of IO at all.
>   On this axis IO is currently *behind* Base44, the competitor this doc names
>   as the worst offender, which at least returns the React frontend.
> - **The version history barely exists.** 43 of 47 app directories in prod
>   have zero commits. The versions + rollback feature listed as shipped below
>   works for 4 apps. Cause: the commit is a prompt instruction to the agent
>   (`claude_executor.py:174-183`) that nothing verifies, plus `.gitignore`
>   rules shaped like build prompts (`apps/create-me-*/` and friends) that
>   swallow 11 real user apps.
> - "You own the box" is true for the operator, not for the end user building
>   an app on it.
>
> Being fixed under `docs/superpowers/specs/2026-07-16-app-history-commit-sweep-design.md`
> (part 1) and an export spec (part 2). The strategic reading of this is in the
> Positioning section, which is also corrected.

## Market scan by area

### 1. Prompt-to-app builders (Lovable, v0, Bolt, Replit, Base44, Firebase Studio, Softgen)

Cool stuff / now table stakes (CONFIRMED):
- Automatic full-stack provisioning: Lovable auto-provisions a full **managed**
  Supabase backend (DB, auth incl. OAuth/magic-links, storage) with **no
  external account required** and one-click deploy; Base44 is all-in-one ("no
  Supabase to configure, no GitHub to wire up"); Softgen generates
  frontend+backend+API+DB with built-in auth and GitHub sync.
  [altar.io, vibecodingacademy.ai, vitara.ai, supabase.com docs]
- The rest of the table-stakes set (from the 2026-07-14 doc, still current):
  live preview tied to the build loop, click-to-edit, clarifying/plan step,
  version timeline with restore, one-click deploy.

Where they fail (the real openings):
- **Security is a systemic failure** (CONFIRMED, high): Veracode's GenAI report
  (100+ LLMs) found **45% of AI-generated code fails basic security tests**
  (XSS failed in 86% of relevant samples), and newer/bigger models are no
  safer. The Jan 2026 **Moltbook breach leaked ~1.5M API tokens + 35k emails**
  because a vibe-coded app shipped **without Supabase Row Level Security**
  (investigated by Wiz). [veracode.com, wiz.io]
- **Lock-in vs ownership** (CONFIRMED, medium): Base44's export is "meaningfully
  more limited" (frontend React only; DB/auth/logic stay in a closed SDK) -> a
  win means "rebuilding, not migrating" (2.4/5 Trustpilot). Softgen counters
  with full ownership + GitHub sync. [altar.io, vitara.ai]
- **Deploy friction** (CONFIRMED, medium): Firebase Studio's default publish
  path requires setting up a Google Cloud **billing account** — "cumbersome,"
  "confusing for beginners" (Google's own docs). [nocode.mba, firebase docs]
- **Multi-file incoherence** (CONFIRMED, medium): Softgen (and the category)
  suffers cascade regressions — "a small tweak can cause side effects
  elsewhere," with auth breaking after several edits past ~15-20 components.
  [vitara.ai]

NOT asserted (these lost their 3-vote verification — do not plan against them):
"v0 has no backend," "Bolt has no database / only partial deploy," "Firebase
relied on browser localStorage for auth," and the "all builders hit a shared
60-70% production wall" framing. Multiple sources contradicted each.

### 2. Coding agents & IDEs (Cursor, Windsurf, Claude Code, Devin, Codex, Copilot, Jules, Amp)

Cool stuff (CONFIRMED, high):
- **Async, PR-returning agents in isolated VMs** are the dominant autonomous
  pattern. Google **Jules** (backed by Gemini 3.1 Pro with VM-level tool
  access): tasks queue into a pool, run in isolated Google Cloud VMs, and return
  **pull requests** against a branch in the user's own repo (15 concurrent tasks
  Pro / 60 Ultra). [blog.google, jules.google, digitalapplied.com]
- Three coexisting paradigms to position against: Claude Code (synchronous
  terminal/IDE orchestrator, human reviews diffs live), Codex, and Jules (fully
  async).

The gap: all of these assume a **developer** — GitHub, branches, PR review. That
is the audience boundary IO sits outside of (see opportunity #6).

### 3. Frontier models for coding (CONFIRMED, high on "who leads"; directional on exact scores)

- Leaderboard shape mid-2026: **GPT-5.6 Sol #1 overall** (llm-stats: 1.1M
  context, ~$7.78/M blended); **Claude Fable 5 / Opus 4.8 / Sonnet 5 hold three
  of the top four**, with Claude strongest on coding sub-scores and independent
  SWE-bench Verified boards (Fable 5 ~95%, Opus 4.8 ~88.6%).
  [llm-stats.com, whatllm.org, anthropic.com, openai.com]
- **Agentic coding is unsolved** (this is the important one): Terminal-Bench Hard
  tops out only in the low-to-mid **60s%** (GPT-5.6 Sol 65.9, Fable 5 62.9, Opus
  4.8 58.3). [artificialanalysis.ai]
- In agent loops, **tool-call reliability and cost beat benchmark peaks** —
  Claude cited for "fewer broken edits" (looks-right-but-breaks-tests) on large
  codebases; GPT-5.5's higher headline SWE-bench comes at $30/M output
  (OpenAI's own pricing), i.e. hardest-tickets-only. [dev.to, layer3labs.io]
- Open models are narrowing the gap (e.g. Qwen 3.6 Plus in the same
  SWE-bench conversation as frontier closed models). [mindstudio.ai]

IO fit: IO already defaults to a Claude coding model (Opus 4.8). Keep the builder
model-pluggable; the research says invest in **reliability + self-repair + smart
routing**, not in chasing the top benchmark line.

### 4. Agent infrastructure (UNDER-EVIDENCED — treat as directional)

- **Pause/resume is becoming a first-class agent architecture** (CONFIRMED,
  high): Google's ADK ships automatic per-tool-call checkpointing — an agent can
  go dormant for days, then "when the webhook fires, the container spins up, the
  session is hydrated from SQLite, and the agent resumes exactly where it
  paused" (ADK 2.0 TOOL_PAUSED / AGENT_STATE_CHECKPOINT events for
  human-in-the-loop). Caveat from the source: durable persistence needs a config
  step and tools run at-least-once (may re-run on resume).
  [developers.googleblog.com, google.github.io/adk-docs]
- MCP adoption specifics, sandboxes (e2b/Daytona), agent memory, and multi-agent
  orchestration did not produce surviving claims — see Open Questions.

## The one pattern that matters most

The industry is converging on **async, pause/resume, PR-returning agents**
(Jules, ADK checkpointing). IO's paused-build **answer-and-resume across
Web/Discord/Slack/Voice** is the same architecture — but pointed at
non-developers on conversational surfaces instead of at PR review. That is
simultaneously (a) validation that IO bet on the right shape and (b) a
differentiator no surveyed competitor occupies. No external product surfaced
that offers conversational building across chat + voice.

## Ranked IO opportunities (build on what shipped, don't repeat it)

1. **Harden + productize multi-surface answer-and-resume as the signature.**
   The seam exists (shipped Jul 13). Make the checkpoint store durable, define
   at-least-once tool semantics on resume, and treat "start a build in Slack,
   answer a question by voice, finish on web" as the headline story. Rationale:
   directly validated by the ADK/Jules async trend; nobody else is chat/voice
   native. Effort: small-medium (mostly hardening + positioning).

2. **Security-by-default provisioning.** RLS on by default, auth scaffolding,
   secret hygiene, and a pre-deploy security gate that blocks (or auto-fixes)
   OWASP-class issues. Rationale: the single most defensible, evidence-backed
   gap in the category (Veracode 45%, Moltbook). Ties to the still-open
   publish-time safety scan (#6 in the 2026-07-14 doc); IO's CLAUDE.md-style
   guardrails + KB grounding make it credible. Effort: medium.

3. **Coherence-aware editing (stop cascade regressions).** Use the version +
   AutoFix machinery IO just shipped as the base: on enhance, diff-scope the
   change, re-run the smoke against previously-working routes, and roll back the
   single change if it regresses them. Rationale: the top unsolved failure mode
   across the category and the reliability gap the model research highlights.
   Effort: medium.

4. **Lower backend onboarding friction without giving up ownership.** IO's
   connect-your-own-Supabase (OAuth link) is an ownership win but a friction
   stall vs Lovable's zero-setup managed backend. Streamline the link to
   near-zero clicks and/or offer an optional managed-provision path — match the
   provisioning table stakes while keeping "you own the DB." Effort: medium.

5. **Reliability-first, cost-tiered model routing (Quick / Deep).** Two named
   presets: cheap executor by default, top-tier planner + hard-bug pass on
   demand; default to a Claude coding model, GPT-5.6 Sol as an option. Extends
   Fusion and the 2026-07-14 doc's #5. Rationale: research says reliability +
   cost tiering beats benchmark chasing. Effort: small.

6. **Own the "non-developer, conversational, voice-native builder" position.**
   Every autonomous-coding competitor targets developers (PRs, GitHub). Lean
   into building for people who will never open a PR. Rationale: uncontested
   space; aligns with IO's existing surfaces. Effort: positioning + UX, small
   code.

7. **OWUI-native tool server + App Builder Model** (carried over from the
   2026-07-14 / OWUI-nuggets docs, still open). Removes the fragile index.html
   DOM injection that already caused a blank-UI incident and makes "build me an
   app" work from any chat/model/channel. Effort: medium, its own spec cycle.

## Positioning summary

IO's sharpest story is exactly where the market is weak: no credit meter, and it
lives in Slack/Discord/Voice where non-developers already are, plus two
category-unique tricks (walkthrough videos of your app, scheduled agents that
keep working after the build). The async answer-and-resume architecture the
whole industry is adopting, IO already has, pointed at a different, underserved
user.

> **CORRECTION 2026-07-16.** This paragraph originally also claimed "real
> rollback (shipped), you own the code + the box + the database". Both are
> withdrawn: rollback works for 4 of 47 prod apps, and there is no export at
> all. See the correction above.
>
> The honest strategic reading is sharper than the original, not weaker.
> **Three things in IO rest on asking the LLM nicely and never checking:** the
> git commit (`claude_executor.py:174`), RLS (`:271-287`, and the OAuth-only
> path does not even receive those instructions), and the `schema.sql` the
> agent is asked to write. All three are broken or unverifiable in production.
> The AutoFix smoke shipped 2026-07-13 is the only step in the build that
> verifies its own claim, and it is the only one of the four that works.
>
> So opportunities 2, 3 and 4 below are not three projects. They are one
> pattern: **stop trusting the prompt, verify the result.** That reframing is
> what makes the ownership and security stories real rather than aspirational,
> and it is a pattern no competitor can copy quickly, because none of them have
> a verify loop wired into the build at all.

## Open questions (worth a focused follow-up)

1. MCP adoption specifics across builders/agents in mid-2026, and emerging
   tool-use / agent-eval standards (no surviving claim — explicit gap).
2. Sandbox + deploy-target landscape (e2b, Daytona) and what IO's
   isolated-execution + deploy target should be (IO already has VM-agent +
   Squid-egress isolation to build on).
3. Voice / chat-native building: no competitor found — what analog signals
   exist, and what are the real UX limits (disambiguation, preview, confirm) of
   building/resuming by voice?
4. Multi-agent orchestration + persistent memory / KB grounding as a fix for the
   cascade-regression gap — how should IO position its KB grounding here?

## Sources

Primary/authoritative: developers.googleblog.com (ADK pause/resume),
google.github.io/adk-docs, blog.google + jules.google (Jules), veracode.com
(GenAI security), wiz.io (Moltbook), firebase.google.com/docs (deploy billing),
supabase.com/docs (Lovable backend), openai.com + anthropic.com (model
releases/pricing).
Secondary/aggregator (corroborated where load-bearing): llm-stats.com,
whatllm.org, artificialanalysis.ai, altar.io, vibecodingacademy.ai, vitara.ai,
nocode.mba, dev.to, layer3labs.io, digitalapplied.com, mindstudio.ai.
