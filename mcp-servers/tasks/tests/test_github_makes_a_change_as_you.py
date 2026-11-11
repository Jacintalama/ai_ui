"""Per-user GitHub can branch and write a file (2026-11-11).

The deferred half of #179. That PR added the six declarative GitHub tools
and deliberately left these two out, with a test asserting their absence,
because both need a read BEFORE the call and that is a prepare step:

    create_branch   a new ref needs the sha the branch starts from
    write_file      an UPDATE needs the existing file's blob sha, and
                    GitHub takes the content base64 encoded

With these, the chain is complete and runs entirely as the person who
typed: create_branch, write_file, create_pull_request. That is what makes
switching the shared `github` server off a real option rather than a
capability cut.

Two things worth knowing about the shapes below, both from GitHub's own
REST v3 reference:

  - POST /git/refs takes `ref` as the FULL ref ("refs/heads/name"), not the
    branch name. Sending the bare name is a 422, and it is the mistake
    anybody writing this by hand makes once.
  - PUT /contents/{path} creates when `sha` is absent and updates when it
    is present. Sending a stale sha is a 409, and sending none for a file
    that exists is a 422. So the sha is read, never assumed, and a 404 on
    that read is the ordinary "this is a new file" case rather than an
    error.
"""
import asyncio
import base64
import json

import pytest

import github_refs as gr
import mytools

OWNER = "thunder500"
REPO = "ai_ui"
MAIN_SHA = "e45829a06b094836ef8c973a39a90a66228d1207"
FILE_SHA = "95b966ae1c166bd92f8ae7d1c0a73d0bd0f4f0bd"

REPO_ROW = {"name": REPO, "default_branch": "main", "private": False}
MAIN_REF = {"ref": "refs/heads/main", "object": {"sha": MAIN_SHA,
                                                 "type": "commit"}}
EXISTING = {"name": "README.md", "path": "README.md", "sha": FILE_SHA,
            "size": 12, "content": base64.b64encode(b"old text\n").decode(),
            "encoding": "base64"}


# --- the pure half ----------------------------------------------------------

def test_a_branch_name_becomes_a_full_ref():
    assert gr.full_ref("my-branch") == "refs/heads/my-branch"


def test_a_name_that_is_already_a_full_ref_is_left_alone():
    """A model that read GitHub's docs may send the full ref. Prefixing it
    twice is a 422 nobody would be able to read."""
    assert gr.full_ref("refs/heads/my-branch") == "refs/heads/my-branch"


def test_a_leading_slash_is_not_doubled():
    assert gr.full_ref("/my-branch") == "refs/heads/my-branch"


def test_content_is_base64_encoded():
    assert gr.encoded("hello\n") == base64.b64encode(b"hello\n").decode()


def test_unicode_content_survives_encoding():
    said = "café ✓"
    assert base64.b64decode(gr.encoded(said)).decode("utf-8") == said


def test_already_encoded_content_is_not_encoded_twice():
    """Double encoding produces a file full of base64 text, which looks
    like it worked and is wrong."""
    once = base64.b64encode(b"hello\n").decode()
    assert gr.encoded(once, already=True) == once


def test_the_sha_is_read_off_a_contents_answer():
    assert gr.sha_of(EXISTING) == FILE_SHA


def test_a_missing_file_has_no_sha():
    """`get` returns None on a 404, which is the ordinary new-file case."""
    assert gr.sha_of(None) is None


def test_a_folder_answer_has_no_sha():
    """GET /contents on a directory answers with a LIST, and taking a sha
    off that would send some other file's sha."""
    assert gr.sha_of([EXISTING]) is None


# --- the tools exist --------------------------------------------------------

def _tools():
    return {t.name: t for t in mytools.GITHUB_TOOLS}


def test_the_write_chain_is_now_complete():
    assert {"create_branch", "write_file", "create_pull_request"} <= set(_tools())


def test_github_now_has_a_prepare_step():
    """#179 asserted the opposite, correctly, because nothing needed one
    then. These two do, and the registration is what makes it run at all."""
    assert "github" in mytools.PREPARE


def test_write_file_is_named_to_match_read_file():
    assert "read_file" in _tools() and "write_file" in _tools()


def test_write_file_says_the_content_is_the_whole_file():
    """A model that thinks this appends will destroy a file it meant to
    add one line to."""
    said = _tools()["write_file"].summary.lower()
    assert "whole" in said or "replace" in said
    assert "append" not in said


def test_create_branch_does_not_ask_for_a_sha():
    """The sha is looked up. Asking the model for one would mean asking it
    to guess, which is how the shared tool's callers got 422s."""
    assert "sha" not in (_tools()["create_branch"].args or {})
    assert "ref" not in (_tools()["create_branch"].args or {})


# --- through the real call --------------------------------------------------

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
            calls.append({"method": method, "url": url, "json": json,
                          "params": params or {}})
            for (m, tail), resp in answers.items():
                if m == method and url.endswith(tail):
                    return resp
            return _Resp(200, {})

    monkeypatch.setattr(mytools, "_secrets_for", secrets)
    monkeypatch.setattr(mytools.httpx, "AsyncClient", _Client)
    base = "/repos/%s/%s" % (OWNER, REPO)
    answers[("GET", base)] = _Resp(200, REPO_ROW)
    answers[("GET", base + "/git/ref/heads/main")] = _Resp(200, MAIN_REF)
    answers[("POST", base + "/git/refs")] = _Resp(
        201, {"ref": "refs/heads/feat/x", "object": {"sha": MAIN_SHA}})
    answers[("PUT", base + "/contents/README.md")] = _Resp(
        200, {"content": {"path": "README.md", "sha": "new"},
              "commit": {"sha": "c1", "html_url": "https://x/commit/c1"}})
    return calls, answers


def _run(name, args):
    tool = {t.name: t for t in mytools.GITHUB_TOOLS}[name]
    return asyncio.run(mytools._call("github", tool, "r@example.com", args))


def test_creating_a_branch_sends_the_full_ref_and_the_looked_up_sha(github):
    calls, _ = github
    out = _run("create_branch", {"owner": OWNER, "repo": REPO,
                                 "branch": "feat/x", "base": "main"})
    assert out["ok"] is True
    sent = [c for c in calls if c["method"] == "POST"][-1]
    assert sent["url"].endswith("/repos/%s/%s/git/refs" % (OWNER, REPO))
    assert sent["json"]["ref"] == "refs/heads/feat/x"
    assert sent["json"]["sha"] == MAIN_SHA


def test_creating_a_branch_with_no_base_asks_the_repo_for_its_default(github):
    calls, _ = github
    out = _run("create_branch", {"owner": OWNER, "repo": REPO,
                                 "branch": "feat/x"})
    assert out["ok"] is True
    reads = [c["url"] for c in calls if c["method"] == "GET"]
    assert any(u.endswith("/repos/%s/%s" % (OWNER, REPO)) for u in reads)
    sent = [c for c in calls if c["method"] == "POST"][-1]
    assert sent["json"]["sha"] == MAIN_SHA


def test_no_branch_is_made_when_the_base_cannot_be_read(github):
    """Better no branch than a branch off a sha we guessed."""
    calls, answers = github
    answers[("GET", "/repos/%s/%s/git/ref/heads/nope" % (OWNER, REPO))] = \
        _Resp(404, {"message": "Not Found"})
    out = _run("create_branch", {"owner": OWNER, "repo": REPO,
                                 "branch": "feat/x", "base": "nope"})
    assert out["ok"] is False
    assert "nope" in out["error"]
    assert not [c for c in calls if c["method"] == "POST"]


def test_writing_a_new_file_sends_base64_and_no_sha(github):
    calls, answers = github
    answers[("GET", "/repos/%s/%s/contents/NEW.md" % (OWNER, REPO))] = \
        _Resp(404, {"message": "Not Found"})
    out = _run("write_file", {"owner": OWNER, "repo": REPO, "path": "NEW.md",
                              "content": "hello\n", "message": "add NEW.md",
                              "branch": "feat/x"})
    assert out["ok"] is True
    sent = [c for c in calls if c["method"] == "PUT"][-1]
    assert sent["json"]["content"] == base64.b64encode(b"hello\n").decode()
    assert sent["json"]["message"] == "add NEW.md"
    assert sent["json"]["branch"] == "feat/x"
    assert "sha" not in sent["json"]


def test_writing_over_an_existing_file_sends_its_sha(github):
    calls, answers = github
    answers[("GET", "/repos/%s/%s/contents/README.md" % (OWNER, REPO))] = \
        _Resp(200, EXISTING)
    out = _run("write_file", {"owner": OWNER, "repo": REPO,
                              "path": "README.md", "content": "new text\n",
                              "message": "update", "branch": "feat/x"})
    assert out["ok"] is True
    sent = [c for c in calls if c["method"] == "PUT"][-1]
    assert sent["json"]["sha"] == FILE_SHA


def test_the_existing_sha_is_read_from_the_branch_being_written_to(github):
    """Reading main's sha and writing it to a feature branch is a 409. The
    read has to carry the same ref as the write."""
    calls, answers = github
    answers[("GET", "/repos/%s/%s/contents/README.md" % (OWNER, REPO))] = \
        _Resp(200, EXISTING)
    _run("write_file", {"owner": OWNER, "repo": REPO, "path": "README.md",
                        "content": "x", "message": "m", "branch": "feat/x"})
    read = [c for c in calls if c["method"] == "GET"][-1]
    assert read["params"].get("ref") == "feat/x"


def test_a_folder_path_does_not_borrow_another_files_sha(github):
    calls, answers = github
    answers[("GET", "/repos/%s/%s/contents/docs" % (OWNER, REPO))] = \
        _Resp(200, [EXISTING])
    _run("write_file", {"owner": OWNER, "repo": REPO, "path": "docs",
                        "content": "x", "message": "m", "branch": "feat/x"})
    sent = [c for c in calls if c["method"] == "PUT"]
    assert sent and "sha" not in sent[-1]["json"]


def test_the_other_github_tools_are_not_slowed_down(github):
    """prepare now runs for every github call, so a tool that needs no
    lookup must still cost exactly one request."""
    calls, answers = github
    answers[("GET", "/repos/%s/%s/branches" % (OWNER, REPO))] = _Resp(200, [])
    _run("list_branches", {"owner": OWNER, "repo": REPO})
    assert [c["method"] for c in calls] == ["GET"]


def test_the_wording_reaches_the_served_api():
    from fastapi.testclient import TestClient
    app = mytools._sub_app("github", mytools.GITHUB_TOOLS)
    with TestClient(app) as c:
        spec = json.dumps(c.get("/openapi.json").json())
    assert "create_branch" in spec
    assert "write_file" in spec
