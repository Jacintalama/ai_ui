"""Tests for scripts/dev_env.py, scripts/dev_up.sh and the local compose files.

Run from the repo root: python -m pytest scripts/test_dev_env.py -q
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest
from cryptography.fernet import Fernet

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "dev_env.py"
DEV_UP = REPO / "scripts" / "dev_up.sh"
COMPOSE = REPO / "docker-compose.dev.yml"
REAL = REPO / "docker-compose.dev.real.yml"

KEYS = {
    "DEV_WEBUI_SECRET_KEY",
    "DEV_POSTGRES_PASSWORD",
    "DEV_AIUI_FERNET_KEY",
    "DEV_CRON_SHARED_SECRET",
    "DEV_ADMIN_EMAIL",
    "DEV_ADMIN_PASSWORD",
    "LOCAL_MODEL",
    "DEV_OPENROUTER_API_KEY",
}

# The names .env.dev used before 2026-10-12. They are also production .env
# names, which is why the compose files no longer interpolate them.
OLD_TO_NEW = {
    "WEBUI_SECRET_KEY": "DEV_WEBUI_SECRET_KEY",
    "POSTGRES_PASSWORD": "DEV_POSTGRES_PASSWORD",
    "AIUI_FERNET_KEY": "DEV_AIUI_FERNET_KEY",
    "OPENROUTER_API_KEY": "DEV_OPENROUTER_API_KEY",
}

needs_docker = pytest.mark.skipif(shutil.which("docker") is None,
                                  reason="docker CLI not installed")


def _git_bash():
    # Not shutil.which("bash") first: on Windows that can be WSL's bash.exe.
    for cand in (r"C:\Program Files\Git\bin\bash.exe", shutil.which("bash")):
        if cand and Path(cand).exists():
            return cand
    return None


BASH = _git_bash()
needs_bash = pytest.mark.skipif(BASH is None, reason="bash not installed")


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


def _clean_env() -> dict:
    """The caller's environment minus anything compose would interpolate
    from it, so a developer's shell cannot make these tests pass."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("DEV_") and k not in OLD_TO_NEW
           and not k.startswith("COMPOSE_")}
    return env


def _config(*args, cwd=REPO, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", *args, "config", "--format", "json"],
        capture_output=True, text=True, cwd=str(cwd), env=env or _clean_env(),
    )


# --- dev_env.py ------------------------------------------------------------

def test_creates_every_key_with_a_valid_fernet_key(tmp_path):
    env = tmp_path / ".env.dev"
    _run(env)
    vals = _parse(env)
    assert set(vals) == KEYS
    Fernet(vals["DEV_AIUI_FERNET_KEY"].encode())  # raises if invalid
    assert vals["DEV_ADMIN_EMAIL"] == "admin@local.test"
    assert vals["LOCAL_MODEL"] == "fake"
    assert vals["DEV_OPENROUTER_API_KEY"] == ""
    for k in ("DEV_WEBUI_SECRET_KEY", "DEV_POSTGRES_PASSWORD",
              "DEV_ADMIN_PASSWORD", "DEV_CRON_SHARED_SECRET"):
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
    assert after["DEV_WEBUI_SECRET_KEY"] != before["DEV_WEBUI_SECRET_KEY"]
    assert after["DEV_AIUI_FERNET_KEY"] != before["DEV_AIUI_FERNET_KEY"]


def test_stdout_names_keys_but_never_values(tmp_path):
    env = tmp_path / ".env.dev"
    first = _run(env)
    second = _run(env)
    vals = _parse(env)
    for out in (first.stdout + first.stderr, second.stdout + second.stderr):
        assert "DEV_WEBUI_SECRET_KEY" in out or "unchanged" in out
        for k, v in vals.items():
            if v:
                assert v not in out, f"value of {k} printed"


def _old_style(path: Path) -> dict:
    """An .env.dev as dev_env.py wrote it before the DEV_ names."""
    old = {
        "WEBUI_SECRET_KEY": "old-webui-secret-value-0123456789abcdef",
        "POSTGRES_PASSWORD": "old-postgres-password-0123456789",
        "AIUI_FERNET_KEY": Fernet.generate_key().decode(),
        "DEV_ADMIN_EMAIL": "admin@local.test",
        "DEV_ADMIN_PASSWORD": "old-admin-password-0123",
        "LOCAL_MODEL": "real",
        "OPENROUTER_API_KEY": "sk-or-old-test-value-0123456789",
    }
    path.write_text("# old header\n" + "".join(f"{k}={v}\n" for k, v in old.items()),
                    encoding="utf-8", newline="\n")
    return old


def test_migrates_old_names_keeping_their_values(tmp_path):
    env = tmp_path / ".env.dev"
    old = _old_style(env)
    r = _run(env)
    vals = _parse(env)
    assert set(vals) == KEYS
    # The Postgres volume keeps its password and encrypted rows stay readable.
    for o, n in OLD_TO_NEW.items():
        assert vals[n] == old[o], n
    for k in ("DEV_ADMIN_EMAIL", "DEV_ADMIN_PASSWORD", "LOCAL_MODEL"):
        assert vals[k] == old[k], k
    # New keys are added with fresh values.
    assert len(vals["DEV_CRON_SHARED_SECRET"]) >= 24
    # Names only on stdout.
    out = r.stdout + r.stderr
    assert "WEBUI_SECRET_KEY -> DEV_WEBUI_SECRET_KEY" in out
    for k, v in vals.items():
        if v:
            assert v not in out, f"value of {k} printed"
    # Idempotent once migrated.
    before = env.read_bytes()
    _run(env)
    assert env.read_bytes() == before


def test_migration_never_overwrites_an_existing_dev_name(tmp_path):
    env = tmp_path / ".env.dev"
    env.write_text("WEBUI_SECRET_KEY=stale\nDEV_WEBUI_SECRET_KEY=current\n",
                   encoding="utf-8")
    _run(env)
    vals = _parse(env)
    assert vals["DEV_WEBUI_SECRET_KEY"] == "current"
    assert "WEBUI_SECRET_KEY" not in vals


def test_env_dev_is_gitignored():
    lines = [l.strip() for l in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()]
    assert ".env.dev" in lines


# --- compose files ----------------------------------------------------------

@needs_docker
def test_dev_compose_renders_as_its_own_project(tmp_path):
    """The dev stack must never share names with production."""
    env = tmp_path / ".env.dev"
    _run(env)
    r = _config("--env-file", str(env), "-f", str(COMPOSE))
    assert r.returncode == 0, r.stderr
    assert "variable is not set" not in r.stderr, r.stderr
    cfg = json.loads(r.stdout)
    assert cfg["name"] == "aiui-dev"
    for name, svc in cfg["services"].items():
        assert "container_name" not in svc, name
    for vol in cfg.get("volumes", {}).values():
        assert vol["name"].startswith("aiui-dev_"), vol["name"]
    vals = _parse(env)
    for svc in ("open-webui", "tasks", "api-gateway"):
        got = cfg["services"][svc]["environment"]["WEBUI_SECRET_KEY"]
        assert got == vals["DEV_WEBUI_SECRET_KEY"], svc
    assert cfg["services"]["postgres"]["environment"]["POSTGRES_PASSWORD"] \
        == vals["DEV_POSTGRES_PASSWORD"]
    assert cfg["services"]["tasks"]["environment"]["AIUI_FERNET_KEY"] \
        == vals["DEV_AIUI_FERNET_KEY"]


@needs_docker
def test_dev_compose_interpolates_only_dev_names():
    """Every ${...} in the dev compose files is a DEV_ name, so a
    production .env can never supply one."""
    import re
    for f in (COMPOSE, REAL):
        names = set(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)", f.read_text(encoding="utf-8")))
        assert names, f
        bad = sorted(n for n in names if not n.startswith("DEV_"))
        assert not bad, f"{f.name} interpolates {bad}"


@needs_docker
@pytest.mark.parametrize("decoy", ["empty", "production-shaped"])
def test_dev_compose_fails_closed_without_dev_env(tmp_path, decoy):
    """A plain `docker compose -f docker-compose.dev.yml ...` reads .env from
    the project directory. Given only production-shaped names (or nothing),
    it must refuse and point at dev_up.sh."""
    dotenv = tmp_path / ".env"
    if decoy == "empty":
        dotenv.write_text("", encoding="utf-8")
    else:
        dotenv.write_text("".join(f"{k}=decoy-{k.lower()}\n" for k in OLD_TO_NEW)
                          + "CRON_SHARED_SECRET=decoy\n", encoding="utf-8")
    # No --env-file: compose falls back to <project dir>/.env, the decoy.
    r = _config("--project-directory", str(tmp_path), "-f", str(COMPOSE))
    assert r.returncode != 0, "rendered from a production-shaped .env"
    assert "dev_up.sh" in r.stderr, r.stderr
    assert "decoy" not in r.stdout
    # The same with the decoy passed explicitly.
    r = _config("--env-file", str(dotenv), "-f", str(COMPOSE))
    assert r.returncode != 0
    assert "dev_up.sh" in r.stderr, r.stderr


@needs_docker
def test_tasks_never_points_at_production_integrations(tmp_path):
    env = tmp_path / ".env.dev"
    _run(env)
    r = _config("--env-file", str(env), "-f", str(COMPOSE))
    assert r.returncode == 0, r.stderr
    tenv = json.loads(r.stdout)["services"]["tasks"]["environment"]
    for k in ("N8N_WEBHOOK_BASE", "WEEKLY_RECAP_WEBHOOK", "OPENAI_API_BASE"):
        host = urlparse(tenv[k]).hostname or ""
        assert host.endswith(".invalid"), (k, host)
    # Empty would skip the auth check on /cron/weekly-recap (routes_cron.py).
    assert tenv["CRON_SHARED_SECRET"] == _parse(env)["DEV_CRON_SHARED_SECRET"]
    assert len(tenv["CRON_SHARED_SECRET"]) >= 24
    blob = json.dumps(tenv)
    for prod in ("coolestdomain", "hstgr", "46.224.193.25"):
        assert prod not in blob, prod


@needs_docker
def test_real_mode_fails_closed_without_a_key(tmp_path):
    env = tmp_path / ".env.dev"
    _run(env)
    r = _config("--env-file", str(env), "-f", str(COMPOSE), "-f", str(REAL))
    assert r.returncode != 0
    assert "DEV_OPENROUTER_API_KEY" in r.stderr, r.stderr
    text = env.read_text(encoding="utf-8").replace(
        "DEV_OPENROUTER_API_KEY=\n", "DEV_OPENROUTER_API_KEY=sk-or-test-dummy\n")
    env.write_text(text, encoding="utf-8")
    r = _config("--env-file", str(env), "-f", str(COMPOSE), "-f", str(REAL))
    assert r.returncode == 0, r.stderr
    owui = json.loads(r.stdout)["services"]["open-webui"]["environment"]
    assert owui["OPENAI_API_KEYS"] == "sk-or-test-dummy"


# --- dev_up.sh --------------------------------------------------------------

def _dev_up(env_file: Path, *args, extra=None) -> subprocess.CompletedProcess:
    env = _clean_env()
    env["DEV_ENV_FILE"] = env_file.as_posix()
    env.update(extra or {})
    return subprocess.run([BASH, str(DEV_UP), *args], capture_output=True,
                          text=True, env=env, cwd=str(REPO))


@needs_bash
@needs_docker
def test_dev_up_ignores_a_shell_compose_project_name(tmp_path):
    env = tmp_path / ".env.dev"
    _run(env)
    r = _dev_up(env, "config", "--format", "json",
                extra={"COMPOSE_PROJECT_NAME": "io"})
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["name"] == "aiui-dev"


@needs_bash
def test_dev_up_model_rejects_an_invalid_local_model(tmp_path):
    env = tmp_path / ".env.dev"
    env.write_text("LOCAL_MODEL=bogus\n", encoding="utf-8")
    r = _dev_up(env, "model")
    assert r.returncode != 0, r.stdout
    assert "LOCAL_MODEL must be fake or real" in r.stderr
    env.write_text("LOCAL_MODEL=fake\n", encoding="utf-8")
    r = _dev_up(env, "model")
    assert r.returncode == 0, r.stderr
    assert "LOCAL_MODEL=fake" in r.stdout
