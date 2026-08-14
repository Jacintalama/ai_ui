"""What we say to someone we do not recognize yet.

Policy, not transport. The code itself comes from the tasks service; this
module only decides how it reads.
"""


def pairing_message(code: str, link_url: str) -> str:
    """The reply an unpaired user gets.

    Deliberately short. It is read on a phone, and the only thing that matters
    is the code and where to put it.

    The last line exists because of a real dead end. On Telegram and the
    terminal, anyone messaging IO had already found IO, so an account could be
    assumed. Slack and Discord broke that: the bot sits in a workspace or a
    server, and a colleague who has never heard of IO can message it and get
    back a code, an instruction to sign in, and no idea what they are signing
    in to. A code is worth nothing without an account to attach it to.

    A code is safe to hand a stranger. It links whichever account redeems it,
    so someone with no account cannot use it at all, and someone who then makes
    one links their own. What it must not do is leave them stuck.
    """
    home = link_url.split("/tasks/")[0] if "/tasks/" in link_url else link_url
    return (
        "Hi. I don't know who you are yet, so I can't reach your IO account.\n\n"
        f"Open {link_url} while signed in to IO, and paste this code:\n\n"
        f"{code}\n\n"
        "It works once and expires in an hour. Send me anything after that and "
        "we're connected.\n\n"
        f"New here? IO is your own AI assistant, with your own memory, files "
        f"and tools. Make an account at {home} first, then paste the code."
    )
