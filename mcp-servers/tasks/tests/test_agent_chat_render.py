"""The panel's markup.

Two rules here are load-bearing rather than cosmetic. Every fragment is one
line, because some of them travel as SSE data where a newline is a field
separator. And an approval bubble shows the tool call only: the held
conversation and the owner's email stay on the server.
"""
import agent_chat_render as render

CALLS = [{"function": {"name": "send_email",
                       "arguments": '{"to": "boss@example.com"}'}}]


def _fragments():
    return [
        render.turn_open("hi team", "abc123def456"),
        render.turn_close(),
        render.into_turn("abc123def456", render.agent_bubble("Ada", "hi")),
        render.turn_status("abc123def456", render.working("Ada")),
        render.agent_bubble("Ada", "hello"),
        render.approval_bubble("Ada", "9f2c1ab34de54f0b", CALLS),
        render.working("Ada"),
        render.note("something happened"),
        render.stream_block(),
        render.empty_thread(),
        render.thread([{"role": "user", "content": "hi"},
                       {"role": "assistant", "agent_name": "Ada",
                        "content": "hello"}]),
    ]


def test_no_fragment_contains_a_newline():
    for fragment in _fragments():
        assert "\n" not in fragment, fragment
        assert "\r" not in fragment, fragment


def test_every_agent_answer_is_its_own_row():
    html = render.thread([
        {"role": "user", "content": "hi team"},
        {"role": "assistant", "agent_name": "Ada", "content": "Ada here"},
        {"role": "assistant", "agent_name": "Mia", "content": "Mia here"},
    ])
    assert html.count('class="am agent"') == 2
    assert "Ada here" in html and "Mia here" in html


def test_agent_answer_is_escaped():
    assert "<img" not in render.agent_bubble("Ada", '<img onerror=x>')


def test_a_turn_carries_the_message_and_a_place_for_answers():
    from agent_chat_render import turn_open
    html = turn_open("what is in my inbox?", "abc123def456")
    assert "what is in my inbox?" in html
    assert "aturn-body" in html
    assert "aturn-status" in html


def test_a_turn_escapes_what_the_person_typed():
    from agent_chat_render import turn_open
    html = turn_open('<img src=x onerror="alert(1)">', "abc123def456")
    assert "<img" not in html
    assert "&lt;img" in html


def test_a_turn_carries_its_own_id():
    """Two other turns can be on screen at once (a queued message opens its
    own while an earlier one is still running), so the id is what tells a
    streamed answer which one it belongs to. Different ids must render
    different elements, not collide on a shared class."""
    from agent_chat_render import turn_open
    first = turn_open("one", "aaa111")
    second = turn_open("two", "bbb222")
    assert 'id="aturn-aaa111"' in first
    assert 'id="aturn-bbb222"' in second
    assert "bbb222" not in first


def test_the_turn_target_functions_agree_with_what_turn_open_renders():
    """turn_body_target/turn_status_target build a selector from an id, and
    turn_open has to stamp that exact id onto the element it creates, or the
    two drift apart with nothing to notice until an answer has nowhere to
    go. This only checks the two agree on the id; whether the resulting
    selector actually resolves against a real, rendered page is checked for
    real in tests/browser/test_agent_chat_turn_targets.py, since a selector
    that looks right as a string can still match nothing once the turn sits
    next to a sibling it did not have before (see that file's docstring for
    the bug this was written to catch)."""
    from agent_chat_render import turn_body_target, turn_open, turn_status_target
    tid = "abc123def456"
    html = turn_open("x", tid)
    assert f'id="aturn-{tid}"' in html
    assert turn_body_target(tid) == f"#aturn-{tid} .aturn-body"
    assert turn_status_target(tid) == f"#aturn-{tid} .aturn-status"


def test_into_turn_and_turn_status_wrap_a_fragment_out_of_band_for_its_id():
    from agent_chat_render import into_turn, turn_status
    tid = "abc123def456"
    body = into_turn(tid, "<div>hi</div>")
    assert 'hx-swap-oob="beforeend:#aturn-abc123def456 .aturn-body"' in body
    assert "<div>hi</div>" in body
    status = turn_status(tid, "Ada is working...")
    assert 'hx-swap-oob="innerHTML:#aturn-abc123def456 .aturn-status"' in status
    assert "Ada is working..." in status


def test_approval_shows_the_call_and_offers_both_answers():
    html = render.approval_bubble("Ada", "q-1", CALLS)
    assert "send_email" in html
    assert "boss@example.com" in html
    assert ">Yes<" in html and ">No<" in html
    assert 'hx-post="/tasks/agents/chat/approve"' in html
    # Both answers say which conversation the page is showing (the agents
    # page and the office both keep it in #ap-agent): without it a Yes in a
    # private chat was looked up in the room and refused (2026-10-16).
    assert html.count('hx-include="#ap-agent"') == 2


def test_approval_never_leaks_the_held_conversation():
    # _pending_payload carries these two next to the calls. Neither may reach
    # a browser, so the renderer is only ever handed the calls.
    html = render.approval_bubble("Ada", "q-1", CALLS)
    assert "conversation" not in html
    assert "user_email" not in html


def test_stream_block_closes_the_connection_and_has_both_targets():
    html = render.stream_block()
    assert 'sse-connect="/tasks/agents/chat/stream"' in html
    assert 'sse-close="close"' in html
    assert 'sse-swap="message"' in html
    assert 'sse-swap="working"' in html



def test_an_approval_is_addressed_by_its_question_not_by_its_agent():
    """Two questions from one agent must be two elements the page can tell
    apart, or htmx sends the second one's Yes at the first one's bubble."""
    first = render.approval_bubble("Ada", "q-1", CALLS)
    second = render.approval_bubble("Ada", "q-2", CALLS)
    assert 'id="await-q-1"' in first
    assert 'id="await-q-2"' in second
    assert '"ask_id": "q-1"' in first
    assert 'hx-target="#await-q-1"' in first
    assert "q-2" not in first


def test_a_replayed_approval_keeps_the_question_it_belongs_to():
    html = render.thread([
        {"role": "assistant", "agent_id": "agent-a", "agent_name": "Ada",
         "content": "May I?", "awaiting": {"ask_id": "q-7", "calls": CALLS}},
    ])
    assert 'id="await-q-7"' in html
    assert '"ask_id": "q-7"' in html


def test_a_note_the_round_stored_is_drawn_on_the_way_back():
    """Persisted deliberately by _run_round. Dropping it here meant a skipped
    agent was explained live and unexplained on reload."""
    html = render.thread([
        {"role": "user", "content": "hi"},
        {"role": "note", "content": "An agent that was in this room no "
                                    "longer exists, so it was skipped."},
        {"role": "assistant", "agent_name": "Mia", "content": "Mia here"},
    ])
    assert "no longer exists" in html
    assert 'class="am note"' in html


def test_round_bookkeeping_still_draws_as_nothing():
    html = render.thread([{"role": "round", "content": ""}])
    # Nothing to show, so the empty state is what a person gets.
    assert "Every agent hears it" in html


def test_a_replayed_conversation_groups_answers_into_turns():
    from agent_chat_render import thread
    html = thread([
        {"role": "user", "content": "one"},
        {"role": "assistant", "agent_name": "Mia", "content": "first"},
        {"role": "user", "content": "two"},
        {"role": "assistant", "agent_name": "Ada", "content": "second"},
    ])
    assert html.count('class="aturn"') == 2
    assert html.count("</div>") >= 2
    assert html.index("first") < html.index("two"), "an answer escaped its turn"


def test_a_replay_with_no_messages_falls_back_to_the_empty_state():
    """/tasks/agents/chat/thread renders this on every page load, including a
    brand new conversation and one just cleared, and those already show the
    empty state today (see test_round_bookkeeping_still_draws_as_nothing
    above, which covers the same case with no visible content for a
    different reason). Turning this into "" would blank that placeholder out
    from under every first-time visitor and everyone who just hit Clear."""
    from agent_chat_render import empty_thread, thread
    assert thread([]) == empty_thread()
    assert thread(None) == empty_thread()


# The panel's avatars are ported from the agent cards so a person recognises
# the same mark in both places. If these drift, Ada is green on her card and
# some other colour two inches to the right in the panel.

def test_the_avatar_letters_match_the_cards():
    assert render._initials("Ada") == "AD"
    assert render._initials("Mia") == "MI"
    assert render._initials("Research Bot") == "RB"
    assert render._initials("") == "AI"
    assert render._initials(None) == "AI"


def test_the_avatar_hue_matches_the_pages_algorithm():
    """Recomputed here the way static/agents.html does it, rather than
    hardcoding an answer, so this fails if either side changes."""
    def js_avatar_hue(name):
        h = 0
        for ch in name:
            h = (h * 31 + ord(ch)) % 360
        return h

    for name in ("Ada", "Mia", "Scout", "Triage", ""):
        assert render._hue(name) == js_avatar_hue(name), name


def test_an_agent_bubble_carries_its_own_colour_and_letters():
    """DESIGN.md, Agent identity: one solid hsl(hue 45% 32%) per agent, the
    same fill as its row in the conversation list. No gradient avatars."""
    html = render.agent_bubble("Ada", "hello")
    assert "gradient" not in html
    assert f'class="aav" style="background:hsl({render._hue("Ada")} 45% 32%)"' in html
    assert ">AD<" in html
    assert "\n" not in html


def test_an_approval_bubble_carries_the_same_mark():
    html = render.approval_bubble("Mia", "ask-1", CALLS)
    assert "gradient" not in html
    assert f'class="aav" style="background:hsl({render._hue("Mia")} 45% 32%)"' in html
    assert ">MI<" in html
    assert "\n" not in html


# --- a failure is drawn as a failure, not a bubble --------------------------
#
# These used to arrive as prose in the thread, in the same shape as an
# answer, and a failure that looks like an answer is one people re-read as an
# answer.

def test_a_failure_is_not_a_bubble():
    from agent_chat_render import failure
    html = failure("Ada", "The free models are all busy.")
    assert "afail" in html
    assert 'class="am agent"' not in html, "it renders as an answer"
    assert "Ada" in html
    assert "The free models are all busy." in html


def test_a_failure_can_carry_the_fix():
    from agent_chat_render import failure
    html = failure("Ada", "The free models are all busy.",
                   "Ada is set to Auto (Free). Pick a specific model.")
    assert "Pick a specific model." in html


def test_a_failure_without_a_fix_shows_no_fix_line():
    """The fix line is real markup (afail-fix), not just an empty string
    inside afail-what. Something has to fail if the fragment always emitted
    the wrapper, fix text or not."""
    from agent_chat_render import failure
    html = failure("Ada", "The free models are all busy.")
    assert "afail-fix" not in html


def test_a_failure_escapes_everything():
    from agent_chat_render import failure
    html = failure("<b>x</b>", "<i>y</i>", "<u>z</u>")
    for tag in ("<b>", "<i>", "<u>"):
        assert tag not in html


def test_a_stored_failure_replays_with_its_own_reason_and_fix():
    """Step 8's replay must show what was actually on screen live, not
    rewrite a specific failure into the generic one. See routes_agent_chat's
    ROUTER_EXHAUSTED branch, which is what stores a reason and a fix."""
    from agent_chat_render import thread
    html = thread([
        {"role": "user", "content": "hi"},
        {"role": "failure", "agent_name": "Ada",
         "content": "the router gave up",
         "reason": "The free models are all busy right now.",
         "fix": "This agent is set to Auto (Free). Choosing a specific "
                "model on its card fixes this."},
    ])
    assert "afail" in html
    assert 'class="am agent"' not in html, "it replayed as an answer"
    assert "The free models are all busy right now." in html
    assert "Choosing a specific model on its card fixes this." in html


def test_a_stored_failure_without_a_reason_falls_back_to_the_generic_one():
    """Older conversations were saved before reason/fix existed. A missing
    key here must not blank the failure out or raise on reload."""
    from agent_chat_render import GENERIC_FAILURE_REASON, thread
    html = thread([
        {"role": "user", "content": "hi"},
        {"role": "failure", "agent_name": "Ada", "content": "whatever"},
    ])
    assert "afail" in html
    assert GENERIC_FAILURE_REASON in html


# --- a stored PASS is protocol, not an answer ------------------------------
#
# PASS is a word in a protocol between routes_agent_chat and the model, and a
# person should never read it (see the comment under `_is_pass(answer)` in
# routes_agent_chat._run_round). The round stopped storing new ones, but rows
# saved before that still hold them, and thread() redrew every one of them as
# a bubble on each load. The shapes below are what the round really stored:
# the dict is _run_round's `messages.append`, and the two contents are a bare
# PASS (the "Ada / PASS" bubble of 2026-09-24) and the Auto (Smart) pass
# copied from production into test_agent_chat_room.py as STORED_SMART_PASS.
# The owner's room still drew that exact 65-character text four times on
# 2026-10-05.

SMART_FOOTER = "\n\n*Auto (Smart): routed to the paid general model `gpt-5.5`.*"
STORED_SMART_PASS = "PASS" + SMART_FOOTER


def _stored(name, content, **extra):
    """One answer, in the shape routes_agent_chat._run_round saves it."""
    m = {"role": "assistant", "agent_id": "agent-" + name.lower(),
         "agent_name": name, "content": content, "replying_to": None}
    m.update(extra)
    return m


def test_a_stored_pass_is_not_drawn_on_the_way_back():
    html = render.thread([
        {"role": "user", "content": "anything new?", "turn_id": "aaa111aaa111"},
        _stored("Ada", "PASS"),
        _stored("Kai", STORED_SMART_PASS),
        _stored("Mia", "Two invoices are due on Friday."),
    ])
    assert html.count('class="am agent"') == 1, "a pass came back as a bubble"
    assert "Two invoices are due on Friday." in html
    assert "PASS" not in html
    assert ">Ada<" not in html and ">Kai<" not in html
    # The question stays, in its own turn. Only the passes go.
    assert html.count('class="aturn"') == 1
    assert "anything new?" in html


def test_a_stored_answer_is_drawn_without_its_route_footer():
    """The footer is the routing pipe talking (auto_smart_pipe.py _footer),
    not the agent. It comes off the last line only, the way is_pass reads
    it, so everything the agent said stays."""
    html = render.thread([
        {"role": "user", "content": "what is due?", "turn_id": "aaa111aaa111"},
        _stored("Mia", "Two invoices are due on Friday." + SMART_FOOTER),
    ])
    assert html.count('class="am agent"') == 1
    assert "Two invoices are due on Friday." in html
    assert "routed to" not in html
    assert "gpt-5.5" not in html


def test_an_answer_that_starts_with_pass_is_still_drawn():
    """Kai's stored reply (STORED_PASS_THEN_ANSWER in test_agent_chat_room.py)
    starts with PASS and then says what it did. is_pass calls that an answer,
    so the thread draws it, word for word."""
    kai = ("PASS\n\n(create-me-a-shoe-website-fe02: I inspected the files. I "
           "read public/index.html and the root index.html, but both read "
           "results were shortened by the tool.)")
    html = render.thread([
        {"role": "user", "content": "check the site", "turn_id": "aaa111aaa111"},
        _stored("Kai", kai),
    ])
    assert html.count('class="am agent"') == 1
    assert "I inspected the files." in html


def test_a_stored_pass_that_asked_permission_keeps_its_question():
    """The round does not treat a pass that came back with a tool call as a
    pass (`_is_pass(answer) and not out.get("pending")`), so _question_events
    stores it with `awaiting`. The Yes and No are what matter, so they stay;
    only the word goes."""
    html = render.thread([
        {"role": "user", "content": "send it", "turn_id": "aaa111aaa111"},
        _stored("Ada", "PASS", awaiting={"ask_id": "q-9", "calls": CALLS}),
    ])
    assert 'id="await-q-9"' in html
    assert "PASS" not in html
    assert 'class="atext md"' not in html, "the pass was drawn above the question"


def test_a_conversation_of_only_passes_falls_back_to_the_empty_state():
    """Nothing left to show is the empty state, as with round bookkeeping
    (test_round_bookkeeping_still_draws_as_nothing)."""
    assert (render.thread([_stored("Ada", STORED_SMART_PASS)])
            == render.empty_thread())


# --- the routing footer is not drawn live either ----------------------------
#
# thread() takes the footer off on the way back, but a round draws a fresh
# answer with agent_bubble straight from the model: _run_round, the
# everybody-passed fallback, _question_events and the approval resume all
# call it with the raw answer. So an Auto (Smart) agent's answer read "routed
# to the paid general model" under it until the page was reloaded (finding 7
# of docs/plans/2026-10-05-ai-agents-workspace-design.md). agent_bubble is
# the one place every one of those answers goes through.

def test_a_live_answer_is_drawn_without_its_route_footer():
    html = render.agent_bubble("Mia",
                               "Two invoices are due on Friday." + SMART_FOOTER)
    assert "Two invoices are due on Friday." in html
    assert "routed to" not in html
    assert "gpt-5.5" not in html


def test_a_footer_shaped_line_inside_an_answer_stays():
    """Only the last line is the pipe's, the one place ROUTE_FOOTER matches.
    The same words anywhere else are something the agent said, and are
    drawn as said."""
    said = ("Here is the plan.\n\n*Auto (Smart): routed to the paid general "
            "model `gpt-5.5`.*\n\nThat is what the router told me.")
    html = render.agent_bubble("Mia", said)
    assert "routed to the paid general model" in html
    assert "That is what the router told me." in html


def test_a_live_answer_that_is_only_a_footer_draws_nothing():
    """An empty answer the routing pipe signed is not a pass (is_pass reads
    what is left, and nothing is not PASS), so the round still hands it to
    agent_bubble. With the footer gone there is nothing to draw: an empty
    bubble live, and none after a reload, would disagree. So it draws none."""
    assert render.agent_bubble("Mia", SMART_FOOTER.strip()) == ""
    assert render.agent_bubble("Mia", SMART_FOOTER) == ""
    # Only a footer that was really there: an answer that was empty to
    # begin with is drawn as it always was.
    assert 'class="am agent"' in render.agent_bubble("Mia", "")


# --- the plan card of a team job --------------------------------------------

JOB_STEPS = [{"name": "Mia", "task": "Find the three latest reports."},
             {"name": "Ada", "task": "Compare them."},
             {"name": "Dev", "task": "Draft a one page summary."}]


def _buttons(html):
    import re
    return re.findall(r'<button[^>]*>([^<]*)</button>', html)


def test_a_job_card_is_one_line():
    for status in (None, {"status": "proposed"},
                   {"status": "running", "done": 1, "total": 3,
                    "current_name": "Ada"}):
        card = render.job_card("job-1", "Lead", JOB_STEPS, status)
        assert "\n" not in card and "\r" not in card


def test_a_job_card_lists_the_plan_in_order_under_the_lead():
    card = render.job_card("job-1", "Lena", JOB_STEPS, {"status": "proposed"})
    assert 'id="job-job-1"' in card
    assert 'class="am agent ajob"' in card
    assert '<div class="awho">Lena</div>' in card
    assert "Plan:" in card
    assert card.index("Mia: Find the three") < card.index("Ada: Compare them.")
    assert card.index("Ada: Compare them.") < card.index("Dev: Draft a one")


def test_a_job_card_escapes_names_and_tasks():
    card = render.job_card("job-<1>", "<b>Lead</b>",
                           [{"name": "<i>Mia</i>", "task": "<script>x</script>"},
                            {"name": "Ada", "task": "a & b"}],
                           {"status": "proposed"})
    assert "<script>" not in card
    assert "<b>Lead</b>" not in card
    assert "<i>Mia</i>" not in card
    assert "&lt;script&gt;" in card
    assert "a &amp; b" in card
    assert 'id="job-job-&lt;1&gt;"' in card


def test_a_proposed_plan_offers_start_and_cancel_and_says_nothing_else():
    card = render.job_card("job-1", "Lena", JOB_STEPS, {"status": "proposed"})
    assert _buttons(card) == ["Start", "Cancel"]
    assert 'hx-post="/tasks/agents/jobs/job-1/start"' in card
    assert 'hx-post="/tasks/agents/jobs/job-1/cancel"' in card
    assert card.count('hx-target="#job-job-1"') == 2
    assert card.count('hx-swap="outerHTML"') == 2
    assert "ajob-status" not in card


def test_a_running_job_says_which_step_and_who_and_offers_stop():
    card = render.job_card("job-1", "Lena", JOB_STEPS,
                           {"status": "running", "done": 2, "total": 3,
                            "current_name": "Dev"})
    assert "Running: step 3 of 3, Dev is working" in card
    assert _buttons(card) == ["Stop"]
    assert 'hx-post="/tasks/agents/jobs/job-1/cancel"' in card
    assert "/start" not in card


def test_a_running_job_between_steps_names_nobody():
    card = render.job_card("job-1", "Lena", JOB_STEPS,
                           {"status": "running", "done": 1, "total": 3,
                            "current_name": None})
    assert "Running: step 2 of 3" in card
    assert "is working" not in card


def test_a_job_waiting_on_the_person_says_so_and_can_be_stopped():
    card = render.job_card("job-1", "Lena", JOB_STEPS,
                           {"status": "needs_you", "done": 1, "total": 3})
    assert "Waiting for your answer above" in card
    assert _buttons(card) == ["Stop"]


def test_a_finished_job_has_its_word_and_no_buttons():
    for status, words in (("done", "Done"),
                          ("failed", "Stopped: a step failed"),
                          ("cancelled", "Cancelled")):
        card = render.job_card("job-1", "Lena", JOB_STEPS,
                               {"status": status, "done": 1, "total": 3})
        assert words in card, status
        assert _buttons(card) == [], status
        assert "hx-post" not in card, status


def test_an_unknown_job_draws_its_plan_with_nothing_to_press():
    """No status means the job could not be read (it is gone, or the
    database did not answer). Drawing a Start that does nothing, or one
    that starts something unseen, is worse than drawing none."""
    card = render.job_card("job-1", "Lena", JOB_STEPS, None)
    assert "Mia: Find the three latest reports." in card
    assert _buttons(card) == []


def _with_job(**extra):
    msg = {"role": "job", "job_id": "job-1", "agent_name": "Lena",
           "steps": JOB_STEPS}
    msg.update(extra)
    return [{"role": "user", "content": "prepare the weekly summary",
             "turn_id": "abc123def456"}, msg]


def test_the_thread_draws_a_stored_plan_with_its_live_status():
    html = render.thread(_with_job(), jobs={
        "job-1": {"status": "running", "done": 0, "total": 3,
                  "current_name": "Mia"}})
    assert 'id="job-job-1"' in html
    assert "Running: step 1 of 3, Mia is working" in html
    assert _buttons(html) == ["Stop"]


def test_the_thread_draws_a_plan_it_has_no_status_for_without_buttons():
    for jobs in (None, {}, {"job-other": {"status": "proposed"}}):
        html = render.thread(_with_job(), jobs=jobs)
        assert "Mia: Find the three latest reports." in html
        assert _buttons(html) == []


def test_existing_callers_of_thread_still_work():
    html = render.thread([{"role": "user", "content": "hi"},
                          {"role": "assistant", "agent_name": "Ada",
                           "content": "hello"}], private=False)
    assert "hello" in html
    assert render.thread([], True) == render.empty_thread(True)


def test_a_stored_plan_with_a_bad_shape_does_not_break_the_thread():
    html = render.thread(_with_job(steps="not a list", agent_name=None),
                         jobs={"job-1": {"status": "proposed"}})
    assert 'id="job-job-1"' in html
    html = render.thread(_with_job(job_id=None))
    assert "turn" in html          # the rest of the thread still drew


def test_a_job_steps_result_says_which_step_it_is():
    html = render.thread([
        {"role": "user", "content": "prepare the weekly summary"},
        {"role": "assistant", "agent_id": "agent-a", "agent_name": "Ada",
         "content": "Compared them.", "job_id": "job-1", "step": 2, "of": 3},
        {"role": "assistant", "agent_name": "Mia", "content": "plain answer"}])
    assert html.count("Step 2 of 3") == 1
    assert html.index("Step 2 of 3") < html.index("Compared them.")
    # An ordinary answer carries no label.
    assert "Step" not in html.split("plain answer")[0].split("Compared them.")[1]


def test_a_bad_step_number_draws_no_label():
    html = render.thread([
        {"role": "assistant", "agent_name": "Ada", "content": "x",
         "step": "two", "of": None}])
    assert "Step" not in html and ">x<" in html


# --- when it was said (2026-10-16) ------------------------------------------

def test_a_message_carries_the_instant_it_was_said():
    html = render.turn_open("hi", "abc123def456", at="2026-10-16T09:15:00+00:00")
    assert 'class="am user" data-at="2026-10-16T09:15:00+00:00"' in html
    bubble = render.agent_bubble("Ada", "hello", at="2026-10-16T09:15:30+00:00")
    assert 'data-at="2026-10-16T09:15:30+00:00"' in bubble


def test_a_message_without_a_time_carries_none():
    assert "data-at" not in render.turn_open("hi", "abc123def456")
    assert "data-at" not in render.agent_bubble("Ada", "hello")


def test_the_time_is_escaped_like_everything_else():
    assert '"><img' not in render.turn_open("hi", "abc", at='"><img onerror=x>')


def test_a_replayed_thread_puts_a_line_between_days():
    html = render.thread([
        {"role": "user", "content": "yesterday's question", "turn_id": "t1",
         "at": "2026-10-15T20:00:00+00:00"},
        {"role": "assistant", "agent_name": "Ada", "content": "an answer",
         "at": "2026-10-15T20:00:10+00:00"},
        {"role": "user", "content": "today's question", "turn_id": "t2",
         "at": "2026-10-16T08:00:00+00:00"},
    ])
    assert html.count('class="aday"') == 2
    assert 'datetime="2026-10-15"' in html and 'datetime="2026-10-16"' in html
    # The day line is before the turn, not inside it.
    assert html.index('datetime="2026-10-16"') < html.index('id="aturn-t2"')


def test_messages_from_before_times_were_kept_draw_no_day_line():
    html = render.thread([
        {"role": "user", "content": "old", "turn_id": "t1"},
        {"role": "assistant", "agent_name": "Ada", "content": "older answer"},
    ])
    assert 'class="aday"' not in html
    assert "data-at" not in html


def test_one_day_line_per_day_not_per_message():
    html = render.thread([
        {"role": "user", "content": "a", "turn_id": "t1", "at": "2026-10-16T08:00:00+00:00"},
        {"role": "assistant", "agent_name": "Ada", "content": "b", "at": "2026-10-16T08:00:05+00:00"},
        {"role": "user", "content": "c", "turn_id": "t2", "at": "2026-10-16T09:00:00+00:00"},
    ])
    assert html.count('class="aday"') == 1


def test_a_queued_turn_names_the_thread_of_its_own_conversation():
    """The office draws a window per conversation (office/js/dock.js), each
    thread marked data-thread; the agents page has one unmarked
    #agent-thread. A queued message has to land in the right window and
    never in a window about somebody else."""
    assert render.thread_selector(None) == '#agent-thread:not([data-thread]), [data-thread=""]'
    assert render.thread_selector("agent-ada-1") == (
        '#agent-thread:not([data-thread]), [data-thread="agent-ada-1"]')
    assert '"' not in render.thread_selector('x"y').split("[data-thread=")[1][1:-2]
