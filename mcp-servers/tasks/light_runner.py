"""Run a light build: one model call, one file, no subprocess.

The agent path spawns a Claude Code CLI and peaks at ~900MB inside a 1GB
container, which is why only one build could run at a time. This path
makes an HTTP request. Several can run at once, capped by
`LIGHT_BUILD_CONCURRENCY` so a burst still cannot exhaust the box.

It finishes a task exactly the way `routes_execution._run_execution`
does, so everything downstream (the chat watcher, publishing, the
version list, rollback, the appearance panel) sees an ordinary finished
build and needs to know nothing about lanes.

Design: docs/superpowers/specs/2026-11-05-light-build-lane-design.md
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

import httpx
from sqlalchemy import update

import app_git
import build_progress
import light_build
from db import session
from models import TaskExecution, TaskItem

logger = logging.getLogger("tasks.light_build")

#: How many light builds may run at once. Its own ceiling, separate from
#: the agent's one-at-a-time, because the whole point is that several
#: people can build together. A cap still exists: a burst of these is
#: small but not free, and nothing else would stop a hundred.
CONCURRENCY = int(os.environ.get("LIGHT_BUILD_CONCURRENCY", "6"))

#: Which model writes the page.
MODEL = os.environ.get("LIGHT_BUILD_MODEL", "claude-sonnet-5")

#: A page is ~11k characters, so this is roughly double the longest one
#: measured, leaving room for a denser design without truncating it.
MAX_TOKENS = int(os.environ.get("LIGHT_BUILD_MAX_TOKENS", "16000"))
TIMEOUT_S = float(os.environ.get("LIGHT_BUILD_TIMEOUT_S", "240"))

_slots: asyncio.Semaphore | None = None


def slots() -> asyncio.Semaphore:
    """Created lazily, because a Semaphore binds to the running loop."""
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(CONCURRENCY)
    return _slots


async def _say(task_id, step: str) -> None:
    """Record the step. Fails open, like every other progress write: a
    build that finishes and could not say so is still finished."""
    try:
        await build_progress._write_seam(task_id, step)
    except Exception:
        logger.warning("light build: could not record step %s", step,
                       exc_info=True)


async def _finish(task_id, execution_id, *, status: str, result: str,
                  slug: str | None) -> None:
    """Write the same final state the agent path writes."""
    values = {
        "status": status,
        "result": result,
        "completed_at": datetime.utcnow() if status == "completed" else None,
    }
    if status == "completed" and slug:
        values["built_app_slug"] = slug
    async with session() as s:
        await s.execute(
            update(TaskExecution).where(TaskExecution.id == execution_id)
            .values(status=("success" if status == "completed" else "failed"),
                    finished_at=datetime.utcnow()))
        await s.execute(
            update(TaskItem).where(TaskItem.id == task_id).values(**values))
        await s.commit()


async def _ask_for_the_page(description: str, slug: str, app_name: str,
                            complaint: str | None) -> str:
    """One model call. `complaint` is what was wrong with the last try."""
    import fusion_engine
    messages = light_build.page_prompt(description, slug, app_name)
    if complaint:
        messages.append({
            "role": "user",
            "content": ("Your last answer could not be used: %s. Send the "
                        "whole file again, fixed. Nothing but the file."
                        % complaint)})
    async with httpx.AsyncClient() as client:
        answer = await fusion_engine.call_model(
            MODEL, messages, max_tokens=MAX_TOKENS, timeout_s=TIMEOUT_S,
            client=client)
    return light_build.html_from(answer)


async def run_light_build(task_id, execution_id, *, slug: str,
                          app_name: str, description: str) -> None:
    """Write a simple site and finish the task.

    Never raises. A build that fails says why, in words the person who
    asked can act on, rather than leaving a task running forever.
    """
    async with slots():
        try:
            await _say(task_id, "drafting")
            html = await _ask_for_the_page(description, slug, app_name, None)

            await _say(task_id, "proofing")
            problem = light_build.page_problem(html)
            if problem:
                # One retry, with the complaint, because the usual
                # failure is a page cut off at the token limit or a
                # stray reference, and both are things a model fixes
                # when told. A second failure is reported rather than
                # retried forever.
                logger.info("light build %s: retrying, %s", slug, problem)
                await _say(task_id, "drafting")
                html = await _ask_for_the_page(description, slug, app_name,
                                               problem)
                await _say(task_id, "proofing")
                problem = light_build.page_problem(html)

            if problem:
                await _finish(
                    task_id, execution_id, status="failed", slug=None,
                    result=("The page could not be finished: %s. Asking "
                            "again usually works." % problem))
                return

            light_build.write_site(
                slug, html,
                light_build.readme_for(slug, app_name, description))

            await _say(task_id, "filing")
            # Fails open, exactly like the agent path's commit sweep: the
            # site is already on disk and will serve. A failed commit
            # costs version history, not the build.
            try:
                await app_git.sweep_app_commit(
                    slug, message="Build %s" % slug, actor_email=None)
            except Exception:
                logger.warning("light build %s: commit sweep failed", slug,
                               exc_info=True)

            await _finish(task_id, execution_id, status="completed",
                          slug=slug,
                          result="Built apps/%s/ as a single page." % slug)
        except Exception as exc:
            logger.exception("light build %s failed", slug)
            await _finish(
                task_id, execution_id, status="failed", slug=None,
                result=("The page could not be built: %s"
                        % str(exc)[:300] or "something went wrong"))
