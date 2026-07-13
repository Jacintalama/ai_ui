from datetime import datetime, timezone
from uuid import uuid4

from schemas import TaskOut


def _mk(desc: str) -> TaskOut:
    return TaskOut(
        id=uuid4(),
        meeting_id=uuid4(),
        action_type="BUILD",
        assignee_name="A",
        assignee_email="a@x.com",
        description=desc,
        priority="IMPORTANT",
        status="pending",
        created_at=datetime.now(timezone.utc),
    )


def test_taskout_user_prompt_computed_from_wrapped_description():
    out = _mk("<rules>\n\nUSER REQUEST:\nbuild a booking site")
    assert out.user_prompt == "build a booking site"


def test_taskout_user_prompt_strips_enhance_prefix():
    out = _mk("Enhance apps/shop-a1/: add a gallery")
    assert out.user_prompt == "add a gallery"


def test_taskout_user_prompt_in_serialized_output():
    out = _mk("<rules>\n\nUSER REQUEST:\njust a landing page")
    dumped = out.model_dump()
    assert dumped["user_prompt"] == "just a landing page"
