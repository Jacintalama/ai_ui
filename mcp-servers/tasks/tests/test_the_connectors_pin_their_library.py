"""Every mcpo install pins the mcp library it is built against.

Measured on the live box 2026-11-06: SEVEN of sixteen MCP servers were
completely unreachable, and every one of them was an mcpo-based
connector while every server written in this repo was fine.

  DOWN  filesystem  trello  sonarqube  clickup  n8n  github  notion
  UP    gmail  gdrive  calendar  web-search  excel  dashboard
        meetings  scheduler  proxy

The cause was dependency drift, not our code. mcp 2.x renamed
`streamablehttp_client` to `streamable_http_client`; mcpo 0.0.20, the
current release, still imports the old name. Every container died on

  ImportError: cannot import name 'streamablehttp_client' from
  'mcp.client.streamable_http'

and restarted, forever: mcp-filesystem had logged 2930 restarts, trello
2927, sonarqube and clickup 2926 each, n8n 1659, github 1193, notion
1162.

Four of them install mcpo at CONTAINER START with no version pin, so the
day that mcp release landed on PyPI they all broke at once and every
restart reinstalled the same broken pair. That is the underlying
fragility and it is why this test exists: a pin is the difference between
a connector fleet that keeps working and one that breaks on somebody
else's release schedule.

Verified in a throwaway container: mcpo 0.0.20 with mcp<2 resolves to mcp
1.30.0 and imports cleanly.
"""
import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")
COMPOSE = os.path.join(ROOT, "docker-compose.unified.yml")
DOCKERFILES = [os.path.join(ROOT, "mcp-servers", d, "Dockerfile")
               for d in ("n8n", "github", "notion")]

#: An install of mcpo, however it is spelled.
_INSTALL = re.compile(r"pip3?\s+install[^\n&|]*\bmcpo\b[^\n&|]*")


def _installs(path):
    with open(path, encoding="utf-8") as fh:
        return _INSTALL.findall(fh.read())


def test_the_files_are_where_this_thinks_they_are():
    """A test that silently checks nothing is worse than no test."""
    assert os.path.isfile(COMPOSE)
    for d in DOCKERFILES:
        assert os.path.isfile(d), d


def test_compose_still_installs_mcpo_at_startup():
    """If this stops being true the connectors were rebuilt as images,
    which is the better answer, and this file should be revisited."""
    found = _installs(COMPOSE)
    assert len(found) == 4, (
        "the mcpo services in compose changed shape; re-read this file")


@pytest.mark.parametrize("path", [COMPOSE] + DOCKERFILES,
                         ids=lambda p: os.path.basename(
                             os.path.dirname(p)) + "/" + os.path.basename(p))
def test_no_mcpo_install_is_left_unpinned(path):
    loose = [line.strip() for line in _installs(path)
             if not any(t in line for t in ("mcp<", "mcp==", "mcp<="))
             or "fastapi" not in line]
    assert not loose, (
        "mcpo is installed without pinning the mcp library, so this "
        "connector breaks on somebody else's release:\n  "
        + "\n  ".join(loose))


@pytest.mark.parametrize("path", [COMPOSE] + DOCKERFILES,
                         ids=lambda p: os.path.basename(
                             os.path.dirname(p)) + "/" + os.path.basename(p))
def test_the_pin_keeps_mcp_below_2(path):
    """mcp 2.x is the release that renamed the symbol mcpo imports. The
    pin is a ceiling rather than an exact version so fixes in the 1.x
    line still arrive.
    """
    for line in _installs(path):
        assert "mcp<2" in line, (
            "the pin is not the one that was verified to work: " + line.strip())


@pytest.mark.parametrize("path", [COMPOSE] + DOCKERFILES,
                         ids=lambda p: os.path.basename(
                             os.path.dirname(p)) + "/" + os.path.basename(p))
def test_fastapi_is_pinned_too(path):
    """A SECOND drift, underneath the first and only visible once the
    first was fixed.

    mcpo 0.0.20 passes `ssl_certfile` to `FastAPI(...)`, which only works
    while FastAPI accepts unknown keyword arguments through `**extra`.
    FastAPI dropped that between 0.129.2 and 0.149.0, so every rebuilt
    connector traded

      ImportError: cannot import name 'streamablehttp_client'

    for

      TypeError: FastAPI.__init__() got an unexpected keyword argument
      'ssl_certfile'

    and kept restarting. Fixing one pin at a time and redeploying is how
    you find a stack of these one deploy apiece, which is the argument
    for pinning the whole set at once.

    Proven end to end on 2026-11-06, not just as a constructor call:
    mcpo 0.0.20 with mcp 1.30.0 and fastapi 0.129.2 served 14 tools over
    HTTP with a real MCP server behind it.
    """
    for line in _installs(path):
        assert "fastapi<0.130" in line, (
            "fastapi is unpinned, so mcpo breaks on FastAPI's next "
            "release: " + line.strip())


def test_the_check_would_catch_an_unpinned_install(tmp_path):
    """Guards the two above. A regex that matched nothing would leave
    them passing on any file at all."""
    bad = tmp_path / "Dockerfile"
    bad.write_text("RUN pip install --no-cache-dir mcpo\n", encoding="utf-8")
    assert _installs(str(bad)), "the regex does not recognise an install"
    with pytest.raises(AssertionError):
        test_no_mcpo_install_is_left_unpinned(str(bad))
