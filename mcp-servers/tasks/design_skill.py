"""The design skill an App Builder run is given, and how the run is told.

An agent can have the Impeccable skill ticked on its Edit agent form. That
agent never writes code: create_app and apply_app_change start an App Builder
run, which is Claude Code. So ticking the skill has to reach that run, or it
would only change the words the agent types. This module is the whole of
that reach: who asked (for_agent), and what the run gets (system_prompt,
cli_args, env, remote_prefix).

Impeccable (https://impeccable.style, Apache 2.0) is written for a person at
the keyboard. Its setup interviews the user, and its design step can open a
question page and wait for an answer. A build here is unattended and has 600
seconds, so every run that gets the skill also gets rules that turn those
steps off, and loses the question tool. Checked on the build host on
2026-10-02 with Claude Code 2.1.140: --disallowedTools AskUserQuestion takes
the tool away, and a skill linked into the run's own .claude/skills is loaded
by that run and by no other.

The rules go in as a system prompt rather than into the task prompt, because
the executors cut the task prompt at MAX_PROMPT_CHARS and a fresh-build
prompt is already longer than that.

Everything here fails open. An unknown agent, a database error or a missing
skill on the host leaves the build exactly as it was before this existed.
"""
from __future__ import annotations

import json
import logging
import math
import os

from sqlalchemy import text

import agent_skills
import build_model
from db import session

logger = logging.getLogger(__name__)

IMPECCABLE = "impeccable"

#: Where scripts/install_impeccable.sh puts the skill on the build host.
#: Expanded by the build user's own shell, so it is that user's home.
REMOTE_SKILL_DIR = "$HOME/.impeccable/skills/impeccable"

DEFAULT_MAX_BUDGET_USD = "1.50"

_RULES = """IMPECCABLE DESIGN SKILL, FOR THIS RUN

The person who asked for this work chose the Impeccable design skill. Before \
you write or change any HTML, CSS or interface code, load it with the Skill \
tool (skill: impeccable) and follow it, with the rules below. This build runs \
unattended, so where the skill and these rules disagree, these rules win.

1. Nobody can answer a question during this run. Never ask, never wait for an \
answer, and never stop with NEEDS_INPUT over a design choice. Where the skill \
says to interview, confirm or ask, decide from the request instead.
2. Product context lives in the app folder. Write apps/{slug}/PRODUCT.md from \
the request, and mark every fact you inferred rather than read with \
"(inferred)". Pass --target apps/{slug} to the skill's commands. Anything you \
write outside apps/{slug}/ is thrown away when the run ends.
3. Build code-first. Do not run serve-question, live, generate, comps or any \
image generation, and do not start a dev server or a browser: this machine \
has no display and no browser.
4. The task's own platform rules still hold: its stack, CDN block, file \
layout, content and README rules. Impeccable decides the design inside them.
5. Before you finish, run .claude/skills/impeccable/scripts/impeccable detect \
apps/{slug} once, fix what it reports in one batch, and do not run it again.
6. Changing an app that already exists is a refinement: keep its look, copy \
and behaviour outside what was asked.
7. Finish exactly as the task says, with its COMPLETED line last.

If the impeccable skill is not available, say so in one line and follow \
rules 4 to 7 anyway."""


def _on(design, slug) -> bool:
    return design == IMPECCABLE and bool(slug)


def system_prompt(slug: str) -> str:
    """The rules for one marked run. str.replace, not format: the rules are
    prose and a brace in them must not become a template field."""
    return _RULES.replace("{slug}", slug)


def max_budget_usd() -> str:
    """The most one marked run may spend, as Claude Code's --max-budget-usd.

    A cap rather than a hope: Impeccable's own guidance is to go all out, and
    a run that loops on its design checker would otherwise spend until the
    600 second limit. Anything that is not a positive finite number falls
    back to the default rather than to no cap.
    """
    raw = os.environ.get("IMPECCABLE_MAX_BUDGET_USD", "").strip()
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_MAX_BUDGET_USD
    if not math.isfinite(value) or value <= 0:
        return DEFAULT_MAX_BUDGET_USD
    return raw


def cli_args(design: str | None, slug: str | None) -> list[str]:
    """Extra claude arguments for a marked run, none for any other."""
    if not _on(design, slug):
        return []
    args = ["--append-system-prompt", system_prompt(slug),
            "--max-budget-usd", max_budget_usd()]
    if not build_model.model():
        # With a model override build_model already disallows this tool among
        # others, and a second --disallowedTools is not something the CLI
        # documents merging.
        args += ["--disallowedTools", "AskUserQuestion"]
    return args


def env(design: str | None, slug: str | None) -> dict[str, str]:
    """Environment for a marked run: Impeccable's question page off. Its
    engine honours this variable and answers "use the structured question
    tool instead", which the run does not have."""
    return {"IMPECCABLE_QUESTION_DISABLED": "1"} if _on(design, slug) else {}


def remote_prefix(design: str | None, slug: str | None) -> str:
    """Shell run on the build host in /agent/work/<slug>, before claude.

    Links the installed skill into this run's own project skills, so only a
    marked run can load it; the folder is deleted when the run ends and is
    never synced back, because only apps/<slug>/ is. `|| true` because the
    remote command runs under set -e, and a host without the skill must
    still build.
    """
    if not _on(design, slug):
        return ""
    return ('{ mkdir -p .claude/skills && ln -sfn "%s" '
            ".claude/skills/impeccable; } || true; "
            "export IMPECCABLE_QUESTION_DISABLED=1; " % REMOTE_SKILL_DIR)


def skill_from_meta(meta) -> str | None:
    """IMPECCABLE when an agent's meta has it ticked, else None."""
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except ValueError:
            return None
    return IMPECCABLE if IMPECCABLE in agent_skills._ids_from(meta) else None


async def for_agent(user_email, agent_id) -> str | None:
    """The design skill for a job this person's agent started, or None.

    Reads the agent row itself rather than taking a flag from the caller:
    the caller is a tool the model drives, and what the model may choose is
    what to build, not how much the build may spend. Scoped to the caller's
    own agent, so one person's id cannot borrow another's settings.
    """
    if not (isinstance(agent_id, str) and agent_id.startswith("agent-")
            and isinstance(user_email, str) and user_email):
        return None
    try:
        async with session() as s:
            row = (await s.execute(text(
                "SELECT m.meta FROM public.model m "
                'JOIN public."user" u ON u.id = m.user_id '
                "WHERE m.id = :agent_id AND lower(u.email) = lower(:email)"),
                {"agent_id": agent_id, "email": user_email})).first()
    except Exception as exc:                                # noqa: BLE001
        logger.warning("design skill lookup for %s failed: %s",
                       agent_id, type(exc).__name__)
        return None
    return skill_from_meta(row[0]) if row else None
