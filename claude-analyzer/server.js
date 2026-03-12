const express = require("express");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const app = express();
app.use(express.json());

const PORT = 3000;
const WORKSPACE = "/workspace";
const CLAUDE_TIMEOUT_MS = 300_000;
const REBUILD_TIMEOUT_MS = 300_000;
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

function runClaude(prompt, cwd, outputFormat = "text", timeoutMs = CLAUDE_TIMEOUT_MS) {
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
      reject(new Error(`Claude Code timed out after ${timeoutMs / 1000} seconds`));
    }, timeoutMs);

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

function extractJSON(raw) {
  let cleaned = raw.replace(/```json\s*/gi, "").replace(/```\s*/g, "").trim();
  const firstBrace = cleaned.indexOf("{");
  const lastBrace = cleaned.lastIndexOf("}");
  if (firstBrace !== -1 && lastBrace > firstBrace) {
    cleaned = cleaned.substring(firstBrace, lastBrace + 1);
  }
  return JSON.parse(cleaned);
}

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

// --- Routes ---

app.get("/health", (_req, res) => {
  res.json({ status: "ok" });
});

app.get("/skills", (_req, res) => {
  res.json({ skills: listSkills() });
});

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
    const raw = await runClaude(skill.prompt, repoDir, "text", timeoutMs);

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
    let parsed;
    try {
      parsed = extractJSON(raw);
    } catch (e) {
      log(`JSON parse failed: ${e.message}. Returning raw text as report.`);
      parsed = { report: raw, user_stories: [] };
    }

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

    // Step 3: Phase 2 — Generate plan or PRD based on recommendation
    log(`Phase 2: Generating ${research.recommendation === "custom-build" ? "PRD" : "integration plan"}...`);

    let plan = "";
    let prd = null;

    if (research.recommendation === "custom-build") {
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
  } catch (err) {
    const duration = ((Date.now() - startTime) / 1000).toFixed(1);
    const safeError = redactString(err.message);
    log(`Rebuild failed after ${duration}s: ${safeError}`);
    res.status(500).json({ error: safeError, status: "error" });
  } finally {
    analyzing = false;
  }
});

app.listen(PORT, () => {
  log(`claude-analyzer listening on port ${PORT}`);
});
