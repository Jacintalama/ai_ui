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
