"""Open WebUI API client for chat completions."""
import httpx
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class OpenWebUIClient:
    """Client for Open WebUI /api/chat/completions endpoint."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = 120.0  # 120 second timeout for pipe function (4 phases)

    async def chat_completion(
        self,
        messages: list[dict],
        model: str = "gpt-4-turbo",
        stream: bool = False
    ) -> Optional[str]:
        """
        Send a chat completion request to Open WebUI.

        Args:
            messages: List of message dicts with 'role' and 'content'
            model: Model to use for completion
            stream: Whether to stream response (not supported yet)

        Returns:
            The assistant's response text, or None on error
        """
        url = f"{self.base_url}/api/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()

                data = response.json()
                # Extract response from OpenAI-compatible format
                if "choices" in data and len(data["choices"]) > 0:
                    return data["choices"][0]["message"]["content"]

                logger.error(f"Unexpected response format: {data}")
                return None

        except httpx.TimeoutException:
            logger.error(f"Timeout calling Open WebUI at {url}")
            return None
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error from Open WebUI: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Error calling Open WebUI: {e}")
            return None

    async def generate_deployment_notes(
        self,
        pr_details: dict,
        model: str = "gpt-4-turbo",
    ) -> Optional[str]:
        """Generate deployment notes from PR details using AI."""
        files_list = "\n".join(
            f"- {f['filename']} ({f['status']}: +{f['additions']}/-{f['deletions']})"
            for f in pr_details.get("files_changed", [])
        )

        prompt = (
            f"Generate concise deployment notes for this merged pull request:\n\n"
            f"PR #{pr_details['number']}: {pr_details['title']}\n"
            f"Author: {pr_details['author']}\n"
            f"Branch: {pr_details['branch']} -> {pr_details['base']}\n"
            f"Merged: {pr_details.get('merged_at', 'unknown')}\n"
            f"Files Changed: {pr_details.get('total_changes', 0)} lines "
            f"across {len(pr_details.get('files_changed', []))} files\n\n"
            f"Changed files:\n{files_list}\n\n"
            f"Description:\n{pr_details.get('body') or 'No description provided.'}\n\n"
            f"Format as:\n"
            f"## Deployment Notes -- PR #{pr_details['number']}\n"
            f"**Date:** [merge date]\n"
            f"**What Changed:** [1-2 sentence summary]\n"
            f"**Files Modified:** [bullet list of key files]\n"
            f"**Impact:** [what users/systems are affected]\n"
            f"**Rollback:** [how to revert if needed]\n"
            f"**Testing:** [what was tested or needs testing]"
        )

        messages = [
            {"role": "system", "content": "You are a deployment notes generator. Be concise and precise."},
            {"role": "user", "content": prompt},
        ]
        return await self.chat_completion(messages=messages, model=model)

    async def analyze_github_issue(
        self,
        title: str,
        body: str,
        labels: list[str],
        model: str = "gpt-4-turbo",
        system_prompt: str = ""
    ) -> Optional[str]:
        """
        Analyze a GitHub issue and return AI suggestions.

        Args:
            title: Issue title
            body: Issue body/description
            labels: List of label names
            model: Model to use
            system_prompt: System prompt for the AI

        Returns:
            AI analysis text, or None on error
        """
        if not system_prompt:
            system_prompt = (
                "You are a helpful AI assistant that analyzes GitHub issues "
                "and suggests solutions. Be concise and actionable."
            )

        labels_str = ", ".join(labels) if labels else "none"

        user_prompt = f"""Analyze this GitHub issue and suggest a solution:

**Title:** {title}

**Description:**
{body or "No description provided."}

**Labels:** {labels_str}

Please provide:
1. Brief summary of the issue
2. Possible root causes
3. Suggested solution steps
4. Related files to check (if applicable)"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        return await self.chat_completion(messages, model=model)

    async def analyze_pull_request(
        self,
        title: str,
        body: str,
        diff_summary: str,
        labels: list[str],
        model: str = "gpt-4-turbo",
        system_prompt: str = ""
    ) -> Optional[str]:
        """
        Analyze a GitHub pull request and return AI review.

        Args:
            title: PR title
            body: PR body/description
            diff_summary: Summary of files changed
            labels: List of label names
            model: Model to use
            system_prompt: System prompt for the AI

        Returns:
            AI review text, or None on error
        """
        if not system_prompt:
            system_prompt = (
                "You are a helpful AI code reviewer. Review pull requests "
                "and provide constructive feedback. Be concise and actionable."
            )

        labels_str = ", ".join(labels) if labels else "none"

        user_prompt = f"""Review this GitHub pull request:

**Title:** {title}

**Description:**
{body or "No description provided."}

**Files Changed:**
{diff_summary or "No diff summary available."}

**Labels:** {labels_str}

Please provide:
1. Brief summary of the changes
2. Potential issues or concerns
3. Suggestions for improvement
4. Overall assessment"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        return await self.chat_completion(messages, model=model)

    async def analyze_comment(
        self,
        context_title: str,
        context_body: str,
        comment_body: str,
        comment_author: str,
        model: str = "gpt-4-turbo",
        system_prompt: str = ""
    ) -> Optional[str]:
        """
        Analyze a GitHub comment (on issue or PR) and return AI response.

        Args:
            context_title: Title of the issue/PR being commented on
            context_body: Body of the issue/PR
            comment_body: The comment text
            comment_author: Who wrote the comment
            model: Model to use
            system_prompt: System prompt for the AI

        Returns:
            AI response text, or None on error
        """
        if not system_prompt:
            system_prompt = (
                "You are a helpful AI assistant responding to GitHub comments. "
                "Be concise, helpful, and actionable."
            )

        user_prompt = f"""Respond to this GitHub comment:

**Context (Issue/PR Title):** {context_title}

**Context (Issue/PR Body):**
{context_body or "No description provided."}

**Comment by {comment_author}:**
{comment_body}

Please provide a helpful response."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        return await self.chat_completion(messages, model=model)

    async def analyze_push(
        self,
        commits: list[dict],
        branch: str,
        pusher: str,
        model: str = "gpt-4-turbo",
        system_prompt: str = ""
    ) -> Optional[str]:
        """
        Analyze a GitHub push event and return AI summary.

        Args:
            commits: List of commit dicts with 'message', 'author', 'url'
            branch: Branch name
            pusher: Who pushed
            model: Model to use
            system_prompt: System prompt for the AI

        Returns:
            AI summary text, or None on error
        """
        if not system_prompt:
            system_prompt = (
                "You are a helpful AI assistant that analyzes git push events. "
                "Summarize changes and detect patterns. Be concise."
            )

        commits_text = ""
        for c in commits[:10]:  # Limit to 10 commits
            msg = c.get("message", "No message")
            author = c.get("author", {}).get("name", "Unknown")
            commits_text += f"- {author}: {msg}\n"

        user_prompt = f"""Analyze this push event:

**Branch:** {branch}
**Pushed by:** {pusher}

**Commits ({len(commits)}):**
{commits_text}

Please provide:
1. Summary of changes
2. Any patterns detected (bug fixes, features, refactoring)
3. Any concerns"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        return await self.chat_completion(messages, model=model)

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
