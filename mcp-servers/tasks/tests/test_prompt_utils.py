from prompt_utils import clean_user_prompt


def test_unwraps_user_request_block():
    d = 'PROJECT NAME: "x".\n<rules text>\n\nUSER REQUEST:\nA CRM, a dashboard, and booking'
    assert clean_user_prompt(d) == "A CRM, a dashboard, and booking"


def test_uses_first_marker_so_user_text_may_contain_it():
    d = "<rules>\n\nUSER REQUEST:\nmake a page titled USER REQUEST: history"
    assert clean_user_prompt(d) == "make a page titled USER REQUEST: history"


def test_enhance_prefix_stripped():
    assert clean_user_prompt("Enhance apps/shop-a1/: add a gallery") == "add a gallery"


def test_plain_description_untouched():
    assert clean_user_prompt("just build a todo list") == "just build a todo list"


def test_empty_and_none():
    assert clean_user_prompt("") == ""
    assert clean_user_prompt(None) == ""


def test_trailing_and_leading_whitespace_trimmed():
    d = "<rules>\n\nUSER REQUEST:\n   spaced prompt   "
    assert clean_user_prompt(d) == "spaced prompt"
