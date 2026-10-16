"""Where the checkout is, for the tests that read the repository itself.

Lives in its own module rather than in conftest.py because there are TWO
conftest files (tests/ and tests/browser/) and, under pytest's default
import mode, both are imported under the bare name `conftest`. Whichever
was imported last wins that name, and once tests/browser/ had a conftest
(2026-10-13) the eight files doing `from conftest import repo_root_or_skip`
failed to collect whenever the whole suite ran. Both conftests import the
helper from here, so the name resolves whichever of them is in sys.modules.
"""
import pathlib


def repo_root_or_skip():
    """The checkout root, or skip the module when there isn't one.

    Six test files read files that live outside this service: the compose file,
    the Open WebUI pipes, the terminal client's mirror. They found them with
    `parents[3]`, which is the repo root in a checkout and does not exist inside
    the container, where /app IS this service.

    An IndexError at import time is a COLLECTION error, and pytest aborts the
    whole run on those. So `pytest tests/` has never been runnable in the
    container, which is the only place the database tier can run at all. These
    files have nothing to say about a deployed container, so they skip there
    instead of taking every other test down with them.
    """
    import pytest
    here = pathlib.Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / "docker-compose.unified.yml").exists():
            return candidate
    pytest.skip("not a checkout: these files read the repository, not the app",
                allow_module_level=True)
