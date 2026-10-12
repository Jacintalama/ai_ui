"""Tests for scripts/dev_env.py and the local compose file it feeds.

Run from the repo root: python -m pytest scripts/test_dev_env.py -q
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "dev_env.py"
COMPOSE = REPO / "docker-compose.dev.yml"

KEYS = {
    "WEBUI_SECRET_KEY",
    "POSTGRES_PASSWORD",
    "AIUI_FERNET_KEY",
    "DEV_ADMIN_EMAIL",
    "DEV_ADMIN_PASSWORD",
    "LOCAL_MODEL",
    "OPENROUTER_API_KEY",
}


def _run(path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--path", str(path), *args],
        capture_output=True, text=True, check=True,
    )


def _parse(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        k, _, v = line.partition("=")
        out[k] = v
    return out


def test_creates_every_key_with_a_valid_fernet_key(tmp_path):
    env = tmp_path / ".env.dev"
    _run(env)
    vals = _parse(env)
    assert set(vals) == KEYS
    Fernet(vals["AIUI_FERNET_KEY"].encode())  # raises if invalid
    assert vals["DEV_ADMIN_EMAIL"] == "admin@local.test"
    assert vals["LOCAL_MODEL"] == "fake"
    assert vals["OPENROUTER_API_KEY"] == ""
    for k in ("WEBUI_SECRET_KEY", "POSTGRES_PASSWORD", "DEV_ADMIN_PASSWORD"):
        assert len(vals[k]) >= 24, k


def test_a_second_run_changes_nothing(tmp_path):
    env = tmp_path / ".env.dev"
    _run(env)
    before = env.read_bytes()
    _run(env)
    assert env.read_bytes() == before


def test_force_regenerates(tmp_path):
    env = tmp_path / ".env.dev"
    _run(env)
    before = _parse(env)
    _run(env, "--force")
    after = _parse(env)
    assert set(after) == KEYS
    assert after["WEBUI_SECRET_KEY"] != before["WEBUI_SECRET_KEY"]
    assert after["AIUI_FERNET_KEY"] != before["AIUI_FERNET_KEY"]


def test_stdout_names_keys_but_never_values(tmp_path):
    env = tmp_path / ".env.dev"
    first = _run(env)
    second = _run(env)
    vals = _parse(env)
    for out in (first.stdout + first.stderr, second.stdout + second.stderr):
        assert "WEBUI_SECRET_KEY" in out or "exists" in out
        for k, v in vals.items():
            if v:
                assert v not in out, f"value of {k} printed"


def test_env_dev_is_gitignored():
    lines = [l.strip() for l in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()]
    assert ".env.dev" in lines


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not installed")
def test_dev_compose_renders_as_its_own_project(tmp_path):
    """The dev stack must never share names with production."""
    env = tmp_path / ".env.dev"
    _run(env)
    r = subprocess.run(
        ["docker", "compose", "--env-file", str(env), "-f", str(COMPOSE),
         "config", "--format", "json"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    assert r.returncode == 0, r.stderr
    assert "variable is not set" not in r.stderr, r.stderr
    cfg = json.loads(r.stdout)
    assert cfg["name"] == "aiui-dev"
    for name, svc in cfg["services"].items():
        assert "container_name" not in svc, name
    for vol in cfg.get("volumes", {}).values():
        assert vol["name"].startswith("aiui-dev_"), vol["name"]
    # Values come from .env.dev, not from the production .env beside it.
    secret = _parse(env)["WEBUI_SECRET_KEY"]
    for svc in ("open-webui", "tasks", "api-gateway"):
        assert cfg["services"][svc]["environment"]["WEBUI_SECRET_KEY"] == secret, svc
