"""Unit tests for the VideoJob ORM model.

These run fully in-memory (no live DB). SQLAlchemy applies column-level
defaults at INSERT/flush, not at construction, so the "queued" status default
and the uuid4 id default are asserted against the column definition rather
than a freshly-constructed instance.
"""
import uuid

from video_models import VideoJob


def test_videojob_defaults():
    j = VideoJob(slug="alpha", user_email="ralph@aiui.com", prompt="demo it")
    assert j.slug == "alpha"
    assert j.user_email == "ralph@aiui.com"
    assert j.prompt == "demo it"
    # Column-level defaults apply at flush, so check the configured default.
    assert VideoJob.__table__.c.status.default.arg == "queued"
    # id is a UUID primary key with a callable default (uuid.uuid4). Asserting
    # is_callable is portable; invoking the wrapped default is not.
    id_col = VideoJob.__table__.c.id
    assert id_col.primary_key is True
    assert id_col.default is not None and id_col.default.is_callable
    assert VideoJob.__table_args__["schema"] == "tasks"
    assert VideoJob.__tablename__ == "video_jobs"


def test_videojob_column_nullability():
    cols = VideoJob.__table__.c
    assert cols.slug.nullable is False
    assert cols.user_email.nullable is False
    assert cols.prompt.nullable is False
    assert cols.status.nullable is False
    assert cols.plan_json.nullable is True
    assert cols.error.nullable is True
    assert cols.output_path.nullable is True


def test_video_job_version_model_columns():
    from video_models import VideoJobVersion
    cols = set(VideoJobVersion.__table__.columns.keys())
    assert cols == {"id", "job_id", "version_no", "plan_json", "summary",
                    "output_path", "created_at"}
    assert VideoJobVersion.__table__.schema == "tasks"


def test_video_job_has_refine_columns():
    from video_models import VideoJob
    cols = set(VideoJob.__table__.columns.keys())
    assert {"conversation", "current_version_no", "pending_summary"} <= cols
