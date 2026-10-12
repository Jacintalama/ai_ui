"""Seed the local Docker stack: a dev admin and three agents (Ada, Mia, Dev).

    python scripts/dev_seed.py

Safe to run any number of times; a second run creates nothing new.
Everything goes through http://localhost:8090, the same way a browser would.
Reads the admin from .env.dev and never prints the password or a token.
"""
import json
import secrets
import sys
import time

from dev_check import model_ids, owned_agent_names, read_env, request, signin

MODEL = "fake-agent"
DEV_AGENT = {
    "name": "Dev",
    "role": "Developer",
    "instructions": "You are Dev, a software developer. Answer briefly.",
}


def ensure_admin(env: dict) -> str:
    token, status = signin(env)
    if token:
        print("admin: signed in")
        return token
    # The first account on a fresh Open WebUI becomes its admin.
    status, _ = request("POST", "/api/v1/auths/signup", {
        "name": "Dev Admin", "email": env["DEV_ADMIN_EMAIL"],
        "password": env["DEV_ADMIN_PASSWORD"]})
    if status != 200:
        sys.exit(f"admin: sign-up failed with status {status}")
    token, status = signin(env)
    if not token:
        sys.exit(f"admin: signed up but sign-in failed with status {status}")
    print("admin: created")
    return token


def wait_for_model(token: str, limit: float = 120.0) -> None:
    """A failed seed is never retried (routes_agents.seed_for_email marks the
    email done either way), so never seed before Open WebUI lists the model
    the agents are created on."""
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        if MODEL in model_ids(token):
            print(f"model: {MODEL} listed")
            return
        time.sleep(3)
    sys.exit(f"model: {MODEL} not listed after {int(limit)} s; not seeding")


def seed_starters(token: str) -> None:
    status, text = request("POST", "/api/tasks/agents/seed", token=token)
    if status != 200:
        sys.exit(f"seed: status {status}")
    body = json.loads(text)
    print(f"seed: seeded={body.get('seeded')} created={body.get('created')}")


def ensure_dev(token: str, names: list) -> None:
    """Create Dev the way the New agent form does (static/agents.html,
    buildAgentBody): Open WebUI's /api/v1/models/create, private to its
    owner."""
    if DEV_AGENT["name"] in names:
        print("dev: exists, skipped")
        return
    instructions = DEV_AGENT["instructions"]
    body = {
        "id": "agent-dev-" + secrets.token_hex(2),
        "name": DEV_AGENT["name"],
        "base_model_id": MODEL,
        "meta": {"description": instructions[:120], "toolIds": [],
                 "agent_instructions": instructions,
                 "role": DEV_AGENT["role"]},
        "params": {"system": instructions},
        "access_grants": [],
        "is_active": True,
    }
    status, _ = request("POST", "/api/v1/models/create", body, token=token)
    if status != 200:
        sys.exit(f"dev: create failed with status {status}")
    print("dev: created")


def main() -> int:
    env = read_env()
    token = ensure_admin(env)
    wait_for_model(token)
    seed_starters(token)
    ensure_dev(token, owned_agent_names(token))
    names = sorted(n for n in owned_agent_names(token) if n)
    print("agents: " + ", ".join(names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
