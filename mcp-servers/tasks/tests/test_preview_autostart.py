"""A build that failed is not asked to run.

Ralph, 2026-09-18: his build was refused by the model provider, and the page
that told him so ALSO showed "Preview couldn't auto-start: 404 {"detail":
"Cannot determine how to run apps/thunder-2b68/ ..."}". Both statements were
true and the second was noise: a build that died before writing a file has
nothing to serve.

Read from the file, the way the other static-page tests here work: the
behaviour lives in one page and asserting on its source is cheaper and more
honest than driving a browser to prove a guard exists.
"""
import pathlib
import re

PAGE = (pathlib.Path(__file__).resolve().parents[1]
        / "static" / "preview.html")


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _init_body(page: str) -> str:
    """Everything from init()'s opening to its auto-start call."""
    start = page.index("async function init()")
    end = page.index("maybeAutoStartPreview();", start)
    return page[start:end + len("maybeAutoStartPreview();")]


def test_a_failed_build_does_not_auto_start_a_preview():
    body = _init_body(_page())
    assert 'initialTask.status !== "failed"' in body, (
        "init still auto-starts a preview for a build that wrote no files")


def test_the_status_it_guards_on_is_the_one_it_actually_fetched():
    """The guard is worthless if it reads a variable nobody assigned. init
    fetches the task to decide whether the build overlay owns the page; this
    is the same object, kept rather than thrown away."""
    body = _init_body(_page())
    assert "initialTask = await apiFetch" in body
    assert "let initialTask = null;" in body


def test_a_build_still_in_flight_is_left_to_the_overlay():
    """The early return that was already there. A pending or running build
    must not reach the auto-start at all, because the overlay owns the page
    and the files do not exist yet either."""
    body = _init_body(_page())
    assert "BUILDING_STATES.has(initialTask.status)" in body
    assert "return;" in body


def test_a_task_that_could_not_be_read_still_starts_normally():
    """The fetch is in a try for a reason: the page has to work when that one
    call fails. Unknown is not failed, so the preview is still attempted."""
    body = _init_body(_page())
    assert "!initialTask ||" in body, (
        "an unreadable task must not be treated as a failed build")


def test_run_is_still_offered_by_hand():
    """Not auto-starting is not the same as taking the button away. Somebody
    who wants to try it on a failed build can still press Run."""
    page = _page()
    assert re.search(r'id="btn-run"', page), "the Run control is gone"
