"""Creating a project must never look like it worked when the build never ran.

`projects.html` calls POST /api/tasks/{id}/execute the instant a project is
created, then redirects to the live-build view. That call used to be wrapped in
a bare try/catch whose comment said failure was "non-fatal — the task sits as
pending and an admin can approve via the task panel". Two things were wrong:

  * for a regular user there is no admin watching, so the real outcome was a
    project card whose build never started and never said why. While /execute
    demanded the admin header, that was EVERY non-admin project.
  * `fetch()` only rejects on a network error. A 403 resolves normally, so the
    catch could not have caught the case it was written for even in principle.

This is the same failure class as the git-commit bug in CLAUDE.md: announce the
action, never check the outcome. These assertions are on the page source
because the file is browser JS driven by a live API — the browser suite in
tests/browser/ covers rendering, not this network path. Stated plainly rather
than dressed up as more than it is.
"""
import pathlib
import re

HTML = (pathlib.Path(__file__).resolve().parents[1]
        / "static" / "projects.html").read_text(encoding="utf-8")

# The block that fires the build, from the fetch to the redirect.
_KICKOFF = re.search(
    r"/execute`.{0,2000}?window\.location\.href", HTML, re.S)


def test_the_kickoff_block_still_exists():
    """Guards every assertion below against a refactor silently emptying them."""
    assert _KICKOFF, "could not find the /execute call and its redirect"


def test_the_response_status_is_actually_checked():
    """The whole bug: a 403 from /execute resolved normally and the page
    redirected as if the build had started."""
    assert re.search(r"\bex\.ok\b|\bresp?\.ok\b|status\s*[<>=]", _KICKOFF.group(0)), (
        "the /execute response is never inspected, so a refusal is "
        "indistinguishable from a started build")


def test_a_failed_kickoff_is_shown_to_the_user():
    """console.warn is not telling the user anything."""
    block = _KICKOFF.group(0)
    assert "showToast" in block, (
        "a failed build start is only logged to the console; the user is told "
        "nothing and waits forever on a task that never runs")


def test_the_message_does_not_claim_the_build_started():
    block = _KICKOFF.group(0)
    lowered = block.lower()
    assert "did not start" in lowered or "didn't start" in lowered, (
        "the failure message must say the build did not start")


def test_the_stale_admin_assumption_is_gone():
    """The old comment told the reader an admin would notice. Nobody does."""
    assert "an admin can approve via the task panel" not in HTML
