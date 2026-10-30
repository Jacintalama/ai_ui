"""An app the platform can act in has to be NAMED where the router looks.

Measured against the live router on 2026-10-30, not reasoned about. Trello
had just been connected: the credential was stored, the per-user tools
answered, `whoami` returned the right account and `list_my_boards` returned
the board. Asked "can you see my trello?", the chat said:

    I can't see your Trello in this reply, I don't have any tools available
    here to access it.

Nothing was broken. Jev scores each tool against its note in TOOL_NOTES and
keeps the ones at or above the cut, so the note is the entire basis for the
decision, and the note said "GitHub, Notion, ClickUp, n8n workflows". Trello
was not in it, so the tool holding every Trello tool was never picked, the
assistant never ran, and the free model answered about an account it cannot
see. Four phrasings, three runs each:

    can you see my trello?             0/3  ->  3/3
    what boards do I have in trello    2/3  ->  3/3
    add a card to my trello board      1/3  ->  3/3
    move my trello card to done        0/3  ->  3/3

This is the same failure as `video`, which went unpicked for 140 turns
because its note described making a video and not listing one
(test_jev_notes_cover_listing.py). That one cost a feature nobody could
reach. This one is worse in one way: the platform denies having a
capability at the exact moment somebody asks for it, right after they did
the work of connecting the account.

So the rule generalises past listing. Every provider with tools that run as
the person must be named in the note, or connecting it buys them nothing.
This test is about the NAME, not a score: scores move with the model and
would make it flaky, while the wording is ours and is the thing that was
wrong.
"""
import agent_jev
import mytools

#: The tool that fronts every connected app. It is not a row in public.tool;
#: it stands for whatever the person has connected.
GATEWAY = "server:mcp-proxy"

#: What a provider is called in a sentence somebody would actually write.
#: The key is the provider id, the value is what has to appear in the note.
SPOKEN = {
    "github": "github",
    "clickup": "clickup",
    "trello": "trello",
    "notion": "notion",
    "n8n": "n8n",
    "airtable": "airtable",
    "hubspot": "hubspot",
    "zapier": "zapier",
}


def _note():
    return " ".join(str(agent_jev.TOOL_NOTES.get(GATEWAY, "")).split()).lower()


def test_every_app_that_can_run_as_the_person_is_named():
    """The rule the measurement produced, and the one that would have caught
    this before a person connected an account and was told it was not
    there."""
    silent = [pid for pid in sorted(mytools.PROVIDER_TOOLS)
              if SPOKEN.get(pid, pid) not in _note()]
    assert silent == [], (
        "these apps have tools that run as the person, and the router "
        "cannot pick them because the note never says their name: "
        + ", ".join(silent))


def test_a_new_provider_cannot_be_added_without_a_name_for_it():
    """Adding a provider to PROVIDER_TOOLS and forgetting the note is the
    exact shape of this bug, so the test has to fail for a provider it has
    never heard of rather than skip it."""
    unknown = [pid for pid in mytools.PROVIDER_TOOLS if pid not in SPOKEN]
    assert unknown == [], (
        "no word recorded for: " + ", ".join(unknown) + ". Add it to SPOKEN "
        "and name the app in the router's note.")


def test_trello_is_named_because_that_is_the_one_that_was_measured():
    note = _note()
    assert "trello" in note
    assert "board" in note and "card" in note


def test_the_note_says_doing_and_not_only_seeing():
    """"add a card to my trello board" scored 1/3 against a note that
    described services rather than what is done with them. A note that only
    names nouns leaves every write unreachable."""
    assert "adding" in _note()


def test_the_gateway_still_covers_the_web_it_always_covered():
    """The note gained the connected apps. It must not have lost web search
    or the knowledge graph on the way, which nothing else offers."""
    note = _note()
    for kept in ("web search", "flights", "knowledge graph"):
        assert kept in note, kept


def test_every_named_app_actually_has_tools_behind_it():
    """The other direction. A name in the note with nothing behind it sends
    the assistant to look for tools that do not exist, which reads to the
    person as the assistant failing at something it promised."""
    note = _note()
    promised = [word for pid, word in SPOKEN.items() if word in note]
    for word in promised:
        pid = next(p for p, w in SPOKEN.items() if w == word)
        assert mytools.PROVIDER_TOOLS.get(pid), pid
