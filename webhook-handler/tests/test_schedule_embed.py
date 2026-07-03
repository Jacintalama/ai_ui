from schedule_format import build_schedule_embed, short_summary

CYAN = 0x22D3EE  # AIUI primary (Cyan Circuit)


def test_completed_embed():
    e = build_schedule_embed("daily report", "completed", "All good.")
    assert e["title"].startswith("✅")
    assert "daily report" in e["title"]
    assert e["color"] == CYAN
    assert e["description"] == "All good."
    assert {"name": "STATUS", "value": "COMPLETE", "inline": True} in e["fields"]
    assert any(f["name"] == "TIME" for f in e["fields"])
    assert "AIUI" in e["author"]["name"]
    assert e["footer"]["text"] == "AIUI"
    assert "timestamp" in e


def test_failed_uses_warning_and_still_single_brand_color():
    e = build_schedule_embed("x", "failed", "boom")
    assert e["title"].startswith("⚠️")
    assert e["color"] == CYAN  # one brand color; status shown via emoji/field
    assert {"name": "STATUS", "value": "FAILED", "inline": True} in e["fields"]


def test_skipped():
    e = build_schedule_embed("x", "skipped", "")
    assert e["title"].startswith("⏭️")
    assert {"name": "STATUS", "value": "SKIPPED", "inline": True} in e["fields"]


def test_empty_result_placeholder():
    e = build_schedule_embed("x", "completed", "   ")
    assert e["description"] == "_(no output)_"


def test_title_truncated_to_256():
    e = build_schedule_embed("n" * 400, "completed", "y")
    assert len(e["title"]) <= 256


def test_short_summary():
    assert short_summary("hello", "completed").startswith("✅")
    assert short_summary("hello", "failed").startswith("⚠️")
