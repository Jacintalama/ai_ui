import os, uuid
import pytest
from video_models import VideoJob, VideoJobVersion
from video_versions import next_version_no, record_version, list_versions, find_version

_DB_URL = os.environ.get("DATABASE_URL", "")
_HAVE_DB = bool(_DB_URL) and "nowhere" not in _DB_URL
PLAN = {"template_id": "product_demo", "title": "t",
        "scenes": [{"screenshot": "screenshot-1.png", "caption": "c",
                    "duration_s": 3, "transition": "cut"}],
        "narration_script": "hello"}

@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_record_version_increments(db_session):
    job = VideoJob(id=uuid.uuid4(), slug="alpha", user_email="r@x.com",
                   prompt="p", status="done", plan_json=PLAN)
    db_session.add(job)
    await db_session.commit()
    n1 = await next_version_no(db_session, job.id)
    assert n1 == 1
    await record_version(db_session, job.id, n1, PLAN, None, "/x/out-v1.mp4")
    await db_session.commit()
    n2 = await next_version_no(db_session, job.id)
    assert n2 == 2
    vs = await list_versions(db_session, job.id)
    assert [v.version_no for v in vs] == [1]
    found = await find_version(db_session, job.id, 1)
    assert found is not None and found.output_path == "/x/out-v1.mp4"
    assert await find_version(db_session, job.id, 99) is None
