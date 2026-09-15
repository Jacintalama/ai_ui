"""Set the OpenRouter model allowlist in Open WebUI without a restart.

Run on the server:
  OPENWEBUI_API_KEY=... python3 scripts/set_openrouter_allowlist.py           # show
  OPENWEBUI_API_KEY=... python3 scripts/set_openrouter_allowlist.py --apply   # write

Reads /openai/config as an admin, replaces model_ids on the connection whose
URL is openrouter.ai, and posts the whole config back. Open WebUI's persisted
config wins over the compose environment, so editing the compose line alone
changes nothing on a running box; this is what changes it.

Allowing an id is not enough for it to answer. Open WebUI's
check_model_access needs a public.model row and a public.access_grant read
row for every base model (admin bypass is off on this box), and this script
cannot write the database from the host. After a run that names ids under
"no model row yet", create both rows, idempotently, in the openwebui
database, then GET /api/models?refresh=true, then prove one completion with
a non-admin token:

  INSERT INTO public.model (id, user_id, base_model_id, name, meta, params,
      created_at, updated_at, is_active)
  VALUES ('<model id>', '<an admin user id>', NULL, '<model id>', '{}', '{}',
      extract(epoch from now())::bigint, extract(epoch from now())::bigint, TRUE)
  ON CONFLICT (id) DO NOTHING;
  INSERT INTO public.access_grant (id, resource_type, resource_id,
      principal_type, principal_id, permission, created_at)
  SELECT gen_random_uuid()::text, 'model', '<model id>', 'user', '*', 'read',
      extract(epoch from now())::bigint
  WHERE NOT EXISTS (SELECT 1 FROM public.access_grant WHERE resource_type = 'model'
      AND resource_id = '<model id>' AND principal_id = '*' AND permission = 'read');

Keys are read
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


class Refused(Exception):
    """The config we read is not safe to post back."""


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
        raise HttpFailure("%s: HTTP %s %s" % (path, e.code, _scrub(detail)[:200]))
    except urllib.error.URLError as e:
        raise HttpFailure("%s: %s" % (path, _scrub(str(e.reason))))
    try:
        return json.loads(body)
    except ValueError:
        raise HttpFailure("%s: reply was not JSON: %s" % (path, _scrub(body)[:200]))


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


#: Shapes an admin UI uses to show a key without revealing it. If one of
#: these comes back from the read, the value in hand is a picture of a key
#: rather than the key, and posting it would store the picture.
MASK_MARKS = ("...", "*")

#: Below this a value cannot be a real provider key. The pipelines
#: connection is the one honest exception: it ships the fixed pseudo-key
#: 0p3n-w3bu!, which is ten characters and is not a secret at all.
MIN_KEY_CHARS = 16


def _short_key_is_normal(url: str) -> bool:
    return "pipelines" in url or "9099" in url


def key_shape(key) -> str:
    """len and four characters. Four is a provider prefix, not a usable key."""
    text = str(key or "")
    return "len=%d prefix=%s" % (len(text), text[:4])


def print_key_shapes(cfg):
    """Let the operator confirm the keys are real without showing them."""
    keys = cfg.get("OPENAI_API_KEYS")
    if not isinstance(keys, list):
        return
    for i, key in enumerate(keys):
        print("connection %d key: %s" % (i, key_shape(key)))


def check_safe_to_write(cfg, idx):
    """Refuse to post back a config whose keys did not survive the read.

    /openai/config/update replaces the whole connection list, so posting a
    keys list that is short, blank, or masked stores that instead of the
    live key and every connection loses its credentials at once. Nothing
    here could put them back: the backup this script writes excludes keys
    by design, so the only remaining copy would be the server's .env.

    A masked read is the case worth naming. An admin UI that renders a key
    as sk-...abc is showing a picture of it; if the config endpoint ever
    answers in that shape, the write would persist the picture.
    """
    keys = cfg.get("OPENAI_API_KEYS")
    urls = cfg.get("OPENAI_API_BASE_URLS")
    if not isinstance(keys, list) or not isinstance(urls, list):
        raise Refused("OPENAI_API_KEYS and OPENAI_API_BASE_URLS must both be lists")
    if len(keys) != len(urls):
        # Lengths only. The values are never printed.
        raise Refused("OPENAI_API_KEYS has %d entries and OPENAI_API_BASE_URLS has %d"
                      % (len(keys), len(urls)))
    at = int(idx)
    if at >= len(keys) or not str(keys[at] or "").strip():
        raise Refused("the openrouter.ai connection at index %s has no key" % idx)
    for i, key in enumerate(keys):
        text = str(key or "")
        mark = next((m for m in MASK_MARKS if m in text), None)
        if mark is not None:
            raise Refused("the key for connection %d contains %r, so the read "
                          "returned a mask rather than the key (%s)"
                          % (i, mark, key_shape(key)))
        if len(text) < MIN_KEY_CHARS and not _short_key_is_normal(str(urls[i] or "")):
            what = "empty" if not text else "only %d characters" % len(text)
            raise Refused("the key for connection %d is %s, too short to be a "
                          "real key (%s)" % (i, what, key_shape(key)))


def _write_backup(cfg) -> str:
    """Mode "x" on purpose: two runs inside the same second land on the same
    filename, and the second must not overwrite the first."""
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(os.getcwd(), "openrouter-allowlist-backup-%s.json" % stamp)
    payload = {
        "OPENAI_API_BASE_URLS": _without_secrets(cfg.get("OPENAI_API_BASE_URLS") or []),
        "OPENAI_API_CONFIGS": _without_secrets(cfg.get("OPENAI_API_CONFIGS") or {}),
    }
    with open(path, "x", encoding="utf-8") as fh:
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
    # The shapes print before the check, so a dry run that is about to
    # refuse still shows the operator what the keys came back looking like.
    dry = "--apply" not in sys.argv
    if dry:
        print_key_shapes(cfg)
    # Checked in both modes, not only before the write: a dry run is how an
    # operator finds out whether applying is safe.
    check_safe_to_write(cfg, idx)
    if dry:
        print("dry run; pass --apply to write")
        return 0

    print("backup:", _write_backup(cfg))
    configs[idx] = dict(configs.get(idx) or {}, enable=True, model_ids=WANTED)
    cfg["OPENAI_API_CONFIGS"] = configs
    out = call("/openai/config/update", cfg)
    written = (out.get("OPENAI_API_CONFIGS") or {}).get(idx) or {}
    now = written.get("model_ids")
    print("written:", json.dumps(now))
    # /api/models is not only the check: reading it is what rebuilds Open
    # WebUI's in-memory model cache, which otherwise keeps answering
    # "Model not found" for an id that is now allowed.
    models = call("/api/models?refresh=true")
    entries = {m.get("id"): m for m in (models.get("data") or []) if isinstance(m, dict)}
    ids = set(entries)
    # A connection with a prefix_id set publishes its models as
    # "<prefix_id>.<model id>", so the bare ids would all look missing.
    # Empty on this server today, which is the only case proven here.
    prefix = str(written.get("prefix_id") or configs[idx].get("prefix_id") or "").strip()
    expected = [prefix + "." + m for m in WANTED] if prefix else list(WANTED)
    missing = [m for m in expected if m not in ids]
    print("visible in /api/models:",
          "all" if not missing else "MISSING " + json.dumps(missing))
    # Listed is not routable. Measured 2026-09-15: two freshly allowed ids
    # showed up here for every token and still answered 400 "Model not
    # found" on every completion, because check_model_access needs a
    # public.model row and a public.access_grant read row for each base
    # model now that admin bypass is off. An entry with no "info" key is
    # exactly an id with no row. The rows are made by hand (see the module
    # docstring), so this only names them.
    no_row = [m for m in expected if m in entries and not entries[m].get("info")]
    if no_row:
        print("no model row yet, completions will answer Model not found "
              "until public.model and access_grant rows exist for:",
              json.dumps(no_row))
    return 1 if (missing or no_row or now != WANTED) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except HttpFailure as exc:
        print("failed:", exc)
        sys.exit(1)
    except Refused as exc:
        print("refusing to write:", exc)
        sys.exit(1)
    except FileExistsError as exc:
        print("backup file already exists, refusing to overwrite:", exc.filename)
        sys.exit(1)
