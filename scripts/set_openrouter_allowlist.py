"""Set the OpenRouter model allowlist in Open WebUI without a restart.

Run on the server:
  OPENWEBUI_API_KEY=... python3 scripts/set_openrouter_allowlist.py           # show
  OPENWEBUI_API_KEY=... python3 scripts/set_openrouter_allowlist.py --apply   # write

Reads /openai/config as an admin, replaces model_ids on the connection whose
URL is openrouter.ai, and posts the whole config back. Open WebUI's persisted
config wins over the compose environment, so editing the compose line alone
changes nothing on a running box; this is what changes it. Keys are read
and sent back untouched and are never printed.

--apply writes a backup of the current connection settings, with every key
stripped out, to the working directory before it changes anything, so the
old allowlist can be put back by hand.
"""
import datetime
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("OPENWEBUI_URL", "http://localhost:3000")
KEY = os.environ.get("OPENWEBUI_API_KEY", "")
if not KEY:
    sys.exit("OPENWEBUI_API_KEY is required")

WANTED = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nex-agi/nex-n2.5-pro:free",
    "nex-agi/nex-n2.5-mini:free",
    "cohere/north-mini-code:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "google/gemini-2.5-flash-lite",
    "openai/gpt-5-mini",
    "anthropic/claude-haiku-4.5",
]

#: Every secret this run has seen, so _scrub can take them back out of
#: anything we are about to print. Filled once the config is read. The
#: admin key itself goes in first, because it is in every request we make.
_SECRETS = [KEY]

#: A field whose name contains one of these is a secret and never reaches
#: the backup file. The connection config in Open WebUI 0.11 holds only
#: enable, prefix_id, model_ids, tags and connection_type, but a future
#: version adding a per-connection key must not quietly start writing it
#: to a file on disk.
SECRET_NAME_PARTS = ("key", "secret", "token", "password")


class HttpFailure(Exception):
    """An HTTP call that did not return a usable body."""


def _scrub(text: str) -> str:
    """Take every known secret back out of text before it is printed.

    Not paranoia about our own prints: FastAPI answers a 422 with a detail
    that echoes the body it rejected, and the body we post to
    /openai/config/update carries OPENAI_API_KEYS. Printing that body raw
    would put live keys in the terminal and in whatever captures it.
    """
    for secret in _SECRETS:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


def call(path, payload=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise HttpFailure(f"{path}: HTTP {e.code} {_scrub(detail)[:200]}")
    except urllib.error.URLError as e:
        raise HttpFailure(f"{path}: {e.reason}")
    try:
        return json.loads(body)
    except ValueError:
        raise HttpFailure(f"{path}: reply was not JSON: {_scrub(body)[:200]}")


def _without_secrets(value):
    """A copy of value with every secret-looking field dropped.

    Recursive because the config is a dict of per-connection dicts and a
    new nested field would otherwise slip through.
    """
    if isinstance(value, dict):
        return {k: _without_secrets(v) for k, v in value.items()
                if not any(part in str(k).lower() for part in SECRET_NAME_PARTS)}
    if isinstance(value, list):
        return [_without_secrets(v) for v in value]
    return value


def _write_backup(cfg) -> str:
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(os.getcwd(), f"openrouter-allowlist-backup-{stamp}.json")
    payload = {
        "OPENAI_API_BASE_URLS": _without_secrets(cfg.get("OPENAI_API_BASE_URLS") or []),
        "OPENAI_API_CONFIGS": _without_secrets(cfg.get("OPENAI_API_CONFIGS") or {}),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    return path


def main() -> int:
    cfg = call("/openai/config")
    # Remember the live keys so a later error body cannot print one.
    for k in (cfg.get("OPENAI_API_KEYS") or []):
        if isinstance(k, str) and k:
            _SECRETS.append(k)

    urls = cfg.get("OPENAI_API_BASE_URLS") or []
    idx = next((str(i) for i, u in enumerate(urls) if "openrouter.ai" in str(u)), None)
    if idx is None:
        print("no openrouter.ai connection in OPENAI_API_BASE_URLS")
        return 1
    configs = cfg.get("OPENAI_API_CONFIGS") or {}
    before = (configs.get(idx) or {}).get("model_ids") or []
    print("connection", idx, "before:", json.dumps(before))
    print("after:   ", json.dumps(WANTED))
    if "--apply" not in sys.argv:
        print("dry run; pass --apply to write")
        return 0

    print("backup:", _write_backup(cfg))
    configs[idx] = dict(configs.get(idx) or {}, enable=True, model_ids=WANTED)
    cfg["OPENAI_API_CONFIGS"] = configs
    out = call("/openai/config/update", cfg)
    now = ((out.get("OPENAI_API_CONFIGS") or {}).get(idx) or {}).get("model_ids")
    print("written:", json.dumps(now))
    # /api/models is not only the check: reading it is what rebuilds Open
    # WebUI's in-memory model cache, which otherwise keeps answering
    # "Model not found" for an id that is now allowed.
    models = call("/api/models")
    ids = {m.get("id") for m in (models.get("data") or [])}
    missing = [m for m in WANTED if m not in ids]
    print("visible in /api/models:",
          "all" if not missing else "MISSING " + json.dumps(missing))
    return 1 if (missing or now != WANTED) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except HttpFailure as exc:
        print("failed:", exc)
        sys.exit(1)
