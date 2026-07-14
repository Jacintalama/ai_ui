# App Builder: what to build next (market research + proposal)

Date: 2026-07-14
Status: proposal for review (research complete; nothing here is built yet)
Companion doc: `docs/owui-v0.10-build-nuggets.md` (Open WebUI-native opportunities)

## How this was researched

Three inputs, cross-referenced:
1. Feature scan of Lovable, Replit Agent, Vercel v0, and Bolt.new from their
   official changelogs/docs/blogs (mid-2026 state).
2. User-demand scan: recurring complaints and switching drivers from HN,
   comparison sites, and review roundups (secondary sources; the loudest
   signals are consistent across many of them).
3. A capability inventory of OUR system (what the App Builder, video
   generator, cron, and connectors already do), verified against the code.

## What the market says

**Top complaints about the big four (in order of loudness):**
1. Credit/token burn on failed fixes: agents loop on a bug, users watch
   credits drain ("doom loops"; reports of hundreds to thousands of dollars).
2. The "80% wall": 0 to MVP is magic, the last 20% burns disproportionate
   time and money.
3. Lost work and trust: no reliable rollback; the famous Replit incident
   (agent deleted a production DB, then faked data to cover it).
4. Auth/DB complexity leaking through the no-code promise (Supabase RLS
   confusion is the canonical case).
5. Quality collapse on complex features + platform lock-in (v0 to Vercel,
   Lovable to Supabase).

**What every serious builder now has (table stakes):** live preview tied to
the build loop, click-to-select element editing, clarifying questions or a
plan step before building, chat-history-as-version-timeline with restore,
one-click Stripe, custom domains, GitHub export, per-action permission
prompts, spend visibility.

**Standout differentiators:** v0's dedicated AutoFix model and durable
"Project" object; Replit's autonomy slider + checkpoints and
plan-approval gate; Lovable's publish-time security scan with auto-fix and
version timeline with restore-as-new-entry; Bolt's layer-based element
picker and real-time multiplayer.

**Where a self-hosted chat-first builder is structurally advantaged:**
1. No credit anxiety (our own API bill, no marked-up meter) - the #1
   complaint simply does not apply to us.
2. Hard rollback guarantees (git/filesystem snapshots we control).
3. Full code ownership, zero lock-in (real demand: open-source alternatives
   like Dyad exist purely for this).
4. Chat-platform-native (Slack/Discord/voice) - all four competitors are
   browser-first with a chat panel bolted on.
5. Cron-native scheduled agents - essentially absent from the category; we
   already have them.

## Where we stand today

Already competitive or ahead: multi-surface chat builds (web/Slack/Discord/
voice), private build threads, templates, enhance loop, paused-build
questions with answer/resume (shipped Jul 13), visual editor with
click-to-edit, publish/unpublish, walkthrough VIDEO generation of built apps
(nobody else has this), cron agents, Gmail/Drive connectors.

Confirmed gaps vs table stakes:
- No versions/checkpoints/rollback for apps (enhance overwrites; the video
  generator has versions, apps do not).
- No AutoFix pass: build/runtime errors surface to the user instead of
  being fed back through a narrow fix loop first.
- No pre-build clarifying questions (we ask questions only mid-build when
  the agent gets stuck).
- No plan-approval gate option.
- No per-app env/secrets story, no publish-time safety scan, no unified
  spend view, no preview annotations.

## Proposal (ranked)

### Build now - quick wins with the strongest signal

**1. App version timeline + restore.** Snapshot the app directory on every
build/enhance completion; "Versions" list with a Restore button on web,
Discord, and Slack. Restore creates a NEW version pointing at the old state
(Lovable's model - never destructive). Directly answers complaint #3, is
table stakes everywhere else, and we already have the exact pattern built
for video jobs (versions table + revert flow) to copy. Estimated: small.

**2. AutoFix loop in the executor.** When a build/enhance produces a broken
app (build error, console error on first load, failed smoke), feed the
exact error back through a narrow "fix only this error" pass up to 2 times
before telling the user. Kills doom-loop frustration at the root; v0 treats
this as their crown jewel. We control the whole executor, so this is a
prompt + retry-policy change plus an error-capture hook in the preview
smoke. Estimated: small-medium.

**3. Pre-build clarifying questions (1-3, with buttons).** Before
scaffolding starts, let the agent ask up to 3 short questions rendered as
buttons/selects on web, Discord, and Slack. We JUST shipped the
answer/resume plumbing for paused builds - this reuses that seam at the
start of the flow. v0 and Bolt both converged on this pattern this year.
Estimated: small.

### Build next - strategic

**4. OWUI-native tool server + first-class App Builder Model.** Per the
companion doc: register build/enhance/preview as a native OWUI tool server
and ship an "App Builder" model users pick from the dropdown. Removes the
fragile index.html DOM injection that already caused one blank-UI incident,
and makes "build me an app" work from any chat. Estimated: medium, its own
spec/plan cycle.

**5. Quick build / Deep build toggle (model tiering).** Two named presets
instead of invisible model choices: Quick (cheap executor tier) and Deep
(top-tier planner pass + executor). Matches the planner/executor/cheap-fix
tiering the whole industry converged on; cheap UX (two buttons in the
panels). Estimated: small.

### Later - valuable, not urgent

6. Publish-time safety scan (open CORS, exposed debug routes, missing auth
   on published apps) with auto-fix of safe findings (Lovable's move).
7. Unified usage ledger queryable in chat ("what did my builds cost this
   month?") - reinforces our no-credit-markup advantage honestly.
8. Preview annotations mode (numbered click-comments batch-sent to the
   agent) in the web editor - our picker.js already selects elements.
9. Per-app secrets vault incl. auto-capture of pasted API keys
   (security review required before building).
10. OWUI Knowledge Bases for the chatbot template (real retrieval instead
    of the paste-in knowledge textarea).

## Positioning note

The research says our sharpest marketing story is exactly what the big four
get beaten up for: no credit meter, real rollback (once #1 ships), you own
the code and the box, and it lives in Slack/Discord where the team already
is - plus two category-unique tricks (walkthrough videos of your app, and
scheduled agents that keep working after the build).

## Model landscape (brief)

Current Anthropic lineup relevant to us: Fable 5 (top tier), Sonnet 5
(default mid tier), Opus 4.8, Haiku 4.5 (cheap/fast). Industry tiering
pattern: top model plans and handles hard bugs sparingly, mid model does
bulk generation, cheap model does lint-level fixes and retries. Proposal #5
adopts exactly this. Competitor model claims from SEO aggregators were NOT
verifiable and are excluded; verify pricing against the official docs
before any cost-dependent decision.
