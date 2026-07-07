from templates_video.style_config import STYLE_CONFIGS
from video_templates import (
    DEFAULT_TEMPLATE_KEY,
    VIDEO_TEMPLATES,
    get_template,
    template_catalog,
    template_prompts,
)


def test_registry_has_the_four_templates_in_order():
    assert [t["key"] for t in VIDEO_TEMPLATES] == [
        "walkthrough", "product", "cinematic", "social"]


def test_every_template_is_complete_and_valid():
    for t in VIDEO_TEMPLATES:
        assert t["key"] and t["name"] and t["emoji"]
        assert t["desc"] and t["prompt"]
        assert t["style"] in STYLE_CONFIGS
        assert t["remotion"] is True


def test_default_key_exists():
    assert get_template(DEFAULT_TEMPLATE_KEY) is not None


def test_catalog_returns_copies():
    cat = template_catalog()
    cat[0]["name"] = "mutated"
    assert VIDEO_TEMPLATES[0]["name"] == "Website Walkthrough"


def test_get_template_unknown_returns_none():
    assert get_template("nope") is None
    assert get_template("") is None


def test_template_prompts_is_the_prompt_set():
    assert template_prompts() == {t["prompt"] for t in VIDEO_TEMPLATES}


def test_templates_route_is_registered_before_job_id():
    """The literal /templates path must come before /{job_id} or FastAPI
    swallows it as a job id."""
    import routes_video
    paths = [r.path for r in routes_video.router.routes]
    assert "/api/video-jobs/templates" in paths
    assert paths.index("/api/video-jobs/templates") < paths.index("/api/video-jobs/{job_id}")
