#!/usr/bin/env python3
"""Push the AIUI voice agent config (prompt + App Builder tools) to ElevenLabs.

Config-as-code for the ElevenLabs Conversational AI agent — the prompt and the
three App Builder webhook tools live HERE, not in the dashboard. Idempotent:
tools are matched by name (create or update), the agent prompt is replaced,
and tool_ids are merged (existing tools are never dropped).

Usage (on the VPS host — stdlib only, no pip deps):
    python3 scripts/setup_voice_agent.py --env-file /root/proxy-server/.env --dry-run
    python3 scripts/setup_voice_agent.py --env-file /root/proxy-server/.env

Reads ELEVENLABS_API_KEY, ELEVENLABS_AGENT_ID, VOICE_WEBHOOK_SECRET from the
environment (or --env-file). Never prints secret values.
"""
import argparse
import json
import os
import sys
import urllib.request

API = "https://api.elevenlabs.io"
WEBHOOK_BASE = "https://ai-ui.coolestdomain.win/webhook/voice"

AGENT_PROMPT = """You are A.I.U.I. (pronounced "ay-eye-you-eye"), a voice assistant for a software development team. Users speak commands to you and you execute them using your available tools.

When a user asks you to do something:
1. Identify which tool matches their request
2. Call the tool with the right parameters
3. Summarize the result conversationally for speech
4. For long results, say a brief summary and mention "I've posted the full details in the text channel"

Available tools map to these capabilities:
- status: check if services are running
- ask: answer general questions
- security: security audit a code repository
- health: code health assessment
- deps: check for outdated dependencies
- license: check license compliance
- pr-review: review a GitHub pull request (needs PR number)
- sheets: write a report to Google Sheets
- analyze: extract business requirements from a repo
- rebuild: research and plan rebuilding an app
- workflows: list automation workflows
- report: generate end-of-day summary
Default repository is TheLukasHenry/proxy-server unless the user specifies otherwise.

## Building websites (App Builder)
When the user wants to create or build a website or app, run this flow one question at a time:
1. First ask: "Would you like to start from a template, or a blank project?"
2. If they choose template: ask what kind of site it is, then call list_templates and suggest the 2 or 3 closest matching templates by label, conversationally. Never read the whole list aloud.
3. Ask for a short description: the site's name plus one or two details (purpose, style, or color).
4. Read back one short summary line, for example: "A restaurant site called Mario's, from the restaurant template — should I build it?" Wait for a clear yes.
5. On yes, call start_build with description, and template_key ONLY when the user picked a template (omit it for a blank project).
6. After it starts: say it takes a few minutes, the preview link will be posted in the text channel, and they can ask "is my build done?" anytime.
7. When they ask whether it's done, call build_status and relay the answer in one sentence.

Be concise in speech — one or two short sentences per reply. Technical details go to the text channel.
IMPORTANT: Common voice commands users will say:
- "status" (may sound like "tadous", "stados", "sta-dus")
- "health" followed by a repository like "jacintalama/devtech"
- "security", "deps", "workflows", "report", "analyze", "rebuild"
- "sheets", "pr review", "license"
- "create a website", "build me a site", "make an app" — start the App Builder flow above
Language instructions: Always respond in the same language the user is speaking. If the user switches languages, follow them. Do not default to English unless the user speaks English."""


# Proper nouns the ASR model can't know — biases recognition so spelled-out
# names stop coming back mangled (live 2026-06-12: J-A-C-I-N-T -> "Jasent").
# Keep the list FOCUSED: too many keywords degrades general recognition.
ASR_KEYWORDS = [
    "AIUI",
    "Jacint", "Jasen", "Alama",
    "Lukas", "Herajt",
    "Ralph", "Benitez",
    "Clarenz", "Bacalla",
]


def build_agent_patch(tool_ids: list) -> dict:
    """The single PATCH payload: prompt + tool ids + ASR keyword bias.
    ElevenLabs deep-merges PATCHes, so untouched config (voice, turn
    settings) survives."""
    return {"conversation_config": {
        "agent": {"prompt": {
            "prompt": AGENT_PROMPT,
            "tool_ids": tool_ids,
        }},
        "asr": {"keywords": ASR_KEYWORDS},
    }}


def _str_prop(description: str) -> dict:
    return {"type": "string", "description": description}


def build_tool_definitions(secret: str) -> list:
    """The three App Builder webhook tools, shaped like the live tools
    (captured 2026-06-12 from GET /v1/convai/tools)."""
    def tool(name: str, description: str, required: list, props: dict) -> dict:
        return {
            "type": "webhook",
            "name": name,
            "description": description,
            "response_timeout_secs": 30,
            "disable_interruptions": True,
            "api_schema": {
                "url": f"{WEBHOOK_BASE}/{name}",
                "method": "POST",
                "request_headers": {"X-Voice-Secret": secret},
                "request_body_schema": {
                    "type": "object",
                    "required": required,
                    "description": f"Request body for {name}",
                    "properties": props,
                },
                "content_type": "application/json",
            },
        }

    return [
        tool(
            "list_templates",
            "List the available App Builder website templates (key, label, "
            "description). Call this when the user wants to start from a "
            "template, then suggest the 2-3 closest matches — never read "
            "the whole list aloud.",
            [],
            {"reason": _str_prop("Optional: what kind of site the user wants")},
        ),
        tool(
            "start_build",
            "Start building a website/app with the App Builder. Call ONLY "
            "after the user confirmed the summary. Takes a few minutes; the "
            "preview link is posted to the Discord text channel.",
            ["description"],
            {
                "description": _str_prop(
                    "One or two sentences describing the site: name, purpose, "
                    "style. Example: a restaurant site called Mario's with a "
                    "menu page"
                ),
                "template_key": _str_prop(
                    "Template key exactly as returned by list_templates, e.g. "
                    "restaurant. OMIT for a blank project."
                ),
            },
        ),
        tool(
            "build_status",
            "Check whether the current website build is finished. Use when "
            "the user asks if their build/site is done or ready.",
            [],
            {
                "task_id": _str_prop(
                    "Optional build task id; omit to use the most recent build"
                ),
            },
        ),
    ]


def plan_tool_changes(existing: list, wanted: list):
    """(creates, updates) — match by tool name; unrelated tools untouched."""
    by_name = {
        (t.get("tool_config") or {}).get("name"): t.get("id")
        for t in existing
    }
    creates = [w for w in wanted if w["name"] not in by_name]
    updates = [(by_name[w["name"]], w) for w in wanted if w["name"] in by_name]
    return creates, updates


def merged_tool_ids(current_ids: list, new_ids: list) -> list:
    """Existing ids first (never dropped), new ones appended, de-duplicated."""
    out = list(current_ids or [])
    for i in new_ids:
        if i not in out:
            out.append(i)
    return out


# --- everything below talks to the API (not unit-tested) -------------------

def _read_env_file(path: str) -> None:
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _req(method: str, path: str, key: str, payload=None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(
        API + path, data=body, method=method,
        headers={"xi-api-key": key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(r, timeout=30) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", help="parse KEY=VALUE pairs into the env first")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.env_file:
        _read_env_file(args.env_file)

    key = os.environ.get("ELEVENLABS_API_KEY", "")
    agent_id = os.environ.get("ELEVENLABS_AGENT_ID", "")
    secret = os.environ.get("VOICE_WEBHOOK_SECRET", "")
    missing = [n for n, v in [("ELEVENLABS_API_KEY", key),
                              ("ELEVENLABS_AGENT_ID", agent_id),
                              ("VOICE_WEBHOOK_SECRET", secret)] if not v]
    if missing:
        print("Missing env:", ", ".join(missing))
        return 1

    wanted = build_tool_definitions(secret)
    existing = _req("GET", "/v1/convai/tools", key).get("tools", [])
    creates, updates = plan_tool_changes(existing, wanted)
    print(f"tools: {len(existing)} existing; create {[t['name'] for t in creates]}; "
          f"update {[u[1]['name'] for u in updates]}")

    agent = _req("GET", f"/v1/convai/agents/{agent_id}", key)
    prompt_cfg = (agent.get("conversation_config", {})
                  .get("agent", {}).get("prompt", {}))
    current_ids = prompt_cfg.get("tool_ids") or []
    prompt_changes = prompt_cfg.get("prompt") != AGENT_PROMPT
    current_keywords = (agent.get("conversation_config", {})
                        .get("asr", {}).get("keywords") or [])
    keyword_changes = current_keywords != ASR_KEYWORDS
    print(f"agent: {len(current_ids)} tool ids; prompt update needed: {prompt_changes}; "
          f"keyword update needed: {keyword_changes}")

    if args.dry_run:
        print("dry-run: no changes written")
        return 0

    new_ids = []
    for cfg in creates:
        created = _req("POST", "/v1/convai/tools", key, {"tool_config": cfg})
        new_ids.append(created["id"])
        print(f"created tool {cfg['name']}")
    for tool_id, cfg in updates:
        _req("PATCH", f"/v1/convai/tools/{tool_id}", key, {"tool_config": cfg})
        new_ids.append(tool_id)
        print(f"updated tool {cfg['name']}")

    payload = build_agent_patch(merged_tool_ids(current_ids, new_ids))
    _req("PATCH", f"/v1/convai/agents/{agent_id}", key, payload)

    final = _req("GET", f"/v1/convai/agents/{agent_id}", key)
    ids = (final.get("conversation_config", {}).get("agent", {})
           .get("prompt", {}).get("tool_ids") or [])
    print(f"done: agent now has {len(ids)} tools")
    return 0


if __name__ == "__main__":
    sys.exit(main())
