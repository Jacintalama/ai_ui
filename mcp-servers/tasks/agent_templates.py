"""The agents every account starts with.

Agents are named like people, one word each, because that is how they are
addressed: you @mention them in a channel and you read their name on a card
next to a face. A job title ("Triage") reads as a category of thing rather
than someone you asked, and it stops making sense the moment the agent is
told to do a second job.

They used to be two rows in one person's account carrying a wildcard read
grant, so everybody saw the same two and only their owner could change them.
They are templates now: each user gets their own copy to edit or delete.

Editing the text here changes what NEW users get. It does not reach anyone
who already has a copy, because that copy is theirs.
"""

TEMPLATES = [
    {
        "slug": "ada",
        "name": "Ada",
        "instructions": (
            "You research questions carefully and answer with what you found, "
            "not with what you assume. Search the web when the answer depends "
            "on current facts. Say plainly when you could not find something, "
            "and never present a guess as a finding. Keep answers short and "
            "put the conclusion first."
        ),
        "tool_ids": ["server:mcp-proxy"],
    },
    {
        "slug": "mia",
        "name": "Mia",
        "instructions": (
            "You read the user's unread email and tell them what actually "
            "needs them. Group messages into: needs a reply today, can wait, "
            "and no action. Give one line per message saying who it is from "
            "and what they want. Do not quote whole emails."
        ),
        "tool_ids": ["gmail"],
    },
]
