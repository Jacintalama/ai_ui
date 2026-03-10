# Design: Claude Analyzer (Business Requirements Extractor)

**Date:** 2026-03-10
**Status:** Approved
**Stakeholder:** Lukas

## Problem

We need a way to point at any GitHub repo and extract what it does (business requirements, use cases, target users) without implementation details. This enables rebuilding applications from requirements using AI.

## Decisions

- **Trigger:** Discord/Slack command only (`/aiui analyze [owner/repo]`)
- **Output:** Structured markdown report (for humans) + JSON user stories (for machines)
- **Delivery:** Discord message with the report
- **Container:** Extend existing pr-reviewer into a generic `claude-analyzer` container with multiple endpoints
- **Scope:** Build BRE endpoint only now; other skills (security, packages, quality) added later as separate PRs

## Architecture

```
Discord/Slack          webhook-handler            claude-analyzer
     |                      |                          |
     | /aiui analyze o/r    |                          |
     |--------------------->| POST /analyze            |
     |                      |------------------------->|
     |                      | 1. Clone/fetch repo      |
     |                      | 2. claude -p with prompt |
     |                      | 3. Return report + JSON  |
     | Discord message      |<-------------------------|
     |<---------------------|                          |
```

### Container: `claude-analyzer`

Renamed from `pr-reviewer`. Same base:
- **Image:** node:20-slim + @anthropic-ai/claude-code
- **Volume:** workspace for cached repos
- **Mutex:** One analysis at a time
- **Memory:** 512MB limit
- **Port:** 3000
- **Env:** ANTHROPIC_API_KEY, GITHUB_TOKEN

### Endpoints

| Endpoint | Purpose | Trigger |
|----------|---------|---------|
| GET /health | Health check | Docker healthcheck |
| POST /review | PR code review (existing) | GitHub webhook + `/aiui pr-review` |
| POST /analyze | Business requirements extraction (new) | `/aiui analyze owner/repo` |
| POST /security | Security audit (future) | `/aiui security owner/repo` |
| POST /packages | Dependency check (future) | `/aiui packages owner/repo` |
| POST /quality | Code quality review (future) | `/aiui quality owner/repo` |

Only `/health`, `/review`, and `/analyze` are built now. Others are documented for future.

### POST /analyze

**Request:**
```json
{
  "owner": "some-org",
  "repo": "some-app",
  "branch": "main"
}
```

**Response:**
```json
{
  "status": "success",
  "report": "## Problem Statement\n...",
  "user_stories": [
    {
      "role": "developer",
      "feature": "submit PRs for automated review",
      "benefit": "get immediate feedback"
    }
  ],
  "duration_seconds": 87.3
}
```

**Prompt template:**
```
Analyze this codebase and extract ONLY the business requirements.

DO NOT describe implementation details, technologies used, or code structure.
Focus on WHAT the application does, not HOW.

Output a JSON object with two fields:

1. "report" - A markdown document with these sections:
   - Problem Statement (what problem does this solve?)
   - Target Users (who uses this?)
   - Core Features (what can users do?)
   - Use Cases (3-5 key scenarios)
   - Integrations (what external systems does it connect to?)

2. "user_stories" - An array of objects, each with:
   - "role": who benefits
   - "feature": what they can do
   - "benefit": why it matters

Read the README, main entry points, route handlers, and UI components.
Skip test files, build configs, and infrastructure code.
```

**Timeout:** 300 seconds
**Diff limit:** N/A (full repo access, no diff needed)

### Webhook Handler Integration

**New command:** `/aiui analyze [owner/repo]`
- No argument → default repo (TheLukasHenry/proxy-server)
- With argument → analyzes specified repo
- Calls POST http://claude-analyzer:3000/analyze
- Posts structured report to Discord/Slack (truncated to 2000 chars)
- Fallback: existing Open WebUI `_handle_analyze` method

**Config:**
```python
claude_analyzer_url: str = "http://claude-analyzer:3000"
```

### Migration from pr-reviewer

1. Rename `pr-reviewer/` → `claude-analyzer/`
2. Update docker-compose.unified.yml: service name, build path
3. Add network alias `pr-reviewer` for backward compatibility
4. Update config.py: `pr_reviewer_url` → `claude_analyzer_url`
5. Update webhook-handler references
6. `/review` endpoint stays identical — zero changes to PR review

### Future Skills Pattern (Task 6)

Each new skill = new endpoint + prompt template. The server logic (clone, mutex, spawn claude, return result) is shared. Adding a skill takes ~30 minutes:

1. Add prompt template
2. Add Express route
3. Add webhook-handler command
4. Register Discord slash command
