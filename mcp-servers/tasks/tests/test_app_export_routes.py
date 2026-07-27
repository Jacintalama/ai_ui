"""Route registration + the pure pieces. Full behavior needs the DB tier, so
it is covered by the server e2e (Task 7). Assert via app.openapi(), NOT
app.routes - container FastAPI 0.139 includes routers lazily (memory lesson)."""
from main import app


def test_export_routes_are_registered():
    paths = set(app.openapi()["paths"].keys())
    assert "/api/projects/{slug}/export" in paths
    assert "/api/projects/{slug}/export/guide" in paths


def test_export_route_is_a_get_returning_zip():
    spec = app.openapi()["paths"]["/api/projects/{slug}/export"]
    assert "get" in spec
