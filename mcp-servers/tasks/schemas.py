"""Request/response schemas."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ActionType = Literal["RESEARCH", "BUILD", "INTEGRATE", "ASK_USER"]
Priority = Literal["CRITICAL", "IMPORTANT", "NICE_TO_HAVE"]
Status = Literal["pending", "claimed_manual", "running", "awaiting_input", "completed", "failed"]
Mode = Literal["ai", "manual"]


class TaskOut(BaseModel):
    id: UUID
    meeting_id: UUID
    action_type: ActionType
    assignee_name: str
    assignee_email: str
    description: str
    query: str | None = None
    priority: Priority
    status: Status
    mode: Mode | None = None
    result: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

    class Config:
        from_attributes = True


class IngestActionItem(BaseModel):
    """One item posted by the meetings decision engine."""

    action_type: ActionType
    assignee: str = Field(description="Raw assignee name from decision engine")
    description: str
    query: str | None = None
    priority: Priority


class IngestRequest(BaseModel):
    meeting_id: UUID
    items: list[IngestActionItem]


class CompleteRequest(BaseModel):
    result: str = ""


class AnswerRequest(BaseModel):
    answer: str
