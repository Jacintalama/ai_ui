from handlers import recruiting_review as rr

CANDS = [
    {"id": "c0", "name": "Alice", "github_url": "gh/a", "email": "a@x.com",
     "subject": "S0", "body": "B0", "selected": True, "status": "draft"},
    {"id": "c1", "name": "Bob", "github_url": "gh/b", "email": "",
     "subject": "", "body": "", "selected": False, "status": "no_email"},
]


def test_message_has_embed_and_three_rows():
    msg = rr.build_review_message("t1", CANDS, role="Python", location="Manila")
    assert "Found 2" in msg["embeds"][0]["title"]
    rows = msg["components"]
    assert len(rows) == 3
    sel = rows[0]["components"][0]
    assert sel["custom_id"] == "aiuiout:sel:t1"
    assert [o["value"] for o in sel["options"]] == ["c0"]
    assert sel["options"][0]["default"] is True
    edit = rows[1]["components"][0]
    assert edit["custom_id"] == "aiuiout:edit:t1"
    assert [o["value"] for o in edit["options"]] == ["c0", "c1"]
    send = rows[2]["components"][0]
    assert send["custom_id"] == "aiuiout:send:t1"
    assert "(1)" in send["label"]


def test_message_with_no_emailable_omits_recipient_select():
    msg = rr.build_review_message("t1", [CANDS[1]], role="X", location="")
    sel_ids = [c["components"][0].get("custom_id", "") for c in msg["components"]]
    assert "aiuiout:sel:t1" not in sel_ids


def test_edit_modal_prefilled_and_parse():
    modal = rr.build_edit_modal("t1", CANDS[0])
    assert modal["custom_id"] == "aiuiout:editmodal:t1:c0"
    vals = {r["components"][0]["custom_id"]: r["components"][0].get("value")
            for r in modal["components"]}
    assert vals["email"] == "a@x.com" and vals["subject"] == "S0" and vals["body"] == "B0"
    assert rr.ids_from_editmodal("aiuiout:editmodal:t1:c0") == ("t1", "c0")


def test_id_parsers():
    assert rr.is_out_sel("aiuiout:sel:t1") and rr.task_id_from_sel("aiuiout:sel:t1") == "t1"
    assert rr.is_out_edit("aiuiout:edit:t1") and rr.task_id_from_edit("aiuiout:edit:t1") == "t1"
    assert rr.is_out_send("aiuiout:send:t1") and rr.task_id_from_send("aiuiout:send:t1") == "t1"
    assert rr.is_out_refresh("aiuiout:refresh:t1")
    assert rr.is_out_editmodal("aiuiout:editmodal:t1:c0")


def test_hire_kind_default_is_unchanged():
    msg = rr.build_review_message("t1", CANDS, role="Python", location="Manila")
    title = msg["embeds"][0]["title"]
    assert title == "\U0001f50d Found 2 · Python · Manila"
    assert msg["embeds"][0]["footer"]["text"] == (
        "Pick who to email · ✏️ edit/add-email · then Send")
    sel = msg["components"][0]["components"][0]
    assert sel["placeholder"] == "Select who to email…"
    send = msg["components"][2]["components"][0]
    assert send["label"] == "\U0001f4e7 Send to selected (1)"


def test_reverse_kind_renders_company_copy():
    msg = rr.build_review_message("t1", CANDS, role="Backend", location="Berlin",
                                  kind="reverse")
    title = msg["embeds"][0]["title"]
    assert title == "Found 2 companies for Backend"   # no location, "companies for"
    assert "apply" in msg["embeds"][0]["footer"]["text"].lower()
    sel = msg["components"][0]["components"][0]
    assert "apply" in sel["placeholder"].lower()
    send = msg["components"][2]["components"][0]
    assert send["label"] == "\U0001f4e7 Send applications (1)"


def test_reverse_empty_list_uses_no_companies_copy():
    msg = rr.build_review_message("t1", [], role="Backend", kind="reverse")
    assert msg["embeds"][0]["description"] == "No companies found."


def test_build_sent_message_accepts_kind_kwarg():
    out = rr.build_sent_message("Emailed 3 companies, saved 5", kind="reverse")
    assert "Emailed 3 companies" in out["content"]
    assert out["components"] == []
