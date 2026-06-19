import pytest
from handlers import recruiting_panel as rp


def test_panel_has_find_and_link_buttons():
    payload = rp.build_recruiting_panel()
    ids = [c["custom_id"] for row in payload["components"] for c in row["components"]
           if "custom_id" in c]
    assert rp.OUT_FIND_ID in ids
    from handlers.app_builder_panel import LINK_START_ID
    assert LINK_START_ID in ids


def test_modal_has_four_inputs_in_order():
    modal = rp.build_outreach_modal()
    assert modal["custom_id"] == rp.OUT_MODAL_ID
    input_ids = [row["components"][0]["custom_id"] for row in modal["components"]]
    assert input_ids == [rp.OUT_ROLE_INPUT, rp.OUT_LOCATION_INPUT,
                         rp.OUT_JOBDESC_INPUT, rp.OUT_COUNT_INPUT]
    styles = {row["components"][0]["custom_id"]: row["components"][0]["style"]
              for row in modal["components"]}
    assert styles[rp.OUT_JOBDESC_INPUT] == 2   # paragraph
    assert styles[rp.OUT_ROLE_INPUT] == 1      # short


def test_is_predicates():
    assert rp.is_out_find(rp.OUT_FIND_ID)
    assert not rp.is_out_find("aiuiout:nope")
    assert rp.is_out_modal(rp.OUT_MODAL_ID)
    assert not rp.is_out_modal("aiuibuild:build:")


@pytest.mark.parametrize("raw,expected", [
    ("10", 10), ("", 10), ("0", 1), ("99", 25), ("abc", 10),
])
def test_parse_outreach_modal_count(raw, expected):
    values = {rp.OUT_ROLE_INPUT: "Python", rp.OUT_LOCATION_INPUT: "",
              rp.OUT_JOBDESC_INPUT: "Hiring", rp.OUT_COUNT_INPUT: raw}
    role, location, jobdesc, count = rp.parse_outreach_modal(values)
    assert count == expected
    assert role == "Python"
    assert jobdesc == "Hiring"


def test_parse_outreach_modal_missing_count_defaults_10():
    values = {rp.OUT_ROLE_INPUT: "Python", rp.OUT_JOBDESC_INPUT: "Hiring"}
    _, _, _, count = rp.parse_outreach_modal(values)
    assert count == 10


def test_panel_has_find_jobs_plain_text_button():
    payload = rp.build_recruiting_panel()
    buttons = [c for row in payload["components"] for c in row["components"]
               if "custom_id" in c]
    ids = [c["custom_id"] for c in buttons]
    assert rp.REV_FIND_ID in ids
    label = next(c["label"] for c in buttons if c["custom_id"] == rp.REV_FIND_ID)
    assert label == "Find Jobs"  # plain text, no emoji


def test_reverse_modal_reuses_outreach_input_ids():
    modal = rp.build_reverse_modal()
    assert modal["custom_id"] == rp.REV_MODAL_ID
    assert modal["title"] == "Find Jobs"
    input_ids = [row["components"][0]["custom_id"] for row in modal["components"]]
    assert input_ids == [rp.OUT_ROLE_INPUT, rp.OUT_LOCATION_INPUT,
                         rp.OUT_JOBDESC_INPUT, rp.OUT_COUNT_INPUT]
    styles = {row["components"][0]["custom_id"]: row["components"][0]["style"]
              for row in modal["components"]}
    assert styles[rp.OUT_JOBDESC_INPUT] == 2   # paragraph (background/skills)
    assert styles[rp.OUT_ROLE_INPUT] == 1      # short


def test_parse_outreach_modal_works_on_reverse_modal_values():
    role, location, jobdesc, count = rp.parse_outreach_modal({
        rp.OUT_ROLE_INPUT: "Senior Python backend", rp.OUT_LOCATION_INPUT: "Berlin",
        rp.OUT_JOBDESC_INPUT: "6 yrs Python/Django", rp.OUT_COUNT_INPUT: "12"})
    assert (role, location, jobdesc, count) == (
        "Senior Python backend", "Berlin", "6 yrs Python/Django", 12)


def test_reverse_is_predicates():
    assert rp.is_rev_find(rp.REV_FIND_ID)
    assert not rp.is_rev_find(rp.OUT_FIND_ID)
    assert rp.is_rev_modal(rp.REV_MODAL_ID)
    assert not rp.is_rev_modal(rp.OUT_MODAL_ID)
