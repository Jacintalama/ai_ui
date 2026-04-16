"""Webhook ingestion from the meetings decision engine."""
import logging

from fastapi import APIRouter, status
from sqlalchemy.dialects.postgresql import insert as pg_insert

from assignee_map import AssigneeMap
from db import session
from models import TaskItem
from schemas import IngestRequest

logger = logging.getLogger("tasks")
router = APIRouter()


@router.post("/webhooks/meeting-action-items", status_code=status.HTTP_201_CREATED)
async def ingest(payload: IngestRequest) -> dict[str, int]:
    """Idempotent insert of action items for a meeting.

    Idempotency relies on the partial unique index
    `items_meeting_desc_uniq UNIQUE (meeting_id, md5(description))`.
    """
    amap = AssigneeMap.from_env()
    created = 0
    async with session() as s:
        for item in payload.items:
            email = amap.resolve(item.assignee)
            stmt = pg_insert(TaskItem.__table__).values(
                meeting_id=payload.meeting_id,
                action_type=item.action_type,
                assignee_name=item.assignee,
                assignee_email=email,
                description=item.description,
                query=item.query,
                priority=item.priority,
            ).on_conflict_do_nothing()
            result = await s.execute(stmt)
            if result.rowcount:
                created += 1
        await s.commit()
    logger.info("Ingested %d new action items for meeting %s", created, payload.meeting_id)
    return {"created": created}
