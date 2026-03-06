# Codebase Analysis via /aiui analyze - Design

**Date:** 2026-03-06
**Status:** Approved

## Problem

Team wants to point AI at any GitHub repo and get a quick summary of what it does, its tech stack, and architecture. No workflow exists for this yet despite having GitHub MCP and filesystem MCP servers running.

## Solution

Add `/aiui analyze [owner/repo]` command that fetches key files from GitHub, sends them to AI, and posts a concise summary to Discord.

## Command

```
/aiui analyze                    -> analyzes TheLukasHenry/proxy-server (default)
/aiui analyze owner/repo         -> analyzes any GitHub repo
```

## Flow

```
User types /aiui analyze [repo]
  -> Parse owner/repo (default: report_github_repo from config)
  -> Fetch repo metadata via GitHub API (description, language, topics)
  -> Fetch file tree (top-level)
  -> Fetch key files (README, config files, entry points) - max 5 files, 2000 chars each
  -> Send all context to OpenWebUI AI
  -> Post 1-2 paragraph summary to Discord
```

## Changes

### Modify: `webhook-handler/clients/github.py`

Add `get_repo_overview(owner, repo)` method:
- GET `/repos/{owner}/{repo}` for metadata (description, language, topics)
- GET `/repos/{owner}/{repo}/git/trees/HEAD?recursive=false` for top-level file tree
- Identify key files from tree: README.md, docker-compose*.yml, package.json, requirements.txt, Cargo.toml, go.mod, main.py, app.py, index.js
- GET `/repos/{owner}/{repo}/contents/{path}` for up to 5 key files (base64 decode, truncate to 2000 chars)
- Return dict with metadata, tree, and file contents

### Modify: `webhook-handler/clients/openwebui.py`

Add `analyze_codebase(repo_overview)` method:
- System prompt: "You are a codebase analyst. Given repo metadata, file tree, and key file contents, provide a concise summary: what the app does, tech stack, architecture, key components. 1-2 paragraphs max."
- User prompt: formatted repo overview data
- Returns AI summary string

### Modify: `webhook-handler/handlers/commands.py`

- Add "analyze" to known_commands set
- Add `_handle_analyze(ctx)` method
- Parse optional owner/repo from arguments (default: settings.report_github_repo)
- Call github_client.get_repo_overview()
- Call openwebui.analyze_codebase()
- Post result to Discord

## Key Files Selection (priority order, max 5)

1. README.md (always if exists)
2. docker-compose*.yml / docker-compose*.yaml
3. package.json / requirements.txt / Cargo.toml / go.mod / pyproject.toml
4. main.py / app.py / index.js / index.ts / src/main.* / cmd/main.go

## Token Management

- Each file truncated to 2000 chars
- Max 5 files fetched
- File tree truncated to 50 entries
- Total prompt stays under ~15k tokens

## Error Handling

- If repo not found (404), respond "Repository not found"
- If GitHub token missing, respond "GitHub not configured"
- If AI unavailable, show raw metadata as fallback
- If no key files found, analyze based on tree + metadata only
