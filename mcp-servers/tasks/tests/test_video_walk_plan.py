from video_walk_plan import build_walk_plan, _clean_headline


def test_clean_headline_strips_site_suffix():
    assert _clean_headline("Home | Animepahe") == "Home"
    assert _clean_headline("Watch X Episode 1 - Animepahe") == "Watch X Episode 1"
    assert _clean_headline("") == ""
    assert _clean_headline("Page Title \u2013 Site Name") == "Page Title"
    assert _clean_headline("Watch X \u00b7 Site") == "Watch X"


def _walk():
    return [
        {"url": "https://s.com/", "title": "Home | S", "click": {"x": 0.09, "y": 0.47, "label": "Show"}},
        {"url": "https://s.com/watch", "title": "Watch | S", "click": {"x": 0.35, "y": 0.69, "label": "Play"}},
        {"url": "https://s.com/series", "title": "Series | S", "click": None},
    ]


def test_build_walk_plan_shape():
    plan = build_walk_plan(_walk(), ["screenshot-1.png", "screenshot-2.png", "screenshot-3.png"],
                           {"host": "s.com"})
    scenes = plan["scenes"]
    # intro + 3 pages + outro
    assert len(scenes) == 5
    assert scenes[0]["kind"] == "intro" and "screenshot" not in scenes[0]
    assert scenes[-1]["kind"] == "outro"
    page_scenes = scenes[1:-1]
    assert [s["screenshot"] for s in page_scenes] == ["screenshot-1.png", "screenshot-2.png", "screenshot-3.png"]
    assert page_scenes[0]["click"] == {"x": 0.09, "y": 0.47, "label": "Show"}
    assert "click" not in page_scenes[2]           # None click omitted
    assert page_scenes[0]["headline"] == "Home"


def test_build_walk_plan_respects_duration_cap():
    walk = [{"url": f"https://s.com/{i}", "title": f"P{i}", "click": None} for i in range(20)]
    names = [f"screenshot-{i+1}.png" for i in range(20)]
    plan = build_walk_plan(walk, names, {"host": "s.com"}, max_duration_s=40.0)
    total = sum(s["duration_s"] for s in plan["scenes"])
    assert total <= 40.0
    assert plan["scenes"][0]["kind"] == "intro" and plan["scenes"][-1]["kind"] == "outro"
    page_scenes = [s for s in plan["scenes"] if s["kind"] == "screenshot"]
    kept = len(page_scenes)
    assert page_scenes[0]["screenshot"] == "screenshot-1.png"
    assert [s["screenshot"] for s in page_scenes] == [f"screenshot-{i+1}.png" for i in range(kept)]


def test_build_walk_plan_single_page():
    walk = [{"url": "https://s.com/", "title": "Only | S", "click": None}]
    plan = build_walk_plan(walk, ["screenshot-1.png"], {"host": "s.com"})
    assert [s["kind"] for s in plan["scenes"]] == ["intro", "screenshot", "outro"]
