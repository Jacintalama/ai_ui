from handlers import intent_cards as ic


def test_confirm_components_discord_carry_token():
    comps = ic.confirm_components_discord("tok123")
    ids = [c["custom_id"] for c in comps[0]["components"]]
    assert ic.INTENT_CONFIRM_PREFIX + "tok123" in ids
    assert ic.INTENT_CANCEL_PREFIX + "tok123" in ids


def test_confirm_blocks_slack_carry_token():
    blocks = ic.confirm_blocks_slack("tok9", "Want me to build it?")
    actions = [b for b in blocks if b["type"] == "actions"][0]
    ids = [e["action_id"] for e in actions["elements"]]
    assert ic.INTENT_CONFIRM_PREFIX + "tok9" in ids
    assert ic.INTENT_CANCEL_PREFIX + "tok9" in ids


def test_confirm_line_names_build():
    assert "build" in ic.confirm_line("build_app", "a form").lower()


def test_suggest_line_names_the_intent():
    assert "video" in ic.suggest_line("make_video").lower()


def test_lines_handle_unknown_intent_gracefully():
    assert isinstance(ic.confirm_line("weird", ""), str)
    assert isinstance(ic.suggest_line("weird"), str)


def test_recap_line_build_includes_detail():
    line = ic.recap_line("build_app", "a portfolio for a photographer")
    assert "a portfolio for a photographer" in line
    assert line.endswith("?")


def test_recap_line_schedule_includes_when():
    line = ic.recap_line(
        "schedule_task", "summarize my emails",
        when="every weekday at 8am", task="summarize my emails")
    assert "summarize my emails" in line
    assert "every weekday at 8am" in line


def test_recap_line_schedule_without_when_ok():
    line = ic.recap_line("schedule_task", "water reminder", task="water reminder")
    assert "water reminder" in line
    assert line.endswith("?")
