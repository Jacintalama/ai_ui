# Codebase Analysis Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `/aiui analyze [owner/repo]` command that fetches key files from any GitHub repo, runs AI analysis, and posts a concise summary of what the app does.

**Architecture:** Add `get_repo_overview()` to GitHubClient to fetch metadata + file tree + key file contents. Add `analyze_codebase()` to OpenWebUIClient for AI analysis. Wire into CommandRouter as a new `analyze` subcommand.

**Tech Stack:** Python, httpx, GitHub REST API, Open WebUI chat completions, Discord bot

---

### Task 1: Add get_repo_overview to GitHubClient

**Files:**
- Modify: `webhook-handler/clients/github.py`

**Step 1: Add the method**

Add this method to the `GitHubClient` class in `webhook-handler/clients/github.py`, after the existing `get_commits_since` method (at the end of the class):

```python
    async def get_repo_overview(self, owner: str, repo: str) -> Optional[dict]:
        """Fetch repo metadata, file tree, and key file contents for analysis."""
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # 1. Repo metadata
                meta_resp = await client.get(
                    f"{self.base_url}/repos/{owner}/{repo}",
                    headers=headers,
                )
                meta_resp.raise_for_status()
                meta = meta_resp.json()

                # 2. File tree (top-level only via contents API)
                tree_resp = await client.get(
                    f"{self.base_url}/repos/{owner}/{repo}/contents",
                    headers=headers,
                )
                tree_resp.raise_for_status()
                tree_items = tree_resp.json()

                tree_names = [
                    f"{'d' if item.get('type') == 'dir' else 'f'} {item['name']}"
                    for item in tree_items[:50]
                ]

                # 3. Identify key files to fetch
                key_patterns = [
                    "README.md", "readme.md",
                    "docker-compose.yml", "docker-compose.yaml",
                    "docker-compose.unified.yml",
                    "package.json", "requirements.txt", "Cargo.toml",
                    "go.mod", "pyproject.toml",
                    "main.py", "app.py", "index.js", "index.ts",
                ]

                available_files = [
                    item["name"] for item in tree_items
                    if item.get("type") == "file"
                ]

                files_to_fetch = []
                for pattern in key_patterns:
                    for fname in available_files:
                        if fname.lower() == pattern.lower() and fname not in files_to_fetch:
                            files_to_fetch.append(fname)
                            break
                    if len(files_to_fetch) >= 5:
                        break

                # 4. Fetch file contents
                file_contents = {}
                for fname in files_to_fetch:
                    try:
                        file_resp = await client.get(
                            f"{self.base_url}/repos/{owner}/{repo}/contents/{fname}",
                            headers={**headers, "Accept": "application/vnd.github.raw+json"},
                        )
                        if file_resp.status_code == 200:
                            content = file_resp.text[:2000]
                            file_contents[fname] = content
                    except Exception as e:
                        logger.warning(f"Failed to fetch {fname}: {e}")

                return {
                    "owner": owner,
                    "repo": repo,
                    "full_name": f"{owner}/{repo}",
                    "description": meta.get("description", ""),
                    "language": meta.get("language", ""),
                    "topics": meta.get("topics", []),
                    "default_branch": meta.get("default_branch", "main"),
                    "stars": meta.get("stargazers_count", 0),
                    "tree": tree_names,
                    "files": file_contents,
                }

        except httpx.HTTPStatusError as e:
            logger.error(f"GitHub API error fetching repo overview: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Failed to fetch repo overview: {e}")
            return None
```

**Step 2: Verify**

Read back the file and confirm `get_repo_overview` is present at the end of the class.

**Step 3: Commit**

```bash
git add webhook-handler/clients/github.py
git commit -m "feat: add get_repo_overview to GitHubClient for codebase analysis"
```

---

### Task 2: Add analyze_codebase to OpenWebUIClient

**Files:**
- Modify: `webhook-handler/clients/openwebui.py`

**Step 1: Add the method**

Add this method to the `OpenWebUIClient` class in `webhook-handler/clients/openwebui.py`, after the existing `analyze_push` method (at the end of the class):

```python
    async def analyze_codebase(
        self,
        repo_overview: dict,
        model: str = "gpt-4-turbo",
    ) -> Optional[str]:
        """Analyze a codebase and return a concise summary."""
        full_name = repo_overview.get("full_name", "unknown")
        description = repo_overview.get("description", "No description")
        language = repo_overview.get("language", "Unknown")
        topics = ", ".join(repo_overview.get("topics", [])) or "none"
        tree = "\n".join(repo_overview.get("tree", []))

        files_text = ""
        for fname, content in repo_overview.get("files", {}).items():
            files_text += f"\n--- {fname} ---\n{content}\n"

        prompt = (
            f"Analyze this GitHub repository and provide a concise summary.\n\n"
            f"**Repository:** {full_name}\n"
            f"**Description:** {description}\n"
            f"**Primary Language:** {language}\n"
            f"**Topics:** {topics}\n\n"
            f"**File Tree (top-level):**\n{tree}\n\n"
            f"**Key File Contents:**\n{files_text}\n\n"
            f"Provide:\n"
            f"1. What this application does (1-2 sentences)\n"
            f"2. Tech stack\n"
            f"3. Key components/architecture\n"
            f"Keep it to 1-2 short paragraphs total."
        )

        messages = [
            {"role": "system", "content": (
                "You are a codebase analyst. Given repository metadata, file tree, "
                "and key file contents, provide a concise summary of what the application "
                "does, its tech stack, and architecture. Be brief and direct."
            )},
            {"role": "user", "content": prompt},
        ]

        return await self.chat_completion(messages=messages, model=model)
```

**Step 2: Verify**

Read back the file and confirm `analyze_codebase` is present at the end of the class.

**Step 3: Commit**

```bash
git add webhook-handler/clients/openwebui.py
git commit -m "feat: add analyze_codebase to OpenWebUIClient"
```

---

### Task 3: Add /aiui analyze command

**Files:**
- Modify: `webhook-handler/handlers/commands.py`

**Step 1: Add "analyze" to known_commands**

Find the `known_commands` set in `parse_command` and add `"analyze"`:

```python
        known_commands = {
            "ask", "workflow", "workflows", "status", "help",
            "report", "pr-review", "pr", "mcp", "diagnose", "analyze",
        }
```

**Step 2: Add analyze to execute dispatch**

In the `execute` method, add before the `else` clause:

```python
            elif ctx.subcommand == "analyze":
                await self._handle_analyze(ctx)
```

**Step 3: Add _handle_analyze method**

Add this method after `_handle_diagnose`:

```python
    async def _handle_analyze(self, ctx: CommandContext) -> None:
        """Analyze a GitHub repository and summarize what it does."""
        if not self._github_client:
            await ctx.respond("GitHub not configured (no GITHUB_TOKEN).")
            return

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
        await ctx.respond(f"Analyzing **{owner}/{repo}**... (fetching repo structure and key files)")

        overview = await self._github_client.get_repo_overview(owner, repo)
        if not overview:
            await ctx.respond(f"Failed to fetch repository `{owner}/{repo}`. Check the name and GitHub access.")
            return

        analysis = await self.openwebui.analyze_codebase(
            repo_overview=overview,
            model=self.ai_model,
        )

        if not analysis:
            # Fallback: show raw metadata
            desc = overview.get("description", "No description")
            lang = overview.get("language", "Unknown")
            tree_preview = "\n".join(overview.get("tree", [])[:20])
            await ctx.respond(
                f"AI analysis unavailable. Raw info for **{owner}/{repo}**:\n"
                f"**Description:** {desc}\n**Language:** {lang}\n"
                f"```\n{tree_preview}\n```"
            )
            return

        response = f"\U0001f50d **Analysis of {owner}/{repo}**\n\n{analysis}"

        limit = 2000 if ctx.platform == "discord" else 3000
        if len(response) > limit:
            response = response[:limit - 20] + "\n\n... (truncated)"

        await ctx.respond(response)
```

**Step 4: Update help text**

In `_handle_help`, add after the diagnose line:

```python
            "`/aiui analyze [owner/repo]` \u2014 AI analysis of a GitHub codebase\n"
```

**Step 5: Commit**

```bash
git add webhook-handler/handlers/commands.py
git commit -m "feat: add /aiui analyze command for codebase analysis"
```

---

### Task 4: Deploy and test

**Step 1: Deploy all changed files**

```bash
scp webhook-handler/clients/github.py root@46.224.193.25:/root/proxy-server/webhook-handler/clients/github.py
scp webhook-handler/clients/openwebui.py root@46.224.193.25:/root/proxy-server/webhook-handler/clients/openwebui.py
scp webhook-handler/handlers/commands.py root@46.224.193.25:/root/proxy-server/webhook-handler/handlers/commands.py
```

**Step 2: Rebuild and restart**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml build --no-cache webhook-handler && docker compose -f docker-compose.unified.yml up -d webhook-handler"
```

**Step 3: Verify healthy**

```bash
ssh root@46.224.193.25 "docker logs webhook-handler 2>&1 | tail -5"
```

**Step 4: Test on Discord**

Run `/aiui analyze` — should analyze TheLukasHenry/proxy-server (default).

Run `/aiui analyze TheLukasHenry/proxy-server` — should produce same result.

Expected: 1-2 paragraph summary of the project with tech stack and architecture.
