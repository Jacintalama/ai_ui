"""Post-execution docs sweep for built apps.

Why this exists: the build prompts (`claude_executor.py`, the DOCS blocks) TELL
the agent that `apps/<slug>/README.md` is mandatory. Telling is not enough. The
commit sweep next door exists for exactly this reason: the agent was told to
`git add` + `git commit` and, measured on prod 2026-07-16, 43 of 47 app dirs had
zero commits. A prompt is a request, not a guarantee.

So this makes the doc a step. If the agent wrote a real README, this leaves it
completely alone. If it skipped it, or left a stub, this writes a minimal honest
one from what we actually know (the slug and the task summary) rather than
inventing features nobody built.

Must run BEFORE `app_git.sweep_app_commit` so the doc lands in the same commit.
"""
import logging
import os
import re
from datetime import date
from pathlib import Path

from routes_projects import _validate_slug as _validate_slug_default

logger = logging.getLogger(__name__)

# Module-level seams so tests can drive this without a real workspace, matching
# the `_run_git` seam in app_git and `_smoke_app` in routes_execution.
_validate_slug = _validate_slug_default
_apps_root = lambda: os.environ.get(  # noqa: E731
    "APPS_DIR",
    os.path.join(os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui"), "apps"),
)
_today = lambda: date.today().isoformat()  # noqa: E731

def _title_from_slug(slug: str) -> str:
    return " ".join(w.capitalize() for w in re.split(r"[-_]+", slug) if w)


def _is_stub(text: str) -> bool:
    """True when a README exists in name only: empty, or headings with nothing
    written under them.

    Deliberately generous. Overwriting a real doc the agent wrote is far worse
    than leaving a thin one alone, so the only question asked is "did anyone
    write a single line of prose?". A short README is still a README: judging
    by length would delete a perfectly good one-line description.
    """
    body = (text or "").strip()
    if not body:
        return True
    prose = [ln for ln in body.splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")]
    return not prose


def _starter_readme(slug: str, summary: str | None) -> str:
    """A minimal, honest doc. It does not invent features: what it claims is
    only what we can actually stand behind, which is what was asked for."""
    asked = " ".join((summary or "").split()) or "No build summary was recorded."
    if len(asked) > 300:
        asked = asked[:297].rstrip() + "..."
    return (
        f"# {_title_from_slug(slug)}\n\n"
        f"{asked}\n\n"
        "## What it does\n\n"
        "This section was generated automatically because the build did not\n"
        "leave one. Ask the builder to update these docs and it will fill this\n"
        "in from the actual code.\n\n"
        "## How to run\n\n"
        f"Open the app from App Builder, or open `apps/{slug}/index.html`\n"
        "in a browser.\n\n"
        "## Changelog\n\n"
        f"- {_today()}: first build.\n"
    )


def app_readme_path(slug: str) -> Path:
    return Path(_apps_root()) / slug / "README.md"


async def sweep_app_docs(slug: str, *, summary: str | None) -> bool:
    """Guarantee apps/<slug>/README.md exists and is not a stub.

    Returns True when this wrote the file, False when it left the agent's doc
    alone or could not act.

    Fails open by design, matching `sweep_app_commit`: this runs after a build
    has already reached "completed", so nothing here may flip that build to
    failed. The worst case is the app has the docs it would have had anyway.
    """
    try:
        _validate_slug(slug)
    except Exception:
        logger.warning("docs sweep: refusing invalid slug %r", slug)
        return False

    try:
        path = app_readme_path(slug)
        if not path.parent.is_dir():
            # No app directory means no build output to document.
            return False
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if not _is_stub(existing):
            # The agent did its job. Leave it completely alone.
            return False
        path.write_text(_starter_readme(slug, summary), encoding="utf-8")
        logger.info("docs sweep: wrote a starter README for %s", slug)
        return True
    except Exception:
        logger.exception("docs sweep: could not write README for %s", slug)
        return False
