"""Request/response schemas."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ActionType = Literal["RESEARCH", "BUILD", "INTEGRATE", "ASK_USER"]
Priority = Literal["CRITICAL", "IMPORTANT", "NICE_TO_HAVE"]
Status = Literal["pending", "planning", "awaiting_plan_review", "claimed_manual", "running", "awaiting_input", "completed", "failed"]
Mode = Literal["ai", "manual"]
PlanStatus = Literal["pending_review", "approved", "rejected"]


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
    max_attempts: int = 1
    attempt_count: int = 0
    conversation_history: list = []
    plan: str | None = None
    plan_status: str | None = None
    built_app_slug: str | None = None
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


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    """Body for POST /api/tasks/chat — lightweight Claude chat (no build)."""

    source_task_id: str = Field(description="UUID of the BUILD task whose app is being discussed")
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=40)


class ChatResponse(BaseModel):
    reply: str


class CreateTaskRequest(BaseModel):
    """Body for admin-created tasks from the panel."""

    description: str = Field(min_length=1, max_length=2000)
    action_type: ActionType
    priority: Priority
    assignee: str = Field(default="self", description="'self', 'team', or a name prefix in the assignee map")
    max_attempts: int = Field(default=1, ge=1, le=10, description="1=one-shot, >1=loop mode")


class PlanReviewRequest(BaseModel):
    approved: bool
    feedback: str = ""


class EnhanceRequest(BaseModel):
    source_task_id: UUID
    prompt: str = Field(min_length=1, max_length=2000)
