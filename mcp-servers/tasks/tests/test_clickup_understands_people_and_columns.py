"""ClickUp from the chat: assign people and move between columns (2026-11-10).

Lukas, 2026-11-10: the chat "doesn't know how to assign tasks", and the order
that matters is create a task, move it between columns, assign it.

What the held calls on production showed (tasks.approval, 2026-11-09/10):

    my-clickup_create_task  assignees: ['ralphbenitez32@gmail.com']
    my-clickup_create_task  assignees: ralphbenitez32@gmail.com
    my-clickup_create_task  (asked to assign it to ralph; no assignee sent)

ClickUp takes numeric user ids, so a model that knows a person by name or
email could not assign anybody. A column is a status, which must be one of
that list's statuses, and a ClickUp 400 reached the model as "ClickUp returned
an error (400)." with ClickUp's reason thrown away.

So the service looks people and columns up, as ClickUp knows them, before the
call. The shapes below are ClickUp's own examples from its v2 API reference
(GET /v2/team, GET /v2/list/{id}, GET /v2/task/{id}), with an `email` on each
member as GET /v2/user defines one.
"""
import asyncio
import json

import pytest

import clickup_people as cp
import mytools

TEAM = {"teams": [{
    "id": "1234", "name": "My ClickUp Workspace", "color": "#000000",
    "avatar": "https://clickup.com/avatar.jpg",
    "members": [
        {"user": {"id": 123, "username": "John Doe", "email": "john@example.com",
                  "color": "#000000", "profilePicture": "https://clickup.com/avatar.jpg"}},
        {"user": {"id": 106928073, "username": "Ralph Benitez",
                  "email": "ralphbenitez32@gmail.com", "color": "#000000",
                  "profilePicture": None}},
        {"user": {"id": 812, "username": "John Smith", "email": "jsmith@example.com",
                  "color": None, "profilePicture": None}},
    ]}]}

LIST = {"id": "124", "name": "Updated List Name", "override_statuses": False,
        "statuses": [
            {"status": "to do", "orderindex": 0, "color": "#d3d3d3", "type": "open"},
            {"status": "in progress", "orderindex": 1, "color": "#4194f6", "type": "custom"},
            {"status": "complete", "orderindex": 2, "color": "#6bc950", "type": "closed"},
        ]}

TASK = {"id": "9hx", "name": "Fix login bug",
        "status": {"status": "in progress", "type": "custom"},
        "list": {"id": "124", "name": "Updated List Name", "access": True}}

MEMBERS = cp.members_of(TEAM)


# --- people -----------------------------------------------------------------------

def test_members_come_from_every_workspace_once():
    two = {"teams": TEAM["teams"] + [{"id": "9", "members": [TEAM["teams"][0]["members"][1]]}]}
    assert [m["id"] for m in cp.members_of(two)] == [123, 106928073, 812]


def test_an_email_is_the_persons_id():
    assert cp.resolve_person("ralphbenitez32@gmail.com", MEMBERS) == (106928073, None)


def test_a_full_name_is_the_persons_id():
    assert cp.resolve_person("ralph benitez", MEMBERS) == (106928073, None)


def test_a_first_name_is_enough_when_only_one_person_has_it():
    """'assign it to ralph', which is how it was asked on 2026-11-10."""
    assert cp.resolve_person("Ralph", MEMBERS) == (106928073, None)


def test_a_first_name_two_people_share_asks_which():
    who, problem = cp.resolve_person("john", MEMBERS)
    assert who is None
    assert "John Doe" in problem and "John Smith" in problem


def test_somebody_who_is_not_there_is_said_with_who_is():
    who, problem = cp.resolve_person("Lukas", MEMBERS)
    assert who is None
    assert "Lukas" in problem and "Ralph Benitez" in problem


def test_an_id_passes_untouched_and_a_digit_string_becomes_one():
    assert cp.resolve_person(106928073, MEMBERS) == (106928073, None)
    assert cp.resolve_person("106928073", []) == (106928073, None)


def test_creating_takes_a_list_and_a_lone_value():
    assert cp.resolve_assignees(["ralph", 123], MEMBERS, for_update=False) == ([106928073, 123], None)
    assert cp.resolve_assignees("ralphbenitez32@gmail.com", MEMBERS, for_update=False) == ([106928073], None)


def test_updating_fills_the_half_clickup_requires():
    """ClickUp's reference marks both add and rem required; the model sent
    {"add": [106928073]} on 2026-11-09."""
    assert cp.resolve_assignees({"add": ["ralph"]}, MEMBERS, for_update=True) == (
        {"add": [106928073], "rem": []}, None)
    assert cp.resolve_assignees({"rem": ["John Doe"]}, MEMBERS, for_update=True) == (
        {"add": [], "rem": [123]}, None)


def test_one_unknown_person_stops_the_whole_assignment():
    value, problem = cp.resolve_assignees(["ralph", "nobody"], MEMBERS, for_update=False)
    assert value is None and "nobody" in problem


# --- columns ----------------------------------------------------------------------

def test_a_column_ignores_case_and_spacing():
    assert cp.resolve_status("In Progress", LIST["statuses"]) == ("in progress", None)
    assert cp.resolve_status("TODO", LIST["statuses"]) == ("to do", None)


def test_done_means_the_lists_closed_column():
    for said in ("done", "Done", "finished", "completed"):
        assert cp.resolve_status(said, LIST["statuses"]) == ("complete", None), said


def test_a_column_the_list_does_not_have_names_the_ones_it_does():
    value, problem = cp.resolve_status("doing", LIST["statuses"])
    assert value is None
    assert "to do" in problem and "in progress" in problem and "complete" in problem


def test_columns_that_could_not_be_read_leave_the_value_to_clickup():
    assert cp.resolve_status("Doing", []) == ("Doing", None)


# --- through the real call --------------------------------------------------------

class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


@pytest.fixture
def clickup(monkeypatch):
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

        async def request(self, method, url, headers=None, params=None, json=None):
            calls.append({"method": method, "url": url, "json": json, "params": params or {}})
            for (m, tail), resp in answers.items():
                if m == method and url.endswith(tail):
                    return resp
            return _Resp(200, {"id": "new1", "name": "x"})

    monkeypatch.setattr(mytools, "_secrets_for", secrets)
    monkeypatch.setattr(mytools.httpx, "AsyncClient", _Client)
    answers[("GET", "/team")] = _Resp(200, TEAM)
    answers[("GET", "/list/124")] = _Resp(200, LIST)
    answers[("GET", "/task/9hx")] = _Resp(200, TASK)
    return calls, answers


def _tool(name):
    return {t.name: t for t in mytools.CLICKUP_TOOLS}[name]


def _run(name, args):
    return asyncio.run(mytools._call("clickup", _tool(name), "r@example.com", args))


def test_creating_a_task_for_somebody_by_email_sends_their_id(clickup):
    calls, _ = clickup
    out = _run("create_task", {"list_id": "124", "name": "Buy milk",
                               "assignees": ["ralphbenitez32@gmail.com"]})
    assert out["ok"] is True
    sent = [c for c in calls if c["method"] == "POST"][-1]
    assert sent["url"].endswith("/list/124/task")
    assert sent["json"]["assignees"] == [106928073]


def test_moving_a_task_to_done_sends_the_lists_closed_column(clickup):
    calls, _ = clickup
    out = _run("update_task", {"task_id": "9hx", "status": "Done"})
    assert out["ok"] is True
    sent = [c for c in calls if c["method"] == "PUT"][-1]
    assert sent["json"]["status"] == "complete"


def test_assigning_on_an_update_sends_add_and_rem(clickup):
    calls, _ = clickup
    _run("update_task", {"task_id": "9hx", "assignees": {"add": ["ralph"]}})
    sent = [c for c in calls if c["method"] == "PUT"][-1]
    assert sent["json"]["assignees"] == {"add": [106928073], "rem": []}


def test_nothing_is_written_when_the_person_is_not_found(clickup):
    calls, _ = clickup
    out = _run("create_task", {"list_id": "124", "name": "x", "assignees": ["Lukas"]})
    assert out["ok"] is False and "Lukas" in out["error"]
    assert not [c for c in calls if c["method"] == "POST"]


def test_nothing_is_written_to_a_column_that_does_not_exist(clickup):
    calls, _ = clickup
    out = _run("update_task", {"task_id": "9hx", "status": "doing"})
    assert out["ok"] is False and "in progress" in out["error"]
    assert not [c for c in calls if c["method"] == "PUT"]


def test_ids_need_no_lookup(clickup):
    """No extra request when there is nothing to look up."""
    calls, _ = clickup
    _run("create_task", {"list_id": "124", "name": "x", "assignees": [106928073]})
    assert [c["method"] for c in calls] == ["POST"]


def test_clickups_reason_for_a_400_reaches_the_model(clickup):
    calls, answers = clickup
    answers[("POST", "/list/124/task")] = _Resp(400, {"err": "Status does not exist", "ECODE": "CRTSK_001"})
    out = _run("create_task", {"list_id": "124", "name": "x"})
    assert out["ok"] is False
    assert "Status does not exist" in out["error"]


def test_the_update_tool_says_it_moves_and_assigns():
    """Tool search reads the summary. "move this to done" has to find it."""
    summary = _tool("update_task").summary.lower()
    assert "column" in summary and "assign" in summary


def test_the_model_is_told_a_name_or_email_is_fine():
    for name in ("create_task", "update_task"):
        desc = _tool(name).args["assignees"][1].lower()
        assert "email" in desc and "name" in desc, (name, desc)
