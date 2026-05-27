"""Static structural checks for the 5 functional templates.

Parametrized over each key. Each test verifies a single structural
property -- together they enforce the spec's static contract without
opening a browser.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_APPS = ROOT / "template_apps"

FUNCTIONAL_KEYS = [
    "flight-booking",
    "food-delivery",
    "job-board",
    "movie-tickets",
    "recipe-site",
]

WHITELISTED_CDN_DOMAINS = {
    "cdn.tailwindcss.com",
    "unpkg.com",
    "cdn.jsdelivr.net",
    "images.unsplash.com",
    "picsum.photos",
    "api.dicebear.com",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
}

PLACEHOLDER_PHRASES = ["Lorem ipsum", "TODO", "<%= APP_NAME %>", "Coming soon", "Add content here"]


def _read(key: str, *parts: str) -> str:
    return (TEMPLATE_APPS / key / Path(*parts)).read_text(encoding="utf-8")


def _strip_html(text: str) -> str:
    """Remove tags and Alpine attributes so placeholder checks scan visible text only."""
    no_tags = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", no_tags).strip()


@pytest.fixture(scope="module", params=FUNCTIONAL_KEYS)
def key(request):
    return request.param


def test_index_html_exists_and_substantial(key):
    p = TEMPLATE_APPS / key / "index.html"
    assert p.exists(), f"{key}/index.html missing"
    size = p.stat().st_size
    assert size > 8192, f"{key}/index.html is only {size} bytes (expected > 8KB)"


def test_index_html_has_exactly_one_h1(key):
    html = _read(key, "index.html")
    h1_count = len(re.findall(r"<h1\b", html, flags=re.IGNORECASE))
    assert h1_count == 1, f"{key}/index.html has {h1_count} <h1> tags (expected exactly 1)"


def test_index_html_has_state_machine_markers(key):
    html = _read(key, "index.html")
    assert 'x-data="appState()"' in html, f"{key}: missing x-data=\"appState()\""
    view_count = len(re.findall(r"x-show=\"view === '[a-z\-]+'\"", html))
    assert view_count >= 2, f"{key}: only {view_count} view sections found (expected >= 2)"


def test_index_html_imports_main_js_as_module(key):
    html = _read(key, "index.html")
    assert re.search(r'<script\s+type="module"\s+src="src/main\.js"', html), \
        f"{key}: missing <script type=\"module\" src=\"src/main.js\">"


def test_lib_files_present(key):
    base = TEMPLATE_APPS / key / "src"
    for f in ("main.js", "data.js", "lib/router.js", "lib/persistence.js", "lib/skeleton.js"):
        assert (base / f).exists(), f"{key}/src/{f} missing"


def test_img_tags_have_required_attrs(key):
    html = _read(key, "index.html")
    # Find every <img> tag including multiline ones (re.DOTALL to handle line breaks in attrs).
    # Skip the decorative SVG (those aren't <img>).
    img_tags = re.findall(r"<img\b[^>]*>", html, flags=re.IGNORECASE | re.DOTALL)
    for tag in img_tags:
        # Accept either static alt="..." or Alpine binding :alt="..."
        assert re.search(r'(?::|\b)alt="[^"]+"', tag), \
            f"{key}: <img> missing non-empty alt: {tag[:120]}"
        assert re.search(r"\bloading=", tag), \
            f"{key}: <img> missing loading attr: {tag[:120]}"
        # Width/height must be numeric (not "auto" or "100%")
        w = re.search(r'\bwidth="(\d+)"', tag)
        h = re.search(r'\bheight="(\d+)"', tag)
        assert w and h, f"{key}: <img> missing numeric width/height: {tag[:120]}"


def test_no_placeholder_strings_in_visible_text(key):
    html = _read(key, "index.html")
    visible = _strip_html(html)
    for phrase in PLACEHOLDER_PHRASES:
        assert phrase not in visible, f"{key}: placeholder phrase '{phrase}' appears in visible text"


def test_only_whitelisted_cdns(key):
    html = _read(key, "index.html")
    urls = re.findall(r'(?:src|href)="(https?://[^"]+)"', html)
    for url in urls:
        domain = re.match(r"https?://([^/]+)", url).group(1)
        # Allow exact matches OR subdomains of whitelisted entries
        ok = any(domain == d or domain.endswith("." + d) for d in WHITELISTED_CDN_DOMAINS)
        assert ok, f"{key}: external URL {url} (domain {domain}) not on whitelist"


def test_data_js_exports_nonempty_array(key):
    data = _read(key, "src/data.js")
    # Each template exports at least one named array. We accept the primary entity name
    # OR any `export const X = [...]` / `export const X = (() => {...})()` pattern.
    has_array_export = bool(re.search(r"export\s+const\s+\w+\s*=\s*\[", data)) \
        or bool(re.search(r"export\s+const\s+\w+\s*=\s*\(\(\)\s*=>", data)) \
        or bool(re.search(r"export\s+const\s+\w+\s*=\s*\w+\.map", data))
    assert has_array_export, f"{key}: src/data.js has no `export const X = [...]` style array export"
    # Sanity: file is substantial
    assert len(data) > 2000, f"{key}: src/data.js is only {len(data)} bytes (expected >2KB)"
