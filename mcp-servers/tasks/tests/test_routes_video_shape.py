"""Route-shape assertions for routes_video (pure, no DB)."""
import routes_video


def _routes():
    return [(r.path, set(r.methods)) for r in routes_video.router.routes]


def test_retry_route_registered_as_post():
    assert any(p == "/api/video-jobs/{job_id}/retry" and "POST" in m
               for p, m in _routes())


def test_delete_route_registered():
    assert any(p == "/api/video-jobs/{job_id}" and "DELETE" in m
               for p, m in _routes())


def test_list_route_registered():
    assert any(p == "/api/video-jobs" and "GET" in m for p, m in _routes())
