#!/usr/bin/env python3
"""Manage tasks.schedules via HTTP.

Env (both required):
  TASKS_URL              base URL of the tasks service
                         (default: http://46.224.193.25/tasks)
  CRON_SHARED_SECRET     value of the X-Cron-Secret header

Usage examples:
  manage_schedules.py list
  manage_schedules.py create --user x@y.com --name daily-summary \\
      --cron "0 9 * * *" --persona "You are terse." --prompt "Summarize MEMORY.md"
  manage_schedules.py delete <id>
  manage_schedules.py enable <id>
  manage_schedules.py disable <id>
  manage_schedules.py run-now <id>
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

URL = os.environ.get("TASKS_URL", "http://46.224.193.25/tasks").rstrip("/")
SECRET = os.environ.get("CRON_SHARED_SECRET", "")


def _req(method: str, path: str, body: dict | None = None) -> dict | list:
    if not SECRET:
        sys.exit("CRON_SHARED_SECRET env var required")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        URL + path,
        data=data,
        method=method,
        headers={
            "X-Cron-Secret": SECRET,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
        # 204 / empty body is legal — return an empty dict so callers
        # don't crash on json.loads("").
        return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"{e.code}: {e.read().decode(errors='replace')}")
    except urllib.error.URLError as e:
        sys.exit(f"connection failed: {e.reason}")


def cmd_list(args):
    print(json.dumps(_req("GET", "/schedules"), indent=2))


def cmd_create(args):
    body = {
        "user_email": args.user,
        "name": args.name,
        "cron_expr": args.cron,
        "tz": args.tz,
        "persona": args.persona,
        "prompt": args.prompt,
        "enabled": not args.disabled,
    }
    print(json.dumps(_req("POST", "/schedules", body), indent=2))


def cmd_delete(args):
    print(json.dumps(_req("DELETE", f"/schedules/{args.id}"), indent=2))


def cmd_enable(args):
    print(json.dumps(_req("POST", f"/schedules/{args.id}/enable"), indent=2))


def cmd_disable(args):
    print(json.dumps(_req("POST", f"/schedules/{args.id}/disable"), indent=2))


def cmd_run_now(args):
    print(json.dumps(_req("POST", f"/schedules/{args.id}/run-now"), indent=2))


def main() -> None:
    p = argparse.ArgumentParser(prog="manage_schedules.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list").set_defaults(func=cmd_list)

    c = sub.add_parser("create")
    c.add_argument("--user", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--cron", required=True, help="5-field cron expr, e.g. '0 20 * * *'")
    c.add_argument("--tz", default="Asia/Manila")
    c.add_argument("--persona", default="")
    c.add_argument("--prompt", required=True)
    c.add_argument("--disabled", action="store_true")
    c.set_defaults(func=cmd_create)

    for name, fn in [
        ("delete", cmd_delete),
        ("enable", cmd_enable),
        ("disable", cmd_disable),
        ("run-now", cmd_run_now),
    ]:
        s = sub.add_parser(name)
        s.add_argument("id")
        s.set_defaults(func=fn)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
