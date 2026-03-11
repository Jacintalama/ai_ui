# Rebuild Pipeline Design

**Date:** 2026-03-11
**Status:** Approved

## Overview

The rebuild pipeline is the second half of Lukas's BRE vision. Given extracted business requirements from any GitHub repo, it:

1. **Researches** existing solutions (open source, SaaS, frameworks) via web search
2. **Plans** how to use the recommended solution — either an integration plan (for existing) or a PRD (for custom build)

Command: `/aiui rebuild owner/repo`

---

## Section 1: Architecture & Flow

```
Discord/Slack              webhook-handler              claude-analyzer
     |                          |                            |
     | /aiui rebuild owner/repo |                            |
     |------------------------->|  POST /rebuild             |
     |                          |--------------------------->|
     |                          |                            |
     |                          |  Phase 1: RESEARCH         |
     |                          |  - Read cached BRE (or     |
     |                          |    run /analyze first)      |
     |                          |  - Claude + WebSearch       |
     |                          |  - Find: open source,       |
     |                          |    SaaS, existing solutions |
     |                          |  - Score & recommend        |
     |                          |                            |
     |                          |  Phase 2: PLAN             |
     |                          |  - If existing solution:    |
     |                          |    → integration plan       |
     |                          |  - If custom build needed:  |
     |                          |    → generate PRD           |
     |                          |  - Return structured output |
     |                          |                            |
     |  Discord message         |<---------------------------|
     |<-------------------------|                            |
```

**Key decisions:**
- Same container (`claude-analyzer`), new `/rebuild` endpoint
- Two sequential `runClaude()` calls inside one request
- Phase 1 output feeds directly into Phase 2 prompt
- Timeout: 600s total (warm) / 900s (cold, includes BRE extraction)
- Same mutex — one rebuild at a time
- BRE caching: if `/analyze` was already run for this repo, reuse cached result from `/workspace/{owner}/{repo}/.bre-cache.json`. If not, run BRE extraction first (~90s)

---

## Section 2: The `/rebuild` Endpoint

### Request
```json
{
  "owner": "some-org",
  "repo": "some-app",
  "branch": "main"
}
```

### Process
1. Validate input (same regex as `/analyze`)
2. Check mutex — return 503 if busy
3. Clone/fetch repo to `/workspace/{owner}/{repo}`
4. Check for cached BRE at `/workspace/{owner}/{repo}/.bre-cache.json`
   - If exists and < 24h old → use it
   - If missing or stale → run BRE extraction first, cache result
5. **Phase 1: Research** — Run Claude with WebSearch-enabled prompt, passing in the BRE
6. Save research results to `/workspace/{owner}/{repo}/.research-cache.json`
7. **Phase 2: Plan** — Run Claude with planning prompt, passing in BRE + research results
8. Parse and return structured response

### Response
```json
{
  "status": "success",
  "recommendation": "open-source | saas | custom-build",
  "research_summary": "## Existing Solutions\n...",
  "solutions": [
    {
      "name": "Cal.com",
      "type": "open-source",
      "url": "https://github.com/calcom/cal.com",
      "fit_score": 85,
      "pros": ["Self-hostable", "Active community"],
      "cons": ["Complex setup", "Missing feature X"],
      "effort": "Medium — 2-4 weeks to customize"
    }
  ],
  "plan": "## Implementation Plan\n...",
  "prd": null,
  "duration_seconds": 245.3
}
```

- `recommendation` — top-level verdict: use existing or build custom
- `solutions` — ranked list of discovered solutions with fit scores
- `plan` — implementation plan for the recommended path
- `prd` — only populated if `recommendation === "custom-build"`, contains full PRD markdown

---

## Section 3: The Prompts

### Phase 1 — Research Prompt

```
You are a solutions researcher. Given these business requirements extracted
from a codebase, find existing solutions that already solve this problem.

BUSINESS REQUIREMENTS:
{bre_report}

USER STORIES:
{bre_user_stories}

YOUR TASK:
1. Use WebSearch to find open-source projects, SaaS products, and existing
   frameworks that solve this problem or major parts of it
2. Search for: "{problem_statement} open source alternative"
3. Search for: "{core_features} SaaS solution"
4. Search for: GitHub repos solving similar problems
5. For each solution found, evaluate:
   - Feature coverage (what % of the BRE does it satisfy?)
   - Maturity (stars, contributors, last commit, funding)
   - Self-hostable vs cloud-only
   - Customization effort
6. Score each solution 0-100 on fit

You MUST output valid JSON with these fields:
- "recommendation": "open-source" | "saas" | "custom-build"
- "reasoning": why this recommendation (2-3 sentences)
- "solutions": array of {name, type, url, fit_score, pros, cons, effort}
- "research_summary": markdown overview of findings
- "gaps": features from BRE that NO existing solution covers

If no existing solution scores above 60, recommend "custom-build".
Search at least 5 different queries. Be thorough.
```

### Phase 2a — Integration Plan Prompt (open-source or SaaS)

```
You are a technical architect. Based on these research findings, create
an implementation plan for adopting the recommended solution.

BUSINESS REQUIREMENTS:
{bre_report}

RESEARCH FINDINGS:
{phase1_output}

Create a detailed implementation plan covering:
1. Setup & deployment steps
2. Configuration needed to match the business requirements
3. Customizations required (what needs to be built on top)
4. Migration path (if replacing an existing system)
5. Timeline estimate (phases with milestones)
6. Risks and mitigation

Output as a markdown document.
```

### Phase 2b — PRD Prompt (custom-build)

```
You are a product manager. Based on these business requirements and
research showing no adequate existing solution, create a Product
Requirements Document for a custom application.

BUSINESS REQUIREMENTS:
{bre_report}

RESEARCH FINDINGS (what exists but doesn't fit):
{phase1_output}

GAPS (features nothing covers):
{gaps}

Create a PRD with:
1. Executive Summary (problem, solution, KPIs)
2. User Personas & Stories (from BRE user_stories)
3. Functional Requirements (detailed, measurable, no vague language)
4. Non-Functional Requirements (performance, security, scalability)
5. Technical Architecture recommendation (stack, integrations)
6. Phased Roadmap (MVP → V1 → V2)
7. Success Metrics

Be specific. "Fast" → "200ms p95 response time".
"Scalable" → "handle 10K concurrent users".

Output as a markdown document.
```

Phase 2 prompt is selected based on Phase 1's `recommendation` field.

---

## Section 4: Webhook Handler Integration & Discord Output

### New command: `/aiui rebuild [owner/repo]`

Added to `CommandRouter` in `commands.py`:
- If no argument → uses default repo
- Calls `POST http://claude-analyzer:3000/rebuild`
- Sends initial acknowledgment, then full result

### Discord output (open-source/SaaS recommendation):
```
🔍 Rebuild Analysis: owner/repo

Recommendation: Open Source — Cal.com

## Top Solutions
1. **Cal.com** (open-source, 85/100)
   ✅ Self-hostable, active community, API-first
   ⚠️ Complex setup, missing feature X
   Effort: 2-4 weeks to customize

2. **Calendly** (SaaS, 72/100)
   ...

## Implementation Plan
1. Deploy Cal.com via Docker
2. Configure OAuth...
... (truncated)
```

### Discord output (custom-build recommendation):
```
🔨 Rebuild Analysis: owner/repo

Recommendation: Custom Build

No existing solution covers >60% of requirements.
Gaps: real-time collaboration, custom RBAC, tenant isolation

## PRD Summary
**Problem:** ...
**MVP Scope:** ...
**Timeline:** Phase 1 (4 weeks) → Phase 2 (6 weeks)
... (truncated)
```

Full report saved to `/workspace/{owner}/{repo}/.rebuild-report.md`.

Timeout: httpx client uses `timeout=960.0` with immediate acknowledgment message.

---

## Section 5: BRE Caching & Performance

### Cache strategy

When `/analyze` runs, save result to:
```
/workspace/{owner}/{repo}/.bre-cache.json
```

When `/rebuild` runs:
1. Check `.bre-cache.json` — if exists and < 24h old, skip BRE extraction
2. If stale or missing, run BRE extraction first (~90s)

### Timeout budget

| Step | Timeout | Notes |
|---|---|---|
| BRE extraction (if needed) | 300s | Same as /analyze |
| Phase 1: Research | 300s | Claude + WebSearch |
| Phase 2: Plan/PRD | 300s | Claude text generation |
| **Total max** | **600s** (warm) / **900s** (cold) |

### Memory
Same 512MB container limit. Research pass is text-in/text-out.

---

## Section 6: Changes Summary

| File | Change |
|---|---|
| `claude-analyzer/server.js` | Add `/rebuild` endpoint, add BRE caching to `/analyze`, add `REBUILD_TIMEOUT_MS = 900_000` |
| `webhook-handler/handlers/commands.py` | Add `rebuild` to `known_commands`, add `_handle_rebuild()`, add `_request_claude_rebuild()` |
| `webhook-handler/config.py` | No changes (reuses `claude_analyzer_url`) |
| `docker-compose.unified.yml` | No changes (same container) |

No new containers, no new dependencies, no new env vars.
