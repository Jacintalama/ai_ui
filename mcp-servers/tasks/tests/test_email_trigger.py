"""An email starts an automation, once, and does not empty the bank.

The whole risk of an email trigger is in four decisions, and every one of
them is a way to spend somebody's money or lose their mail:

  * a brand new rule must NOT fire on the mailbox's history. One agent turn
    per message, against years of email, is a bill and an inbox full of
    replies. This is the single most important test in the file.
  * the same email must not fire twice, and it will be offered twice,
    because the query carries a deliberate overlap.
  * a flood must not queue fifty turns. The App Builder has already been
    stopped dead by a 402 from OpenRouter once.
  * a cursor must only move forward, and must survive a restart.

All of it is pure, so all of it is tested here rather than against a
mailbox. The poller's own talking is checked on the box, because a poller is
exactly the sort of thing that passes its tests and never runs.
"""
import email_trigger as et


# --- what gets asked of Gmail ------------------------------------------------

def test_the_boxes_compose_into_a_gmail_query():
    assert et.compose_query(from_address="boss@example.com",
                            unread_only=True) == "from:boss@example.com is:unread"


def test_a_subject_with_a_space_is_quoted():
    """Unquoted, "sales report" becomes two unrelated terms and the rule
    fires on far more than the person asked for."""
    assert et.compose_query(subject="sales report") == 'subject:"sales report"'


def test_a_quote_in_the_subject_cannot_break_out_of_the_quoting():
    assert '""' not in et.compose_query(subject='the "big" one')


def test_a_hand_written_query_is_used_exactly():
    """Somebody who typed Gmail syntax meant it. ANDing the boxes onto it
    would quietly change what they wrote."""
    assert et.compose_query(from_address="ignored@example.com",
                            advanced="from:a@b.c OR from:d@e.f") == (
        "from:a@b.c OR from:d@e.f")


def test_an_empty_rule_is_refused():
    """It would match every email, and this trigger runs an agent on each
    one. Refused at the door, not discovered on the first tick."""
    assert et.query_problem("")
    assert et.query_problem("   ")


def test_a_real_query_is_accepted():
    assert et.query_problem("from:boss@example.com") == ""


def test_a_hand_written_date_is_refused():
    """The poller owns the time window. A second one would fight the cursor
    and either re-fire old mail or never fire at all."""
    assert et.query_problem("from:a@b.c after:2026/01/01")
    assert et.query_problem("before:2026/01/01")


def test_the_window_is_added_with_an_overlap():
    q = et.search_query("from:boss@example.com", 1_000_000)
    assert q == "from:boss@example.com after:%d" % (1_000_000 - et.OVERLAP_SECONDS)


def test_the_window_never_goes_negative():
    """A rule created in the first two minutes of the epoch would otherwise
    ask for after:-1, which Gmail rejects, and a rejected query is a rule
    that never fires at all."""
    assert "after:0" in et.search_query("from:a@b.c", 10)


# --- a new rule does not fire on history -------------------------------------

def test_a_new_rule_fires_on_nothing(monkeypatch):
    """The cursor starts at creation time, so the first tick's query returns
    nothing and nothing is fired. Written as the empty result that query
    produces, which is what the poller actually sees."""
    fire, skipped, cursor, seen = et.new_messages([], [], 1_700_000_000)
    assert fire == [] and skipped == 0
    assert cursor == 1_700_000_000, "the cursor moved on an empty tick"
    assert seen == []


# --- the same email does not fire twice ---------------------------------------

def _msg(mid, epoch, subject="hello"):
    return {"id": mid, "thread_id": "t-" + mid, "from": "a@b.c",
            "subject": subject, "date": "Wed, 29 Oct 2026 09:00:00 +0000",
            "snippet": "...", "internal_date": str(epoch * 1000)}


def test_a_message_already_seen_is_not_fired_again():
    """The overlap guarantees this case: the query deliberately asks for a
    window it has already covered."""
    fire, _skipped, _cursor, _seen = et.new_messages(
        [_msg("m1", 1000)], ["m1"], 1000)
    assert fire == []


def test_a_duplicate_inside_one_page_is_fired_once():
    fire, _s, _c, _seen = et.new_messages([_msg("m1", 1000), _msg("m1", 1000)],
                                          [], 500)
    assert [e["id"] for e in fire] == ["m1"]


def test_what_was_fired_is_remembered():
    _f, _s, _c, seen = et.new_messages([_msg("m1", 1000)], [], 500)
    assert "m1" in seen


def test_the_memory_is_capped_and_keeps_the_newest():
    """Unbounded, this row grows for ever. The cap has to comfortably
    exceed one overlap window or the overlap itself would re-fire mail."""
    old = ["old-%d" % i for i in range(et.SEEN_KEPT)]
    _f, _s, _c, seen = et.new_messages([_msg("new", 9999)], old, 500)
    assert len(seen) == et.SEEN_KEPT
    assert seen[0] == "new", "the newest id was dropped instead of the oldest"
    assert et.SEEN_KEPT > 50, "too small to cover an overlap window"


# --- a flood cannot queue fifty agent turns -----------------------------------

def test_a_burst_is_capped():
    msgs = [_msg("m%d" % i, 1000 + i) for i in range(20)]
    fire, skipped, _c, _seen = et.new_messages(msgs, [], 500)
    assert len(fire) == et.BURST
    assert skipped == 20 - et.BURST


def test_the_cursor_moves_past_what_was_skipped():
    """Holding it back would make the same flood arrive again on the next
    tick, and the one after that, for ever."""
    msgs = [_msg("m%d" % i, 1000 + i) for i in range(20)]
    _f, _s, cursor, _seen = et.new_messages(msgs, [], 500)
    assert cursor == 1000 + 19


def test_what_was_skipped_is_not_offered_again():
    """It is remembered as well as skipped, so the next tick does not fire
    on mail the person was already told was dropped."""
    msgs = [_msg("m%d" % i, 1000 + i) for i in range(20)]
    _f, _s, _c, seen = et.new_messages(msgs, [], 500)
    assert len(seen) == 20


def test_the_oldest_are_fired_first():
    """A thread of three must reach the agent in the order it was written,
    not backwards: Gmail returns newest first."""
    msgs = [_msg("new", 3000), _msg("mid", 2000), _msg("old", 1000)]
    fire, _s, _c, _seen = et.new_messages(msgs, [], 500)
    assert [e["id"] for e in fire] == ["old", "mid", "new"]


# --- the cursor ---------------------------------------------------------------

def test_the_cursor_only_moves_forward():
    """A message dated in the past, which happens, must not drag the window
    back over mail that was already handled."""
    _f, _s, cursor, _seen = et.new_messages([_msg("m1", 50)], [], 1000)
    assert cursor == 1000


def test_a_message_with_no_internal_date_is_fired_not_dropped():
    """Gmail always sets internalDate, but a tick must not lose an email to
    a field that arrived unexpectedly missing."""
    broken = {"id": "m1", "subject": "no date"}
    fire, _s, _c, _seen = et.new_messages([broken], [], 500)
    assert [e["id"] for e in fire] == ["m1"]


def test_a_nonsense_internal_date_does_not_crash_a_tick():
    broken = dict(_msg("m1", 1000), internal_date="not a number")
    fire, _s, cursor, _seen = et.new_messages([broken], [], 500)
    assert [e["id"] for e in fire] == ["m1"]
    assert cursor == 500, "a bad date moved the cursor"


def test_rubbish_in_the_result_does_not_crash_a_tick():
    fire, _s, _c, _seen = et.new_messages(
        [None, "a string", 7, {"no": "id"}, _msg("m1", 1000)], [], 500)
    assert [e["id"] for e in fire] == ["m1"]


def test_nothing_at_all_is_handled():
    assert et.new_messages(None, None, 0) == ([], 0, 0, [])


# --- what the agent is told ----------------------------------------------------

def test_the_agent_is_given_the_message_it_can_act_on():
    p = et.payload_for(_msg("m1", 1000, subject="Invoice 42 overdue"))
    assert p["subject"] == "Invoice 42 overdue"
    assert p["from"] == "a@b.c"
    # So the agent can read the full message or reply on the right thread
    # with its own Gmail tool, rather than the poller hauling every body.
    assert p["id"] == "m1" and p["thread_id"] == "t-m1"


def test_newlines_in_a_header_are_flattened():
    """A folded or injected header must not break the line the runner wraps
    this payload in."""
    p = et.payload_for({"id": "m1", "subject": "two\nlines", "from": "a\r\nb"})
    assert "\n" not in p["subject"] and "\r" not in p["from"]
    assert p["subject"] == "two lines"


def test_a_missing_field_becomes_an_empty_string_not_a_crash():
    p = et.payload_for({})
    assert p == {"id": "", "thread_id": "", "from": "", "subject": "",
                 "date": "", "snippet": ""}
