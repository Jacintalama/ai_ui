"""Create the ready-made agents everyone gets.

A platform agent is an ordinary agent carrying a wildcard read grant, the same
mechanism the base models use. Everyone sees it; only its owner can edit it.

The grant is NOT set here. It is applied by grant_platform_agents.sql, because
the create endpoint filters access_grants through the sharing.public_models
permission and that is false on this platform. Writing the row directly is the
path that was actually proved to work.

Idempotent: an agent that already exists is updated rather than duplicated.
Run inside mcp-proxy with ADMIN_TOKEN set.
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = "https://ai-ui.coolestdomain.win"
# Cloudflare 1010-blocks urllib's default User-Agent on this domain.
UA = "Mozilla/5.0"

# Every agent needs a real base model. A model row with base_model_id NULL is
# not a derived model at all: the list endpoint filters those out, so an agent
# created that way would be invisible to the page that exists to show it.
BASE_MODEL = "gpt-4o-mini"

AGENTS = [
    {
        "id": "agent-research-assistant-0001",
        "name": "Research Assistant",
        "system": (
            "You research questions carefully and answer with what you found, "
            "not with what you assume. Search the web when the answer depends "
            "on current facts. Say plainly when you could not find something, "
            "and never present a guess as a finding. Keep answers short and "
            "put the conclusion first."
        ),
        "tools": ["server:mcp-proxy"],
    },
    {
        "id": "agent-inbox-triage-0002",
        "name": "Inbox Triage",
        "system": (
            "You read the user's unread email and tell them what actually "
            "needs them. Group messages into: needs a reply today, can wait, "
            "and no action. Give one line per message with who it is from and "
            "what they want. Never send or delete anything without being "
            "asked to."
        ),
        "tools": ["gmail"],
    },
]


def body_for(a):
    return {
        "id": a["id"],
        "name": a["name"],
        "base_model_id": BASE_MODEL,
        "meta": {
            "description": a["system"][:120],
            "toolIds": a["tools"],
            # The instructions are stored TWICE on purpose. The list endpoint
            # blanks params for any caller without write access, and a platform
            # agent is read-only to everyone except its owner, so params.system
            # arrives as null for every user who might want to copy it.
            # Measured on production: meta survives, params does not. Without
            # this copy the "Duplicate to my own" button copies an empty string.
            "agent_instructions": a["system"],
        },
        "params": {"system": a["system"]},
        "is_active": True,
    }


def post(path, body, token):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": UA,
                 "Authorization": "Bearer " + token})
    return urllib.request.urlopen(req, timeout=30)


def is_duplicate(err):
    """A duplicate id comes back as 401, not 400 or 409.

    Measured on production: the body is
    {"detail": "Uh-oh! This model id is already registered. ..."}. Keying on
    the status alone would treat a real permission failure as a duplicate and
    quietly overwrite, or treat a duplicate as a permission failure and stop.
    """
    if err.code != 401:
        return False
    try:
        detail = json.loads(err.read(400).decode("utf-8", "replace")).get("detail")
    except Exception:
        return False
    return isinstance(detail, str) and "already registered" in detail.lower()


def main():
    token = os.environ.get("ADMIN_TOKEN")
    if not token:
        print("ADMIN_TOKEN is not set")
        return 1

    failures = 0
    for a in AGENTS:
        body = body_for(a)
        try:
            post("/api/v1/models/create", body, token)
            print("created", a["id"])
        except urllib.error.HTTPError as e:
            if is_duplicate(e):
                try:
                    post("/api/v1/models/model/update?id=" + a["id"], body, token)
                    print("updated", a["id"])
                except urllib.error.HTTPError as e2:
                    print("FAILED to update", a["id"], e2.code)
                    failures += 1
            else:
                print("FAILED", a["id"], e.code)
                failures += 1
        except urllib.error.URLError as e:
            # This link drops often enough that one timeout should not look
            # like a rejection.
            print("FAILED", a["id"], "URLError", e.reason)
            failures += 1

    print("done, %d failure(s)" % failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
