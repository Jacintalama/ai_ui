# Skill Runner Design — Generic `/aiui <skill>` System

> **Goal:** Add a generic skill runner so that `/aiui health owner/repo`, `/aiui security owner/repo`, `/aiui deps owner/repo`, and `/aiui license owner/repo` all work through a single endpoint. Future skills = just add a `.md` file.

---

## Section 1: Architecture

```
Discord/Slack → webhook-handler → POST /skill {owner, repo, skill} → claude-analyzer
                                                                          ↓
                                                              cloneOrFetch(owner/repo)
                                                                          ↓
                                                              Load skills/<skill>.md
                                                                          ↓
                                                              runClaude(skillPrompt, repoDir)
                                                                          ↓
                                                              Parse JSON → respond
```

Each skill is a markdown file in `claude-analyzer/skills/`:

```
claude-analyzer/
  skills/
    health.md
    security.md
    deps.md
    license.md
  server.js
  Dockerfile
```

Each `.md` file contains the full skill description + instructions + output format. When the `/skill` endpoint runs, it reads the file and passes it as the prompt to `claude -p`. Claude Code gets the full skill context (progressive disclosure).

- Adding a new skill = adding a new `.md` file
- No code changes needed to add future skills
- Skills can be iterated on by editing markdown, not JavaScript

---

## Section 2: Skill File Format

Each skill `.md` file follows this structure:

```markdown
---
name: health
description: Assess overall code quality, tech debt, and architecture health
timeout: 300000
---

You are a senior software architect performing a codebase health assessment.

[... detailed instructions ...]

You MUST output valid JSON and nothing else. Output a JSON object with:
- "summary": one-paragraph overall assessment
- "score": 0-100 overall health score
- "findings": array of {category, severity, title, detail}
- "recommendations": array of prioritized improvement suggestions
```

**Frontmatter** (`---` block) provides metadata:
- `name` — skill identifier (matches filename)
- `description` — shown in `/aiui help` and used for skill discovery
- `timeout` — override default timeout per skill (default 300s)

**Body** is the full prompt passed to Claude Code CLI:
- Role/persona for Claude
- What to analyze and how
- What files to read / skip
- Required JSON output format with exact fields

---

## Section 3: The 4 Skills

### `/aiui health owner/repo`
- **What Claude does:** Reads entry points, architecture, test files, error handling patterns, README
- **Returns:** Health score (0-100), findings by category (architecture, testing, error handling, documentation, tech debt), prioritized recommendations
- **Timeout:** 300s

### `/aiui security owner/repo`
- **What Claude does:** Traces data flows, checks auth patterns, looks for OWASP Top 10 (injection, XSS, CSRF, secrets in code, insecure crypto, broken access control)
- **Returns:** Risk level (critical/high/medium/low), vulnerabilities list with severity + location + remediation, overall security posture summary
- **Timeout:** 300s

### `/aiui deps owner/repo`
- **What Claude does:** Reads package.json, requirements.txt, go.mod, Cargo.toml etc. Uses WebSearch to check latest versions and known CVEs for each dependency
- **Returns:** Total deps count, outdated count, vulnerable count, list of issues with package name + current version + latest version + CVEs if any
- **Timeout:** 300s

### `/aiui license owner/repo`
- **What Claude does:** Reads dependency manifests, uses WebSearch to look up each package's license. Flags GPL/AGPL contamination risks, missing licenses, incompatible combinations
- **Returns:** License distribution (MIT: 42, Apache-2.0: 15, etc.), risk flags, compliance status (clean/warning/violation)
- **Timeout:** 300s

---

## Section 4: Generic `/skill` Endpoint

One endpoint handles all skills:

```javascript
app.post("/skill", async (req, res) => {
  const { owner, repo, branch = "main", skill } = req.body;

  // 1. Validate inputs (same SAFE_NAME_RE pattern)
  // 2. Check skill exists in skills/ directory
  // 3. Parse frontmatter for timeout override
  // 4. Clone/fetch repo
  // 5. Run Claude with skill body as prompt
  // 6. Parse JSON response
  // 7. Return { status, skill, results, duration_seconds }
});
```

**Skill discovery endpoint:**

```javascript
app.get("/skills", (_req, res) => {
  // Reads skills/ directory, parses frontmatter from each .md file
  // Returns array of { name, description } for all available skills
});
```

**Shared behavior across all skills:**
- Same `analyzing` mutex (one skill at a time, 3.8GB RAM)
- Same `cloneOrFetch()` for repo access
- Same `extractJSON()` for parsing Claude's response
- Skill-specific timeout from frontmatter (default 300s)
- Results cached to `.skill-<name>-cache.json` in repo dir (24h TTL)

**Webhook handler side — one generic method:**

```python
async def _handle_skill(self, ctx, skill_name):
    # Parse owner/repo from args
    # POST to claude-analyzer:3000/skill with {owner, repo, skill: skill_name}
    # Format response based on skill name
    # Send to Discord
```

Each command routes to `_handle_skill(ctx, "health")` etc.

---

## Section 5: Discord Response Formatting

### health
```
🏥 Health Report: owner/repo
Score: 85/100 ████████░░

📋 Findings (4)
🔴 No test coverage for auth module
🟡 3 circular dependencies detected
🟡 Error handling inconsistent in API layer
🟢 Good separation of concerns

💡 Top Recommendations
1. Add integration tests for auth flow
2. Break circular deps in services/
3. Standardize error handling middleware
```

### security
```
🔒 Security Audit: owner/repo
Risk Level: MEDIUM

🚨 Vulnerabilities (3)
🔴 CRITICAL: SQL injection in /api/users (users.py:42)
🟡 HIGH: Missing CSRF protection on POST routes
🟢 LOW: Console.log exposes internal paths

🛡️ Remediation steps included for each finding
```

### deps
```
📦 Dependency Report: owner/repo
Total: 47 | Outdated: 12 | Vulnerable: 2

🔴 express 4.17.1 → 4.21.0 (CVE-2024-XXXX)
🔴 lodash 4.17.20 → 4.17.21 (prototype pollution)
🟡 axios 0.21.0 → 1.7.2 (outdated)
🟡 react 18.2.0 → 18.3.1 (outdated)
... +8 more outdated
```

### license
```
⚖️ License Report: owner/repo
Status: ⚠️ WARNING

📊 Distribution: MIT (42) | Apache-2.0 (15) | ISC (8) | GPL-3.0 (1)

🔴 GPL-3.0: node-sass — copyleft, may require open-sourcing
🟢 All other deps are permissive licensed
```

**Truncation:** If message exceeds Discord's 2000 char limit, truncate findings list and add "... +N more findings. Full report saved."

---

## Section 6: Changes Summary

| File | Change |
|------|--------|
| `claude-analyzer/skills/health.md` | **New** — Health assessment skill prompt |
| `claude-analyzer/skills/security.md` | **New** — Security audit skill prompt |
| `claude-analyzer/skills/deps.md` | **New** — Dependency checker skill prompt |
| `claude-analyzer/skills/license.md` | **New** — License compliance skill prompt |
| `claude-analyzer/server.js` | **Modify** — Add generic `/skill` and `/skills` endpoints, add `loadSkill()` and `listSkills()` helpers |
| `claude-analyzer/Dockerfile` | **No change** — Claude Code CLI + git already installed |
| `webhook-handler/handlers/commands.py` | **Modify** — Add `health`, `security`, `deps`, `license` to known commands, add `_handle_skill()` generic method, update help text |

**What stays the same:**
- Existing `/review`, `/analyze`, `/rebuild` endpoints untouched
- Same Docker image, same container, same mutex
- Same `cloneOrFetch()`, `runClaude()`, `extractJSON()` shared functions

**Total new code:**
- ~4 skill markdown files (~80-120 lines each)
- ~60 lines new JS in server.js (generic endpoint + helpers)
- ~80 lines new Python in commands.py (generic handler + formatters)
