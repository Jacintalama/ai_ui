import routes_projects


def test_public_url_uses_apex_apps_path(monkeypatch):
    monkeypatch.setattr(
        routes_projects,
        "PUBLIC_BASE_URL",
        "https://ai-ui.example",
        raising=False,
    )

    assert routes_projects._public_url_for("alpha") == "https://ai-ui.example/apps/alpha/"
