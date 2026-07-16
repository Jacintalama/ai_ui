"""The .gitignore must not swallow real user apps.

`_slugify` (routes_aiuibuilder.py:187) builds an app's slug from the first five
words of the user's build description, so any `apps/<verb>-*` rule collides with
real apps by construction. On 2026-07-16 five such rules were ignoring 11 real
user apps on prod, which is one of the two reasons 43 of 47 apps had no version
history at all (`git add` on an ignored path is a silent no-op).
"""
import subprocess
from pathlib import Path

import pytest

from routes_aiuibuilder import _slugify
from routes_projects import REPO_ROOT as _BIND_MOUNTED_REPO


def _find_repo_root() -> Path | None:
    """The git tree that actually holds .gitignore.

    Local checkout: walk up from this file (IO/mcp-servers/tasks/tests -> IO).
    In the tasks container the code is COPYd to /app, which has no .gitignore
    and only two parents to walk, while the real git tree is bind-mounted at
    /workspace/ai_ui. Hard-coding parents[3] passed locally and raised
    IndexError in the container, so find it rather than assume it.
    """
    for p in Path(__file__).resolve().parents:
        if (p / ".gitignore").is_file() and (p / ".git").exists():
            return p
    fallback = Path(_BIND_MOUNTED_REPO)
    if (fallback / ".gitignore").is_file() and (fallback / ".git").exists():
        return fallback
    return None


REPO_ROOT = _find_repo_root()

pytestmark = pytest.mark.skipif(
    REPO_ROOT is None,
    reason="no git tree with a .gitignore reachable from here",
)


def _ignored_by(slug: str) -> str | None:
    """The .gitignore pattern ignoring apps/<slug>/, or None if not ignored.

    Two traps this deliberately avoids, both of which produced false results
    when checked by hand:

    1. `git check-ignore -q` exits 0 for ANY non-existent path, reporting a
       phantom match against a blank line. The exit code is therefore useless
       here. Only a `-v` result whose PATTERN field is non-empty is a real
       match.
    2. The `apps/*` rules carry a trailing slash, making them directory-only,
       so the queried path must carry one too or real matches silently vanish.
    """
    out = subprocess.run(
        ["git", "check-ignore", "-v", f"apps/{slug}/"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    ).stdout
    if not out.strip():
        return None
    # -v format: <source>:<lineno>:<pattern>\t<pathname>
    head = out.split("\t")[0]
    parts = head.split(":", 2)
    if len(parts) < 3:
        return None
    return parts[2].strip() or None


# Real user apps found on prod 2026-07-16, every one of them ignored at the time.
REAL_USER_APPS = [
    "create-me-a-keyboard-landing-de7b",
    "create-me-a-landing-page-bf8a",
    "create-me-a-landing-page-eb8e",
    "create-me-an-ai-landing-9d4a",
    "create-me-a-shoe-website-fe02",
    "create-me-chicken-joy-landing-afa6",
    "create-me-door-store-landing-6ae3",
    "create-me-ice-cream-landing-8b42",
    "make-the-restaurant-name-to-67c1",
    "me-a-icecream-website-5505",
    "me-a-website-for-a-1803",
]

# Slugs a real user would plausibly generate from a natural description.
PLAUSIBLE_USER_APPS = [
    "create-me-a-crm-1a2b",           # "create me a CRM"
    "make-the-landing-page-3c4d",     # "make the landing page for my bakery"
    "upload-a-csv-parser-5e6f",       # "upload a CSV parser"
    "smoke-alarm-shop-7a8b",          # "smoke alarm shop"
    "me-a-portfolio-site-9c0d",
]

# Junk our own harnesses generate. These must STAY ignored.
HARNESS_JUNK = [
    "browser-smoke-1777559405",
    "build-smoke-may22-d44b",
    "smoke-upload-1777558507",
    "caddy-auth-test-1777559213",
    "landing-page-for-aiui-bot-6c96",
    "upload-c2f78c78",
    "upload-da5312a9",
    "e2e-4f3e4b",
    "foo-app",
    "alama-flight",
    "crudsimple",
    "diag-test",
    "test-crud",
    "test-project",
    "testfly",
]


@pytest.mark.parametrize("slug", REAL_USER_APPS)
def test_real_user_apps_are_not_ignored(slug):
    pattern = _ignored_by(slug)
    assert pattern is None, (
        f"apps/{slug}/ is a real user app but is ignored by {pattern!r}; "
        f"it will silently get no version history and nothing to export"
    )


@pytest.mark.parametrize("slug", PLAUSIBLE_USER_APPS)
def test_plausible_user_descriptions_are_not_ignored(slug):
    pattern = _ignored_by(slug)
    assert pattern is None, (
        f"apps/{slug}/ comes from an ordinary build description but is "
        f"ignored by {pattern!r}"
    )


@pytest.mark.parametrize("slug", HARNESS_JUNK)
def test_harness_junk_stays_ignored(slug):
    assert _ignored_by(slug) is not None, (
        f"apps/{slug}/ is test junk and should stay out of git"
    )


def test_reserved_test_prefix_is_ignored():
    """The collision-proof home for generated test apps."""
    assert _ignored_by("_test-browser-smoke-123") is not None
    assert _ignored_by("_test-anything-at-all") is not None


@pytest.mark.parametrize("seed", [
    "_test foo",
    "__test a thing",
    "_test-me a coffee shop",
    "   _test   ",
    "!!!_test",
])
def test_slugify_can_never_produce_the_reserved_prefix(seed):
    """Why apps/_test-*/ is safe to wildcard while apps/create-me-*/ was not:
    _slugify collapses every non-alphanumeric run to '-' and drops empty
    leading segments, so a user description cannot reach the _test- namespace."""
    assert not _slugify(seed).startswith("_")
