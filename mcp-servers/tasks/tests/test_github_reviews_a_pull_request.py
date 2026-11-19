"""GitHub can approve, request changes on, or comment on a pull request
(2026-11-19).

Lukas's example at stand-up was "every morning go to Google Sheet, and if
there is a PR on GitHub, approve it". The connection could list, read and
comment on a pull request, and open one, but not review it: "approve" had
no tool behind it, so the example could not run from the chat, a skill or
n8n.

GitHub's review endpoint takes one of three events. Two of them are
refused by GitHub without a body, and approving your OWN pull request is
refused with a 422 whose reason is in a list GitHub's `message` does not
carry ("Unprocessable Entity"), so it is worded here instead of left as
noise.
"""
import asyncio
import json
import os

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import agent_tools
import app_triage
import mytools

OWNER, REPO = "o", "r"
REVIEWS = "/repos/o/r/pulls/7/reviews"


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


@pytest.fixture
def github(monkeypatch):
    calls = []
    answers = {}

    async def secrets(email, provider):
        return {"token": "ghp_" + "0" * 36} if provider == "github" else {}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, headers=None, params=None,
                          json=None):
            calls.append({"method": method, "url": url, "json": json})
            for (m, tail), resp in answers.items():
                if m == method and url.endswith(tail):
                    return resp
            return _Resp(200, {})

    monkeypatch.setattr(mytools, "_secrets_for", secrets)
    monkeypatch.setattr(mytools.httpx, "AsyncClient", _Client)
    return calls, answers


def _tool():
    return {t.name: t for t in mytools.GITHUB_TOOLS}["review_pull_request"]


def _run(args):
    return asyncio.run(mytools._call("github", _tool(), "r@example.com", args))


def _posts(calls):
    return [c for c in calls if c["method"] == "POST"]


def test_review_pull_request_is_on_the_github_server():
    assert "review_pull_request" in {t.name for t in mytools.GITHUB_TOOLS}


def test_approving_posts_event_approve(github):
    calls, answers = github
    answers[("POST", REVIEWS)] = _Resp(200, {"id": 1, "state": "APPROVED"})
    out = _run({"owner": OWNER, "repo": REPO, "number": 7, "event": "approve"})
    assert out["ok"] is True
    sent = _posts(calls)[-1]
    assert sent["url"].endswith(REVIEWS)
    assert sent["json"]["event"] == "APPROVE"


def test_request_changes_without_a_body_is_refused_before_github(github):
    calls, _ = github
    out = _run({"owner": OWNER, "repo": REPO, "number": 7,
                "event": "REQUEST_CHANGES"})
    assert out["ok"] is False
    assert "say what" in out["error"].lower()
    assert not _posts(calls)


def test_a_comment_review_with_a_body_is_sent(github):
    calls, _ = github
    out = _run({"owner": OWNER, "repo": REPO, "number": 7,
                "event": "COMMENT", "body": "Looks fine"})
    assert out["ok"] is True
    assert _posts(calls)[-1]["json"] == {"event": "COMMENT",
                                         "body": "Looks fine"}


def test_an_unknown_event_is_refused(github):
    calls, _ = github
    out = _run({"owner": OWNER, "repo": REPO, "number": 7, "event": "MERGE"})
    assert out["ok"] is False
    assert "APPROVE" in out["error"]
    assert not _posts(calls)


def test_approving_your_own_pull_request_says_so_plainly(github):
    _, answers = github
    answers[("POST", REVIEWS)] = _Resp(422, {
        "message": "Unprocessable Entity",
        "errors": ["Can not approve your own pull request"]})
    out = _run({"owner": OWNER, "repo": REPO, "number": 7, "event": "APPROVE"})
    assert out["ok"] is False
    assert out["error"] == ("GitHub does not let you approve your own pull "
                            "request. Someone else has to review it.")


def test_review_is_a_write():
    assert mytools._writes(_tool()) is True
    assert agent_tools.is_write_tool("review_pull_request") is True


def test_triage_says_github_can_review_and_rests_on_the_tool():
    gh = app_triage.APPS["github"]
    assert "review_pull_request" in gh.tools
    assert "approve" in gh.can
