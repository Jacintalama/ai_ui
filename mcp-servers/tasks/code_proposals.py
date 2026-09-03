"""The token that stands between an agent's idea and a real build.

Proposing writes a row and changes nothing. Applying consumes the row, and
that consumption is the single-use guarantee: the UPDATE that marks the row
used is the same statement that reads it, so two confirms arriving at once
cannot both come away with a proposal.

The slug is read back out of the row rather than taken from the caller, so
a token cannot be pointed at a different app after the fact.
"""
import logging
import secrets

from sqlalchemy import text

from db import session

logger = logging.getLogger(__name__)

#: Long enough that a proposal is still valid while somebody reads it and
#: replies, short enough that an abandoned one cannot be applied tomorrow.
PROPOSAL_TTL_SECONDS = 1800

#: A change description becomes a build agent's instruction, so it is
#: bounded here rather than in whichever route happens to call this. Far
#: more than any real request needs, far less than a stored prompt that
#: could cost somebody an expensive run.
MAX_DESCRIPTION_CHARS = 4000


class ProposalError(Exception):
    """Refused. `reason` is written to be shown to the person asking."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


async def create_proposal(user_email: str, slug: str, description: str) -> str:
    slug = slug.strip() if isinstance(slug, str) else ""
    description = description.strip() if isinstance(description, str) else ""
    if not slug:
        raise ProposalError("no app was named")
    if not description:
        raise ProposalError("there was no change to propose")
    if len(description) > MAX_DESCRIPTION_CHARS:
        raise ProposalError("that change description is too long")

    token = secrets.token_urlsafe(24)
    async with session() as s:
        await s.execute(
            text("INSERT INTO tasks.agent_proposals"
                 " (token, user_email, slug, description)"
                 " VALUES (:token, :email, :slug, :description)"),
            {"token": token, "email": user_email, "slug": slug,
             "description": description},
        )
        await s.commit()
    return token


async def consume_proposal(user_email: str, token: str) -> dict:
    """Mark a proposal used and return what it asked for.

    Every refusal says the same thing. Telling the difference between "no
    such token" and "that is not yours" would let somebody map which
    tokens exist.
    """
    if not isinstance(token, str) or not token.strip():
        raise ProposalError("that approval code is not usable")

    async with session() as s:
        row = (await s.execute(
            text("UPDATE tasks.agent_proposals"
                 "   SET used_at = now()"
                 " WHERE token = :token"
                 "   AND user_email = :email"
                 "   AND used_at IS NULL"
                 "   AND created_at > now() - make_interval(secs => :ttl)"
                 " RETURNING slug, description"),
            {"token": token.strip(), "email": user_email,
             "ttl": PROPOSAL_TTL_SECONDS},
        )).first()
        await s.commit()

    if row is None:
        raise ProposalError("that approval code is not usable")
    return {"slug": row[0], "description": row[1]}


async def restore_proposal(user_email: str, token: str) -> None:
    """Put a consumed proposal back, for a build that provably never
    started.

    Only ever called for failures the builder raises BEFORE it inserts
    its task row: no such app, wrong role, one already in flight. Any
    other failure leaves the token spent, because a token restored after
    work began could start that work a second time.
    """
    async with session() as s:
        await s.execute(
            text("UPDATE tasks.agent_proposals"
                 "   SET used_at = NULL"
                 " WHERE token = :token AND user_email = :email"),
            {"token": (token or "").strip(), "email": user_email})
        await s.commit()
