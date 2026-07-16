"""TaskOut must be able to represent every task our own DB holds.

Live bug, 2026-07-16: `GET /api/tasks?status=done` returned 500 with

    ResponseValidationError: Input should be 'RESEARCH', 'BUILD', 'INTEGRATE'
    or 'ASK_USER', input: 'OUTREACH'

`routes_outreach.py:141` writes `action_type="OUTREACH"`, but the shared
`ActionType` literal never listed it. TaskOut is a RESPONSE model, so a single
unrepresentable row 500s the WHOLE list endpoint for everyone. Two such rows
(created 2026-06-10) had been breaking the Task Panel's done list for a month.

The split below is the point: be liberal in what a response can represent (the
data already exists, validating it against ourselves only breaks the endpoint),
stay strict about what a request may create.
"""
from datetime import datetime
from typing import get_args
from uuid import uuid4

import pytest
from pydantic import ValidationError

from schemas import ActionType, CreateTaskRequest, IngestActionItem, TaskActionType, TaskOut


def _task_kwargs(**over):
    base = dict(
        id=uuid4(),
        meeting_id=uuid4(),
        action_type="BUILD",
        assignee_name="Jane",
        assignee_email="jane@example.com",
        description="do a thing",
        priority="IMPORTANT",
        status="completed",
        created_at=datetime(2026, 6, 10, 1, 24, 19),
    )
    base.update(over)
    return base


# --- the response must represent reality -----------------------------------

def test_task_out_accepts_an_outreach_task():
    """The exact row shape that 500'd GET /api/tasks?status=done."""
    t = TaskOut(**_task_kwargs(action_type="OUTREACH"))
    assert t.action_type == "OUTREACH"


@pytest.mark.parametrize("action", ["RESEARCH", "BUILD", "INTEGRATE", "ASK_USER", "OUTREACH"])
def test_task_out_accepts_every_action_type_the_code_writes(action):
    assert TaskOut(**_task_kwargs(action_type=action)).action_type == action


def test_response_action_types_are_a_superset_of_request_ones():
    """Anything a request may create must be representable in a response, or
    creating it now breaks every list endpoint that returns it."""
    assert set(get_args(ActionType)) <= set(get_args(TaskActionType))


def test_outreach_is_response_only():
    """OUTREACH is the difference: routes_outreach creates it server-side, no
    caller may post it."""
    assert "OUTREACH" in get_args(TaskActionType)
    assert "OUTREACH" not in get_args(ActionType)


# --- requests stay strict ---------------------------------------------------

def test_ingest_still_rejects_outreach():
    """OUTREACH tasks are created by routes_outreach.py, never posted by the
    decision engine. Widening the response must not widen the input."""
    with pytest.raises(ValidationError):
        IngestActionItem(
            action_type="OUTREACH", assignee="Jane",
            description="x", priority="IMPORTANT",
        )


def test_admin_create_still_rejects_outreach():
    with pytest.raises(ValidationError):
        CreateTaskRequest(description="x", action_type="OUTREACH", priority="IMPORTANT")


def test_requests_still_reject_pure_nonsense():
    with pytest.raises(ValidationError):
        CreateTaskRequest(description="x", action_type="NOT_A_REAL_TYPE", priority="IMPORTANT")


def test_task_out_still_rejects_pure_nonsense():
    """Widened, not disabled."""
    with pytest.raises(ValidationError):
        TaskOut(**_task_kwargs(action_type="NOT_A_REAL_TYPE"))
