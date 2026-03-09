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

let reviewing = false;

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

app.get("/health", (_req, res) => {
  res.json({ status: "ok" });
});

app.post("/review", async (req, res) => {
  if (reviewing) {
    return res.status(503).json({ error: "Review already in progress", status: "busy" });
  }

  const { owner, repo, pr_number, branch, base_branch } = req.body;

  if (!owner || !repo || !pr_number || !branch || !base_branch) {
    return res.status(400).json({
      error: "Missing required fields: owner, repo, pr_number, branch, base_branch",
      status: "error",
    });
  }

  // Validate inputs to prevent path traversal and injection
  if (!SAFE_NAME_RE.test(owner) || !SAFE_NAME_RE.test(repo)) {
    return res.status(400).json({ error: "Invalid owner or repo name", status: "error" });
  }
  if (!SAFE_REF_RE.test(branch) || !SAFE_REF_RE.test(base_branch)) {
    return res.status(400).json({ error: "Invalid branch name", status: "error" });
  }

  const GITHUB_TOKEN = process.env.GITHUB_TOKEN;
  if (!GITHUB_TOKEN) {
    return res.status(500).json({ error: "GITHUB_TOKEN not configured", status: "error" });
  }

  reviewing = true;
  const startTime = Date.now();

  try {
    const repoDir = path.join(WORKSPACE, owner, repo);
    const repoUrl = `https://${GITHUB_TOKEN}@github.com/${owner}/${repo}.git`;

    // Clone or fetch
    const cleanRepoUrl = `https://github.com/${owner}/${repo}.git`;
    if (!fs.existsSync(path.join(repoDir, ".git"))) {
      log(`Cloning ${owner}/${repo}...`);
      fs.mkdirSync(path.join(WORKSPACE, owner), { recursive: true });
      await runCommand("git", ["clone", repoUrl, repoDir]);
      // Strip token from stored remote URL so it doesn't persist in .git/config
      await runCommand("git", ["remote", "set-url", "origin", cleanRepoUrl], { cwd: repoDir });
    } else {
      log(`Fetching latest for ${owner}/${repo}...`);
      // Temporarily set authenticated URL for fetch, then clean it
      await runCommand("git", ["remote", "set-url", "origin", repoUrl], { cwd: repoDir });
      await runCommand("git", ["fetch", "origin"], { cwd: repoDir });
      await runCommand("git", ["remote", "set-url", "origin", cleanRepoUrl], { cwd: repoDir });
    }

    // Checkout PR branch
    log(`Checking out branch ${branch}...`);
    await runCommand("git", ["checkout", branch], { cwd: repoDir });
    // Temporarily set authenticated URL for pull, then clean it
    await runCommand("git", ["remote", "set-url", "origin", repoUrl], { cwd: repoDir });
    await runCommand("git", ["pull", "origin", branch], { cwd: repoDir });
    await runCommand("git", ["remote", "set-url", "origin", cleanRepoUrl], { cwd: repoDir });

    // Generate diff against remote base to avoid stale local refs
    log(`Generating diff origin/${base_branch}...${branch}...`);
    let diff = await runCommand("git", ["diff", `origin/${base_branch}...${branch}`], { cwd: repoDir });
    if (diff.length > MAX_DIFF_BYTES) {
      log(`Diff too large (${diff.length} bytes), truncating to ${MAX_DIFF_BYTES} bytes`);
      diff = diff.substring(0, MAX_DIFF_BYTES) + "\n\n... [DIFF TRUNCATED - full diff was " + diff.length + " bytes] ...";
    }
    fs.writeFileSync("/tmp/pr-diff.txt", diff);
    log(`Diff written to /tmp/pr-diff.txt (${diff.length} bytes)`);

    // Run Claude Code
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

    log("Starting Claude Code review...");
    const review = await new Promise((resolve, reject) => {
      const proc = spawn("claude", ["-p", promptText, "--output-format", "text"], {
        cwd: repoDir,
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

    const duration = ((Date.now() - startTime) / 1000).toFixed(1);
    log(`Review completed in ${duration}s`);

    res.json({ review, status: "success", duration_seconds: parseFloat(duration) });
  } catch (err) {
    const duration = ((Date.now() - startTime) / 1000).toFixed(1);
    const safeError = redactString(err.message);
    log(`Review failed after ${duration}s: ${safeError}`);
    res.status(500).json({ error: safeError, status: "error" });
  } finally {
    reviewing = false;
  }
});

app.listen(PORT, () => {
  log(`pr-reviewer listening on port ${PORT}`);
});
