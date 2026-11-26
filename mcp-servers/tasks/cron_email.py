"""Email a cron job's answer to the person who owns it.

Why (2026-11-26): the only cron runs that failed in two weeks were jobs asked
to email their summary. A schedule runs read only unless its agent may act on
its own everywhere (agent_access.effective_mode), so "email me a summary" was
refused every morning, and the main chat still told the person "you will get
an email".

Emailing yourself the answer is delivery, not an action. The platform sends
the finished answer after the run, through the owner's own connected Gmail,
to that same Gmail address and nowhere else. The agent only writes the answer
(BRIEF tells it not to send it), so nobody's access is widened.

It talks to mcp-gmail directly with `X-User-Email`, the way email_poller does.
Every function here returns a sentence or None and never raises: an email
that could not go is said on the output, and never costs the run.
"""
from __future__ import annotations

import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

GMAIL_URL = os.environ.get("GMAIL_URL", "http://mcp-gmail:8000")
TIMEOUT_SECONDS = 20

#: Longest answer put in an email. Cron outputs keeps the whole one.
MAX_BODY = 20000

#: Where the person changes or stops the job.
PAGE = os.environ.get("PUBLIC_BASE_URL",
                      "https://ai-ui.coolestdomain.win").rstrip("/") + "/cronjobs"

#: Added to the agent's brief on a job that emails. Without it the agent
#: reads "email me a summary" in its task, tries send_email, is refused (it
#: is read only on a schedule) and the run is marked refused, which is the
#: failure this module exists to end.
BRIEF = ("This job's answer is emailed to the person by the platform when you "
         "finish, to their own Gmail. Do not send it yourself and do not make "
         "a draft of it: write the answer itself, as the email's content, "
         "even where the task says to email or send it.")

#: Said on the output when the email could not go.
NOT_CONNECTED = ("I could not email this: Gmail is not connected. Connect "
                 "Gmail on Connections and the next run will be emailed.")
COULD_NOT = ("I could not email this: Gmail did not take it this time. It is "
             "here in Cron outputs, and the next run will try again.")

#: Said when a job is set to email and Gmail is not connected.
CONNECT_FIRST = ("To email you the answer, connect Gmail first: open "
                 "Connections, connect Gmail, then turn this on.")


def subject_for(name: str, status: str) -> str:
    """The job's name, and a note when the run did not finish."""
    name = " ".join(str(name or "").split()) or "Your cron job"
    if status == "completed":
        return name
    return name + " (did not finish)"


_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.M)
_MARKS = re.compile(r"\*\*|__|`")


def plain(text: str) -> str:
    """Markdown as a person would read it in a plain text email."""
    text = str(text or "").replace("\r\n", "\n")
    text = _LINK.sub(r"\1 (\2)", text)
    text = _HEADING.sub("", text)
    return _MARKS.sub("", text).strip()


def body_for(name: str, result: str) -> str:
    """The email: the answer, then where it came from and how to stop it."""
    text = plain(result) or "This run gave no answer."
    if len(text) > MAX_BODY:
        text = (text[:MAX_BODY].rstrip()
                + "\n\n[cut here: the full answer is in Cron outputs]")
    name = " ".join(str(name or "").split()) or "your cron job"
    return (text + "\n\n--\nSent by your cron job \"%s\". Change or stop it "
            "on Cron Jobs: %s" % (name, PAGE))


async def _get(path: str, user_email: str):
    """GET on mcp-gmail as this person. A seam, so tests need no network."""
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        r = await client.get(GMAIL_URL.rstrip("/") + path,
                             headers={"X-User-Email": user_email})
    return r.json() if r.status_code == 200 else {"error": r.status_code}


async def _post(path: str, user_email: str, body: dict):
    """POST on mcp-gmail as this person. A seam, so tests need no network."""
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        r = await client.post(GMAIL_URL.rstrip("/") + path,
                              headers={"X-User-Email": user_email}, json=body)
    return r.json() if r.status_code == 200 else {"error": r.status_code}


async def _account(user_email: str):
    """(connected, address) for this person's Gmail. Raises on an outage."""
    status = await _get("/auth/status", user_email)
    if not isinstance(status, dict) or not status.get("connected"):
        return False, None
    address = status.get("account")
    if not isinstance(address, str) or "@" not in address:
        return True, None
    return True, address


async def gmail_problem(user_email: str) -> str | None:
    """Why a job cannot be set to email this person, or None.

    Only "not connected" is a reason. An outage is not: a create must never
    be refused because the Gmail service was restarting, and the run itself
    will say so if it still cannot send.
    """
    try:
        connected, _address = await _account(user_email)
    except Exception:                                       # noqa: BLE001
        logger.warning("could not check Gmail for a cron job's email")
        return None
    return None if connected else CONNECT_FIRST


async def send(user_email: str, name: str, status: str,
               result: str) -> str | None:
    """Email this run's answer to the owner's own Gmail. None when it went,
    else the sentence to put on the output. Never raises.

    The address is the one their own Gmail connection belongs to, read from
    mcp-gmail, never anything from the job, the prompt or the answer: this
    can only ever email a person themselves.
    """
    try:
        connected, address = await _account(user_email)
    except Exception:                                       # noqa: BLE001
        # No exception text: an httpx error carries the internal URL.
        logger.warning("could not reach Gmail to email a cron job's answer")
        return COULD_NOT
    if not connected:
        return NOT_CONNECTED
    if not address:
        return COULD_NOT
    try:
        sent = await _post("/gmail_send_email", user_email, {
            "to": address,
            "subject": subject_for(name, status),
            "body": body_for(name, result),
        })
    except Exception:                                       # noqa: BLE001
        logger.warning("Gmail did not take a cron job's email")
        return COULD_NOT
    if not isinstance(sent, dict) or not sent.get("success"):
        logger.warning("Gmail refused a cron job's email")
        return COULD_NOT
    return None
