"""Static pages must parse, and their element ids must be unique.

Written after shipping a duplicate `const dmModal` into projects.html: the
Docs modal reused a name the Delete-project modal already had. One SyntaxError
takes down the whole inline script, so the App Builder never called load() and
sat on "Loading your projects..." forever. Nothing caught it, because the
Python tests never look at the JavaScript.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

STATIC = pathlib.Path(__file__).resolve().parent.parent / "static"
PAGES = sorted(STATIC.glob("*.html"))

_SCRIPT_RE = re.compile(r"<script(?![^>]*\ssrc=)[^>]*>(.*?)</script>", re.S)
_ID_RE = re.compile(r'\bid="([^"]+)"')


def _inline_scripts(html: str) -> list[str]:
    return _SCRIPT_RE.findall(html)


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_inline_javascript_parses(page, tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    html = page.read_text(encoding="utf-8")
    for i, script in enumerate(_inline_scripts(html)):
        if not script.strip():
            continue
        f = tmp_path / f"{page.stem}_{i}.js"
        f.write_text(script, encoding="utf-8")
        r = subprocess.run([node, "--check", str(f)],
                           capture_output=True, text=True)
        assert r.returncode == 0, (
            f"{page.name} inline script #{i} does not parse. One SyntaxError "
            f"kills the whole page:\n{r.stderr}")


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_element_ids_are_unique(page):
    # A duplicate id is not a parse error, so it fails quietly: getElementById
    # hands back whichever came first and the second feature drives the wrong
    # element. This is how the Docs modal ended up sharing dm-slug with the
    # Delete-project modal.
    html = page.read_text(encoding="utf-8")
    ids = _ID_RE.findall(html)
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"{page.name} reuses element ids: {dupes}"
