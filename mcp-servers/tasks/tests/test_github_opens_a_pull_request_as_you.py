"""Per-user GitHub can open a pull request and search (2026-11-11).

Second half of the connector boundary work. Four admins act as the
`Jacintalama` account whenever a `github_*` tool is picked, and the reason
is not the access code, which is correct, but that `my-github` cannot do
the work, so the shared server is the only way.

Counted off `mcp_proxy.tool_embeddings` on 2026-11-11: `my-github` has 13
tools, shared `github` has 32. The 19 difference is NOT 19 missing
capabilities, which is worth writing down because the first count said it
was. Seven of them are the same thing under another name:

    add_issue_comment  -> comment_on_issue        already here
    get_file_contents  -> read_file               already here
    get_me             -> whoami                  already here
    list_issues        -> list_repo_issues        already here
    list_pull_requests -> list_repo_pull_requests already here
    pull_request_read  -> read_pull_request       already here
    issue_read         -> list_repo_issues        already here

and four more are niche (get_tag, get_label, list_issue_types, ui_get).

What is genuinely missing is opening a pull request, seeing branches and
commits, and search. This adds those six. `create_branch` and `push_files`
are deliberately NOT here: both need a commit sha looked up before the
call, which is a prepare step and new machinery, so they get their own PR
rather than being smuggled into this one.

Everything below is declarative against GitHub's own REST v3 shapes, so
there is no lookup step and nothing to resolve: GitHub takes an owner, a
repository and a branch as plain strings.
"""
import asyncio
import json

import pytest

import mytools

OWNER = "thunder500"
REPO = "ai_ui"

# GET /repos/{o}/{r}/branches
BRANCHES = [
    {"name": "main", "commit": {"sha": "e45829a06b094836ef8c973a39a90a66228d1207",
                                "url": "https://api.github.com/x"},
     "protected": True},
    {"name": "feat/trello-assigns-as-you",
     "commit": {"sha": "570151584aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "url": "https://api.github.com/y"}, "protected": False},
]

# GET /repos/{o}/{r}/commits
COMMITS = [
    {"sha": "e45829a06b094836ef8c973a39a90a66228d1207",
     "commit": {"message": "Merge PR #177: assign in the create",
                "author": {"name": "Ralph Benitez",
                           "date": "2026-11-10T22:39:00Z"}},
     "html_url": "https://github.com/x/y/commit/e45829a"},
]

# POST /repos/{o}/{r}/pulls
NEW_PR = {"number": 178, "title": "Trello assigns as you", "state": "open",
          "html_url": "https://github.com/Jacintalama/ai_ui/pull/178",
          "head": {"ref": "feat/trello-assigns-as-you"},
          "base": {"ref": "main"}}

# GET /search/repositories, and every other search: an envelope, not a list.
SEARCH_REPOS = {"total_count": 1, "incomplete_results": False,
                "items": [{"full_name": "Jacintalama/ai_ui", "private": False,
                           "html_url": "https://github.com/Jacintalama/ai_ui",
                           "description": "IO Platform",
                           "updated_at": "2026-11-10T22:39:00Z"}]}

SEARCH_CODE = {"total_count": 1, "incomplete_results": False,
               "items": [{"name": "mytools.py", "path": "mcp-servers/tasks/mytools.py",
                          "html_url": "https://github.com/x/y/blob/main/mytools.py",
                          "repository": {"full_name": "Jacintalama/ai_ui"}}]}

SEARCH_ISSUES = {"total_count": 1, "incomplete_results": False,
                 "items": [{"number": 139, "title": "Shared ClickUp connector",
                            "state": "closed",
                            "html_url": "https://github.com/x/y/issues/139"}]}


def _tools():
    return {t.name: t for t in mytools.GITHUB_TOOLS}


# --- the six exist ----------------------------------------------------------

def test_the_six_missing_tools_are_now_on_the_per_user_server():
    assert {"create_pull_request", "list_branches", "list_commits",
            "search_repositories", "search_code",
            "search_issues"} <= set(_tools())


def test_the_thirteen_that_already_worked_are_untouched():
    assert {"list_my_repos", "list_my_issues", "list_repo_issues",
            "create_issue", "read_file", "list_folder", "read_pull_request",
            "read_pull_request_changes", "list_my_pull_requests",
            "list_repo_pull_requests", "comment_on_issue",
            "comment_on_pull_request", "whoami"} <= set(_tools())


def test_the_two_that_need_a_sha_lookup_are_not_smuggled_in():
    """create_branch and push_files need a commit sha read first, which is
    a prepare step. They get their own PR; this one stays declarative."""
    assert "create_branch" not in _tools()
    assert "push_files" not in _tools()


def test_github_still_needs_no_prepare_step():
    """Nothing here resolves anything, so adding a prepare for github would
    be machinery with no job, and would cost a read on every github call."""
    assert "github" not in mytools.PREPARE


# --- what the model is told -------------------------------------------------

def test_create_pull_request_says_which_branch_goes_where():
    """head and base are the two every model gets backwards."""
    args = _tools()["create_pull_request"].args
    assert "head" in args and "base" in args
    said = (args["head"][1] + " " + args["base"][1]).lower()
    assert "from" in said or "merge" in said
    assert "into" in said or "onto" in said


def test_create_pull_request_is_not_described_as_merging():
    """Opening a PR does not merge it, and a model that thinks it does will
    reach for this when somebody says "merge my branch"."""
    said = _tools()["create_pull_request"].summary.lower()
    assert "open" in said
    assert "merges" not in said


def test_each_search_tool_says_it_takes_github_search_syntax():
    for name in ("search_repositories", "search_code", "search_issues"):
        said = _tools()[name].args["query"][1].lower()
        assert "repo:" in said or "qualifier" in said or "syntax" in said, name


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
    answers[("GET", "/repos/%s/%s/branches" % (OWNER, REPO))] = _Resp(200, BRANCHES)
    answers[("GET", "/repos/%s/%s/commits" % (OWNER, REPO))] = _Resp(200, COMMITS)
    answers[("POST", "/repos/%s/%s/pulls" % (OWNER, REPO))] = _Resp(201, NEW_PR)
    answers[("GET", "/search/repositories")] = _Resp(200, SEARCH_REPOS)
    answers[("GET", "/search/code")] = _Resp(200, SEARCH_CODE)
    answers[("GET", "/search/issues")] = _Resp(200, SEARCH_ISSUES)
    return calls, answers


def _run(name, args):
    tool = {t.name: t for t in mytools.GITHUB_TOOLS}[name]
    return asyncio.run(mytools._call("github", tool, "r@example.com", args))


def test_opening_a_pull_request_sends_head_and_base_in_the_body(github):
    calls, _ = github
    out = _run("create_pull_request",
               {"owner": OWNER, "repo": REPO, "title": "Trello assigns as you",
                "head": "feat/trello-assigns-as-you", "base": "main",
                "body": "why"})
    assert out["ok"] is True
    sent = [c for c in calls if c["method"] == "POST"][-1]
    assert sent["url"].endswith("/repos/%s/%s/pulls" % (OWNER, REPO))
    assert sent["json"]["head"] == "feat/trello-assigns-as-you"
    assert sent["json"]["base"] == "main"
    assert sent["json"]["title"] == "Trello assigns as you"


def test_the_pull_request_number_and_url_come_back(github):
    out = _run("create_pull_request",
               {"owner": OWNER, "repo": REPO, "title": "t", "head": "h",
                "base": "main"})
    said = json.dumps(out)
    assert "178" in said
    assert "pull/178" in said


def test_a_pull_request_with_no_base_is_refused_before_github_sees_it(github):
    """base is required: a PR opened against the wrong branch is worse than
    one not opened.

    Asserted at the SERVED boundary, because that is where the guarantee
    actually lives. `_model_for` marks a required argument with
    `Field(...)` and pydantic refuses the request before the route body
    runs; `_call` itself does not check, for any tool of any provider. A
    test driving `_call` directly would therefore be asserting a promise
    nothing makes.
    """
    from fastapi.testclient import TestClient
    calls, _ = github
    app = mytools._sub_app("github", mytools.GITHUB_TOOLS)
    with TestClient(app) as c:
        r = c.post("/create_pull_request",
                   headers={"X-User-Email": "r@example.com"},
                   json={"owner": OWNER, "repo": REPO, "title": "t",
                         "head": "h"})
    assert r.status_code == 422, r.text
    assert "base" in r.text
    assert not [x for x in calls if x["method"] == "POST"]


def test_listing_branches_keeps_the_name_and_sha(github):
    out = _run("list_branches", {"owner": OWNER, "repo": REPO})
    assert out["ok"] is True
    said = json.dumps(out)
    assert "feat/trello-assigns-as-you" in said
    assert "e45829a06b094836ef8c973a39a90a66228d1207" in said


def test_listing_commits_keeps_the_message(github):
    out = _run("list_commits", {"owner": OWNER, "repo": REPO})
    assert out["ok"] is True
    assert "assign in the create" in json.dumps(out)


def test_listing_commits_can_be_asked_for_one_branch(github):
    calls, _ = github
    _run("list_commits", {"owner": OWNER, "repo": REPO, "branch": "main"})
    sent = [c for c in calls if c["method"] == "GET"][-1]
    assert sent["params"].get("sha") == "main"


def test_searching_repositories_unwraps_the_envelope(github):
    """Every GitHub search answers {"total_count":..,"items":[..]}, so a
    tool that does not unwrap hands the model a count and no results."""
    out = _run("search_repositories", {"query": "ai_ui user:Jacintalama"})
    assert out["ok"] is True
    got = out.get("items")
    assert isinstance(got, list), got
    assert got and got[0].get("full_name") == "Jacintalama/ai_ui"


def test_searching_repositories_sends_the_query_as_q(github):
    calls, _ = github
    _run("search_repositories", {"query": "ai_ui user:Jacintalama"})
    sent = [c for c in calls if c["method"] == "GET"][-1]
    assert sent["params"]["q"] == "ai_ui user:Jacintalama"


def test_searching_code_unwraps_and_keeps_the_path(github):
    out = _run("search_code", {"query": "resolve_person repo:Jacintalama/ai_ui"})
    assert out["ok"] is True
    got = out.get("items")
    assert isinstance(got, list) and got
    assert got[0].get("path") == "mcp-servers/tasks/mytools.py"


def test_searching_issues_unwraps_and_keeps_the_number(github):
    out = _run("search_issues", {"query": "connector repo:Jacintalama/ai_ui"})
    assert out["ok"] is True
    got = out.get("items")
    assert isinstance(got, list) and got
    assert got[0].get("number") == 139


def test_a_search_with_no_query_is_refused_before_github_sees_it(github):
    """Same reasoning as the pull request above: the served boundary is
    where a required argument is enforced."""
    from fastapi.testclient import TestClient
    calls, _ = github
    app = mytools._sub_app("github", mytools.GITHUB_TOOLS)
    with TestClient(app) as c:
        r = c.post("/search_code", json={},
                   headers={"X-User-Email": "r@example.com"})
    assert r.status_code == 422, r.text
    assert "query" in r.text
    assert not calls


# --- the wiring -------------------------------------------------------------

def test_the_wording_reaches_the_served_api():
    """#174: a description that never leaves the service teaches nobody."""
    from fastapi.testclient import TestClient
    app = mytools._sub_app("github", mytools.GITHUB_TOOLS)
    with TestClient(app) as c:
        spec = json.dumps(c.get("/openapi.json").json())
    for name in ("create_pull_request", "list_branches", "list_commits",
                 "search_repositories", "search_code", "search_issues"):
        assert name in spec, name
