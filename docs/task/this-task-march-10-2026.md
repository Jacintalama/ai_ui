# Tasks — March 10, 2026

## Immediate / This Sprint
1. **Test PR review in Discord** — Lukas will test it today on real PRs
2. **Robin to PR his n8n workflows** — PR notification + code review comments into the main repo
3. **Gmail & Google Sheets integration working** — Connect email and sheets to the platform (what we've been fixing)

## Next Direction
4. **Business Requirements Extractor** — New container skill that analyzes any GitHub repo and extracts only the business requirements (what it does, which problem it solves, use cases) — NOT implementation details
5. **Rebuild from requirements** — Use those extracted requirements to rebuild the app from scratch with AI
6. **More Claude Code container skills** — Reuse the PR reviewer container pattern for:
   - Security audits
   - Package update checks
   - Business requirements analysis
   - Code quality reviews

## Longer Term
7. **Voice-driven development** — Lukas uses voice (11Labs + Claude Code) to talk instead of type. Wants this as part of the workflow.
8. **Better agent skills** — "Providing good skills to the agents will be the key" — building a library of reusable skills

Tasks 1-3 are what we're actively working on. Task 4 is what Lukas sees as the next big thing to build.

---

## Research Notes (for Tasks 4-6)

### Business Requirements Extractor (Task 4)
- **Research:** LLMs achieve F1 score of 0.8 extracting user stories from code ([arXiv 2509.19587](https://arxiv.org/html/2509.19587v1))
- **Best approach:** One-shot prompting (single example outperforms complex chain-of-thought)
- **Keep code under 200 lines per chunk** for best accuracy
- **Prompt pattern:** "Extract WHAT the code does for the end user, not HOW. Format as user stories: As a [role], I want [feature], so that [benefit]."
- **Same container as PR reviewer** — just different CLAUDE.md prompt

### Container Skill Architecture (Task 6)
All skills reuse the same Docker pattern (Claude Code CLI in container):

```bash
claude -p "Your analysis prompt here" \
  --allowedTools "Read,Grep,Glob" \
  --output-format json \
  --dangerously-skip-permissions
```

**Key CLI flags:**
- `-p` / `--print` — Non-interactive (headless) mode
- `--dangerously-skip-permissions` — Skip prompts (containers only)
- `--allowedTools` — Whitelist specific tools
- `--output-format json` — Structured output
- `--append-system-prompt` — Add role context

**Minimal Dockerfile:**
```dockerfile
FROM node:18-alpine
RUN npm install -g @anthropic-ai/claude-code
USER node
WORKDIR /workspace
```

**DevContainer reference:** `github.com/anthropics/claude-code/.devcontainer/`

### Security Audit Skill
- Anthropic's "Claude Code Security" found 500+ zero-day vulnerabilities in production OSS
- Best results: combine Claude Code with SAST tools (Semgrep, Trivy, SonarQube)
- LLMs excel at semantic reasoning about logic flows; SAST excels at known patterns
- Semgrep research: 14% true positive rate standalone, much higher combined with SAST

### Package Update Skill
- Pipe `npm audit --json` / `pip-audit` output to Claude Code for AI impact analysis
- **Fossabot** detects breaking changes by analyzing changelogs against your codebase
- **Astra** uses Tree-sitter + OSV.dev + AI for fix suggestions
- Key gap traditional tools miss: "will this update break MY app?"

### Skills System
- Create `.claude/skills/my-skill/SKILL.md` with YAML frontmatter
- Can run in isolated subagents with own model/tools
- Priority: Enterprise > Personal (`~/.claude/skills/`) > Project (`.claude/skills/`)
