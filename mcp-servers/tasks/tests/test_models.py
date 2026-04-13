"""Smoke tests for ORM persistence."""
import pytest
from sqlalchemy.exc import IntegrityError

from models import TaskExecution, TaskItem


async def test_can_persist_and_query_task(db_session, fake_meeting_id):
    item = TaskItem(
        meeting_id=fake_meeting_id,
        action_type="BUILD",
        assignee_name="Ralph Benitez",
        assignee_email="ralph@aiui.com",
        description="Fix Caddy routing",
        priority="CRITICAL",
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    assert item.id is not None
    assert item.status == "pending"


async def test_partial_unique_index_blocks_two_running_executions(db_session, fake_meeting_id):
    """Inserting two 'running' rows for the same task must fail."""
    item = TaskItem(
        meeting_id=fake_meeting_id,
        action_type="BUILD",
        assignee_name="x",
        assignee_email="x@y",
        description="d",
        priority="IMPORTANT",
    )
    db_session.add(item)
    await db_session.commit()

    db_session.add(TaskExecution(task_id=item.id, status="running"))
    await db_session.commit()
    db_session.add(TaskExecution(task_id=item.id, status="running"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
