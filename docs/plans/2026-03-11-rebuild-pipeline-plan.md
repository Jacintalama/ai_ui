# Rebuild Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `/aiui rebuild owner/repo` command that researches existing solutions for a codebase's business requirements, then generates an integration plan or PRD.

**Architecture:** Two-phase pipeline inside the existing claude-analyzer container. Phase 1 runs Claude Code CLI with WebSearch to find open source/SaaS solutions. Phase 2 generates either an integration plan (if solution found) or a PRD (if custom build needed). BRE results are cached between `/analyze` and `/rebuild` calls.

**Tech Stack:** Node.js (Express), Claude Code CLI, Python (webhook-handler/FastAPI)

**Design doc:** `docs/plans/2026-03-11-rebuild-pipeline-design.md`

---

### Task 1: Add BRE caching to `/analyze` endpoint

**Files:**
- Modify: `claude-analyzer/server.js:267-276` (after successful parse, before response)

**Step 1: Add cache write after successful analysis**

After line 266 (end of JSON parse try/catch) and before line 268 (`const duration`), add BRE cache write:

```javascript
    // Cache BRE result for /rebuild reuse
    const cacheFile = path.join(repoDir, ".bre-cache.json");
    try {
      fs.writeFileSync(cacheFile, JSON.stringify({
        timestamp: new Date().toISOString(),
        report: parsed.report || raw,
        user_stories: parsed.user_stories || [],
      }));
      log(`BRE cached to ${cacheFile}`);
    } catch (cacheErr) {
      log(`BRE cache write failed: ${cacheErr.message}`);
    }
```

**Step 2: Add shared helper to read BRE cache**

After the `runClaude` function (line 123), add:

```javascript
function readBRECache(repoDir) {
  const cacheFile = path.join(repoDir, ".bre-cache.json");
  try {
    if (!fs.existsSync(cacheFile)) return null;
    const data = JSON.parse(fs.readFileSync(cacheFile, "utf-8"));
    const age = Date.now() - new Date(data.timestamp).getTime();
    const MAX_AGE = 24 * 60 * 60 * 1000; // 24 hours
    if (age > MAX_AGE) {
      log(`BRE cache expired (${(age / 3600000).toFixed(1)}h old)`);
      return null;
    }
    log(`BRE cache hit (${(age / 60000).toFixed(0)}m old)`);
    return data;
  } catch (e) {
    log(`BRE cache read failed: ${e.message}`);
    return null;
  }
}
```

**Step 3: Add shared JSON extraction helper**

After `readBRECache`, add a reusable function (currently duplicated inline in `/analyze`):

```javascript
function extractJSON(raw) {
  let cleaned = raw.replace(/```json\s*/gi, "").replace(/```\s*/g, "").trim();
  const firstBrace = cleaned.indexOf("{");
  const lastBrace = cleaned.lastIndexOf("}");
  if (firstBrace !== -1 && lastBrace > firstBrace) {
    cleaned = cleaned.substring(firstBrace, lastBrace + 1);
  }
  return JSON.parse(cleaned);
}
```

**Step 4: Update `/analyze` to use `extractJSON` helper**

Replace lines 252-266 in the `/analyze` endpoint:

```javascript
    let parsed;
    try {
      parsed = extractJSON(raw);
    } catch (e) {
      log(`JSON parse failed: ${e.message}. Returning raw text as report.`);
      parsed = { report: raw, user_stories: [] };
    }
```

**Step 5: Commit**

```bash
git add claude-analyzer/server.js
git commit -m "feat: add BRE caching and shared JSON extraction to claude-analyzer"
```

---

### Task 2: Add `/rebuild` endpoint — Phase 1 (Research)

**Files:**
- Modify: `claude-analyzer/server.js` (add new route before `app.listen`)
- Modify: `claude-analyzer/server.js:11` (add `REBUILD_TIMEOUT_MS` constant)

**Step 1: Add timeout constant**

After line 11 (`const CLAUDE_TIMEOUT_MS = 300_000;`), add:

```javascript
const REBUILD_TIMEOUT_MS = 300_000; // per-phase timeout for rebuild
```

**Step 2: Add the `/rebuild` endpoint skeleton with BRE loading**

Before `app.listen(PORT, ...)` (line 287), add the full `/rebuild` route. Start with validation, mutex, clone, and BRE cache check:

```javascript
app.post("/rebuild", async (req, res) => {
  if (analyzing) {
    return res.status(503).json({ error: "Analysis already in progress", status: "busy" });
  }

  const { owner, repo, branch = "main" } = req.body;

  if (!owner || !repo) {
    return res.status(400).json({
      error: "Missing required fields: owner, repo",
      status: "error",
    });
  }

  if (!SAFE_NAME_RE.test(owner) || !SAFE_NAME_RE.test(repo)) {
    return res.status(400).json({ error: "Invalid owner or repo name", status: "error" });
  }
  if (!SAFE_REF_RE.test(branch)) {
    return res.status(400).json({ error: "Invalid branch name", status: "error" });
  }

  analyzing = true;
  const startTime = Date.now();

  try {
    const repoDir = await cloneOrFetch(owner, repo, branch);

    // Step 1: Get BRE (from cache or fresh extraction)
    let bre = readBRECache(repoDir);
    if (!bre) {
      log("No BRE cache found, running extraction first...");
      const brePrompt = `Analyze this codebase and extract ONLY the business requirements.

DO NOT describe implementation details, technologies used, or code structure.
Focus on WHAT the application does, not HOW.

You MUST output valid JSON and nothing else. Output a JSON object with exactly two fields:

1. "report" - A markdown string with these sections:
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
Skip test files, build configs, and infrastructure code.`;

      const breRaw = await runClaude(brePrompt, repoDir, "text");
      let breParsed;
      try {
        breParsed = extractJSON(breRaw);
      } catch (e) {
        breParsed = { report: breRaw, user_stories: [] };
      }
      bre = {
        timestamp: new Date().toISOString(),
        report: breParsed.report || breRaw,
        user_stories: breParsed.user_stories || [],
      };
      // Cache for future calls
      try {
        fs.writeFileSync(path.join(repoDir, ".bre-cache.json"), JSON.stringify(bre));
      } catch (e) { /* ignore cache write failure */ }
    }

    const breReport = bre.report;
    const breStories = Array.isArray(bre.user_stories)
      ? bre.user_stories.map(s => `- As a ${s.role}, I want ${s.feature}, so that ${s.benefit}`).join("\n")
      : "";

    // Step 2: Phase 1 — Research via Claude + WebSearch
    log("Phase 1: Researching existing solutions...");
    const researchPrompt = `You are a solutions researcher. Given these business requirements extracted from a codebase, find existing solutions that already solve this problem.

BUSINESS REQUIREMENTS:
${breReport}

USER STORIES:
${breStories}

YOUR TASK:
1. Use WebSearch to find open-source projects, SaaS products, and existing frameworks that solve this problem or major parts of it
2. Search for the problem statement + "open source alternative"
3. Search for the core features + "SaaS solution"
4. Search for GitHub repos solving similar problems
5. For each solution found, evaluate:
   - Feature coverage (what % of the business requirements does it satisfy?)
   - Maturity (stars, contributors, last commit, funding)
   - Self-hostable vs cloud-only
   - Customization effort
6. Score each solution 0-100 on fit

You MUST output valid JSON and nothing else. Output a JSON object with these fields:
- "recommendation": one of "open-source", "saas", or "custom-build"
- "reasoning": why this recommendation (2-3 sentences)
- "solutions": array of objects each with {name, type, url, fit_score, pros, cons, effort}
- "research_summary": markdown overview of findings
- "gaps": array of strings — features from the business requirements that NO existing solution covers

If no existing solution scores above 60, recommend "custom-build".
Search at least 5 different queries. Be thorough.`;

    const researchRaw = await runClaude(researchPrompt, repoDir, "text");

    let research;
    try {
      research = extractJSON(researchRaw);
    } catch (e) {
      log(`Research JSON parse failed: ${e.message}`);
      research = {
        recommendation: "custom-build",
        reasoning: "Could not parse research results. Defaulting to custom build.",
        solutions: [],
        research_summary: researchRaw,
        gaps: [],
      };
    }

    // Cache research results
    try {
      fs.writeFileSync(
        path.join(repoDir, ".research-cache.json"),
        JSON.stringify({ timestamp: new Date().toISOString(), ...research })
      );
    } catch (e) { /* ignore */ }

    // >>> Phase 2 will be added in Task 3 <<<

    const duration = ((Date.now() - startTime) / 1000).toFixed(1);
    log(`Rebuild completed in ${duration}s — recommendation: ${research.recommendation}`);

    // Placeholder response (Phase 2 replaces this)
    res.json({
      status: "success",
      recommendation: research.recommendation || "custom-build",
      research_summary: research.research_summary || "",
      solutions: research.solutions || [],
      plan: "",
      prd: null,
      duration_seconds: parseFloat(duration),
    });
  } catch (err) {
    const duration = ((Date.now() - startTime) / 1000).toFixed(1);
    const safeError = redactString(err.message);
    log(`Rebuild failed after ${duration}s: ${safeError}`);
    res.status(500).json({ error: safeError, status: "error" });
  } finally {
    analyzing = false;
  }
});
```

**Step 3: Commit**

```bash
git add claude-analyzer/server.js
git commit -m "feat: add /rebuild endpoint with Phase 1 research via Claude + WebSearch"
```

---

### Task 3: Add `/rebuild` Phase 2 (Plan or PRD generation)

**Files:**
- Modify: `claude-analyzer/server.js` (replace placeholder in `/rebuild` route)

**Step 1: Replace the placeholder comment with Phase 2 logic**

Replace the `// >>> Phase 2 will be added in Task 3 <<<` line and the placeholder response block with:

```javascript
    // Step 3: Phase 2 — Generate plan or PRD based on recommendation
    log(`Phase 2: Generating ${research.recommendation === "custom-build" ? "PRD" : "integration plan"}...`);

    let plan = "";
    let prd = null;

    if (research.recommendation === "custom-build") {
      // Phase 2b: PRD for custom build
      const gapsText = Array.isArray(research.gaps) ? research.gaps.join("\n- ") : "None identified";
      const prdPrompt = `You are a product manager. Based on these business requirements and research showing no adequate existing solution, create a Product Requirements Document for a custom application.

BUSINESS REQUIREMENTS:
${breReport}

RESEARCH FINDINGS (what exists but doesn't fit):
${research.research_summary || JSON.stringify(research.solutions)}

GAPS (features nothing covers):
- ${gapsText}

Create a PRD with:
1. Executive Summary (problem, solution, KPIs)
2. User Personas & Stories (from the user stories above)
3. Functional Requirements (detailed, measurable, no vague language)
4. Non-Functional Requirements (performance, security, scalability)
5. Technical Architecture recommendation (stack, integrations)
6. Phased Roadmap (MVP → V1 → V2)
7. Success Metrics

Be specific. "Fast" → "200ms p95 response time". "Scalable" → "handle 10K concurrent users".

Output as a markdown document.`;

      prd = await runClaude(prdPrompt, repoDir, "text");
      plan = `## Recommendation: Custom Build\n\nNo existing solution covers >60% of requirements.\n\n### Gaps\n- ${gapsText}\n\nSee PRD below for full specification.`;
    } else {
      // Phase 2a: Integration plan for existing solution
      const planPrompt = `You are a technical architect. Based on these research findings, create an implementation plan for adopting the recommended solution.

BUSINESS REQUIREMENTS:
${breReport}

RESEARCH FINDINGS:
${JSON.stringify(research, null, 2)}

Create a detailed implementation plan covering:
1. Setup & deployment steps
2. Configuration needed to match the business requirements
3. Customizations required (what needs to be built on top)
4. Migration path (if replacing an existing system)
5. Timeline estimate (phases with milestones)
6. Risks and mitigation

Output as a markdown document.`;

      plan = await runClaude(planPrompt, repoDir, "text");
    }

    // Save full report to disk
    const reportContent = [
      `# Rebuild Analysis: ${owner}/${repo}`,
      `\nDate: ${new Date().toISOString()}`,
      `\nRecommendation: **${research.recommendation}**`,
      `\n${research.reasoning || ""}`,
      `\n## Research Summary\n${research.research_summary || ""}`,
      `\n## Implementation Plan\n${plan}`,
      prd ? `\n## Product Requirements Document\n${prd}` : "",
    ].join("\n");

    try {
      fs.writeFileSync(path.join(repoDir, ".rebuild-report.md"), reportContent);
      log("Rebuild report saved to .rebuild-report.md");
    } catch (e) { /* ignore */ }

    const duration = ((Date.now() - startTime) / 1000).toFixed(1);
    log(`Rebuild completed in ${duration}s — recommendation: ${research.recommendation}`);

    res.json({
      status: "success",
      recommendation: research.recommendation || "custom-build",
      research_summary: research.research_summary || "",
      solutions: research.solutions || [],
      plan,
      prd,
      duration_seconds: parseFloat(duration),
    });
```

Also remove the old placeholder response block that Task 2 left (the `const duration` through `res.json(...)` lines after the Phase 2 comment).

**Step 2: Commit**

```bash
git add claude-analyzer/server.js
git commit -m "feat: add Phase 2 plan/PRD generation to /rebuild endpoint"
```

---

### Task 4: Add `/aiui rebuild` command to webhook-handler

**Files:**
- Modify: `webhook-handler/handlers/commands.py:78-81` (add `rebuild` to known_commands)
- Modify: `webhook-handler/handlers/commands.py:108-109` (add dispatch case)
- Modify: `webhook-handler/handlers/commands.py` (add handler methods at end)

**Step 1: Add `rebuild` to known_commands set**

In `commands.py` line 78-81, add `"rebuild"` to the set:

```python
        known_commands = {
            "ask", "workflow", "workflows", "status", "help",
            "report", "pr-review", "pr", "mcp", "diagnose", "analyze",
            "email", "sheets", "rebuild",
        }
```

**Step 2: Add dispatch case in `execute()` method**

After line 109 (`await self._handle_analyze(ctx)`), add:

```python
            elif ctx.subcommand == "rebuild":
                await self._handle_rebuild(ctx)
```

**Step 3: Add `_handle_rebuild()` and `_request_claude_rebuild()` methods**

At the end of the `CommandRouter` class (before the `_gather_*` helper methods), add:

```python
    async def _handle_rebuild(self, ctx: CommandContext) -> None:
        """Research solutions and generate rebuild plan for a GitHub repository."""
        repo_arg = ctx.arguments.strip() if ctx.arguments else ""
        if repo_arg and "/" in repo_arg:
            parts = repo_arg.split("/", 1)
            owner, repo = parts[0], parts[1]
        elif repo_arg:
            await ctx.respond(
                f"Invalid format: `{repo_arg}`. Use `/aiui rebuild owner/repo`"
            )
            return
        else:
            parts = settings.report_github_repo.split("/", 1)
            if len(parts) != 2:
                await ctx.respond("No default repository configured.")
                return
            owner, repo = parts

        logger.info(f"[{ctx.platform}] rebuild {owner}/{repo} from {ctx.user_name}")
        await ctx.respond(
            f"Researching solutions for **{owner}/{repo}**... "
            f"(Phase 1: web search for existing solutions, Phase 2: plan/PRD generation. "
            f"This takes 3-5 minutes)"
        )

        result = await self._request_claude_rebuild(owner, repo)

        if not result:
            await ctx.respond(
                "Rebuild analysis failed. Claude analyzer may be unavailable or busy.\n"
                "Try again in a few minutes, or run `/aiui analyze` first to warm the cache."
            )
            return

        recommendation = result.get("recommendation", "unknown")
        solutions = result.get("solutions", [])
        plan = result.get("plan", "")
        prd = result.get("prd")
        duration = result.get("duration_seconds", 0)

        # Build Discord response
        if recommendation == "custom-build":
            emoji = "\U0001f528"  # hammer
            header = f"{emoji} **Rebuild Analysis: {owner}/{repo}**\n\n"
            header += f"**Recommendation: Custom Build**\n"
            header += f"{result.get('research_summary', '')[:300]}\n"
            if prd:
                # Show PRD summary (first 800 chars)
                response = header + f"\n**PRD Summary**\n{prd[:800]}"
            else:
                response = header + f"\n{plan[:800]}"
        else:
            emoji = "\U0001f50d"  # magnifying glass
            header = f"{emoji} **Rebuild Analysis: {owner}/{repo}**\n\n"
            top_solution = solutions[0]["name"] if solutions else "Unknown"
            header += f"**Recommendation: {recommendation.replace('-', ' ').title()} — {top_solution}**\n\n"

            # Show top 3 solutions
            sol_lines = []
            for i, s in enumerate(solutions[:3], 1):
                pros = ", ".join(s.get("pros", [])[:3])
                cons = ", ".join(s.get("cons", [])[:2])
                sol_lines.append(
                    f"{i}. **{s['name']}** ({s.get('type', '?')}, {s.get('fit_score', '?')}/100)\n"
                    f"   Pros: {pros}\n"
                    f"   Cons: {cons}\n"
                    f"   Effort: {s.get('effort', '?')}"
                )
            response = header + "\n".join(sol_lines)
            if plan:
                response += f"\n\n**Plan**\n{plan[:400]}"

        response += f"\n\n_Completed in {duration}s by Claude Code CLI_"

        limit = 2000 if ctx.platform == "discord" else 3000
        if len(response) > limit:
            response = response[:limit - 20] + "\n\n... (truncated)"
        await ctx.respond(response)

    async def _request_claude_rebuild(
        self, owner: str, repo: str, branch: str = "main"
    ) -> Optional[dict]:
        """Request rebuild analysis from claude-analyzer container."""
        analyzer_url = settings.claude_analyzer_url
        if not analyzer_url:
            return None

        try:
            async with httpx.AsyncClient(timeout=960.0) as client:
                resp = await client.post(
                    f"{analyzer_url}/rebuild",
                    json={"owner": owner, "repo": repo, "branch": branch},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "success":
                        return data
                logger.warning(
                    f"claude-analyzer /rebuild returned {resp.status_code}: {resp.text[:200]}"
                )
                return None
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.info(f"claude-analyzer /rebuild unavailable: {e}")
            return None
        except Exception as e:
            logger.warning(f"claude-analyzer /rebuild error: {e}")
            return None
```

**Step 4: Update help text**

In `_handle_help()` (around line 304-320), add before the last line:

```python
            "`/aiui rebuild [owner/repo]` \u2014 Research solutions & generate rebuild plan\n"
```

**Step 5: Commit**

```bash
git add webhook-handler/handlers/commands.py
git commit -m "feat: add /aiui rebuild command to webhook-handler"
```

---

### Task 5: Deploy and test

**Step 1: Deploy claude-analyzer changes to server**

```bash
scp claude-analyzer/server.js root@46.224.193.25:/root/proxy-server/claude-analyzer/server.js
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml build --no-cache claude-analyzer && docker compose -f docker-compose.unified.yml up -d claude-analyzer"
```

**Step 2: Deploy webhook-handler changes to server**

```bash
scp webhook-handler/handlers/commands.py root@46.224.193.25:/root/proxy-server/webhook-handler/handlers/commands.py
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml build --no-cache webhook-handler && docker compose -f docker-compose.unified.yml up -d webhook-handler"
```

**Step 3: Verify containers are running**

```bash
ssh root@46.224.193.25 "docker logs claude-analyzer --tail 3 2>&1 && docker logs webhook-handler --tail 3 2>&1"
```

Expected: Both show startup messages, no errors.

**Step 4: Test `/aiui rebuild` in Discord**

Run in Discord: `/aiui rebuild TheLukasHenry/proxy-server`

Expected flow:
1. Immediate acknowledgment message
2. 3-5 minute wait
3. Response with recommendation, solutions list, and plan

**Step 5: Final commit with any fixes**

```bash
git add -A
git commit -m "fix: deployment adjustments for rebuild pipeline"
```
