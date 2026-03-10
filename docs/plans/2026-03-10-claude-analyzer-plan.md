# Claude Analyzer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rename pr-reviewer to claude-analyzer and add a /analyze endpoint that extracts business requirements from any GitHub repo.

**Architecture:** Extend the existing pr-reviewer Express server with a new /analyze endpoint. Refactor shared logic (clone/fetch, mutex, claude spawn) into reusable functions. Update docker-compose and webhook-handler to use the new service name with backward compatibility.

**Tech Stack:** Node.js/Express, Claude Code CLI, Docker, Python/FastAPI (webhook-handler)

---

### Task 1: Rename pr-reviewer directory to claude-analyzer

**Files:**
- Rename: `pr-reviewer/` → `claude-analyzer/`
- Modify: `claude-analyzer/package.json`
- Modify: `claude-analyzer/server.js` (line 194 — log message)

**Step 1: Copy directory**

```bash
cp -r pr-reviewer claude-analyzer
```

**Step 2: Update package.json name**

In `claude-analyzer/package.json`, change:
```json
"name": "claude-analyzer"
```

**Step 3: Update server.js log message**

In `claude-analyzer/server.js` line 194, change:
```javascript
log(`pr-reviewer listening on port ${PORT}`);
```
to:
```javascript
log(`claude-analyzer listening on port ${PORT}`);
```

**Step 4: Verify files exist**

```bash
ls claude-analyzer/
```
Expected: `Dockerfile  package.json  server.js`

**Step 5: Commit**

```bash
git add claude-analyzer/
git commit -m "feat: copy pr-reviewer to claude-analyzer container"
```

---

### Task 2: Add /analyze endpoint to server.js

**Files:**
- Modify: `claude-analyzer/server.js`

**Step 1: Refactor shared clone/fetch logic into a function**

Add after the `redactString` function (after line 32), before the `/health` route:

```javascript
async function cloneOrFetch(owner, repo, branch) {
  const GITHUB_TOKEN = process.env.GITHUB_TOKEN;
  if (!GITHUB_TOKEN) throw new Error("GITHUB_TOKEN not configured");

  const repoDir = path.join(WORKSPACE, owner, repo);
  const repoUrl = `https://${GITHUB_TOKEN}@github.com/${owner}/${repo}.git`;
  const cleanRepoUrl = `https://github.com/${owner}/${repo}.git`;

  if (!fs.existsSync(path.join(repoDir, ".git"))) {
    log(`Cloning ${owner}/${repo}...`);
    fs.mkdirSync(path.join(WORKSPACE, owner), { recursive: true });
    await runCommand("git", ["clone", repoUrl, repoDir]);
    await runCommand("git", ["remote", "set-url", "origin", cleanRepoUrl], { cwd: repoDir });
  } else {
    log(`Fetching latest for ${owner}/${repo}...`);
    await runCommand("git", ["remote", "set-url", "origin", repoUrl], { cwd: repoDir });
    await runCommand("git", ["fetch", "origin"], { cwd: repoDir });
    await runCommand("git", ["remote", "set-url", "origin", cleanRepoUrl], { cwd: repoDir });
  }

  log(`Checking out ${branch}...`);
  await runCommand("git", ["checkout", branch], { cwd: repoDir });
  await runCommand("git", ["remote", "set-url", "origin", repoUrl], { cwd: repoDir });
  await runCommand("git", ["pull", "origin", branch], { cwd: repoDir });
  await runCommand("git", ["remote", "set-url", "origin", cleanRepoUrl], { cwd: repoDir });

  return repoDir;
}

function runClaude(prompt, cwd, outputFormat = "text") {
  return new Promise((resolve, reject) => {
    const args = ["-p", prompt, "--output-format", outputFormat];
    if (outputFormat === "json") {
      args.push("--dangerously-skip-permissions");
    }
    log(`Starting Claude Code (${outputFormat} mode)...`);
    const proc = spawn("claude", args, {
      cwd,
      env: {
        ANTHROPIC_API_KEY: process.env.ANTHROPIC_API_KEY,
        HOME: "/root",
        PATH: process.env.PATH,
      },
      stdio: ["ignore", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";
    proc.stdout.on("data", (d) => (stdout += d.toString()));
    proc.stderr.on("data", (d) => (stderr += d.toString()));

    const timeout = setTimeout(() => {
      log("Claude Code timed out, killing process...");
      proc.kill("SIGTERM");
      reject(new Error("Claude Code timed out after 300 seconds"));
    }, CLAUDE_TIMEOUT_MS);

    proc.on("close", (code) => {
      clearTimeout(timeout);
      if (code !== 0) {
        reject(new Error(`Claude exited with code ${code}: ${stderr.trim()}`));
      } else {
        resolve(stdout.trim());
      }
    });

    proc.on("error", (err) => {
      clearTimeout(timeout);
      reject(err);
    });
  });
}
```

**Step 2: Add the /analyze endpoint**

Add after the `/review` endpoint (after the closing `});` of the review route):

```javascript
app.post("/analyze", async (req, res) => {
  if (reviewing) {
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

  reviewing = true;
  const startTime = Date.now();

  try {
    const repoDir = await cloneOrFetch(owner, repo, branch);

    const promptText = `Analyze this codebase and extract ONLY the business requirements.

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

    const raw = await runClaude(promptText, repoDir, "text");

    // Parse JSON from Claude's response (may have markdown fences)
    let parsed;
    try {
      const jsonMatch = raw.match(/\{[\s\S]*\}/);
      parsed = jsonMatch ? JSON.parse(jsonMatch[0]) : JSON.parse(raw);
    } catch (e) {
      // If JSON parsing fails, return raw text as report
      parsed = { report: raw, user_stories: [] };
    }

    const duration = ((Date.now() - startTime) / 1000).toFixed(1);
    log(`Analysis completed in ${duration}s`);

    res.json({
      status: "success",
      report: parsed.report || raw,
      user_stories: parsed.user_stories || [],
      duration_seconds: parseFloat(duration),
    });
  } catch (err) {
    const duration = ((Date.now() - startTime) / 1000).toFixed(1);
    const safeError = redactString(err.message);
    log(`Analysis failed after ${duration}s: ${safeError}`);
    res.status(500).json({ error: safeError, status: "error" });
  } finally {
    reviewing = false;
  }
});
```

**Step 3: Update the /review endpoint to use shared functions**

Replace lines 87-123 of the existing `/review` handler (the clone/fetch/checkout/diff block) with:

```javascript
    const repoDir = await cloneOrFetch(owner, repo, branch);

    // Generate diff against remote base
    log(`Generating diff origin/${base_branch}...${branch}...`);
    let diff = await runCommand("git", ["diff", `origin/${base_branch}...${branch}`], { cwd: repoDir });
    if (diff.length > MAX_DIFF_BYTES) {
      log(`Diff too large (${diff.length} bytes), truncating to ${MAX_DIFF_BYTES} bytes`);
      diff = diff.substring(0, MAX_DIFF_BYTES) + "\n\n... [DIFF TRUNCATED - full diff was " + diff.length + " bytes] ...";
    }
    fs.writeFileSync("/tmp/pr-diff.txt", diff);
    log(`Diff written to /tmp/pr-diff.txt (${diff.length} bytes)`);
```

And replace lines 142-177 (the Claude spawn block) with:

```javascript
    const review = await runClaude(promptText, repoDir, "text");
```

**Step 4: Verify the file is valid JavaScript**

```bash
cd claude-analyzer && node -c server.js && echo "Syntax OK"
```
Expected: `Syntax OK`

**Step 5: Commit**

```bash
git add claude-analyzer/server.js
git commit -m "feat: add /analyze endpoint and refactor shared logic"
```

---

### Task 3: Update docker-compose.unified.yml

**Files:**
- Modify: `docker-compose.unified.yml` (lines 136-161, 669)

**Step 1: Replace the pr-reviewer service block**

Replace the entire pr-reviewer service (lines 136-161) with:

```yaml
  # ===========================================================================
  # CLAUDE ANALYZER - Claude Code Analysis (PR Review, BRE, Security, etc.)
  # ===========================================================================
  claude-analyzer:
    build: ./claude-analyzer
    container_name: claude-analyzer
    restart: unless-stopped
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - GITHUB_TOKEN=${GITHUB_TOKEN}
    volumes:
      - analyzer-workspace:/workspace
    networks:
      backend:
        aliases:
          - pr-reviewer
    deploy:
      resources:
        limits:
          memory: 512M
        reservations:
          memory: 256M
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://127.0.0.1:3000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
```

Note: `aliases: [pr-reviewer]` ensures the old `http://pr-reviewer:3000` URL still works.

**Step 2: Rename the volume**

In the `volumes:` section at the bottom, replace:
```yaml
  pr-review-workspace:
```
with:
```yaml
  analyzer-workspace:
```

**Step 3: Verify compose file is valid**

```bash
docker compose -f docker-compose.unified.yml config --quiet && echo "Compose valid"
```
Expected: `Compose valid` (or warnings about missing env vars, which is fine)

**Step 4: Commit**

```bash
git add docker-compose.unified.yml
git commit -m "feat: rename pr-reviewer to claude-analyzer in docker-compose"
```

---

### Task 4: Update webhook-handler config and github.py references

**Files:**
- Modify: `webhook-handler/config.py` (lines 39-40)
- Modify: `webhook-handler/handlers/github.py` (lines 162-203)

**Step 1: Update config.py**

Replace lines 39-40:
```python
    # PR Reviewer (Claude Code)
    pr_reviewer_url: str = "http://pr-reviewer:3000"
```
with:
```python
    # Claude Analyzer (PR Review, BRE, Security, etc.)
    claude_analyzer_url: str = "http://claude-analyzer:3000"
```

**Step 2: Update github.py references**

In `webhook-handler/handlers/github.py`, replace line 166-167:
```python
        pr_reviewer_url = settings.pr_reviewer_url
        if not pr_reviewer_url:
```
with:
```python
        analyzer_url = settings.claude_analyzer_url
        if not analyzer_url:
```

Replace line 173:
```python
                    f"{pr_reviewer_url}/review",
```
with:
```python
                    f"{analyzer_url}/review",
```

Update log messages at lines 195, 199, 202 — replace `pr-reviewer` with `claude-analyzer`.

**Step 3: Update docker-compose env var**

In `docker-compose.unified.yml`, in the webhook-handler environment section, find:
```yaml
      - PR_REVIEWER_URL=${PR_REVIEWER_URL:-http://pr-reviewer:3000}
```
If it exists, replace with:
```yaml
      - CLAUDE_ANALYZER_URL=${CLAUDE_ANALYZER_URL:-http://claude-analyzer:3000}
```
If it doesn't exist (it may just use the default from config.py), no change needed.

**Step 4: Commit**

```bash
git add webhook-handler/config.py webhook-handler/handlers/github.py docker-compose.unified.yml
git commit -m "refactor: update webhook-handler to use claude-analyzer URL"
```

---

### Task 5: Upgrade /aiui analyze command to use claude-analyzer

**Files:**
- Modify: `webhook-handler/handlers/commands.py` (lines 382-436)

**Step 1: Replace `_handle_analyze` method**

Replace the entire `_handle_analyze` method (lines 382-436) with:

```python
    async def _handle_analyze(self, ctx: CommandContext) -> None:
        """Extract business requirements from a GitHub repository."""
        # Parse owner/repo from arguments, default to configured repo
        repo_arg = ctx.arguments.strip() if ctx.arguments else ""
        if repo_arg and "/" in repo_arg:
            parts = repo_arg.split("/", 1)
            owner, repo = parts[0], parts[1]
        elif repo_arg:
            await ctx.respond(
                f"Invalid format: `{repo_arg}`. Use `/aiui analyze owner/repo`"
            )
            return
        else:
            parts = settings.report_github_repo.split("/", 1)
            if len(parts) != 2:
                await ctx.respond("No default repository configured.")
                return
            owner, repo = parts

        logger.info(f"[{ctx.platform}] analyze {owner}/{repo} from {ctx.user_name}")
        await ctx.respond(
            f"Analyzing **{owner}/{repo}**... (extracting business requirements, this may take 1-3 minutes)"
        )

        # Try claude-analyzer container first
        result = await self._request_claude_analysis(owner, repo)

        if result:
            report = result.get("report", "")
            stories = result.get("user_stories", [])
            duration = result.get("duration_seconds", 0)

            response = f"**Business Requirements: {owner}/{repo}**\n\n{report}"

            if stories:
                story_lines = "\n".join(
                    f"- As a **{s.get('role', '?')}**, I want {s.get('feature', '?')}, so that {s.get('benefit', '?')}."
                    for s in stories[:10]
                )
                response += f"\n\n**User Stories**\n{story_lines}"

            response += f"\n\n_Analyzed in {duration}s by Claude Code CLI_"
        else:
            # Fallback to Open WebUI analysis
            if not self._github_client:
                await ctx.respond("Claude analyzer unavailable and GitHub not configured.")
                return

            overview = await self._github_client.get_repo_overview(owner, repo)
            if not overview:
                await ctx.respond(f"Failed to fetch repository `{owner}/{repo}`.")
                return

            analysis = await self.openwebui.analyze_codebase(
                repo_overview=overview, model=self.ai_model
            )
            if analysis:
                response = f"**Analysis of {owner}/{repo}** (Open WebUI fallback)\n\n{analysis}"
            else:
                desc = overview.get("description", "No description")
                lang = overview.get("language", "Unknown")
                tree_preview = "\n".join(overview.get("tree", [])[:20])
                response = (
                    f"AI analysis unavailable. Raw info for **{owner}/{repo}**:\n"
                    f"**Description:** {desc}\n**Language:** {lang}\n"
                    f"```\n{tree_preview}\n```"
                )

        limit = 2000 if ctx.platform == "discord" else 3000
        if len(response) > limit:
            response = response[:limit - 20] + "\n\n... (truncated)"
        await ctx.respond(response)

    async def _request_claude_analysis(
        self, owner: str, repo: str, branch: str = "main"
    ) -> Optional[dict]:
        """Request business requirements analysis from claude-analyzer container."""
        analyzer_url = settings.claude_analyzer_url
        if not analyzer_url:
            return None

        try:
            async with httpx.AsyncClient(timeout=360.0) as client:
                resp = await client.post(
                    f"{analyzer_url}/analyze",
                    json={"owner": owner, "repo": repo, "branch": branch},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "success":
                        return data
                logger.warning(
                    f"claude-analyzer /analyze returned {resp.status_code}: {resp.text[:200]}"
                )
                return None
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.info(f"claude-analyzer unavailable, falling back to Open WebUI: {e}")
            return None
        except Exception as e:
            logger.warning(f"claude-analyzer error: {e}")
            return None
```

**Step 2: Add import if missing**

Ensure `Optional` is imported at the top of commands.py. Check for:
```python
from typing import Optional, Any
```

**Step 3: Commit**

```bash
git add webhook-handler/handlers/commands.py
git commit -m "feat: upgrade /aiui analyze to use claude-analyzer BRE endpoint"
```

---

### Task 6: Deploy and test

**Step 1: Push to git**

```bash
git push proxy-server fix/mcp-network-split
```

**Step 2: Deploy to server**

```bash
scp -r claude-analyzer/ root@46.224.193.25:/root/proxy-server/claude-analyzer/
scp webhook-handler/config.py root@46.224.193.25:/root/proxy-server/webhook-handler/config.py
scp webhook-handler/handlers/commands.py root@46.224.193.25:/root/proxy-server/webhook-handler/handlers/commands.py
scp webhook-handler/handlers/github.py root@46.224.193.25:/root/proxy-server/webhook-handler/handlers/github.py
scp docker-compose.unified.yml root@46.224.193.25:/root/proxy-server/docker-compose.unified.yml
```

**Step 3: Build and start claude-analyzer**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build claude-analyzer webhook-handler"
```

**Step 4: Verify health**

```bash
ssh root@46.224.193.25 "docker logs claude-analyzer --tail 5 2>&1"
```
Expected: `claude-analyzer listening on port 3000`

```bash
ssh root@46.224.193.25 "docker logs webhook-handler --tail 5 2>&1"
```
Expected: `Webhook handler ready on port 8086`

**Step 5: Test /review still works**

```bash
curl -s -X POST http://claude-analyzer:3000/health
```
Expected: `{"status":"ok"}`

**Step 6: Test /analyze endpoint directly**

```bash
ssh root@46.224.193.25 "curl -s -X POST http://localhost:3000/analyze -H 'Content-Type: application/json' -d '{\"owner\":\"TheLukasHenry\",\"repo\":\"proxy-server\",\"branch\":\"main\"}' | head -c 500"
```
Expected: JSON with `status: "success"`, `report`, and `user_stories`

**Step 7: Test via Discord**

Type in Discord: `/aiui analyze TheLukasHenry/proxy-server`
Expected: Business requirements report with user stories
