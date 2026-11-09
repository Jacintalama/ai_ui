"""What compose gives mcp-proxy, and what it no longer starts (2026-11-09).

Measured that day: `docker restart mcp-proxy` at the 768M limit had its main
process killed at 758 MB while starting, with the host's swap full, and the
container went on reading "running" because the second process in start.sh
stayed up. Connector tools were down for six and a half minutes. It holds
about 1.1 GB once running.

docker update fixed the running container only. This is the file the next
recreate reads.
"""
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
COMPOSE = os.path.join(ROOT, "docker-compose.unified.yml")


def _services():
    import yaml
    with open(COMPOSE, encoding="utf-8") as fh:
        return yaml.safe_load(fh).get("services") or {}


def _megabytes(limit):
    text = str(limit).strip().upper()
    if text.endswith("G"):
        return int(float(text[:-1]) * 1024)
    assert text.endswith("M"), text
    return int(text[:-1])


def test_the_proxy_is_allowed_what_it_needs_to_start():
    limit = _services()["mcp-proxy"]["deploy"]["resources"]["limits"]["memory"]
    assert _megabytes(limit) >= 1200


def test_the_shared_clickup_container_is_not_started():
    """Off by name in tenants.py since 11-06, and crash-looping. Left in
    compose, any deploy that touches this file starts it again."""
    assert "mcp-clickup" not in _services()
