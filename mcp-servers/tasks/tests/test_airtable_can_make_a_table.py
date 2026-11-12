"""Asked to make a table, the chat had nothing to make one with.

Ralph, 2026-11-12, in the main chat on the live site:

    "can you check airtable and create a a table in it for aiui team
     name, status, role"

and the answer, correctly:

    "Looking at my Airtable tools, I have ones for listing bases, tables
     and records, but I do not see a tool for creating a table. So even
     on a fresh try, I may be able to read everything but not build the
     table with name, status and role myself."

That was true. The four Airtable tools read and nothing else, the
connect asked for read scopes only, and the catalogue said so in as many
words. This is the three write tools, the two scopes they need, and the
truth that follows them through the catalogue.

TWO THINGS A MODEL GETS WRONG WITH AIRTABLE, which is why the body is
built here rather than handed over as the model wrote it:

  - A FIELD TYPE USUALLY NEEDS AN `options` BLOCK. `singleSelect` wants
    its choices, `number` its precision, `date` its format. A model asked
    for a Status column reaches for `singleSelect` and Airtable answers
    422. Every type that needs options is made a text column instead,
    which is a column that exists rather than a table that does not.

  - A TABLE WITH NO FIELDS IS NOT A TABLE. Airtable rejects it, and the
    first field is the primary one, so order is not decoration.

AND THE SCOPES ARE A RECONNECT. A token holds what was approved when it
was made, so Ralph's Airtable connection from this morning can read and
cannot write however new these tools are. 403 is the answer he gets, and
the sentence under it has to say reconnect, without telling somebody
whose plan ran out to reconnect a credential that works (PR #182).
"""
import json

import pytest

import app_triage
import mytools
import oauth_providers

TOOLS = {t.name: t for t in mytools.PROVIDER_TOOLS["airtable"]}


def _body(tool_name, **args):
    return mytools._payload_for(TOOLS[tool_name], args)


def _names(tool_name, **args):
    return [f["name"] for f in _body(tool_name, **args)["fields"]]


# --- a table gets made ----------------------------------------------------

def test_there_is_a_tool_that_makes_a_table():
    assert "create_table" in TOOLS


def test_it_asks_airtable_to_make_it_in_the_base_it_was_given():
    t = TOOLS["create_table"]
    assert t.method == "POST"
    assert t.path == "/meta/bases/{base_id}/tables"


def test_the_table_is_named_what_was_asked_for():
    assert _body("create_table", base_id="appX", name="AIUI Team",
                 columns=["Name"])["name"] == "AIUI Team"


def test_the_columns_asked_for_are_the_columns_made():
    assert _names("create_table", base_id="appX", name="AIUI Team",
                  columns=["Name", "Status", "Role"]) == [
        "Name", "Status", "Role"]


def test_the_order_is_kept_because_the_first_column_is_the_primary_one():
    """Airtable makes the first field the primary field. A set would put
    Role in front of Name a third of the time."""
    assert _names("create_table", base_id="appX", name="T",
                  columns=["Role", "Name"])[0] == "Role"


def test_a_column_is_a_text_column():
    fields = _body("create_table", base_id="appX", name="T",
                   columns=["Name"])["fields"]
    assert fields == [{"name": "Name", "type": "singleLineText"}]


def test_a_type_that_needs_options_is_made_a_text_column_instead():
    """The failure this prevents: a model asked for a Status column
    sends `singleSelect`, which Airtable will not create without its
    choices, and the whole table is a 422 instead of three columns."""
    fields = _body("create_table", base_id="appX", name="T",
                   columns=[{"name": "Status", "type": "singleSelect"}])
    assert fields["fields"] == [{"name": "Status", "type": "singleLineText"}]


def test_a_type_that_needs_nothing_is_kept():
    """An email column is an email column. Airtable makes that one with
    no options at all, so there is nothing to protect anybody from."""
    fields = _body("create_table", base_id="appX", name="T",
                   columns=[{"name": "Email", "type": "email"}])
    assert fields["fields"] == [{"name": "Email", "type": "email"}]


def test_a_column_with_no_name_is_dropped():
    assert _names("create_table", base_id="appX", name="T",
                  columns=["Name", "", None, "  "]) == ["Name"]


def test_the_same_column_twice_is_one_column():
    """Airtable refuses a table with two fields of one name, and a model
    listing columns from a sentence repeats itself."""
    assert _names("create_table", base_id="appX", name="T",
                  columns=["Name", "name", "Status"]) == ["Name", "Status"]


def test_a_table_with_no_columns_still_gets_one():
    """Airtable rejects a table with an empty `fields`, so "make me a
    table called Leads" has to mean something rather than fail."""
    assert _names("create_table", base_id="appX", name="Leads",
                  columns=[]) == ["Name"]


def test_a_description_is_sent_when_there_is_one():
    assert _body("create_table", base_id="appX", name="T", columns=["A"],
                 description="the team")["description"] == "the team"


def test_no_description_is_sent_rather_than_an_empty_one():
    assert "description" not in _body("create_table", base_id="appX",
                                      name="T", columns=["A"])


# --- a row gets added -----------------------------------------------------

def test_there_is_a_tool_that_adds_a_row():
    assert "create_record" in TOOLS


def test_the_row_goes_to_the_table_it_was_given():
    t = TOOLS["create_record"]
    assert t.method == "POST"
    assert t.path == "/{base_id}/{table}"


def test_the_values_are_sent_under_fields_the_way_airtable_takes_them():
    sent = _body("create_record", base_id="appX", table="Team",
                 fields={"Name": "Ada", "Role": "engineer"})
    assert sent["fields"] == {"Name": "Ada", "Role": "engineer"}


def test_a_written_value_is_allowed_to_land_in_a_chosen_column():
    """`typecast` is what makes "Active" land in a single-select named
    Active instead of being refused as an unknown option id. A model has
    the word, never the id."""
    assert _body("create_record", base_id="appX", table="T",
                 fields={"Status": "Active"})["typecast"] is True


def test_the_columns_of_a_row_are_declared_an_object():
    """A dict declared a string is how a model's correct answer gets
    stopped at our own door (ClickUp assignees, 2026-11-09)."""
    kind, desc, required = TOOLS["create_record"].args["fields"]
    assert kind == "object", kind
    assert required is True
    assert "{" in desc, "the model is shown no shape to copy: %r" % desc


# --- several rows at once -------------------------------------------------

def test_several_rows_can_go_in_one_call():
    """The round limit is the reason this exists rather than a loop.

    A reply stops after seven rounds of tool use, and the same screenshot
    that asked for this table carried "Stopped after 7 rounds of tool
    use, so this answer may be incomplete." Five people added one call
    each is five of those seven rounds spent on typing.
    """
    assert "create_records" in TOOLS
    t = TOOLS["create_records"]
    assert t.method == "POST"
    assert t.path == "/{base_id}/{table}"


def test_each_row_is_wrapped_the_way_airtable_wants_it():
    sent = _body("create_records", base_id="appX", table="T",
                 rows=[{"Name": "Ada"}, {"Name": "Lin"}])
    assert sent["records"] == [{"fields": {"Name": "Ada"}},
                               {"fields": {"Name": "Lin"}}]
    assert sent["typecast"] is True


def test_more_rows_than_airtable_takes_are_not_all_sent():
    """Airtable's limit is ten per call and answers 422 above it, which
    would lose every row rather than the eleventh."""
    sent = _body("create_records", base_id="appX", table="T",
                 rows=[{"Name": str(n)} for n in range(25)])
    assert len(sent["records"]) == 10


def test_a_row_that_is_not_a_row_is_dropped():
    sent = _body("create_records", base_id="appX", table="T",
                 rows=[{"Name": "Ada"}, "Lin", None, {}])
    assert sent["records"] == [{"fields": {"Name": "Ada"}}]


def test_changing_a_row_changes_only_the_columns_given():
    t = TOOLS["update_record"]
    assert t.method == "PATCH", (
        "PUT clears every column the call did not name")
    assert t.path == "/{base_id}/{table}/{record_id}"


def test_a_changed_row_is_sent_the_same_way_as_a_new_one():
    sent = _body("update_record", base_id="appX", table="T", record_id="recX",
                 fields={"Status": "Done"})
    assert sent == {"fields": {"Status": "Done"}, "typecast": True}


# --- nothing claims more than the tools do --------------------------------

def test_the_catalogue_says_airtable_can_write_now():
    app = app_triage.APPS["airtable"]
    assert "add" in app.can or "create" in app.can, app.can
    assert "add or change rows" not in (app.cannot or ""), (
        "the thing it cannot do is the thing it now does")


def test_every_tool_the_catalogue_names_for_airtable_is_real():
    missing = set(app_triage.APPS["airtable"].tools) - set(TOOLS)
    assert not missing, missing


def test_what_it_still_cannot_do_is_said():
    """It cannot delete, and it cannot make a base. Both are easy to
    assume from "it can make a table", so both are stated."""
    cannot = app_triage.APPS["airtable"].cannot or ""
    assert "delete" in cannot, cannot


def test_nothing_deletes():
    assert not [t for t in TOOLS.values() if t.method == "DELETE"]


# --- the connect asks for exactly what the tools call ---------------------

def test_the_connect_asks_to_be_allowed_to_make_a_table():
    assert "schema.bases:write" in oauth_providers.AIRTABLE_SCOPE


def test_the_connect_asks_to_be_allowed_to_write_a_row():
    assert "data.records:write" in oauth_providers.AIRTABLE_SCOPE


def test_the_paste_instructions_name_the_write_scopes_too():
    """The other door. Somebody who pastes a personal access token never
    sees the consent screen, so the only place the scopes are named to
    them is this sentence, and a token made from the old one reads and
    cannot write exactly like an old OAuth connection."""
    import connections

    where = connections.PROVIDERS["airtable"].where
    assert "schema.bases:write" in where, where
    assert "data.records:write" in where, where


def test_it_still_asks_for_nothing_it_does_not_use():
    """The rule this scope was written under: every scope on the consent
    screen is one these tools call. A scope nobody uses is somebody's
    account handed over for nothing."""
    assert set(oauth_providers.AIRTABLE_SCOPE.split()) == {
        "data.records:read", "data.records:write",
        "schema.bases:read", "schema.bases:write",
        "user.email:read"}


# --- the 403 that is really "you approved this before it existed" ---------

class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload or {})

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


#: What Airtable really answers a write on a read-only token.
AIRTABLE_403 = {"error": {"type": "INVALID_PERMISSIONS_OR_MODEL_NOT_FOUND",
                          "message": "Invalid permissions, or the requested "
                                     "model was not found."}}

#: What ClickUp really answered a create_space on 2026-11-11 (PR #182).
CLICKUP_PAYWALL = {"err": "Your plan is limited to 5 usages of feature, 5 "
                          "usage.", "ECODE": "PAYWALL_004"}


def _said(payload, label="Airtable", provider="airtable", writes=True):
    return mytools._refusal(_Resp(403, payload), label, {"token": "tok_abc"},
                            provider, "create_table", writes=writes)


def test_a_write_refused_for_permission_says_to_reconnect():
    """Ralph's connection was approved this morning, when these scopes
    did not exist. Nothing he can read off Airtable's answer tells him
    that a reconnect is the fix."""
    said = _said(AIRTABLE_403)
    assert "Reconnect" in said or "reconnect" in said, said


def test_it_says_why_rather_than_just_telling_him_to_reconnect():
    assert "before" in _said(AIRTABLE_403).lower()


def test_the_vendors_own_reason_is_still_there():
    assert "Invalid permissions" in _said(AIRTABLE_403)


def test_a_nested_error_is_read_as_a_sentence_rather_than_a_dict():
    """Airtable nests its message under `error`. Printed as it arrives
    that is `{'type': 'INVALID_PERMISSIONS...'}` in the middle of a chat
    reply."""
    said = _said(AIRTABLE_403)
    assert "{" not in said and "'" not in said, said


#: Airtable's whole answer, measured live on 2026-11-12 against Ralph's
#: own read-only token. It is 178 characters, and the cap on a vendor's
#: words is 160.
AIRTABLE_LONG = {"error": {
    "type": "INVALID_PERMISSIONS_OR_MODEL_NOT_FOUND",
    "message": "Invalid permissions, or the requested model was not found. "
               "Check that both your user and your token have the required "
               "permissions, and that the model names and/or ids are "
               "correct."}}


def test_a_long_vendor_message_is_cut_between_words():
    """Measured live: the cut landed inside "and/or" and the reply read
    "...that the model names and/ If you connected Airtable before".
    A word broken in half reads like something went wrong with us."""
    said = _said(AIRTABLE_LONG)
    assert "names and/ " not in said, said


def test_a_cut_message_says_it_was_cut():
    """Otherwise a sentence that simply stops looks like the vendor's
    whole answer, and somebody goes looking for the rest of it."""
    assert "..." in _said(AIRTABLE_LONG)


def test_a_message_that_fits_is_not_touched():
    short = {"message": "Invalid permissions."}
    assert "..." not in _said(short)
    assert "Invalid permissions." in _said(short)


def test_a_plan_limit_is_still_not_a_reconnect():
    """The regression PR #182 fixed, from the other side. create_space is
    a write too, and a write refused for money must not send anybody to
    reconnect a credential that works."""
    said = _said(CLICKUP_PAYWALL, label="ClickUp", provider="clickup")
    assert "econnect" not in said, said
    assert "plan is limited" in said


def test_money_wins_over_permission_when_a_vendor_says_both():
    """Some refusals carry both words: "insufficient permissions on the
    Free plan". Reconnecting cannot buy a plan, so the sentence is left
    off. No vendor measured here answers in those words yet, so this is
    a decision about precedence rather than a recording of one; it is
    written down so it cannot drift without somebody meaning it."""
    said = _said({"message": "Insufficient permissions on the Free plan."})
    assert "econnect" not in said, said


def test_a_read_refused_is_left_exactly_as_it_was():
    """A GET cannot be short of a write scope, so nothing is added."""
    said = _said(AIRTABLE_403, writes=False)
    assert "econnect" not in said, said


def test_the_call_path_says_whether_it_was_a_write():
    """The one wire that makes the sentence above reachable: a NameError
    or a forgotten argument here is a default of False and silence."""
    import inspect
    src = inspect.getsource(mytools._call)
    assert "writes=" in src, (
        "_call asks for the refusal without saying it was a write")
