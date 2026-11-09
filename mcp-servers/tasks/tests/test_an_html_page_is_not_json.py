"""An HTML page answered with 200 is not JSON, and must not read as success.

2026-11-09. Ralph's chat showed a red toast saying:

    Unexpected token '<', "<!DOCTYPE "... is not valid JSON

Nobody traced it and it is in no log. Measured against production instead
of reasoned about:

    /api/v1/nonexistent   200 text/html   <!doctype html><html lang="en">...
    /api/v1/auths/        401 application/json
    /tasks/api/nonexistent 404 application/json

A wrong or MOVED path under /api/ is answered with Open WebUI's index.html
and HTTP 200. So `if (!r.ok)` passes, `r.json()` then throws V8's parse
message, and that string is what reaches the screen. Our own routes are
correct; the exposure is our client code calling Open WebUI's API, which
an upgrade can rename under us. Then the page says "Unexpected token '<'"
and nothing says which call broke or why.

`r.ok` cannot catch this, which is why every guard in the codebase missed
it: the request succeeded, by HTTP's reckoning. Only the content type
tells the truth.

These tests RUN util.js in node against stubbed responses rather than
grepping its source. Four times last week a test asserted a fix was
present in a file while the behaviour was absent, so a test that reads
source text is not enough for this one. The fake json() does a real
JSON.parse, so the unfixed code produces the genuine V8 error here, and
the test fails for the true reason.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

HERE = pathlib.Path(__file__).resolve().parent
RUNNER = HERE / "js" / "read_json_cases.mjs"
UTIL = HERE.parent / "static" / "office" / "js" / "util.js"

NODE = shutil.which("node")


@pytest.fixture(scope="module")
def ran():
    if not NODE:
        pytest.skip("node is not on PATH")
    assert RUNNER.is_file(), RUNNER
    assert UTIL.is_file(), UTIL
    proc = subprocess.run(
        [NODE, str(RUNNER), UTIL.resolve().as_uri()],
        capture_output=True, text=True, timeout=90)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


def test_the_runner_and_the_file_are_where_this_thinks(ran):
    assert set(ran) == {"json_200", "html_200", "html_200_no_type", "json_404"}


def test_real_json_still_comes_back(ran):
    """The guard must not break the ordinary case, which is every read the
    office does."""
    assert ran["json_200"] == {"threw": False, "value": {"a": 1}}


def test_an_html_page_with_200_is_an_error(ran):
    """The find. Before this it was returned as if it had worked, and the
    caller then threw a parse error from somewhere else entirely."""
    assert ran["html_200"]["threw"] is True


def test_the_message_says_what_arrived_not_what_failed_to_parse(ran):
    """The point of the whole change. "Unexpected token '<'" tells the
    person nothing and tells me nothing; the content type and the URL tell
    us the route moved."""
    msg = ran["html_200"]["message"]
    assert "Unexpected token" not in msg, (
        "still reporting V8's parse error instead of what arrived: " + msg)
    assert "/api/v1/auths/" in msg, msg
    assert "html" in msg.lower(), msg


def test_a_missing_content_type_does_not_crash_the_guard(ran):
    """headers.get can answer null. A guard that throws its own TypeError
    here would be worse than the bug."""
    r = ran["html_200_no_type"]
    assert r["threw"] is True
    assert "TypeError" not in r["message"], r["message"]
    assert "Cannot read" not in r["message"], r["message"]


def test_a_real_http_error_still_reports_its_status(ran):
    """Existing behaviour, kept: a 404 named its status and that is the
    useful thing about it."""
    r = ran["json_404"]
    assert r["threw"] is True
    assert "404" in r["message"], r["message"]


# --- the sites that do not go through getJson ---------------------------

DIRECT = [
    ("static/task-panel.js", "/api/v1/auths/"),
    ("static/office/js/office.js", "/api/v1/models"),
    ("static/agent-chat.js", "/api/v1/models/list"),
]


@pytest.mark.parametrize("rel,_url", DIRECT)
def test_a_direct_json_read_checks_the_content_type_too(rel, _url):
    """getJson covers most of the office, but these three call Open WebUI's
    API directly and would each show the raw parse error. task-panel.js and
    agent-chat.js are not modules and cannot import util.js, so they carry
    their own copy of the check; that duplication is deliberate and small,
    and this test is what keeps the copies honest."""
    src = (HERE.parent / rel).read_text(encoding="utf-8").lower()
    # Not just "content-type": every one of these SETS that header on the
    # request, so searching for the bare word passes without any check at
    # all. agent-chat.js did exactly that on the first run of this test.
    # What matters is the RESPONSE being checked, either by reading the
    # header here or by handing the response to expectJson, which is what a
    # file that can import util.js should do.
    checked = ('headers.get("content-type")' in src) or ("expectjson(" in src)
    assert checked, (
        rel + " parses JSON without checking the response content type, so "
        "an HTML page with 200 reads as success")
