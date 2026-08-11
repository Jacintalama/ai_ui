"""What we say to someone we do not recognize yet.

Policy, not transport. The code itself comes from the tasks service; this
module only decides how it reads.
"""


def pairing_message(code: str, link_url: str) -> str:
    """The reply an unpaired user gets.

    Deliberately short. It is read on a phone, and the only thing that matters
    is the code and where to put it.
    """
    return (
        "Hi. I don't know who you are yet, so I can't reach your IO account.\n\n"
        f"Open {link_url} while signed in to IO, and paste this code:\n\n"
        f"{code}\n\n"
        "It works once and expires in an hour. Send me anything after that and "
        "we're connected."
    )
