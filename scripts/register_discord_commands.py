"""Idempotently register the full /aiui subcommand tree with Discord.

Discord's PUT /applications/{app_id}/commands REPLACES all commands —
partial updates are not supported. This script re-PUTs all 20 subcommands
every run.

Usage:
    DISCORD_APPLICATION_ID=... DISCORD_BOT_TOKEN=... python scripts/register_discord_commands.py

If DISCORD_GUILD_ID is set, registers as a guild-scoped command (instant
update, for testing). Otherwise registers globally (up to 1 hour propagation).
"""
import os
import sys

import httpx


# Discord option types
SUB_COMMAND = 1
STRING = 3
ATTACHMENT = 11

# All 20 /aiui subcommands. Each is one Discord SUB_COMMAND.
SUBCOMMANDS = [
    ("ask",         "Ask the AI a question",                     [("question",  "What to ask",            True)]),
    ("pr-review",   "AI review of a GitHub PR",                  [("number",    "PR number",              True)]),
    ("mcp",         "Execute an MCP tool",                       [("args",      "server tool [json]",    True)]),
    ("workflow",    "Trigger an n8n workflow",                   [("name",      "Workflow name",          True)]),
    ("workflows",   "List active n8n workflows",                 []),
    ("report",      "End-of-day activity report",                []),
    ("status",      "Service health check",                      []),
    ("help",        "Show available commands",                   []),
    ("diagnose",    "AI diagnosis of recent errors",             [("container", "Container name (opt)",  False)]),
    ("analyze",     "AI analysis of a GitHub repo",              [("repo",      "owner/repo",             False)]),
    ("rebuild",     "Research + rebuild plan for repo",          [("repo",      "owner/repo",             False)]),
    ("email",       "Summarize recent emails",                   []),
    ("sheets",      "Generate report to Google Sheets",          [("type",      "daily or errors",        False)]),
    ("web-search",  "Search web + save to KB",                   [("query",     "Search query",           True)]),
    ("health",      "Code health assessment",                    [("repo",      "owner/repo",             False)]),
    ("security",    "Security audit",                            [("repo",      "owner/repo",             False)]),
    ("deps",        "Dependency report",                         [("repo",      "owner/repo",             False)]),
    ("license",     "License compliance",                        [("repo",      "owner/repo",             False)]),
    ("cronjob",     "Manage scheduled prompts",                  [("args",      'e.g. list | create "0 8 * * *" "summarize emails" | delete <id>', True)]),
    ("aiuibuilder", "Manage App Builder projects",               [
        ("args", "e.g. build <desc> | enhance <slug> <change> | list | status <slug>", True),
        # Optional file (PDF/Word/text) read into the build/enhance. Listed AFTER
        # args (required-before-optional, and so the parser still reads args first).
        ("file", "Optional PDF / Word / text file to read into the build", False, ATTACHMENT),
    ]),
]


def _build_option(opt: tuple) -> dict:
    """An option tuple is (name, description, required[, type]); type defaults
    to STRING so existing 3-tuples are unchanged."""
    opt_name, opt_desc, req = opt[0], opt[1], opt[2]
    opt_type = opt[3] if len(opt) > 3 else STRING
    return {"name": opt_name, "description": opt_desc, "type": opt_type, "required": req}


def build_command_payload() -> dict:
    return {
        "name": "aiui",
        "description": "AIUI assistant commands",
        "options": [
            {
                "name": name,
                "description": desc,
                "type": SUB_COMMAND,
                "options": [_build_option(o) for o in opts],
            }
            for name, desc, opts in SUBCOMMANDS
        ],
    }


def build_video_command_payload() -> dict:
    """A top-level /video command: `add` (up to 12 screenshot attachments) and
    `list`. Subcommands mirror the /aiui structure (type SUB_COMMAND)."""
    shot_opts = [(f"shot{i}", f"Screenshot {i}", False, ATTACHMENT) for i in range(1, 13)]
    return {
        "name": "video",
        "description": "Generate narrated videos from screenshots",
        "options": [
            {"name": "add", "description": "Add screenshots to your current video",
             "type": SUB_COMMAND, "options": [_build_option(o) for o in shot_opts]},
            {"name": "list", "description": "List your videos",
             "type": SUB_COMMAND, "options": []},
        ],
    }


def main() -> int:
    app_id = os.environ.get("DISCORD_APPLICATION_ID", "").strip()
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    guild_id = os.environ.get("DISCORD_GUILD_ID", "").strip()

    if not app_id or not token:
        print("ERROR: DISCORD_APPLICATION_ID and DISCORD_BOT_TOKEN must be set.",
              file=sys.stderr)
        return 1

    if guild_id:
        url = f"https://discord.com/api/v10/applications/{app_id}/guilds/{guild_id}/commands"
        scope = f"guild {guild_id}"
    else:
        url = f"https://discord.com/api/v10/applications/{app_id}/commands"
        scope = "GLOBAL (may take up to 1 hour to propagate)"

    payload = [build_command_payload(), build_video_command_payload()]  # PUT replaces the whole list
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}

    print(f"Registering /aiui ({len(SUBCOMMANDS)} subcommands) and /video ({scope})...")
    with httpx.Client(timeout=30.0) as client:
        r = client.put(url, headers=headers, json=payload)
    if r.status_code in (200, 201):
        print(f"OK — {r.status_code}")
        return 0
    print(f"ERROR — {r.status_code} {r.text}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
