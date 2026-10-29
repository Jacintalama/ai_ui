"""A person reads the brief before the agent exists.

Asked for by Lukas on 2026-10-29: "align all the instruction he needs
before puting it to the agent when creating please ask the user first let
him see the prompt or instruction".

It is enforced in the SERVICE, not asked for in the tool's docstring. A
docstring is an instruction to a model, and this repo has been burned by
treating those as guarantees ("The prompt is not a guarantee" in
CLAUDE.md). A model that calls create with no confirm code gets a preview
back whether it wanted one or not.

It also matters more than it reads. The main chat's assistant runs on Ask
and its writes are held for approval, but a model calling this tool
natively through Open WebUI has no such brake, and the plan is to attach
this tool to every tool-capable model. This is that brake.
"""
import routes_agents as ra

OWNER = "owner@example.com"
NAME = "Crane"
BRIEF = "Watch my scheduled jobs and tell me when one fails."
ROLE = "Cron keeper"


def _code(name=NAME, brief=BRIEF, role=ROLE, access="ask", email=OWNER):
    return ra._proposal_key(email, name, brief, role, access)


# --- the code stands for the brief, not the name ------------------------------

def test_the_same_proposal_gives_the_same_code():
    assert _code() == _code()


def test_changing_one_word_of_the_brief_changes_the_code():
    """The person approved a brief. If the wording is altered between the
    preview and the create, the approval does not carry over."""
    assert _code() != _code(brief=BRIEF + " And email me.")


def test_changing_the_access_changes_the_code():
    """Approving a read-only agent must not confirm one that can act."""
    assert _code(access="ask") != _code(access="all")


def test_changing_the_role_or_name_changes_the_code():
    assert _code() != _code(name="Heron")
    assert _code() != _code(role="Something else")


def test_one_persons_code_is_not_anothers():
    assert _code() != _code(email="someone@else.com")


# --- what the person is shown -------------------------------------------------

def test_the_brief_is_shown_whole_and_never_summarised():
    """Approving a summary is approving something nobody read."""
    shown = ra.proposal_text(NAME, ROLE, "ask", BRIEF, _code())
    assert BRIEF in shown


def test_the_preview_says_nothing_has_been_made():
    shown = ra.proposal_text(NAME, ROLE, "ask", BRIEF, _code())
    assert "Nothing has been made yet" in shown


def test_the_access_is_explained_not_just_named():
    """"ask" means nothing to a person who has not read the docs."""
    shown = ra.proposal_text(NAME, ROLE, "ask", BRIEF, _code())
    assert "asks you first" in shown
    assert "Acts on its own" in ra.proposal_text(NAME, ROLE, "all", BRIEF, "x")
    assert "changes nothing" in ra.proposal_text(NAME, ROLE, "read", BRIEF, "x")


def test_the_code_is_in_the_text_so_it_can_be_sent_back():
    code = _code()
    assert code in ra.proposal_text(NAME, ROLE, "ask", BRIEF, code)


# --- the code cannot be guessed or reused -------------------------------------

def test_a_code_that_was_never_issued_is_not_live():
    assert ra._proposal_is_live("deadbeefcafe") is False


def test_an_issued_code_is_live():
    code = _code()
    ra._remember_proposal(code)
    assert ra._proposal_is_live(code) is True


def test_an_expired_code_is_not_live(monkeypatch):
    """A code found in an old transcript must not still create an agent."""
    code = _code()
    ra._remember_proposal(code)
    later = ra.time.time() + ra.PROPOSAL_TTL_SECONDS + 1
    monkeypatch.setattr(ra.time, "time", lambda: later)
    assert ra._proposal_is_live(code) is False


def test_old_proposals_do_not_pile_up_for_ever(monkeypatch):
    """Every preview adds a row to a module dict, and a chat can produce a
    lot of them."""
    ra._PROPOSALS.clear()
    ra._remember_proposal("old-one")
    later = ra.time.time() + ra.PROPOSAL_TTL_SECONDS + 1
    monkeypatch.setattr(ra.time, "time", lambda: later)
    ra._remember_proposal("new-one")
    assert "old-one" not in ra._PROPOSALS
    assert "new-one" in ra._PROPOSALS


def test_a_code_is_short_enough_to_read_back():
    """A model has to echo it, and a person may read it aloud."""
    assert 8 <= len(_code()) <= 16
