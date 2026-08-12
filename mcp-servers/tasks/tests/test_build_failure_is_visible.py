"""A build that died must never look like a build that is queued.

Reported by a user on 2026-08-12: "why its never ending loading". Their build
sat on QUEUED forever. Production evidence:

    POST /api/tasks/{id}/execute      -> 200        the build did start
    GET  /api/tasks/{id}/executions   -> 403 x282   every progress poll refused
    task row: status=pending, result="Credit balance is too low"
    execution: status=failed, error=NULL, ran 9s (487ms of API time)

The agent had returned `{"is_error":true,"api_error_status":400,
"result":"Credit balance is too low"}` — the Anthropic key was out of credit.
**45 builds** had failed this way since at least 2026-08-10, every one showing a
spinner that never ended.

Two defects, and the credit itself is neither of them:

1. `list_executions` still required the admin header, so a non-admin's page
   could not read its own build log. The route's body already calls
   `_get_owned_task`, so the gate only ever blocked owners — the same redundant
   gate pattern as 2a931c158..dda2d632f.

2. A failed run leaves the task back at `status="pending"` with the reason in
   `result`. `pending` renders as QUEUED, so a dead build is indistinguishable
   from a waiting one. The page already polls GET /api/tasks/{id} successfully
   (283 times, all 200) — the reason was on screen-adjacent data the whole time
   and simply was not shown.

That is this codebase's documented failure mode inverted: not "announced
success it never checked", but "announced progress that had already stopped".
"""
import inspect
import re
import uuid

import pytest

import routes_tasks
from auth import current_admin, current_admin_or_capability, current_user_or_capability


def _deps(func):
    out = []
    for param in inspect.signature(func).parameters.values():
        d = param.default
        if d is not inspect.Parameter.empty and hasattr(d, "dependency"):
            out.append(d.dependency)
    return out


# ---------------------------------------------------------------------------
# 1. The owner can read their own build log.
# ---------------------------------------------------------------------------

def test_executions_does_not_demand_the_admin_header():
    """The 403 the user actually hit, 282 times."""
    assert current_admin_or_capability not in _deps(routes_tasks.list_executions), (
        "GET /{id}/executions still falls back to the admin header, so a "
        "regular user cannot see why their own build failed")
    assert current_admin not in _deps(routes_tasks.list_executions)


def test_executions_still_requires_a_signed_in_user():
    assert current_user_or_capability in _deps(routes_tasks.list_executions), (
        "GET /{id}/executions lost its authentication")


def test_the_ownership_check_is_still_in_the_body():
    """Relaxing the gate is only safe because this check exists."""
    src = inspect.getsource(routes_tasks.list_executions)
    assert "_get_owned_task" in src


# ---------------------------------------------------------------------------
# 2. The team bucket is not a back door.
# ---------------------------------------------------------------------------

def test_the_ownership_helper_can_refuse_the_team_bucket():
    """_get_owned_task treated team@aiui.local as everyone's, which was
    harmless while the routes were admin-only and is not any more: a signed-in
    stranger could read a team build's full log by guessing a UUID."""
    sig = inspect.signature(routes_tasks._get_owned_task)
    assert "is_admin" in sig.parameters, (
        "_get_owned_task cannot distinguish an admin, so the team-bucket "
        "shortcut applies to every signed-in caller")


@pytest.mark.parametrize("is_admin,expected", [(True, "allowed"), (False, "refused")])
def test_the_team_bucket_is_admin_only(is_admin, expected):
    import asyncio

    from models import TaskItem
    from fastapi import HTTPException

    TEAM = routes_tasks.TEAM_EMAIL
    item = TaskItem(id=uuid.uuid4(), meeting_id=uuid.uuid4(), action_type="BUILD",
                    assignee_name="team", assignee_email=TEAM, description="x",
                    priority="IMPORTANT", status="pending", max_attempts=1,
                    attempt_count=0, conversation_history=[])

    class _S:
        async def execute(self, _q):
            class _R:
                def scalar_one_or_none(self_): return item
            return _R()

    async def go():
        return await routes_tasks._get_owned_task(
            _S(), item.id, "stranger@example.com", is_admin=is_admin)

    if expected == "allowed":
        assert asyncio.get_event_loop_policy().new_event_loop().run_until_complete(go()) is item
    else:
        with pytest.raises(HTTPException) as e:
            asyncio.get_event_loop_policy().new_event_loop().run_until_complete(go())
        assert e.value.status_code == 403


# ---------------------------------------------------------------------------
# 3. The page must not render a dead build as QUEUED.
# ---------------------------------------------------------------------------

PREVIEW = None


def _preview():
    global PREVIEW
    if PREVIEW is None:
        import pathlib
        PREVIEW = (pathlib.Path(routes_tasks.__file__).parent
                   / "static" / "preview.html").read_text(encoding="utf-8")
    return PREVIEW


def test_the_page_reads_the_failure_reason_off_the_task():
    """`result` already held "Credit balance is too low" while the page showed
    QUEUED. It polls GET /api/tasks/{id} successfully, so this needs no new
    request — only that the field be looked at."""
    html = _preview()
    assert "lastRunFailed" in html or "runFailureReason" in html, (
        "nothing in preview.html inspects the task's failure reason, so a "
        "pending-after-failure build still renders as QUEUED")


def test_a_credit_failure_is_named_rather_than_shown_as_a_raw_error():
    """A user seeing "Credit balance is too low" needs to be told it is
    billing, not their prompt. 45 builds died on this without anyone
    connecting it.

    Matched case-insensitively on purpose: the agent's string is capitalised
    ("Credit balance is too low") but the page must recognise it however the
    API cases it, so the check in the source is a case-insensitive regex.
    """
    html = _preview()
    assert re.search(r"credit balance", html, re.I), (
        "the one failure that has actually happened 45 times is not "
        "recognised, so the user is left to interpret a raw API string")
    assert re.search(r"credit.{0,40}(ran out|billing|top)", html, re.I), (
        "the credit case is detected but the user is not told it is a billing "
        "limit rather than something wrong with their request")
