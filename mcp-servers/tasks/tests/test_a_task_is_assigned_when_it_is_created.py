"""Assign in the create, because a second call is not offered.

Ralph, 2026-11-10, with a screenshot. He asked for "create a ClickUp task
called Buy milk 7 in Project 1 and assign it to ralph" and got:

    I created the task Buy milk 7 in Project 1. However, I don't have a
    tool to assign the task to you. The ClickUp tools available to me can
    create tasks, add tags, guests, and comments, but not assign existing
    workspace members to a task.

He said "in the prevouis session u can assigned", and the next turn made
a SECOND task:

    Done, assigned to you (ralph). New task: .../14zhcp5g0y1
    Heads up: there are now two tasks called "Buy milk 7" in Project 1,
    since the earlier one couldn't be edited.

The model was telling the truth. Measured on the box with the real
ranking, for that exact sentence:

    create_task 0.7623, add_task_to_list, add_guest_to_task,
    create_task_comment, create_checklist
      -> update_task offered: False

And for the follow-up "assign the task to ralph":

    create_task 0.6958, add_task_to_list, add_guest_to_task, ...
      -> update_task offered: False

So there was no tool in front of it that changes an existing task, and
making a duplicate was the only move it had.

The two summaries, before this file:

    update_task  "Update a task: move it to another column (status),
                  assign or unassign people, rename it, ..."
    create_task  "Create Task. Create a new task."

update_task SAYS assign and is never found; create_task says nothing
about it and is always found, because tool search matches the person's
whole sentence and theirs begins "create a ClickUp task called". Rewording
update_task to climb the ranking is guessing at a ranking function, which
was considered and rejected when find_list hit the same wall
(test_clickup_takes_a_list_by_name.py). The wording belongs on the tool
the model already lands on.

So create_task says it assigns people in the same call, which is true:
clickup_people.prepare resolves a name or an email to a ClickUp id before
the call leaves. One call, one task, assigned. And it names update_task
for the case where the task already exists, so a model that has only this
one tool in hand still knows what to look for instead of creating a
second task with the same name.
"""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

import mytools


def _tool(name):
    return mytools.CLICKUP_TOOLS_BY_NAME[name]


# --- what create_task says about itself --------------------------------

def test_create_task_says_it_can_assign_in_the_same_call():
    said = _tool("create_task").summary.lower()
    assert "assign" in said, said


def test_create_task_says_a_name_or_an_email_will_do():
    """True because clickup_people.prepare looks them up. A model told
    only "assignees" sends an email address as a user id, which is the
    production failure PR #168 was for."""
    said = _tool("create_task").summary.lower()
    assert "name" in said or "email" in said, said


def test_create_task_points_at_update_task_for_one_that_exists():
    """The whole of Ralph's second screenshot. update_task is not in the
    set tool search returns for his sentence, so the only way a model
    learns it exists is for the tool it DID find to name it."""
    said = _tool("create_task").summary
    assert "update_task" in said, said


def test_create_task_says_not_to_make_a_second_one():
    said = _tool("create_task").summary.lower()
    assert "same name" in said or "duplicate" in said or "two tasks" in said, \
        said


def test_create_task_no_longer_says_only_that_it_creates_a_task():
    """ClickUp's generated wording was "Create Task. Create a new task.",
    which tells a model nothing it could not guess from the name."""
    assert _tool("create_task").summary != "Create Task. Create a new task."


def test_update_task_still_says_what_it_changes():
    """Unchanged by this. It is still the right tool and still says so;
    it is simply not what the search returns for "create ... and assign"."""
    said = _tool("update_task").summary.lower()
    assert "assign" in said and "status" in said, said


def test_the_assignee_wording_on_the_argument_is_untouched():
    """The summary is how a model CHOOSES; the argument description is
    how it fills the call. Both have to say it and this fixes only one."""
    said = _tool("create_task").args["assignees"][1].lower()
    assert "email" in said and "name" in said, said


# --- and a model actually reads it -------------------------------------

@pytest.fixture(scope="module")
def served():
    """The OpenAPI tool search and describe_tools read, not the dataclass.

    PR #174's lesson: every argument description in this repo was correct
    on the Tool and dropped on the way out, and the tests passed the whole
    time because they asserted the dataclass.
    """
    app = mytools.build_app()
    with TestClient(app) as c:
        return c.get("/clickup/openapi.json").json()


def _summary_of(doc, tool_name):
    post = (doc.get("paths") or {}).get("/" + tool_name, {}).get("post") or {}
    return str(post.get("summary") or post.get("description") or "")


def test_what_create_task_says_arrives_on_the_surface(served):
    said = _summary_of(served, "create_task").lower()
    assert "assign" in said, said
    assert "update_task" in said, said


def test_what_update_task_says_arrives_too(served):
    assert "assign" in _summary_of(served, "update_task").lower()


# --- one call, one task ------------------------------------------------

class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


TEAM = {"teams": [{"id": "1301320000000306", "name": "AIUI", "members": [
    {"user": {"id": 252150963, "username": "Ralph Benitez",
              "email": "ralphbenitez32@gmail.com"}}]}]}


@pytest.fixture
def clickup(monkeypatch):
    calls = []

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
            if url.endswith("/team"):
                return _Resp(200, TEAM)
            return _Resp(200, {"id": "new1", "name": "Buy milk 7"})

    monkeypatch.setattr(mytools, "_secrets_for", secrets)
    monkeypatch.setattr(mytools.httpx, "AsyncClient", _Client)
    return calls


def test_a_task_named_and_assigned_is_one_write(clickup):
    """The behaviour the wording promises. Two writes is how a duplicate
    gets made in the first place."""
    out = asyncio.run(mytools._call(
        "clickup", _tool("create_task"), "r@example.com",
        {"list_id": "1301320000003388", "name": "Buy milk 7",
         "assignees": ["ralph"]}))
    assert out["ok"] is True
    writes = [c for c in clickup if c["method"] == "POST"]
    assert len(writes) == 1, writes
    assert writes[0]["json"]["assignees"] == [252150963]
