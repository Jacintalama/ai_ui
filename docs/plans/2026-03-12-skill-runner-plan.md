# Skill Runner Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a generic skill runner so `/aiui health`, `/aiui security`, `/aiui deps`, and `/aiui license` all work through one `/skill` endpoint. Future skills = just add a `.md` file.

**Architecture:** Each skill is a markdown file with frontmatter (name, description, timeout) and a body (the prompt). A single `/skill` endpoint loads the file, runs Claude Code CLI, parses JSON, and responds. Webhook handler routes all 4 commands through one `_handle_skill()` method.

**Tech Stack:** Node.js (Express), Claude Code CLI, Python (webhook-handler/FastAPI)

**Design doc:** `docs/plans/2026-03-12-skill-runner-design.md`

---

### Task 1: Create the 4 skill markdown files

**Files:**
- Create: `claude-analyzer/skills/health.md`
- Create: `claude-analyzer/skills/security.md`
- Create: `claude-analyzer/skills/deps.md`
- Create: `claude-analyzer/skills/license.md`

**Step 1: Create `claude-analyzer/skills/health.md`**

```markdown
---
name: health
description: Assess overall code quality, tech debt, and architecture health
timeout: 300000
---

You are a senior software architect performing a codebase health assessment.

Analyze this codebase for overall quality, architecture health, and technical debt.

READ these files (if they exist):
- README, CONTRIBUTING, package.json, requirements.txt, go.mod, Cargo.toml
- Main entry points (index.js, main.py, app.py, main.go, etc.)
- Route handlers, API definitions
- Test directories (tests/, __tests__/, spec/)
- CI/CD configs (.github/workflows/, Dockerfile, docker-compose*)
- Error handling patterns (try/catch, error middleware)

EVALUATE these categories:
1. Architecture — separation of concerns, modularity, dependency direction
2. Testing — test coverage, test quality, edge cases
3. Error Handling — consistent patterns, graceful failures, logging
4. Documentation — README quality, inline comments where needed, API docs
5. Tech Debt — TODOs, deprecated APIs, outdated patterns, dead code
6. Security Basics — env vars for secrets, input validation, auth patterns
7. Dependencies — pinned versions, minimal dependency count, no abandoned packages

SCORING:
- 90-100: Excellent — production-ready, well-maintained
- 70-89: Good — solid foundation, minor improvements needed
- 50-69: Fair — functional but needs attention
- 30-49: Poor — significant issues, refactoring needed
- 0-29: Critical — major risks, not production-ready

You MUST output valid JSON and nothing else. Output a JSON object with:
- "summary": one-paragraph overall assessment (2-3 sentences)
- "score": 0-100 overall health score
- "findings": array of objects each with {"category": string, "severity": "critical"|"high"|"medium"|"low", "title": string, "detail": string}
- "recommendations": array of strings — prioritized improvement suggestions (top 5)

Be specific. Reference actual file names and line numbers where possible.
```

**Step 2: Create `claude-analyzer/skills/security.md`**

```markdown
---
name: security
description: Deep security audit — OWASP Top 10, data flow tracing, secrets detection
timeout: 300000
---

You are a senior security researcher performing a deep security audit of this codebase.

DO NOT just pattern-match. Read and reason about the code like a human security researcher:
- Trace how data flows from user input through the application
- Understand how components interact
- Look for complex vulnerabilities that rule-based tools miss

CHECK FOR (OWASP Top 10 + extras):
1. Injection — SQL injection, command injection, NoSQL injection, LDAP injection
2. Broken Authentication — weak password handling, session management, JWT issues
3. Sensitive Data Exposure — secrets in code, unencrypted data, verbose errors
4. XML External Entities (XXE) — if applicable
5. Broken Access Control — missing auth checks, IDOR, privilege escalation
6. Security Misconfiguration — debug mode, default credentials, unnecessary features
7. Cross-Site Scripting (XSS) — reflected, stored, DOM-based
8. Insecure Deserialization — untrusted data deserialization
9. Using Components with Known Vulnerabilities — check package versions via WebSearch
10. Insufficient Logging & Monitoring — missing audit trails
11. CSRF — missing CSRF protection on state-changing endpoints
12. Secrets in Code — API keys, passwords, tokens hardcoded
13. Path Traversal — user input in file paths
14. Race Conditions — TOCTOU bugs, concurrent state mutation

READ these files:
- All route handlers and API endpoints
- Authentication/authorization middleware
- Database queries and ORM usage
- File upload/download handlers
- Environment variable usage
- Configuration files

You MUST output valid JSON and nothing else. Output a JSON object with:
- "summary": one-paragraph security posture assessment
- "risk_level": "critical"|"high"|"medium"|"low"
- "vulnerabilities": array of objects each with {"severity": "critical"|"high"|"medium"|"low", "category": string, "title": string, "location": string (file:line if possible), "detail": string, "remediation": string}
- "positive_findings": array of strings — security things done well

Sort vulnerabilities by severity (critical first). Be specific about locations.
```

**Step 3: Create `claude-analyzer/skills/deps.md`**

```markdown
---
name: deps
description: Check dependencies for outdated versions and known vulnerabilities
timeout: 300000
---

You are a dependency auditor. Analyze this project's dependencies for outdated packages and known security vulnerabilities.

FIND and READ all dependency manifests:
- package.json, package-lock.json (Node.js/npm)
- requirements.txt, Pipfile, pyproject.toml, setup.py (Python)
- go.mod, go.sum (Go)
- Cargo.toml (Rust)
- pom.xml, build.gradle (Java)
- Gemfile (Ruby)
- composer.json (PHP)

FOR EACH dependency found:
1. Note the current pinned/specified version
2. Use WebSearch to find the latest stable version
3. Use WebSearch to check for known CVEs (search: "<package name> CVE vulnerability")
4. Classify: up-to-date, outdated (minor), outdated (major), or vulnerable

PRIORITIZE:
- Vulnerable packages with known CVEs (critical)
- Major version behind (high)
- Minor version behind with security patches (medium)
- Minor version behind, no security impact (low)

You MUST output valid JSON and nothing else. Output a JSON object with:
- "summary": one-paragraph overview of dependency health
- "total_deps": number of total dependencies found
- "outdated_count": number of outdated dependencies
- "vulnerable_count": number of dependencies with known CVEs
- "issues": array of objects each with {"package": string, "current_version": string, "latest_version": string, "severity": "critical"|"high"|"medium"|"low", "cves": array of strings (CVE IDs), "detail": string}
- "ecosystem": string — primary package ecosystem detected (npm, pip, go, etc.)

Sort issues by severity (critical first). Only include packages that are outdated or vulnerable, not up-to-date ones.
```

**Step 4: Create `claude-analyzer/skills/license.md`**

```markdown
---
name: license
description: Check dependency licenses for compliance risks (GPL contamination, missing licenses)
timeout: 300000
---

You are a software license compliance auditor. Analyze this project's dependencies for license risks.

FIND and READ all dependency manifests:
- package.json (check "license" field and dependencies)
- requirements.txt, pyproject.toml, setup.py
- go.mod
- Cargo.toml
- Any LICENSE, COPYING, or NOTICE files in the project root

FOR EACH direct dependency:
1. Use WebSearch to look up the package's license (search: "<package name> npm license" or "<package name> pypi license")
2. Classify the license: permissive (MIT, Apache-2.0, BSD, ISC), weak copyleft (LGPL, MPL), strong copyleft (GPL, AGPL), or unknown

FLAG these risks:
- GPL/AGPL dependencies in a proprietary project (copyleft contamination)
- LGPL dependencies used incorrectly (statically linked)
- Dependencies with no license (legal risk)
- License incompatibilities (e.g., Apache-2.0 + GPL-2.0-only)
- Multiple conflicting license requirements

CHECK the project's own LICENSE file and determine if dependencies are compatible.

You MUST output valid JSON and nothing else. Output a JSON object with:
- "summary": one-paragraph compliance assessment
- "status": "clean"|"warning"|"violation"
- "project_license": string — the project's own license (or "none" if not found)
- "distribution": object mapping license names to counts (e.g., {"MIT": 42, "Apache-2.0": 15})
- "risks": array of objects each with {"package": string, "license": string, "risk_type": "copyleft"|"no-license"|"incompatible"|"unknown", "severity": "critical"|"high"|"medium"|"low", "detail": string}
- "total_deps_checked": number

Sort risks by severity. Only include packages with actual risk, not clean ones.
```

**Step 5: Verify files exist**

Run: `ls claude-analyzer/skills/`
Expected: `deps.md  health.md  license.md  security.md`

**Step 6: Commit**

```bash
git add claude-analyzer/skills/
git commit -m "feat: add skill prompt files for health, security, deps, license"
```

---

### Task 2: Add `loadSkill()`, `listSkills()`, and `/skill` + `/skills` endpoints to server.js

**Files:**
- Modify: `claude-analyzer/server.js` — add after line 153 (after `extractJSON`), and before the routes section

**Step 1: Add `loadSkill()` and `listSkills()` helpers after `extractJSON()` (after line 153)**

Insert after the `extractJSON` function (line 153), before the `// --- Routes ---` comment (line 155):

```javascript
const SKILLS_DIR = path.join(__dirname, "skills");
const DEFAULT_SKILL_TIMEOUT = 300_000;

function parseSkillFrontmatter(content) {
  const match = content.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
  if (!match) return { meta: {}, prompt: content };
  const meta = {};
  for (const line of match[1].split("\n")) {
    const idx = line.indexOf(":");
    if (idx > 0) {
      const key = line.slice(0, idx).trim();
      let val = line.slice(idx + 1).trim();
      if (/^\d+$/.test(val)) val = parseInt(val, 10);
      meta[key] = val;
    }
  }
  return { meta, prompt: match[2].trim() };
}

function loadSkill(skillName) {
  if (!SAFE_NAME_RE.test(skillName)) return null;
  const filePath = path.join(SKILLS_DIR, `${skillName}.md`);
  if (!fs.existsSync(filePath)) return null;
  const content = fs.readFileSync(filePath, "utf-8");
  return parseSkillFrontmatter(content);
}

function listSkills() {
  if (!fs.existsSync(SKILLS_DIR)) return [];
  return fs.readdirSync(SKILLS_DIR)
    .filter(f => f.endsWith(".md"))
    .map(f => {
      const content = fs.readFileSync(path.join(SKILLS_DIR, f), "utf-8");
      const { meta } = parseSkillFrontmatter(content);
      return { name: meta.name || f.replace(".md", ""), description: meta.description || "" };
    });
}

function readSkillCache(repoDir, skillName) {
  const cacheFile = path.join(repoDir, `.skill-${skillName}-cache.json`);
  try {
    if (!fs.existsSync(cacheFile)) return null;
    const data = JSON.parse(fs.readFileSync(cacheFile, "utf-8"));
    const age = Date.now() - new Date(data.timestamp).getTime();
    const MAX_AGE = 24 * 60 * 60 * 1000;
    if (age > MAX_AGE) {
      log(`Skill cache expired for ${skillName} (${(age / 3600000).toFixed(1)}h old)`);
      return null;
    }
    log(`Skill cache hit for ${skillName} (${(age / 60000).toFixed(0)}m old)`);
    return data.results;
  } catch (e) {
    return null;
  }
}
```

**Step 2: Add `/skills` GET endpoint after the `/health` route (after line 159)**

Insert after the `/health` endpoint:

```javascript
app.get("/skills", (_req, res) => {
  res.json({ skills: listSkills() });
});
```

**Step 3: Add `/skill` POST endpoint after the `/skills` route**

```javascript
app.post("/skill", async (req, res) => {
  if (analyzing) {
    return res.status(503).json({ error: "Analysis already in progress", status: "busy" });
  }

  const { owner, repo, branch = "main", skill: skillName } = req.body;

  if (!owner || !repo || !skillName) {
    return res.status(400).json({
      error: "Missing required fields: owner, repo, skill",
      status: "error",
    });
  }

  if (!SAFE_NAME_RE.test(owner) || !SAFE_NAME_RE.test(repo)) {
    return res.status(400).json({ error: "Invalid owner or repo name", status: "error" });
  }
  if (!SAFE_REF_RE.test(branch)) {
    return res.status(400).json({ error: "Invalid branch name", status: "error" });
  }

  const skill = loadSkill(skillName);
  if (!skill) {
    const available = listSkills().map(s => s.name);
    return res.status(400).json({
      error: `Unknown skill: ${skillName}. Available: ${available.join(", ")}`,
      status: "error",
    });
  }

  analyzing = true;
  const startTime = Date.now();
  const timeoutMs = skill.meta.timeout || DEFAULT_SKILL_TIMEOUT;

  try {
    const repoDir = await cloneOrFetch(owner, repo, branch);

    // Check cache first
    const cached = readSkillCache(repoDir, skillName);
    if (cached) {
      const duration = ((Date.now() - startTime) / 1000).toFixed(1);
      log(`Skill ${skillName} served from cache in ${duration}s`);
      return res.json({ status: "success", skill: skillName, results: cached, cached: true, duration_seconds: parseFloat(duration) });
    }

    log(`Running skill: ${skillName}...`);
    const raw = await runClaude(skill.prompt, repoDir, "text");

    let results;
    try {
      results = extractJSON(raw);
    } catch (e) {
      log(`Skill ${skillName} JSON parse failed: ${e.message}`);
      results = { raw_output: raw };
    }

    // Cache results
    try {
      fs.writeFileSync(
        path.join(repoDir, `.skill-${skillName}-cache.json`),
        JSON.stringify({ timestamp: new Date().toISOString(), results })
      );
    } catch (e) { /* ignore */ }

    const duration = ((Date.now() - startTime) / 1000).toFixed(1);
    log(`Skill ${skillName} completed in ${duration}s`);

    res.json({ status: "success", skill: skillName, results, duration_seconds: parseFloat(duration) });
  } catch (err) {
    const duration = ((Date.now() - startTime) / 1000).toFixed(1);
    const safeError = redactString(err.message);
    log(`Skill ${skillName} failed after ${duration}s: ${safeError}`);
    res.status(500).json({ error: safeError, status: "error" });
  } finally {
    analyzing = false;
  }
});
```

**Step 4: Update `runClaude` to accept custom timeout**

Modify the `runClaude` function signature (line 85) to accept a timeout parameter:

Change line 85 from:
```javascript
function runClaude(prompt, cwd, outputFormat = "text") {
```
To:
```javascript
function runClaude(prompt, cwd, outputFormat = "text", timeoutMs = CLAUDE_TIMEOUT_MS) {
```

And change line 108 from:
```javascript
    }, CLAUDE_TIMEOUT_MS);
```
To:
```javascript
    }, timeoutMs);
```

And update the timeout error message (line 107) from:
```javascript
      reject(new Error("Claude Code timed out after 300 seconds"));
```
To:
```javascript
      reject(new Error(`Claude Code timed out after ${timeoutMs / 1000} seconds`));
```

Then in the `/skill` endpoint, change the `runClaude` call to pass the skill timeout:

```javascript
const raw = await runClaude(skill.prompt, repoDir, "text", timeoutMs);
```

**Step 5: Verify syntax**

Run: `node -c claude-analyzer/server.js`
Expected: No errors

**Step 6: Commit**

```bash
git add claude-analyzer/server.js
git commit -m "feat: add generic /skill and /skills endpoints with skill loader"
```

---

### Task 3: Add skill commands to webhook-handler

**Files:**
- Modify: `webhook-handler/handlers/commands.py`

**Step 1: Add skill names to `known_commands` set (line 78-82)**

Change:
```python
        known_commands = {
            "ask", "workflow", "workflows", "status", "help",
            "report", "pr-review", "pr", "mcp", "diagnose", "analyze",
            "email", "sheets", "rebuild",
        }
```
To:
```python
        known_commands = {
            "ask", "workflow", "workflows", "status", "help",
            "report", "pr-review", "pr", "mcp", "diagnose", "analyze",
            "email", "sheets", "rebuild",
            "health", "security", "deps", "license",
        }
```

**Step 2: Add dispatch cases in `execute()` method (after line 111, the rebuild case)**

After:
```python
            elif ctx.subcommand == "rebuild":
                await self._handle_rebuild(ctx)
```
Add:
```python
            elif ctx.subcommand in ("health", "security", "deps", "license"):
                await self._handle_skill(ctx, ctx.subcommand)
```

**Step 3: Add `_handle_skill()` method (after `_request_claude_rebuild()`, around line 591)**

```python
    async def _handle_skill(self, ctx: CommandContext, skill_name: str) -> None:
        """Run a generic Claude analyzer skill on a GitHub repository."""
        repo_arg = ctx.arguments.strip() if ctx.arguments else ""
        if repo_arg and "/" in repo_arg:
            parts = repo_arg.split("/", 1)
            owner, repo = parts[0], parts[1]
        elif repo_arg:
            await ctx.respond(
                f"Invalid format: `{repo_arg}`. Use `/aiui {skill_name} owner/repo`"
            )
            return
        else:
            parts = settings.report_github_repo.split("/", 1)
            if len(parts) != 2:
                await ctx.respond("No default repository configured.")
                return
            owner, repo = parts

        skill_labels = {
            "health": ("\U0001f3e5", "Health Report"),
            "security": ("\U0001f512", "Security Audit"),
            "deps": ("\U0001f4e6", "Dependency Report"),
            "license": ("\u2696\ufe0f", "License Report"),
        }
        emoji, label = skill_labels.get(skill_name, ("\U0001f527", skill_name.title()))

        logger.info(f"[{ctx.platform}] {skill_name} {owner}/{repo} from {ctx.user_name}")
        await ctx.respond(
            f"Running **{label}** on **{owner}/{repo}**... "
            f"(This takes 2-5 minutes)"
        )

        result = await self._request_skill(owner, repo, skill_name)

        if not result:
            await ctx.respond(
                f"{label} failed. Claude analyzer may be unavailable or busy.\n"
                "Try again in a few minutes."
            )
            return

        results = result.get("results", {})
        cached = result.get("cached", False)
        duration = result.get("duration_seconds", 0)
        cache_note = " (cached)" if cached else ""

        response = self._format_skill_response(
            skill_name, owner, repo, results, emoji, label, duration, cache_note
        )

        limit = 2000 if ctx.platform == "discord" else 3000
        if len(response) > limit:
            response = response[:limit - 20] + "\n\n... (truncated)"
        await ctx.respond(response)

    def _format_skill_response(
        self, skill_name: str, owner: str, repo: str,
        results: dict, emoji: str, label: str,
        duration: float, cache_note: str,
    ) -> str:
        """Format skill results for Discord/Slack."""
        header = f"{emoji} **{label}: {owner}/{repo}**\n\n"

        if skill_name == "health":
            score = results.get("score", "?")
            bar = self._score_bar(score) if isinstance(score, (int, float)) else ""
            summary = results.get("summary", "No summary available.")
            findings = results.get("findings", [])
            recs = results.get("recommendations", [])

            body = f"**Score: {score}/100** {bar}\n\n{summary}\n\n"
            if findings:
                body += f"\U0001f4cb **Findings ({len(findings)})**\n"
                for f in findings[:8]:
                    sev_icon = {
                        "critical": "\U0001f534", "high": "\U0001f534",
                        "medium": "\U0001f7e1", "low": "\U0001f7e2",
                    }.get(f.get("severity", ""), "\u26aa")
                    body += f"{sev_icon} {f.get('title', 'Unknown')}\n"
                if len(findings) > 8:
                    body += f"... +{len(findings) - 8} more\n"
            if recs:
                body += f"\n\U0001f4a1 **Top Recommendations**\n"
                for i, r in enumerate(recs[:5], 1):
                    body += f"{i}. {r}\n"

        elif skill_name == "security":
            risk = results.get("risk_level", "unknown").upper()
            summary = results.get("summary", "No summary available.")
            vulns = results.get("vulnerabilities", [])
            positives = results.get("positive_findings", [])

            body = f"**Risk Level: {risk}**\n\n{summary}\n\n"
            if vulns:
                body += f"\U0001f6a8 **Vulnerabilities ({len(vulns)})**\n"
                for v in vulns[:8]:
                    sev_icon = {
                        "critical": "\U0001f534", "high": "\U0001f534",
                        "medium": "\U0001f7e1", "low": "\U0001f7e2",
                    }.get(v.get("severity", ""), "\u26aa")
                    loc = f" ({v['location']})" if v.get("location") else ""
                    body += f"{sev_icon} **{v.get('severity', '').upper()}**: {v.get('title', 'Unknown')}{loc}\n"
                if len(vulns) > 8:
                    body += f"... +{len(vulns) - 8} more\n"
            if positives:
                body += f"\n\u2705 **Done Well**\n"
                for p in positives[:3]:
                    body += f"- {p}\n"

        elif skill_name == "deps":
            total = results.get("total_deps", "?")
            outdated = results.get("outdated_count", "?")
            vuln = results.get("vulnerable_count", "?")
            issues = results.get("issues", [])

            body = f"**Total: {total} | Outdated: {outdated} | Vulnerable: {vuln}**\n\n"
            if issues:
                for iss in issues[:10]:
                    sev_icon = {
                        "critical": "\U0001f534", "high": "\U0001f534",
                        "medium": "\U0001f7e1", "low": "\U0001f7e2",
                    }.get(iss.get("severity", ""), "\u26aa")
                    cves = ", ".join(iss.get("cves", []))
                    cve_text = f" ({cves})" if cves else ""
                    body += f"{sev_icon} **{iss.get('package', '?')}** {iss.get('current_version', '?')} \u2192 {iss.get('latest_version', '?')}{cve_text}\n"
                if len(issues) > 10:
                    body += f"... +{len(issues) - 10} more\n"

        elif skill_name == "license":
            status = results.get("status", "unknown")
            status_icon = {"clean": "\u2705", "warning": "\u26a0\ufe0f", "violation": "\U0001f6d1"}.get(status, "\u2753")
            dist = results.get("distribution", {})
            risks = results.get("risks", [])

            dist_text = " | ".join(f"{k} ({v})" for k, v in list(dist.items())[:6])
            body = f"**Status: {status_icon} {status.upper()}**\n\n"
            if dist_text:
                body += f"\U0001f4ca **Distribution:** {dist_text}\n\n"
            if risks:
                for r in risks[:6]:
                    sev_icon = {
                        "critical": "\U0001f534", "high": "\U0001f534",
                        "medium": "\U0001f7e1", "low": "\U0001f7e2",
                    }.get(r.get("severity", ""), "\u26aa")
                    body += f"{sev_icon} **{r.get('package', '?')}** ({r.get('license', '?')}) \u2014 {r.get('risk_type', '?')}\n"
                if len(risks) > 6:
                    body += f"... +{len(risks) - 6} more\n"

        else:
            body = json.dumps(results, indent=2)[:1000]

        return header + body + f"\n\n_Completed in {duration}s{cache_note} by Claude Code CLI_"

    @staticmethod
    def _score_bar(score: int, width: int = 10) -> str:
        filled = round(score / 100 * width)
        return "\u2588" * filled + "\u2591" * (width - filled)

    async def _request_skill(
        self, owner: str, repo: str, skill_name: str, branch: str = "main"
    ) -> Optional[dict]:
        """Request a skill run from claude-analyzer container."""
        analyzer_url = settings.claude_analyzer_url
        if not analyzer_url:
            return None

        try:
            async with httpx.AsyncClient(timeout=960.0) as client:
                resp = await client.post(
                    f"{analyzer_url}/skill",
                    json={"owner": owner, "repo": repo, "branch": branch, "skill": skill_name},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "success":
                        return data
                logger.warning(
                    f"claude-analyzer /skill/{skill_name} returned {resp.status_code}: {resp.text[:200]}"
                )
                return None
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.info(f"claude-analyzer /skill/{skill_name} unavailable: {e}")
            return None
        except Exception as e:
            logger.warning(f"claude-analyzer /skill/{skill_name} error: {e}")
            return None
```

**Step 4: Update help text (around line 306-323)**

Add 4 new lines before the help line:

```python
            "`/aiui health [owner/repo]` \u2014 Code quality & architecture health assessment\n"
            "`/aiui security [owner/repo]` \u2014 Deep security audit (OWASP Top 10)\n"
            "`/aiui deps [owner/repo]` \u2014 Check for outdated/vulnerable dependencies\n"
            "`/aiui license [owner/repo]` \u2014 License compliance check\n"
```

**Step 5: Verify syntax**

Run: `python -m py_compile webhook-handler/handlers/commands.py`
Expected: No errors

**Step 6: Commit**

```bash
git add webhook-handler/handlers/commands.py
git commit -m "feat: add health, security, deps, license skill commands to webhook handler"
```

---

### Task 4: Deploy and verify

**Step 1: Copy files to server**

```bash
scp -r claude-analyzer/skills/ root@ai-ui.coolestdomain.win:/opt/app/claude-analyzer/skills/
scp claude-analyzer/server.js root@ai-ui.coolestdomain.win:/opt/app/claude-analyzer/server.js
scp webhook-handler/handlers/commands.py root@ai-ui.coolestdomain.win:/opt/app/webhook-handler/handlers/commands.py
```

**Step 2: Rebuild and restart containers**

```bash
ssh root@ai-ui.coolestdomain.win "cd /opt/app && docker compose -f docker-compose.unified.yml build --no-cache claude-analyzer webhook-handler && docker compose -f docker-compose.unified.yml up -d claude-analyzer webhook-handler"
```

**Step 3: Verify `/skills` discovery endpoint**

```bash
ssh root@ai-ui.coolestdomain.win "docker exec claude-analyzer curl -s http://localhost:3000/skills"
```
Expected: JSON with 4 skills listed (health, security, deps, license) with descriptions

**Step 4: Verify `/skill` endpoint validation**

```bash
ssh root@ai-ui.coolestdomain.win "docker exec claude-analyzer curl -s -X POST http://localhost:3000/skill -H 'Content-Type: application/json' -d '{\"owner\":\"test\",\"repo\":\"test\",\"skill\":\"nonexistent\"}'"
```
Expected: 400 error listing available skills

**Step 5: Verify command parsing for new skills**

Test via Python:
```bash
ssh root@ai-ui.coolestdomain.win "docker exec webhook-handler python -c \"
from handlers.commands import CommandRouter
print(CommandRouter.parse_command('health TheLukasHenry/proxy-server'))
print(CommandRouter.parse_command('security TheLukasHenry/proxy-server'))
print(CommandRouter.parse_command('deps TheLukasHenry/proxy-server'))
print(CommandRouter.parse_command('license TheLukasHenry/proxy-server'))
\""
```
Expected: Each prints `('health', 'TheLukasHenry/proxy-server')` etc.

**Step 6: Commit verification notes**

No code change. Document that deployment was verified.
