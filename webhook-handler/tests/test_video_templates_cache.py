import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers import video_templates as vtpl


@pytest.fixture(autouse=True)
def _reset_cache():
    vtpl._cache = list(vtpl.FALLBACK_TEMPLATES)
    vtpl._fetched_at = 0.0
    yield
    vtpl._cache = list(vtpl.FALLBACK_TEMPLATES)
    vtpl._fetched_at = 0.0


def test_fallback_has_the_four_templates():
    assert [t["key"] for t in vtpl.FALLBACK_TEMPLATES] == [
        "walkthrough", "product", "cinematic", "social"]
    for t in vtpl.FALLBACK_TEMPLATES:
        assert t["style"] and t["prompt"] and t["name"]


def test_cached_templates_never_empty_and_is_a_copy():
    got = vtpl.cached_templates()
    assert got
    got.clear()
    assert vtpl.cached_templates()


def test_get_template_and_unknown():
    assert vtpl.get_template("walkthrough")["style"] == "clean_product_demo"
    assert vtpl.get_template("nope") is None


def test_cache_starts_stale():
    assert vtpl.cache_is_fresh() is False


@pytest.mark.asyncio
async def test_refresh_replaces_cache_and_freshens():
    tc = MagicMock()
    tc.get_video_templates = AsyncMock(return_value={
        "templates": [{"key": "walkthrough", "name": "WT", "style": "cinematic",
                       "prompt": "p", "emoji": "x", "desc": "d", "remotion": True}],
        "default": "walkthrough"})
    ok = await vtpl.refresh_templates(tc)
    assert ok is True
    assert vtpl.cache_is_fresh() is True
    assert vtpl.cached_templates()[0]["style"] == "cinematic"


@pytest.mark.asyncio
async def test_refresh_failure_keeps_fallback():
    tc = MagicMock()
    tc.get_video_templates = AsyncMock(side_effect=RuntimeError("down"))
    ok = await vtpl.refresh_templates(tc)
    assert ok is False
    assert [t["key"] for t in vtpl.cached_templates()] == [
        "walkthrough", "product", "cinematic", "social"]


@pytest.mark.asyncio
async def test_refresh_empty_payload_keeps_fallback():
    tc = MagicMock()
    tc.get_video_templates = AsyncMock(return_value={"templates": []})
    ok = await vtpl.refresh_templates(tc)
    assert ok is False
    assert vtpl.cached_templates()


def test_template_prompts_includes_fallback_prompts():
    prompts = vtpl.template_prompts()
    for t in vtpl.FALLBACK_TEMPLATES:
        assert t["prompt"] in prompts
