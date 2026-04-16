"""Resolve raw assignee names from the decision engine to admin emails."""
from __future__ import annotations

import os
from dataclasses import dataclass

TEAM_EMAIL = "team@aiui.local"


@dataclass(frozen=True)
class AssigneeMap:
    """Map of lowercase prefix -> email."""

    entries: tuple[tuple[str, str], ...]

    @classmethod
    def from_env_string(cls, raw: str) -> "AssigneeMap":
        pairs: list[tuple[str, str]] = []
        for chunk in (raw or "").split(","):
            chunk = chunk.strip()
            if not chunk or ":" not in chunk:
                continue
            key, email = chunk.split(":", 1)
            pairs.append((key.strip().lower(), email.strip()))
        return cls(entries=tuple(pairs))

    @classmethod
    def from_env(cls) -> "AssigneeMap":
        return cls.from_env_string(os.environ.get("TASKS_ASSIGNEE_MAP", ""))

    def resolve(self, assignee_name: str) -> str:
        if not assignee_name:
            return TEAM_EMAIL
        lower = assignee_name.strip().lower()
        if lower == "team":
            return TEAM_EMAIL
        for key, email in self.entries:
            if lower.startswith(key):
                return email
        return TEAM_EMAIL

    def admin_emails(self) -> list[str]:
        return [email for _, email in self.entries]
