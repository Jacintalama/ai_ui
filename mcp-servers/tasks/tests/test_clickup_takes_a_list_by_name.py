"""A ClickUp call takes the list NAME, because that is what gets asked.

Measured on the box, 2026-11-10, right after find_list went live. It is
indexed, it works, and tool search ranks it FIRST for "which ClickUp
list is Project 1" (0.7518) and for "what is the list id for Project 1"
(0.7307).

For the request that actually gets typed it is nowhere:

    "create a ClickUp task called Buy milk 3 in Project 1 and
     assign it to ralph"
      1. my-clickup_create_task              0.7623
      2. my-clickup_add_task_to_list         0.7314
      3. my-clickup_add_tag_to_task          0.7285
      ... find_list NOT IN TOP 8

    "create a task in Project 1"
      1. my-clickup_create_task              0.7841
      ... find_list NOT IN TOP 8

Of course: the search text is the person's own words, and their words are
"create a task". So the model finds create_task, which needs an id it has
not got, and it is back to climbing the tree or guessing. A tool nobody
reaches is not a feature.

So the lookup moves to where the model already lands. create_task takes
"Project 1" and the prepare step resolves it, the same way it already
resolves a person by name and a column as said. find_list stays, because
"which list is Project 1" is a real question and it answers that one
first.

Rewording the summary to chase the embedding was the other option. It was
rejected: it would be guessing at a ranking function, and winning would
only buy a round the model does not have to spend at all.
"""
import asyncio
import json

import pytest

import clickup_find
import clickup_people as cp
import mytools

WORKSPACE = {"id": "1301320000000306", "name": "AIUI"}
SPACES = [{"id": "2688", "name": "Space"},
          {"id": "2694", "name": "Team Space"}]
TEAM = {"teams": [dict(WORKSPACE, members=[
    {"user": {"id": 252150963, "username": "Ralph Benitez",
              "email": "ralphbenitez32@gmail.com"}}])]}
LISTS_2694 = [
    {"id": "1301320000003388", "name": "Project 1", "task_count": 8},
    {"id": "1301320000003389", "name": "Project 2", "task_count": 3},
]
LIST_STATUSES = {"id": "1301320000003388", "name": "Project 1", "statuses": [
    {"status": "to do", "type": "open"},
    {"status": "in progress", "type": "custom"},
    {"status": "complete", "type": "closed"}]}


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


@pytest.fixture
def clickup(monkeypatch):
    """The real _call path, with ClickUp's hierarchy behind it."""
    calls = []
    answers = {}

    async def secrets(email, provider):
        return {"token": "pk_test_000000000000"} if provider == "clickup" else {}

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
            tail = url.split("/api/v2", 1)[-1]
            for (m, path), resp in answers.items():
                if m == method and tail == path:
                    return resp
            return _Resp(200, {"id": "new1", "name": "x"})

    monkeypatch.setattr(mytools, "_secrets_for", secrets)
    monkeypatch.setattr(mytools.httpx, "AsyncClient", _Client)
    answers[("GET", "/team")] = _Resp(200, TEAM)
    answers[("GET", "/team/1301320000000306/space")] = _Resp(
        200, {"spaces": SPACES})
    for sid in ("2688", "2694"):
        answers[("GET", "/space/%s/folder" % sid)] = _Resp(200, {"folders": []})
    answers[("GET", "/space/2688/list")] = _Resp(200, {"lists": []})
    answers[("GET", "/space/2694/list")] = _Resp(200, {"lists": LISTS_2694})
    answers[("GET", "/list/1301320000003388")] = _Resp(200, LIST_STATUSES)
    return calls, answers


def _tool(name):
    return mytools.CLICKUP_TOOLS_BY_NAME[name]


def _run(name, args):
    return asyncio.run(mytools._call("clickup", _tool(name),
                                     "r@example.com", args))


def _paths(calls, method):
    return [c["url"].split("/api/v2", 1)[-1]
            for c in calls if c["method"] == method]


# --- is this a name or an id -------------------------------------------

@pytest.mark.parametrize("value,looked_up", [
    ("Project 1", True),
    ("project 1", True),
    ("1301320000003388", False),
    (1301320000003388, False),
    ("", False),
    (None, False),
    ("   ", False),
])
def test_only_a_name_costs_a_lookup(value, looked_up):
    """ClickUp's ids are digits. Anything else is what a person said."""
    assert cp.needs_list_lookup(value) is looked_up


# --- one name to one id -------------------------------------------------

def _getter(calls=None):
    async def get(path, extra=None):
        if calls is not None:
            calls.append(path)
        if path == "/team":
            return TEAM
        if path.endswith("/space"):
            return {"spaces": SPACES}
        if path.endswith("/folder"):
            return {"folders": []}
        if path == "/space/2694/list":
            return {"lists": LISTS_2694}
        if path.endswith("/list"):
            return {"lists": []}
        return {}
    return get


def test_a_name_becomes_the_one_id():
    got, problem = asyncio.run(
        clickup_find.resolve_list("Project 1", _getter()))
    assert problem is None
    assert got == "1301320000003388"


def test_a_name_that_is_not_there_says_which_names_are():
    got, problem = asyncio.run(
        clickup_find.resolve_list("Marketing", _getter()))
    assert got is None
    assert "Marketing" in problem
    assert "Project 1" in problem and "Project 2" in problem


def test_a_name_that_fits_two_lists_asks_which_rather_than_choosing():
    """Picking one would put a task somewhere nobody named, and the
    person would not find out until they went looking for it."""
    got, problem = asyncio.run(clickup_find.resolve_list("Project", _getter()))
    assert got is None
    assert "Project 1" in problem and "Project 2" in problem
    assert "which" in problem.lower()


# --- through the real call ---------------------------------------------

def test_creating_a_task_in_project_1_by_name_lands_in_project_1(clickup):
    calls, _ = clickup
    out = _run("create_task", {"list_id": "Project 1", "name": "Buy milk 3"})
    assert out["ok"] is True
    sent = [c for c in calls if c["method"] == "POST"][-1]
    assert sent["url"].endswith("/list/1301320000003388/task")


def test_the_name_and_the_person_are_both_resolved_in_one_call(clickup):
    """The whole request, as it gets typed: a list by name and somebody
    by first name, in one tool call and one round."""
    calls, _ = clickup
    out = _run("create_task", {"list_id": "Project 1", "name": "Buy milk 3",
                               "assignees": ["ralph"]})
    assert out["ok"] is True
    sent = [c for c in calls if c["method"] == "POST"][-1]
    assert sent["url"].endswith("/list/1301320000003388/task")
    assert sent["json"]["assignees"] == [252150963]


def test_a_column_is_read_off_the_list_the_name_resolved_to(clickup):
    """The status lookup reads /list/{id}/. Before the name was resolved
    it would have read /list/Project 1, found nothing, and sent the
    person's own word as the status for ClickUp to refuse."""
    calls, _ = clickup
    out = _run("create_task", {"list_id": "Project 1", "name": "x",
                               "status": "Done"})
    assert out["ok"] is True
    assert "/list/1301320000003388" in _paths(calls, "GET")
    assert "/list/Project 1" not in _paths(calls, "GET")
    sent = [c for c in calls if c["method"] == "POST"][-1]
    assert sent["json"]["status"] == "complete"


def test_an_id_still_costs_no_lookup_at_all(clickup):
    """The common case stays one request. A walk on every call would put
    eight requests in front of every ClickUp write."""
    calls, _ = clickup
    _run("create_task", {"list_id": "1301320000003388", "name": "x"})
    assert [c["method"] for c in calls] == ["POST"]


def test_nothing_is_written_when_the_list_name_is_unknown(clickup):
    calls, _ = clickup
    out = _run("create_task", {"list_id": "Marketing", "name": "x"})
    assert out["ok"] is False
    assert "Project 1" in out["error"]
    assert not [c for c in calls if c["method"] == "POST"]


def test_reading_takes_a_name_too(clickup):
    """"show me the tasks in Project 1" is the same dead end as creating
    one, so the lookup is on the argument rather than on create_task."""
    calls, _ = clickup
    out = _run("get_tasks", {"list_id": "Project 1"})
    assert out["ok"] is True
    assert "/list/1301320000003388/task" in _paths(calls, "GET")


# --- the model has to be told it may say a name -------------------------

def test_every_tool_taking_a_list_id_says_a_name_will_do():
    """A model is told only what the argument description says. A lookup
    nothing announces is a lookup nothing uses, which is exactly how
    find_list ended up unreachable."""
    takes = [t for t in mytools.CLICKUP_TOOLS if "list_id" in (t.args or {})]
    assert len(takes) >= 8, "expected many ClickUp tools to take a list_id"
    for tool in takes:
        said = tool.args["list_id"][1].lower()
        assert "name" in said, (tool.name, said)
        assert "project 1" in said, (tool.name, said)


def test_the_generated_description_for_a_list_id_is_not_just_its_own_name():
    """ClickUp's spec gives `list_id` the description "list_id", which
    tells a model nothing at all."""
    assert _tool("create_task").args["list_id"][1] != "list_id"
