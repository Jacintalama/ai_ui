#!/usr/bin/env python3
"""Talk to IO from a terminal.

    python scripts/io.py                 interactive
    python scripts/io.py "what's on today"    one shot
    echo "summarise this" | python scripts/io.py

Standard library only, so it runs anywhere Python does with nothing installed.

First run writes a random device id to ~/.io/device. That file IS your
credential: anyone holding it can talk to IO as you. It is created 0600. Delete
it to unpair, then pair again from the link page.
"""
import argparse
import json
import os
import pathlib
import secrets
import sys
import urllib.error
import urllib.request

DEFAULT_URL = os.environ.get("IO_URL", "https://ai-ui.coolestdomain.win")
DEVICE_FILE = pathlib.Path(os.environ.get("IO_HOME", pathlib.Path.home() / ".io")) / "device"


def device_id() -> str:
    """Read the device id, creating one on first run."""
    if DEVICE_FILE.exists():
        existing = DEVICE_FILE.read_text(encoding="utf-8").strip()
        if len(existing) == 32:
            return existing
    DEVICE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fresh = secrets.token_hex(16)
    # 0600 before anything is written, not after: a credential must never exist
    # world-readable, not even for one syscall.
    fd = os.open(DEVICE_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(fresh)
    return fresh


def ask(base_url: str, text: str) -> str:
    body = json.dumps({
        "device_id": device_id(),
        "device_name": os.environ.get("HOSTNAME") or pathlib.Path.home().name,
        "text": text,
    }).encode()
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/webhook/gateway/cli",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as resp:
            return json.loads(resp.read()).get("reply", "")
    except urllib.error.HTTPError as e:
        return f"[{e.code}] {e.read().decode(errors='replace')[:400]}"
    except urllib.error.URLError as e:
        return f"Could not reach {base_url}: {e.reason}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Talk to IO from a terminal.")
    parser.add_argument("message", nargs="*", help="send one message and exit")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"default {DEFAULT_URL}")
    args = parser.parse_args()

    if args.message:
        print(ask(args.url, " ".join(args.message)))
        return 0
    if not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            print(ask(args.url, piped))
        return 0

    print("Talking to IO. Ctrl-C to stop, /help for commands.")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in ("exit", "quit"):
            return 0
        print(ask(args.url, line))
        print()


if __name__ == "__main__":
    sys.exit(main())
