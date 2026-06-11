"""Static-HTML structural checks for the 5 design-forward templates.

Each template must:
  • have an index.html on disk under template_apps/<key>/
  • parse as HTML5 (single <h1>, no obvious malformed structure)
  • include a <link> to styles/main.css and <script type="module"> to src/main.js
  • declare every expected section via data-section="<name>" markers
  • have alt text + loading attribute + width/height on every <img>
  • NOT contain placeholder strings (Lorem ipsum, TODO, Coming soon, etc.)
  • only reference whitelisted CDNs (tailwind, alpine, fonts.googleapis,
    cdn.jsdelivr, unpkg, images.unsplash.com, picsum.photos)
"""
import re
from pathlib import Path

import pytest

TEMPLATE_APPS_DIR = Path(__file__).resolve().parents[1] / "template_apps"

# Keys -> ordered list of data-section markers expected in index.html.
EXPECTED_SECTIONS = {
    "agency":      ["nav", "hero", "marquee", "work", "stats", "capabilities", "logos", "testimonial", "cta", "footer"],
    "restaurant":  ["nav", "hero", "story", "menu", "gallery", "hours", "reservation", "footer"],
    "photography": ["nav", "hero", "series", "gallery", "about", "contact", "footer"],
    "event":       ["nav", "hero", "stats", "speakers", "schedule", "sponsors", "venue", "tickets", "faq", "footer"],
    "real-estate": ["nav", "hero", "stats", "description", "gallery", "map", "more-listings", "agent", "footer"],
}

PLACEHOLDER_FORBIDDEN = re.compile(
    r"\b(lorem ipsum|TODO:|coming soon|your bio goes here|add content here)\b",
    re.IGNORECASE,
)
# Match HTML tags (including attributes that span newlines).
TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)

# Allowed external hosts. Any other src= or href= host is a failure.
ALLOWED_HOSTS = {
    "cdn.tailwindcss.com",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "cdn.jsdelivr.net",
    "unpkg.com",
    "images.unsplash.com",
    "picsum.photos",
}

EXTERNAL_URL_RE = re.compile(r'https?://([^/\s"\'<>]+)')


@pytest.mark.parametrize("key", list(EXPECTED_SECTIONS.keys()))
def test_template_index_html_exists(key):
    p = TEMPLATE_APPS_DIR / key / "index.html"
    assert p.exists(), f"{p} missing"
    assert p.stat().st_size > 5_000, f"{p} suspiciously small ({p.stat().st_size} bytes)"


@pytest.mark.parametrize("key", list(EXPECTED_SECTIONS.keys()))
def test_template_has_required_section_markers(key):
    html = (TEMPLATE_APPS_DIR / key / "index.html").read_text(encoding="utf-8")
    for section in EXPECTED_SECTIONS[key]:
        marker = f'data-section="{section}"'
        assert marker in html, f"{key}: missing section marker {marker!r}"


@pytest.mark.parametrize("key", list(EXPECTED_SECTIONS.keys()))
def test_template_single_h1(key):
    html = (TEMPLATE_APPS_DIR / key / "index.html").read_text(encoding="utf-8")
    h1_count = len(re.findall(r"<h1\b", html, flags=re.IGNORECASE))
    assert h1_count == 1, f"{key}: expected exactly one <h1>, got {h1_count}"


@pytest.mark.parametrize("key", list(EXPECTED_SECTIONS.keys()))
def test_template_imgs_have_required_attrs(key):
    html = (TEMPLATE_APPS_DIR / key / "index.html").read_text(encoding="utf-8")
    img_tags = re.findall(r"<img\b[^>]*>", html, flags=re.IGNORECASE)
    assert img_tags, f"{key}: no <img> tags found (visual templates need images)"

    required = {
        "alt":     re.compile(r'\balt="[^"]+"'),                 # non-empty alt
        "loading": re.compile(r'\bloading="(lazy|eager|auto)"'),
        "width":   re.compile(r'\bwidth="\d+"'),
        "height":  re.compile(r'\bheight="\d+"'),
    }
    for tag in img_tags:
        for name, pattern in required.items():
            assert pattern.search(tag), (
                f"{key}: <img> missing valid {name}=…: {tag[:120]}…"
            )


@pytest.mark.parametrize("key", list(EXPECTED_SECTIONS.keys()))
def test_template_no_placeholder_strings(key):
    html = (TEMPLATE_APPS_DIR / key / "index.html").read_text(encoding="utf-8")
    visible_text = TAG_RE.sub(" ", html)
    m = PLACEHOLDER_FORBIDDEN.search(visible_text)
    assert m is None, f"{key}: placeholder string {m.group(0)!r} present in visible text"


@pytest.mark.parametrize("key", list(EXPECTED_SECTIONS.keys()))
def test_template_only_whitelisted_external_hosts(key):
    html = (TEMPLATE_APPS_DIR / key / "index.html").read_text(encoding="utf-8")
    hosts = set(EXTERNAL_URL_RE.findall(html))
    bad = hosts - ALLOWED_HOSTS
    assert not bad, f"{key}: non-whitelisted external hosts: {sorted(bad)}"


@pytest.mark.parametrize("key", list(EXPECTED_SECTIONS.keys()))
def test_template_loads_main_js_and_css(key):
    html = (TEMPLATE_APPS_DIR / key / "index.html").read_text(encoding="utf-8")
    assert 'href="styles/main.css"' in html, f"{key}: missing styles/main.css link"
    assert 'src="src/main.js"' in html, f"{key}: missing src/main.js script"
    assert 'type="module"' in html, f"{key}: src/main.js must load as ES module"
