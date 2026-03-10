const express = require("express");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const app = express();
app.use(express.json());

const PORT = 3000;
const WORKSPACE = "/workspace";
const CLAUDE_TIMEOUT_MS = 300_000;
const MAX_DIFF_BYTES = 50_000;

let analyzing = false;

const SAFE_NAME_RE = /^[a-zA-Z0-9._-]+$/;
const SAFE_REF_RE = /^[a-zA-Z0-9._\-/]+$/;

function log(msg) {
  console.log(`[${new Date().toISOString()}] ${msg}`);
}

function redactSecrets(args) {
  const token = process.env.GITHUB_TOKEN;
  if (!token) return args;
  return args.map((a) => (typeof a === "string" ? a.replaceAll(token, "***") : a));
}

function redactString(str) {
  const token = process.env.GITHUB_TOKEN;
  return token ? str.replaceAll(token, "***") : str;
}

function runCommand(cmd, args, options = {}) {
  return new Promise((resolve, reject) => {
    log(`Running: ${cmd} ${redactSecrets(args).join(" ")}`);
    const proc = spawn(cmd, args, { ...options, stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    proc.stdout.on("data", (d) => (stdout += d.toString()));
    proc.stderr.on("data", (d) => (stderr += d.toString()));
    proc.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(redactString(`${cmd} exited with code ${code}: ${stderr.trim()}`)));
      } else {
        resolve(stdout.trim());
      }
    });
    proc.on("error", reject);
  });
}

// --- Shared functions ---

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

// --- Routes ---

app.get("/health", (_req, res) => {
  res.json({ status: "ok" });
});

app.post("/review", async (req, res) => {
  if (analyzing) {
    return res.status(503).json({ error: "Analysis already in progress", status: "busy" });
  }

  const { owner, repo, pr_number, branch, base_branch } = req.body;

  if (!owner || !repo || !pr_number || !branch || !base_branch) {
    return res.status(400).json({
      error: "Missing required fields: owner, repo, pr_number, branch, base_branch",
      status: "error",
    });
  }

  if (!SAFE_NAME_RE.test(owner) || !SAFE_NAME_RE.test(repo)) {
    return res.status(400).json({ error: "Invalid owner or repo name", status: "error" });
  }
  if (!SAFE_REF_RE.test(branch) || !SAFE_REF_RE.test(base_branch)) {
    return res.status(400).json({ error: "Invalid branch name", status: "error" });
  }

  analyzing = true;
  const startTime = Date.now();

  try {
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

    const promptText = `Review PR #${pr_number} for the ${owner}/${repo} repository.

The git diff is at /tmp/pr-diff.txt. Read it to understand what changed.

Review the actual source files in this repository for full context.
Follow the CLAUDE.md guidelines in the repo root.

Provide a structured review covering:
1. Summary of changes
2. Potential bugs or issues
3. Security concerns
4. Suggestions for improvement

Be concise and actionable.`;

    const review = await runClaude(promptText, repoDir, "text");

    const duration = ((Date.now() - startTime) / 1000).toFixed(1);
    log(`Review completed in ${duration}s`);

    res.json({ review, status: "success", duration_seconds: parseFloat(duration) });
  } catch (err) {
    const duration = ((Date.now() - startTime) / 1000).toFixed(1);
    const safeError = redactString(err.message);
    log(`Review failed after ${duration}s: ${safeError}`);
    res.status(500).json({ error: safeError, status: "error" });
  } finally {
    analyzing = false;
  }
});

app.post("/analyze", async (req, res) => {
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

    // Parse JSON from Claude's response
    // Claude may wrap in ```json ... ``` fences or add preamble text
    let parsed;
    try {
      // Strip markdown code fences first
      let cleaned = raw.replace(/```json\s*/gi, "").replace(/```\s*/g, "").trim();
      // Try to find the outermost JSON object
      const firstBrace = cleaned.indexOf("{");
      const lastBrace = cleaned.lastIndexOf("}");
      if (firstBrace !== -1 && lastBrace > firstBrace) {
        cleaned = cleaned.substring(firstBrace, lastBrace + 1);
      }
      parsed = JSON.parse(cleaned);
    } catch (e) {
      log(`JSON parse failed: ${e.message}. Returning raw text as report.`);
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
    analyzing = false;
  }
});

app.listen(PORT, () => {
  log(`claude-analyzer listening on port ${PORT}`);
});
