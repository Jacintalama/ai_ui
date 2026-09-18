"""HTML fragments for the agent chat panel.

Every function here returns ONE line with no newline in it. Several of these
fragments travel as SSE `data:`, where a newline is a field separator, so a
multi-line fragment arrives cut into pieces.

Server-rendered rather than assembled in the browser, following the Fusion
page: the panel then has no client-side model of the conversation that can
drift from the server's.
"""
import html
import re
import uuid


def esc(s: str) -> str:
    return html.escape(s or "")


def _initials(name: str) -> str:
    """The same two letters the agent's card shows.

    Ported from `initials` in static/agents.html rather than invented, so a
    person recognises the same mark in the panel that they picked from the
    cards. A one-letter mark here and a two-letter mark there read as two
    different agents.
    """
    parts = [p for p in str(name or "").strip().split() if p]
    if not parts:
        return "AI"
    if len(parts) == 1:
        return esc(parts[0][:2].upper())
    return esc((parts[0][0] + parts[-1][0]).upper())


def _hue(name: str) -> int:
    """Ported from `avatarHue` in static/agents.html, character for character.

    Every avatar being the same colour made two agents tell apart only by
    their letters. This must stay identical to the page's version or Ada is
    green on her card and some other colour two inches to the right.
    """
    h = 0
    for ch in str(name or ""):
        h = (h * 31 + ord(ch)) % 360
    return h


def _avatar(name: str) -> str:
    h = _hue(name)
    return (f'<div class="aav" style="background:linear-gradient(150deg,'
            f'hsl({h} 58% 46%),hsl({(h + 26) % 360} 58% 34%))">'
            f'{_initials(name)}</div>')


def new_turn_id() -> str:
    """A name for one turn.

    Short enough to sit comfortably in a CSS selector, long enough not to
    collide within one conversation. Generated here, it is always plain
    hex, so turn_body_target/turn_status_target/turn_open escaping it costs
    nothing. It is still done in all three: turn_open already escaped it
    before turn_body_target/turn_status_target existed, so the two either
    agreed with that choice or silently disagreed with it, and disagreeing
    for free was worse than agreeing for free.
    """
    return uuid.uuid4().hex[:12]


def turn_body_target(turn_id: str) -> str:
    """Where one turn's answers land, addressed by id rather than position.

    The first version of this selector was
    `#agent-thread .aturn:last-child .aturn-body`. It matched nothing the
    moment a real round ran: the send response is turn_open + turn_close +
    stream_block(), all appended by ONE beforeend swap, which makes the
    stream block a SIBLING of the turn rather than something inside it, and
    the stream block sits after the turn, so it is the stream block that
    ends up last, not the turn. A queued turn arriving later, also as a
    sibling, made it worse, not better: whichever turn was newest kept
    stealing :last-child from the one a round was still answering, so a
    drain could answer turn 1 into turn 2's body. An id does not move.
    """
    return f"#aturn-{esc(turn_id)} .aturn-body"


def turn_status_target(turn_id: str) -> str:
    """Where one turn's status line lands. See turn_body_target."""
    return f"#aturn-{esc(turn_id)} .aturn-status"


def turn_open(text: str, turn_id: str) -> str:
    """One turn: the person's message, a status row, and room for answers.

    Carries its own id because more than one turn can be open on screen at
    once (a queued message opens its own turn while an earlier one is still
    being answered), and one SSE connection answers both, one after another,
    on its way through a drain. Only an id lets a streamed fragment say which
    turn it belongs to regardless of what has been appended after it since.
    """
    return (f'<div class="aturn" id="aturn-{esc(turn_id)}">'
            '<div class="am user"><div class="ab">'
            f'{esc(text)}</div></div>'
            '<div class="aturn-status"></div>'
            '<div class="aturn-body"></div>')


def turn_close() -> str:
    """Closes the element turn_open left open."""
    return "</div>"


def into_turn(turn_id: str, fragment: str) -> str:
    """Wraps a streamed answer so it swaps into the turn that asked for it.

    Out of band and addressed by id, not left to the SSE element's own swap
    target: one connection answers more than one turn across a drain (the
    round in flight, then whatever was queued behind it), so the target has
    to travel with each message. See stream_block for the sink this content
    would otherwise land in.
    """
    return (f'<div hx-swap-oob="beforeend:{turn_body_target(turn_id)}">'
            f'{fragment}</div>')


def turn_status(turn_id: str, fragment: str) -> str:
    """Wraps a status line the way into_turn wraps an answer."""
    return (f'<div hx-swap-oob="innerHTML:{turn_status_target(turn_id)}">'
            f'{fragment}</div>')


#: How much of the question a reply quotes. Enough to recognise, not enough
#: to reprint: a paragraph you typed would otherwise reappear above every
#: answer to it, twice over when two agents both reply.
QUOTE_CHARS = 90


def _quote(text) -> str:
    """The message an answer is answering, shown above it.

    Empty when there is nothing to quote, which is the ordinary case: one
    question, one answer, and nothing above it to confuse it with. A quote
    there only repeats the line directly above.
    """
    if not isinstance(text, str) or not text.strip():
        return ""
    one_line = " ".join(text.split())
    if len(one_line) > QUOTE_CHARS:
        one_line = one_line[:QUOTE_CHARS].rstrip() + "…"
    return f'<div class="aquote">{esc(one_line)}</div>'


#: An app this platform serves, in an answer. Matched on the path rather than
#: on the host so it still works from a custom domain or a subdomain, and the
#: slug is taken from the URL rather than from anything the model said about
#: it. Kept deliberately narrow: a link to a page INSIDE an app
#: (/apps/x/about.html) is a link, not the app, and gets no card.
_APP_LINK = re.compile(
    r"https?://[^\s<>\"']+/apps/([a-z0-9][a-z0-9._-]*)/?(?=[\s<>\"']|$)")


def app_card(url: str, slug: str) -> str:
    """One app, as something to open.

    An agent that has just changed an app used to end with a sentence about
    App Builder, and the person had to go and find it. The card is drawn from
    the answer's own text, so a reload shows the same thing the round did
    rather than a bare link where a card used to be.
    """
    return ('<a class="acard" href="%s" target="_blank" rel="noopener">'
            '<span class="acard-icon" aria-hidden="true">&#9654;</span>'
            '<span class="acard-body">'
            '<span class="acard-title">%s</span>'
            '<span class="acard-sub">%s</span>'
            '</span>'
            '<span class="acard-go">Open</span></a>'
            % (esc(url), esc(slug), esc(url)))


def app_cards_for(content: str) -> str:
    """A card for every app linked in this answer, each one once."""
    seen = []
    out = []
    for match in _APP_LINK.finditer(content or ""):
        url = match.group(0)
        if url in seen:
            continue
        seen.append(url)
        out.append(app_card(url, match.group(1)))
    return "".join(out)


def agent_bubble(name: str, content: str, replying_to=None) -> str:
    """One agent's finished answer: its own row, its own name, its own avatar.

    This is the entire feature. Nothing is stacked into another agent's bubble,
    because the panel draws the bubbles itself.

    `replying_to` is the message being answered, and it is passed only when
    more than one of the person's messages is on screen unanswered. Nobody has
    to press anything to see it, which is the whole point: in an ordinary chat
    app you long-press a message to reply to it, and here the answer says what
    it belongs to by itself.
    """
    return ('<div class="am agent">'
            f'{_avatar(name)}'
            '<div class="abody">'
            f'{_quote(replying_to)}'
            f'<div class="awho">{esc(name)}</div>'
            f'<div class="atext md">{esc(content)}</div>'
            f'{app_cards_for(content)}'
            '</div></div>')


def approval_bubble(name: str, ask_id: str, calls: list[dict]) -> str:
    """An agent that stopped to ask permission.

    Identified by the question, not by the agent. One agent can be waiting on
    two answers at once, and two bubbles carrying the same id would have htmx
    resolve both Yes buttons to the first of them, so answering the second
    question would swap the first one away.

    Handed only the calls, never the whole pending payload: that also carries
    the held conversation and the owner's email, and neither belongs in a
    browser.
    """
    items = []
    for call in calls or []:
        fn = call.get("function") if isinstance(call, dict) else None
        fn = fn if isinstance(fn, dict) else {}
        name_txt = esc(str(fn.get("name") or ""))
        args_txt = esc(str(fn.get("arguments") or ""))
        items.append(f'<li><code>{name_txt}</code> '
                     f'<span class="aargs">{args_txt}</span></li>')
    aid = esc(ask_id)
    return (f'<div class="am agent awaiting" id="await-{aid}">'
            f'{_avatar(name)}'
            '<div class="abody">'
            f'<div class="awho">{esc(name)}</div>'
            f'<div class="atext">{esc(name)} wants to run:</div>'
            f'<ul class="acalls">{"".join(items)}</ul>'
            '<div class="aactions">'
            '<button class="btn primary" type="button" '
            'hx-post="/tasks/agents/chat/approve" '
            f'hx-vals=\'{{"ask_id": "{aid}", "approved": "yes"}}\' '
            f'hx-target="#await-{aid}" hx-swap="outerHTML">Yes</button>'
            '<button class="btn" type="button" '
            'hx-post="/tasks/agents/chat/approve" '
            f'hx-vals=\'{{"ask_id": "{aid}", "approved": "no"}}\' '
            f'hx-target="#await-{aid}" hx-swap="outerHTML">No</button>'
            '</div></div></div>')


def working(name: str) -> str:
    """Which agent is running right now.

    A round of three agents that each use tools can hold the stream open for
    minutes. Without this line a slow round is indistinguishable from a broken
    one.
    """
    return f'<div class="aworking">{esc(name)} is working...</div>'


def note(text: str) -> str:
    """A system line in the thread: a skipped agent, a refusal, a hint."""
    return f'<div class="am note">{esc(text)}</div>'


#: What a failure says when the round did not have a more specific reason to
#: give, and what a stored failure falls back to when it predates recording
#: one at all (an older conversation, saved before this field existed).
GENERIC_FAILURE_REASON = "Something went wrong on our side. Nothing was changed."


def failure(name: str, reason: str, fix: str = "") -> str:
    """An agent that could not answer, drawn as a failure.

    Deliberately not a bubble. These used to arrive as prose in the thread,
    in the same shape as an answer, and a failure that looks like an answer
    is one people re-read as an answer.
    """
    tail = f'<div class="afail-fix">{esc(fix)}</div>' if fix else ""
    return ('<div class="afail">'
            f'<div class="afail-what">{esc(name)} could not answer. '
            f'{esc(reason)}</div>{tail}</div>')


def stream_block() -> str:
    """The element that opens the SSE connection for one round.

    The two sse-swap divs are sinks, not destinations. One connection can
    answer more than one turn across a drain (the round in flight, then
    whatever was queued behind it), so a fixed target here cannot follow
    that; every message and working line this connection delivers already
    names its own turn and swaps out of band into it (see into_turn,
    turn_status), which leaves nothing for these two to actually show.
    `sse-close` stops the browser reconnecting, which would otherwise re-run
    a round that has already been paid for.
    """
    return ('<div class="astream" hx-ext="sse" '
            'sse-connect="/tasks/agents/chat/stream" sse-close="close">'
            '<div class="alive" sse-swap="message" hx-swap="beforeend"></div>'
            '<div class="awork" sse-swap="working" hx-swap="innerHTML"></div>'
            '</div>')


def empty_thread() -> str:
    return ('<div class="aempty">Ask anything. Every agent hears it, and '
            'the ones with something to say answer. Name one and only they '
            'reply.</div>')


def thread(messages: list[dict]) -> str:
    """A saved conversation replayed, grouped into turns.

    Roles other than user, assistant, note and failure are the round
    bookkeeping (see routes_agent_chat) and render as nothing. Notes and
    failures ARE drawn, because a round stores them on purpose: a skipped
    agent, or one that could not answer, said out loud while the round ran
    and then gone on reload leaves a conversation that no longer makes sense.

    Every user message opens a new turn, closing whichever one was open, so
    replay produces the same one-block-per-question shape a live round does.
    The turn id is the one that was stored with the message; a message from
    before turns existed has none, so a fresh one is generated on the way
    out so old conversations still render instead of erroring on a missing
    key. No messages, or none that leave anything to show (round bookkeeping
    only, say), still falls back to the empty state: that placeholder is
    what a brand new conversation and a freshly cleared one show live today,
    and this function is what /tasks/agents/chat/thread renders on every
    page load, so returning "" here would blank that out instead.
    """
    out = []
    open_turn = False
    for m in messages or []:
        role = m.get("role")
        content = m.get("content") or ""
        if role == "user":
            if open_turn:
                out.append(turn_close())
            turn_id = str(m.get("turn_id") or new_turn_id())
            out.append(turn_open(content, turn_id))
            open_turn = True
            continue
        if role == "note":
            if content:
                out.append(note(content))
        elif role == "failure":
            # reason/fix are the ones stored when the round hit this, kept so
            # a reload shows the same words that were on screen live. Falls
            # back to the generic reason only for a message saved before
            # these fields existed.
            out.append(failure(str(m.get("agent_name") or "That agent"),
                               str(m.get("reason") or GENERIC_FAILURE_REASON),
                               str(m.get("fix") or "")))
        elif role == "assistant":
            name = str(m.get("agent_name") or "Agent")
            if content:
                # The stored decision, not a fresh one. After a reload the
                # messages are in order and nothing looks ambiguous any more,
                # so recomputing would silently drop a quote that was on
                # screen a moment ago.
                out.append(agent_bubble(name, content,
                                        m.get("replying_to")))
            awaiting = m.get("awaiting")
            if isinstance(awaiting, dict) and awaiting.get("calls"):
                out.append(approval_bubble(name,
                                           str(awaiting.get("ask_id") or ""),
                                           awaiting["calls"]))
    if open_turn:
        out.append(turn_close())
    return "".join(out) if out else empty_thread()
