"""The docs sweep guarantees apps/<slug>/README.md exists after a build.

The prompt already mandates the file. This suite exists because a mandate in a
prompt is a request: the commit sweep next door was written after prod measured
43 of 47 app dirs ignoring the same kind of instruction. So the rules that
matter here are (a) it never overwrites a doc the agent actually wrote, and
(b) it never lets a build fail.
"""
import pytest

import app_docs


@pytest.fixture
def apps_root(tmp_path, monkeypatch):
    monkeypatch.setattr(app_docs, "_apps_root", lambda: str(tmp_path))
    monkeypatch.setattr(app_docs, "_validate_slug", lambda slug: None)
    monkeypatch.setattr(app_docs, "_today", lambda: "2026-07-16")
    return tmp_path


def _app(root, slug="my-app"):
    d = root / slug
    d.mkdir(parents=True)
    return d


@pytest.mark.anyio
async def test_writes_a_readme_when_the_agent_skipped_it(apps_root):
    _app(apps_root)
    wrote = await app_docs.sweep_app_docs("my-app", summary="Build a booking form")
    assert wrote is True
    text = (apps_root / "my-app" / "README.md").read_text(encoding="utf-8")
    assert text.startswith("# My App")
    assert "Build a booking form" in text
    for heading in ("## What it does", "## How to run", "## Changelog"):
        assert heading in text
    assert "2026-07-16: first build." in text


@pytest.mark.anyio
async def test_leaves_a_real_readme_completely_alone(apps_root):
    d = _app(apps_root)
    real = ("# Booking Form\n\nA form the clinic uses to take appointments.\n\n"
            "## What it does\n\n- Collects a name and a date\n- Emails the desk\n\n"
            "## Changelog\n\n- 2026-07-01: built it\n")
    (d / "README.md").write_text(real, encoding="utf-8")
    wrote = await app_docs.sweep_app_docs("my-app", summary="something else")
    assert wrote is False
    assert (d / "README.md").read_text(encoding="utf-8") == real


@pytest.mark.anyio
async def test_replaces_an_empty_readme(apps_root):
    d = _app(apps_root)
    (d / "README.md").write_text("   \n", encoding="utf-8")
    assert await app_docs.sweep_app_docs("my-app", summary="x") is True
    assert "## What it does" in (d / "README.md").read_text(encoding="utf-8")


@pytest.mark.anyio
async def test_replaces_a_headings_only_readme(apps_root):
    # Headings with no prose under them are not documentation, which is exactly
    # the shape a lazy agent leaves behind.
    d = _app(apps_root)
    (d / "README.md").write_text(
        "# My App\n\n## What it does\n\n## How to run\n\n## Changelog\n",
        encoding="utf-8")
    assert await app_docs.sweep_app_docs("my-app", summary="a real summary") is True
    assert "a real summary" in (d / "README.md").read_text(encoding="utf-8")


@pytest.mark.anyio
async def test_does_nothing_when_the_app_dir_is_missing(apps_root):
    assert await app_docs.sweep_app_docs("never-built", summary="x") is False
    assert not (apps_root / "never-built").exists()


@pytest.mark.anyio
async def test_refuses_an_invalid_slug(apps_root, monkeypatch):
    def boom(slug):
        raise ValueError("bad slug")
    monkeypatch.setattr(app_docs, "_validate_slug", boom)
    assert await app_docs.sweep_app_docs("../../etc", summary="x") is False


@pytest.mark.anyio
async def test_fails_open_when_the_write_blows_up(apps_root, monkeypatch):
    # A build has already reached "completed" by the time this runs, so nothing
    # here may raise and flip it to failed.
    _app(apps_root)

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(app_docs.Path, "write_text", boom)
    assert await app_docs.sweep_app_docs("my-app", summary="x") is False


@pytest.mark.anyio
async def test_missing_summary_does_not_invent_features(apps_root):
    _app(apps_root)
    await app_docs.sweep_app_docs("my-app", summary=None)
    text = (apps_root / "my-app" / "README.md").read_text(encoding="utf-8")
    assert "No build summary was recorded." in text


@pytest.mark.anyio
async def test_long_summary_is_truncated(apps_root):
    _app(apps_root)
    await app_docs.sweep_app_docs("my-app", summary="y" * 900)
    text = (apps_root / "my-app" / "README.md").read_text(encoding="utf-8")
    assert "y" * 297 + "..." in text
    assert "y" * 400 not in text


def test_title_from_slug_handles_dashes_and_underscores():
    assert app_docs._title_from_slug("my-cool_app") == "My Cool App"


# --------------------------------------------------- prompt + wiring contract

def test_every_build_prompt_mandates_the_readme():
    # A build reaches the agent through one of these three templates, so a docs
    # rule missing from any one of them is a silent hole. Enhance matters most:
    # it is the path every later edit takes, and it is where "keep the doc
    # current" has to beat its own "make the smallest possible change" rule.
    import claude_executor as ce
    for name in ("PROMPT_TEMPLATE", "TDD_EXECUTE_PROMPT_TEMPLATE"):
        assert "DOCS - NON-NEGOTIABLE" in getattr(ce, name), name
        assert "README.md" in getattr(ce, name), name
    assert "8. DOCS:" in ce.ENHANCE_PROMPT_TEMPLATE
    assert "OVERRIDES rule 1" in ce.ENHANCE_PROMPT_TEMPLATE


def test_docs_sweep_runs_before_the_commit_sweep():
    # Order is load-bearing: the doc has to be on disk before the commit sweep
    # stages apps/<slug>/, or it lands a build late (or never).
    import io
    src = io.open("routes_execution.py", encoding="utf-8").read()
    assert src.index("_sweep_app_docs(") < src.index("_sweep_app_commit(")
