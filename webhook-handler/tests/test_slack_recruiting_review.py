from handlers import slack_recruiting_review as srr
from handlers import recruiting_labels

CANDS = [
    {"id": "c0", "name": "Alice", "github_url": "gh/a", "email": "a@x.com",
     "subject": "S0", "body": "B0", "selected": True, "status": "draft"},
    {"id": "c1", "name": "Bob", "github_url": "gh/b", "email": "",
     "subject": "", "body": "", "selected": False, "status": "no_email"},
]


def _by_action_prefix(blocks, prefix):
    """First Block Kit element across all actions blocks whose action_id starts with prefix."""
    for b in blocks:
        if b.get("type") != "actions":
            continue
        for el in b["elements"]:
            if el.get("action_id", "").startswith(prefix):
                return el
    return None


def test_review_message_shape_and_ids_hire():
    msg = srr.build_review_message("t1", CANDS, role="Python", location="Manila")
    assert set(msg) == {"text", "blocks"}
    lbl = recruiting_labels.labels_for("hire")
    header = msg["blocks"][0]["text"]["text"]
    assert lbl["found_prefix"] in header and "2" in header and "Python" in header

    sel = _by_action_prefix(msg["blocks"], srr.SEL_PREFIX)
    assert sel["action_id"] == "aiuiout:sel:t1"
    assert sel["type"] == "multi_static_select"
    assert [o["value"] for o in sel["options"]] == ["c0"]  # emailable only
    assert [o["value"] for o in sel["initial_options"]] == ["c0"]  # pre-selected
    assert sel["placeholder"]["text"] == lbl["select_placeholder"]

    edit = _by_action_prefix(msg["blocks"], srr.EDIT_PREFIX)
    assert edit["action_id"] == "aiuiout:edit:t1"
    assert [o["value"] for o in edit["options"]] == ["c0", "c1"]  # all candidates
    assert edit["placeholder"]["text"] == lbl["edit_placeholder"]

    send = _by_action_prefix(msg["blocks"], srr.SEND_PREFIX)
    assert send["action_id"] == "aiuiout:send:t1"
    assert lbl["send_button"] in send["text"]["text"] and "(1)" in send["text"]["text"]
    assert _by_action_prefix(msg["blocks"], srr.REFRESH_PREFIX)["action_id"] == "aiuiout:refresh:t1"


def test_review_message_no_emailable_omits_multiselect():
    msg = srr.build_review_message("t1", [CANDS[1]], role="X", location="")
    assert _by_action_prefix(msg["blocks"], srr.SEL_PREFIX) is None
    # edit select + send/refresh still render
    assert _by_action_prefix(msg["blocks"], srr.EDIT_PREFIX) is not None
    assert _by_action_prefix(msg["blocks"], srr.SEND_PREFIX) is not None


def test_review_message_reverse_uses_company_copy():
    rev = recruiting_labels.labels_for("reverse")
    msg = srr.build_review_message("t1", CANDS, role="Backend", location="", kind="reverse")
    header = msg["blocks"][0]["text"]["text"]
    assert rev["found_prefix"] in header
    assert "companies for Backend" in header   # company phrasing, parity with Discord
    assert "\U0001f50d" not in header          # no magnifying-glass emoji for reverse
    assert _by_action_prefix(msg["blocks"], srr.SEL_PREFIX)["placeholder"]["text"] == rev["select_placeholder"]
    assert rev["send_button"] in _by_action_prefix(msg["blocks"], srr.SEND_PREFIX)["text"]["text"]


import json


def test_build_edit_modal_view_prefilled_and_meta():
    v = srr.build_edit_modal_view("t1", CANDS[0], "https://hook")
    assert v["type"] == "modal"
    assert v["callback_id"] == "aiuiout:editmodal:t1:c0"
    meta = json.loads(v["private_metadata"])
    assert meta == {"response_url": "https://hook", "task_id": "t1", "cid": "c0"}
    inits = {b["block_id"]: b["element"].get("initial_value") for b in v["blocks"]}
    assert inits["edit_email"] == "a@x.com"
    assert inits["edit_subject"] == "S0"
    assert inits["edit_body"] == "B0"


def test_edit_modal_omits_empty_initial_value():
    # Slack rejects initial_value="" — a blank-email candidate must omit the key.
    v = srr.build_edit_modal_view("t1", CANDS[1], "")
    email_el = [b for b in v["blocks"] if b["block_id"] == "edit_email"][0]["element"]
    assert "initial_value" not in email_el
    assert json.loads(v["private_metadata"])["response_url"] == ""


def test_edit_fields_and_parsers_round_trip():
    view = {"state": {"values": srr.sample_edit_state("z@x.com", "Hi", "Body!")}}
    assert srr.edit_fields_from_view(view) == ("z@x.com", "Hi", "Body!")
    assert srr.ids_from_editmodal("aiuiout:editmodal:t1:c0") == ("t1", "c0")
    meta = json.dumps({"response_url": "https://hook", "task_id": "t1", "cid": "c0"})
    assert srr.response_url_from_meta(meta) == "https://hook"
    assert srr.response_url_from_meta("not json") == ""
