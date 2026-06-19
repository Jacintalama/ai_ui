from handlers import recruiting_labels as rl

KEYS = {"found_prefix", "select_placeholder", "edit_placeholder", "send_button",
        "footer", "none_found", "ready", "pick_one"}


def test_hire_has_all_keys_and_engineer_copy():
    lab = rl.labels_for("hire")
    assert set(lab) == KEYS
    assert lab["select_placeholder"] == "Select who to email…"
    assert lab["footer"] == "Pick who to email · ✏️ edit/add-email · then Send"
    assert lab["none_found"] == "No engineers found."
    assert lab["ready"] == "Engineers ready to review."
    assert lab["pick_one"] == "Pick at least one engineer first."
    assert lab["send_button"] == "\U0001f4e7 Send to selected"
    assert lab["found_prefix"] == "\U0001f50d Found"


def test_reverse_has_all_keys_and_company_copy():
    lab = rl.labels_for("reverse")
    assert set(lab) == KEYS
    assert "apply" in lab["select_placeholder"].lower()
    assert "apply" in lab["footer"].lower()
    assert "compan" in lab["none_found"].lower()
    assert "compan" in lab["ready"].lower()
    assert "compan" in lab["pick_one"].lower()
    assert "application" in lab["send_button"].lower()
    assert lab["found_prefix"] == "Found"


def test_unknown_and_empty_kind_fall_back_to_hire():
    assert rl.labels_for("") == rl.labels_for("hire")
    assert rl.labels_for("bogus") == rl.labels_for("hire")


def test_returns_independent_copy():
    a = rl.labels_for("hire")
    a["footer"] = "MUTATED"
    assert rl.labels_for("hire")["footer"] != "MUTATED"
