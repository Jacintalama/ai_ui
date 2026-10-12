"""Check the local Docker stack, one layer per line.

    python scripts/dev_check.py

Prints PASS or FAIL for each layer and exits non-zero on any FAIL. Reads the
dev admin from .env.dev and never prints the password or the token.
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASE = "http://localhost:8090"


def read_env(path: Path = REPO / ".env.dev") -> dict:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def request(method: str, path: str, body=None, token: str = None,
            timeout: float = 30.0):
    """(status, text). Never raises for an HTTP error status."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:                                  # noqa: BLE001
        return 0, type(e).__name__


def signin(env: dict):
    status, text = request("POST", "/api/v1/auths/signin", {
        "email": env["DEV_ADMIN_EMAIL"], "password": env["DEV_ADMIN_PASSWORD"]})
    if status != 200:
        return None, status
    try:
        return json.loads(text).get("token"), status
    except ValueError:
        return None, status


def model_ids(token: str) -> list:
    status, text = request("GET", "/api/models", token=token)
    if status != 200:
        return []
    try:
        return [m.get("id") for m in json.loads(text).get("data", [])]
    except (ValueError, AttributeError):
        return []


def owned_agent_names(token: str) -> list:
    """Names of the workspace models (agents) this account can see, read the
    way the Agents page reads them: /api/v1/models/list, page by page."""
    names = []
    for page in range(1, 20):
        status, text = request("GET", f"/api/v1/models/list?page={page}",
                               token=token)
        if status != 200:
            break
        try:
            body = json.loads(text)
        except ValueError:
            break
        items = body.get("items", body.get("data", [])) if isinstance(body, dict) else body
        if not items:
            break
        names += [m.get("name") for m in items if isinstance(m, dict)]
        total = body.get("total") if isinstance(body, dict) else None
        if total is None or len(names) >= total:
            break
    return names


def main() -> int:
    env = read_env()
    results = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        results.append(ok)
        line = f"{'PASS' if ok else 'FAIL'}  {label}"
        if detail and not ok:
            line += f"  ({detail})"
        print(line, flush=True)

    status, text = request("GET", "/tasks/healthz")
    try:
        healthy = status == 200 and json.loads(text).get("status") == "ok"
    except ValueError:
        healthy = False
    check("1 tasks /tasks/healthz is ok", healthy, f"status {status}")

    status, text = request("GET", "/")
    check("2 / serves the override index.html (task-panel.js)",
          status == 200 and "task-panel.js" in text, f"status {status}")

    token, status = signin(env)
    check("3 Open WebUI sign-in as the dev admin returns a token",
          bool(token), f"status {status}")

    ids = model_ids(token) if token else []
    check("4 /api/models lists fake-agent", "fake-agent" in ids,
          f"models {ids}")

    status, _ = request("GET", "/api/tasks/agents/tools", token=token) if token else (0, "")
    check("5 /api/tasks/agents/tools answers 200", status == 200,
          f"status {status}")

    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
