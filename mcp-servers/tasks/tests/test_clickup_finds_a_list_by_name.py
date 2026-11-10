"""One call turns "Project 1" into a list id.

Why this exists
---------------
Creating a ClickUp task needs a list id, and nothing in ClickUp's API
hands you one from a name. The only route was to climb: GET /team, then
/team/{id}/space, then /space/{id}/folder, then /folder/{id}/list. Four
calls, and every one of them is a separate round of the chat's tool loop,
which is why a ClickUp request ended in "Stopped after 7 rounds of tool
use" before any work happened.

Measured against the real connected account on 2026-11-10, which is what
the fake vendor below reproduces:

  - one workspace, "AIUI"
  - three spaces: "Space", "Team Space", "aiui tema"
  - NO folders in any of them
  - "Project 1" and "Project 2" are FOLDERLESS lists in "Team Space"

So the ladder was worse than slow, it was wrong: `get_folders` answers
with nothing for every space, and a model that then tries
`get_lists(folder_id=...)` has no folder to ask about. The lists are only
reachable through `/space/{id}/list`, a branch nothing told it to take.

The whole walk of that account is 8 HTTP calls inside one tool. HTTP
calls are not the cost. A round of the tool loop is.
"""
import json

import pytest
from fastapi.testclient import TestClient

import clickup_find
import mytools

#: The connected account as it really is (probed 2026-11-10). Names and
#: ids are Ralph's own test workspace.
WORKSPACE = {"id": "1301320000000306", "name": "AIUI"}
SPACES = [
    {"id": "1301320000002688", "name": "Space"},
    {"id": "1301320000002694", "name": "Team Space"},
    {"id": "1301320000002851", "name": "aiui tema"},
]
TEAM_SPACE_LISTS = [
    {"id": "1301320000003389", "name": "Project 2", "task_count": 0},
    {"id": "1301320000003388", "name": "Project 1", "task_count": 3},
    {"id": "1301320000003390", "name": "Get Started with ClickUp",
     "task_count": 7},
]


def _vendor(folders=None, folder_lists=None, fail=None):
    """A stand-in for ClickUp. Returns (routes, calls).

    `folders` maps a space id to its folders, `folder_lists` maps a
    folder id to its lists, `fail` maps a path fragment to a status code.
    """
    folders = folders or {}
    folder_lists = folder_lists or {}
    fail = fail or {}
    calls = []

    def route(path):
        calls.append(path)
        for fragment, status in fail.items():
            if fragment in path:
                return status, {"err": "nope"}
        if path == "/team":
            return 200, {"teams": [dict(WORKSPACE, members=[])]}
        if path.endswith("/space"):
            return 200, {"spaces": SPACES}
        if path.endswith("/folder"):
            space_id = path.split("/")[2]
            return 200, {"folders": folders.get(space_id, [])}
        if path.startswith("/folder/") and path.endswith("/list"):
            return 200, {"lists": folder_lists.get(path.split("/")[2], [])}
        if path.startswith("/space/") and path.endswith("/list"):
            space_id = path.split("/")[2]
            if space_id == "1301320000002694":
                return 200, {"lists": TEAM_SPACE_LISTS}
            if space_id == "1301320000002851":
                return 200, {"lists": [{"id": "1301320000003630",
                                        "name": "List", "task_count": 0}]}
            return 200, {"lists": []}
        return 404, {}

    return route, calls


@pytest.fixture
def clickup(monkeypatch):
    """The tool app with a connected ClickUp account and a faked vendor.

    Returns a function: post(body, **vendor_kwargs) -> (result, calls).
    """
    async def _fake_secrets(email, provider):
        return {"token": "pk_SECRET_TOKEN_VALUE"} if provider == "clickup" \
            else {}

    monkeypatch.setattr(mytools, "_secrets_for", _fake_secrets)
    state = {"route": None, "calls": None}

    class _Resp:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload
            self.text = json.dumps(payload)

        def json(self):
            return self._payload

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, headers=None, params=None,
                          json=None):
            path = url.split("/api/v2", 1)[-1]
            status, payload = state["route"](path)
            return _Resp(status, payload)

    monkeypatch.setattr(mytools.httpx, "AsyncClient", _FakeClient)
    app = mytools.build_app()

    def post(body, **vendor_kwargs):
        route, calls = _vendor(**vendor_kwargs)
        state["route"], state["calls"] = route, calls
        with TestClient(app) as c:
            r = c.post("/clickup/find_list", json=body,
                       headers={"X-User-Email": "ralphbenitez32@gmail.com"})
        assert r.status_code == 200, r.text
        return r.json(), calls

    post.app = app
    return post


# --- the whole point: one round -----------------------------------------

def test_one_call_turns_project_1_into_a_list_id(clickup):
    result, _ = clickup({"name": "Project 1"})
    assert result["ok"] is True
    assert result["count"] == 1
    assert result["items"][0]["list_id"] == "1301320000003388"


def test_the_id_is_called_list_id_because_that_is_what_create_task_wants(clickup):
    """create_task's required argument is `list_id`. Naming the field
    anything else makes the model translate, and a model that translates
    an id sometimes translates it wrong."""
    assert "list_id" in mytools.CLICKUP_TOOLS_BY_NAME["create_task"].args
    result, _ = clickup({"name": "Project 1"})
    assert "list_id" in result["items"][0]


def test_a_folderless_list_is_found_at_all(clickup):
    """The ladder could not reach these: no folder exists to ask about.
    This is the actual shape of the connected account."""
    result, calls = clickup({"name": "Project 2"})
    assert [i["list_id"] for i in result["items"]] == ["1301320000003389"]
    assert any(c == "/space/1301320000002694/list" for c in calls)


def test_the_answer_says_where_the_list_lives(clickup):
    """Two spaces can hold a list of the same name, so an id on its own
    does not let anybody confirm the right one was picked."""
    item = clickup({"name": "Project 1"})[0]["items"][0]
    assert item["space"] == "Team Space"
    assert item["folder"] is None
    assert item["path"] == "AIUI > Team Space > Project 1"


# --- matching ------------------------------------------------------------

def test_an_exact_match_does_not_drag_in_longer_names(clickup):
    """"Project 1" is a prefix of "Project 10". Returning both would put
    the choice back on the model for a name that was exactly right."""
    result, _ = clickup({"name": "Project 1"}, folders={
        "1301320000002688": [{"id": "F1", "name": "Folder",
                              "lists": [{"id": "L10", "name": "Project 10"}]}]})
    assert [i["list_id"] for i in result["items"]] == ["1301320000003388"]


def test_a_partial_name_returns_the_candidates(clickup):
    result, _ = clickup({"name": "project"})
    assert sorted(i["name"] for i in result["items"]) == ["Project 1",
                                                          "Project 2"]


@pytest.mark.parametrize("asked", ["project 1", "PROJECT 1", "  Project  1 ",
                                   "Project\t1"])
def test_case_and_spacing_are_not_how_a_person_types_a_name(clickup, asked):
    result, _ = clickup({"name": asked})
    assert [i["list_id"] for i in result["items"]] == ["1301320000003388"]


def test_nothing_matching_says_what_is_actually_there(clickup):
    """A bare "not found" costs another round and usually a wrong guess.
    The names were already fetched, so they go back with the answer."""
    result, _ = clickup({"name": "Marketing"})
    assert result["count"] == 0
    assert result["items"] == []
    assert "Project 1" in result["available"]
    assert "Get Started with ClickUp" in result["available"]


def test_a_folder_name_answers_with_the_lists_inside_it(clickup):
    """You cannot put a task in a folder. Somebody who says "in
    Marketing", where Marketing is a folder, means a list in it."""
    result, _ = clickup({"name": "Marketing"}, folders={
        "1301320000002688": [{"id": "F1", "name": "Marketing", "lists": [
            {"id": "L1", "name": "Campaigns"},
            {"id": "L2", "name": "Content"}]}]})
    assert sorted(i["name"] for i in result["items"]) == ["Campaigns",
                                                          "Content"]
    assert all(i["matched_via"] == "folder" for i in result["items"])
    assert all(i["folder"] == "Marketing" for i in result["items"])


def test_a_list_wins_over_a_folder_of_the_same_name(clickup):
    result, _ = clickup({"name": "Project 1"}, folders={
        "1301320000002688": [{"id": "F1", "name": "Project 1", "lists": [
            {"id": "L1", "name": "Something else"}]}]})
    assert [i["list_id"] for i in result["items"]] == ["1301320000003388"]
    assert result["items"][0]["matched_via"] == "list"


def test_a_space_name_answers_with_the_lists_in_that_space(clickup):
    result, _ = clickup({"name": "Team Space"})
    assert sorted(i["name"] for i in result["items"]) == [
        "Get Started with ClickUp", "Project 1", "Project 2"]
    assert all(i["matched_via"] == "space" for i in result["items"])


# --- the walk itself -----------------------------------------------------

def test_lists_a_folder_already_carries_are_not_fetched_again(clickup):
    """ClickUp's Get Folders embeds each folder's lists. Asking for them
    again is a call per folder for rows already in hand."""
    _, calls = clickup({"name": "Campaigns"}, folders={
        "1301320000002688": [{"id": "F1", "name": "Marketing", "lists": [
            {"id": "L1", "name": "Campaigns"}]}]})
    assert "/folder/F1/list" not in calls


def test_a_folder_that_carries_no_lists_is_asked(clickup):
    """Not every ClickUp response embeds them, and a folder reported with
    no lists at all would otherwise be a space nobody can reach."""
    result, calls = clickup({"name": "Campaigns"},
                            folders={"1301320000002688": [
                                {"id": "F1", "name": "Marketing"}]},
                            folder_lists={"F1": [{"id": "L1",
                                                  "name": "Campaigns"}]})
    assert "/folder/F1/list" in calls
    assert [i["list_id"] for i in result["items"]] == ["L1"]


def test_the_walk_of_the_real_account_is_eight_calls(clickup):
    """One for the workspace, one for its spaces, two per space. The
    number is here so a change that multiplies it is visible."""
    _, calls = clickup({"name": "Project 1"})
    assert len(calls) == 8, calls


def test_one_workspace_can_be_named_to_narrow_the_walk(clickup):
    _, calls = clickup({"name": "Project 1",
                        "workspace_id": "1301320000000306"})
    assert "/team" not in calls
    assert calls[0] == "/team/1301320000000306/space"


def test_the_walk_is_bounded(clickup):
    """A workspace with hundreds of spaces must not become hundreds of
    requests against somebody's rate limit."""
    many = [{"id": "S%d" % i, "name": "Space %d" % i} for i in range(200)]
    route, calls = _vendor()

    def wide(path):
        if path.endswith("/space") and path.startswith("/team/"):
            calls.append(path)
            return 200, {"spaces": many}
        return route(path)

    async def get(path, params=None):
        status, payload = wide(path)
        return payload

    result = __import__("asyncio").run(
        clickup_find.find_list(get, {"name": "Project 1"}))
    assert len(calls) <= clickup_find.MAX_CALLS, len(calls)
    assert result["truncated"] is True


# --- failure -------------------------------------------------------------

def test_a_rejected_credential_says_to_reconnect(clickup):
    result, _ = clickup({"name": "Project 1"}, fail={"/team": 401})
    assert result["ok"] is False
    assert "Reconnect it from Connections" in result["error"]


def test_one_unreachable_space_does_not_lose_the_others(clickup):
    """A private space somebody cannot read answers 401 for that space
    alone. Failing the whole search would make the tool useless on any
    workspace with one locked space in it."""
    result, _ = clickup({"name": "Project 1"},
                        fail={"/space/1301320000002688": 403})
    assert result["ok"] is True
    assert [i["list_id"] for i in result["items"]] == ["1301320000003388"]


def test_a_blank_name_is_a_sentence_and_costs_no_calls(clickup):
    """A name left out entirely never reaches this code: `name` is a
    required field, so FastAPI answers 422 first, the same as it does for
    create_task's list_id and every other required argument on the
    surface. A name of spaces is the case that does reach it, and
    walking the whole tree to match nothing would return every list in
    the account as a suggestion."""
    result, calls = clickup({"name": "   "})
    assert result["ok"] is False
    assert "Project 1" in result["error"]
    assert calls == []


def test_a_name_left_out_is_refused_before_any_work(clickup):
    with TestClient(clickup.app) as c:
        r = c.post("/clickup/find_list", json={},
                   headers={"X-User-Email": "ralphbenitez32@gmail.com"})
    assert r.status_code == 422


def test_the_credential_is_never_in_the_answer(clickup):
    """Tool results go straight into a chat. ClickUp echoes the request
    on some errors, which is how a token gets rendered to a person."""
    for body, kwargs in (({"name": "Project 1"}, {}),
                         ({"name": "Project 1"}, {"fail": {"/team": 400}}),
                         ({"name": "nothing"}, {})):
        result, _ = clickup(body, **kwargs)
        assert "pk_SECRET_TOKEN_VALUE" not in json.dumps(result)


# --- matching, with no vendor at all ------------------------------------

@pytest.mark.parametrize("asked,name,tier", [
    ("Project 1", "Project 1", clickup_find.EXACT),
    ("project 1", "PROJECT 1", clickup_find.EXACT),
    ("Project", "Project 1", clickup_find.PREFIX),
    ("1", "Project 1", clickup_find.CONTAINS),
    ("started clickup", "Get Started with ClickUp", clickup_find.WORDS),
    ("Project 1", "Project 10", clickup_find.PREFIX),
    ("Marketing", "Project 1", None),
    ("", "Project 1", None),
])
def test_how_close_a_name_is(asked, name, tier):
    assert clickup_find.tier(asked, name) == tier


def test_the_best_tier_wins_and_the_rest_are_dropped():
    """Mixing tiers is what returns "Project 10" alongside an exact
    "Project 1"."""
    rows = [{"name": "Project 10", "tier": clickup_find.PREFIX},
            {"name": "Project 1", "tier": clickup_find.EXACT}]
    assert [r["name"] for r in clickup_find.best(rows)] == ["Project 1"]


# --- the model has to be able to find the tool --------------------------

def test_the_tool_is_on_the_clickup_surface(clickup):
    assert "find_list" in mytools.CLICKUP_TOOLS_BY_NAME


def test_looking_something_up_never_stops_to_ask(clickup):
    """A lookup that waits for a click is worse than the four calls it
    replaces: the person has to approve a step that changes nothing
    before the work can even be proposed. It reads as a read because
    both of its words are read verbs, and this pins that, because the
    classifier judges the NAME and a rename would move it silently.

    The third assertion is the one the agent loop actually evaluates
    (agent_runner: `is_write_call(name, probe) and not write_allowed`),
    so it is also what lets an agent on read_only look a list up. A
    level is a ceiling, and "which list is Project 1" is a question."""
    import agent_tools
    assert agent_tools.is_write_tool("find_list") is False
    assert agent_tools.is_write_tool("my-clickup_find_list") is False
    assert agent_tools.is_write_call(
        "call_tool", {"tool_name": "my-clickup_find_list"}) is False


def test_the_summary_says_the_words_somebody_would_search(clickup):
    """search_tools matches on this text. The generated catalogue has 172
    ClickUp tools, so a summary that does not say "list" and "name" and
    "id" loses to get_lists, which is the call this replaces."""
    summary = mytools.CLICKUP_TOOLS_BY_NAME["find_list"].summary.lower()
    for word in ("list", "name", "id", "folder", "space", "create a task"):
        assert word in summary, word
