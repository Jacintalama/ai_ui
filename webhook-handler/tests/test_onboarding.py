from handlers import onboarding as ob
from handlers.app_builder_panel import LINK_START_ID, PANEL_NEW_ID, SCHED_OPEN_ID


def test_not_linked_text_discord_is_friendly_and_self_service():
    txt = ob.not_linked_text_discord()
    assert "Lukas" not in txt
    assert "Link my account" in txt


def test_link_button_row_carries_link_start_id():
    row = ob.link_button_row()
    btn = row[0]["components"][0]
    assert btn["custom_id"] == LINK_START_ID
    assert "Link my account" in btn["label"]


def test_welcome_components_discord_has_build_and_schedule_buttons():
    row = ob.welcome_components_discord()[0]
    ids = [c["custom_id"] for c in row["components"]]
    assert PANEL_NEW_ID in ids
    assert SCHED_OPEN_ID in ids


import pytest


def test_not_linked_text_slack_has_no_bare_scope_jargon_lead():
    txt = ob.not_linked_text_slack()
    assert "Lukas" not in txt
    assert txt.lower().startswith("i can")
    assert "email access" in txt.lower()


def test_welcome_blocks_slack_have_two_action_buttons():
    blocks = ob.welcome_blocks_slack()
    actions = [b for b in blocks if b["type"] == "actions"][0]
    ids = [e["action_id"] for e in actions["elements"]]
    assert PANEL_NEW_ID in ids
    assert SCHED_OPEN_ID in ids


def test_buttons_footer_slack_is_an_actions_block():
    footer = ob.buttons_footer_slack()
    assert footer["type"] == "actions"
    assert len(footer["elements"]) == 2


@pytest.mark.parametrize("text", [
    "hi", "Hello", "hey there", "help", "get started",
    "what can you do", "how do i start", "start",
])
def test_getting_started_matches_greetings_and_help(text):
    assert ob.looks_like_getting_started(text) is True


@pytest.mark.parametrize("text", [
    "summarize my unread emails every morning",
    "build me a booking site for my salon with stripe checkout",
    "why is my published app returning a 404 error",
])
def test_getting_started_ignores_real_requests(text):
    assert ob.looks_like_getting_started(text) is False


@pytest.mark.parametrize("text", ["fix bug", "stripe checkout", "add feature"])
def test_getting_started_ignores_terse_real_requests(text):
    assert ob.looks_like_getting_started(text) is False


def test_getting_started_true_for_empty():
    assert ob.looks_like_getting_started("   ") is True


def test_approval_dm_approved_has_build_button():
    text, components = ob.approval_dm_discord(approved=True)
    assert "you're in" in text.lower()
    assert components is not None
    assert components[0]["components"][0]["custom_id"] == PANEL_NEW_ID


def test_approval_dm_rejected_is_polite_and_buttonless():
    text, components = ob.approval_dm_discord(approved=False)
    assert components is None
    assert "wasn't approved" in text.lower()
    assert "Lukas" not in text
