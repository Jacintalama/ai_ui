"""Unit tests for the URL-capture SSRF guard and helpers. The real-browser
capture test is skipped unless Playwright+Chromium are installed locally."""
import pytest

from video_capture import CaptureError, assert_capturable, capture_enabled, is_blocked_ip


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "10.0.0.5", "172.16.3.4", "192.168.1.1", "169.254.169.254",
    "0.0.0.0", "::1", "fc00::1", "fe80::1", "::ffff:127.0.0.1", "not-an-ip",
])
def test_is_blocked_ip_blocks_internal(ip):
    assert is_blocked_ip(ip) is True


@pytest.mark.parametrize("ip", ["1.1.1.1", "8.8.8.8", "93.184.216.34", "2606:2800:220:1::1"])
def test_is_blocked_ip_allows_public(ip):
    assert is_blocked_ip(ip) is False


@pytest.mark.parametrize("url", [
    "ftp://example.com", "file:///etc/passwd", "http://localhost/x",
    "http://app.localhost/x", "http://127.0.0.1/x", "http://10.0.0.1/x",
    "http://169.254.169.254/latest/meta-data/",
])
async def test_assert_capturable_rejects(url):
    with pytest.raises(CaptureError):
        await assert_capturable(url)


async def test_assert_capturable_allows_public_ip_literal():
    # A public IP literal resolves to itself — no DNS needed, safe offline.
    assert await assert_capturable("https://1.1.1.1/") == "https://1.1.1.1/"


async def test_assert_capturable_honors_extra_blocklist(monkeypatch):
    # Operator blocklist (e.g. the box's own public IP) is refused even though
    # it is a public address.
    monkeypatch.setenv("VIDEO_CAPTURE_BLOCKED_HOSTS", "1.1.1.1, mybox.example")
    with pytest.raises(CaptureError):
        await assert_capturable("https://1.1.1.1/")


def test_capture_enabled_default_true(monkeypatch):
    monkeypatch.delenv("VIDEO_CAPTURE_ENABLED", raising=False)
    assert capture_enabled() is True
    monkeypatch.setenv("VIDEO_CAPTURE_ENABLED", "false")
    assert capture_enabled() is False


playwright_async = pytest.importorskip("playwright.async_api")


@pytest.mark.asyncio
async def test_capture_site_real_example():
    """Real headless-Chromium capture of a public page. Skipped if Playwright or
    its Chromium build is not installed (so the suite stays green offline); run
    locally after `python -m playwright install chromium`."""
    from video_capture import CaptureError, capture_site
    try:
        frames, _ctx = await capture_site("https://example.com", max_frames=2)
    except CaptureError as e:
        pytest.skip(f"chromium not available: {e}")
    assert 1 <= len(frames) <= 2
    assert frames[0][:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic


async def test_capture_site_scrolls_into_distinct_frames(monkeypatch):
    """A tall page must yield DISTINCT frames as the engine scrolls top-to-bottom
    (guards against the clip/captureBeyondViewport trap of re-capturing the top).
    Serves a 4-section tall page locally; is_blocked_ip is patched off so the
    SSRF guard (which otherwise blocks 127.0.0.1) allows the loopback test server.
    Skipped if Chromium is unavailable."""
    import hashlib
    import http.server
    import socketserver
    import threading

    import video_capture
    from video_capture import CaptureError, capture_site

    monkeypatch.setattr(video_capture, "is_blocked_ip", lambda ip: False)
    html = (b"<!doctype html><html><body style='margin:0'>"
            b"<div style='height:800px;background:#c00'></div>"
            b"<div style='height:800px;background:#0c0'></div>"
            b"<div style='height:800px;background:#00c'></div>"
            b"<div style='height:800px;background:#cc0'></div>"
            b"</body></html>")

    class _H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, *a):
            pass

    srv = socketserver.TCPServer(("127.0.0.1", 0), _H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        try:
            frames, _ctx = await capture_site(f"http://127.0.0.1:{port}/", max_frames=4)
        except CaptureError as e:
            pytest.skip(f"chromium not available: {e}")
    finally:
        srv.shutdown()
    assert len(frames) >= 3
    hashes = {hashlib.md5(f).hexdigest() for f in frames}
    assert len(hashes) == len(frames)  # every scrolled frame is different


# ---- extract_site_context ----------------------------------------------------

from video_capture import extract_site_context  # noqa: E402


class _FakePage:
    def __init__(self, title="T", headings=None, meta="M", fail=False):
        self._title, self._headings, self._meta, self._fail = title, headings or ["A", "B"], meta, fail

    async def title(self):
        if self._fail:
            raise RuntimeError("boom")
        return self._title

    async def evaluate(self, js):
        if self._fail:
            raise RuntimeError("boom")
        return self._headings if "querySelectorAll" in js else self._meta


async def test_extract_site_context_reads_fields():
    ctx = await extract_site_context(_FakePage(title="Acme", headings=["Hero", "Pricing"], meta="desc"))
    assert ctx["title"] == "Acme"
    assert ctx["headings"] == ["Hero", "Pricing"]
    assert ctx["meta_description"] == "desc"


async def test_extract_site_context_never_raises():
    ctx = await extract_site_context(_FakePage(fail=True))
    assert ctx == {"title": "", "headings": [], "meta_description": ""}


# ---- same_origin --------------------------------------------------------

from video_capture import same_origin  # noqa: E402


def test_same_origin_matches_same_host():
    assert same_origin("https://animepahe.ch/", "https://animepahe.ch/az-list/") is True


def test_same_origin_rejects_external_host():
    assert same_origin("https://animepahe.ch/", "https://google.com/") is False


def test_same_origin_rejects_non_http_schemes():
    base = "https://animepahe.ch/"
    assert same_origin(base, "mailto:a@b.com") is False
    assert same_origin(base, "tel:+123") is False
    assert same_origin(base, "javascript:void(0)") is False
    assert same_origin(base, "#top") is False


def test_same_origin_treats_www_as_same():
    assert same_origin("https://example.com/", "https://www.example.com/x") is True


# ---- pick_walk_target, normalize_url, COLLECT_ANCHORS_JS ----

from video_capture import pick_walk_target, normalize_url, COLLECT_ANCHORS_JS  # noqa: E402


def _cand(href, x=100, y=300, w=200, h=120, text="link"):
    return {"href": href, "x": x, "y": y, "w": w, "h": h, "text": text}


def test_collect_anchors_js_is_a_function_expression():
    assert "querySelectorAll" in COLLECT_ANCHORS_JS
    assert "getBoundingClientRect" in COLLECT_ANCHORS_JS


def test_normalize_url_strips_fragment_and_trailing_slash():
    assert normalize_url("https://A.com/x/#frag") == "https://a.com/x"
    assert normalize_url("https://a.com/") == "https://a.com"


def test_pick_prefers_largest_same_origin_link():
    base = "https://site.com/"
    cands = [
        _cand("https://site.com/small", w=50, h=50, text="tiny"),
        _cand("https://site.com/big", w=300, h=200, text="Big Poster"),
    ]
    t = pick_walk_target(cands, base, set())
    assert t["href"] == "https://site.com/big"
    assert t["label"] == "Big Poster"
    assert 0.0 <= t["x"] <= 1.0 and 0.0 <= t["y"] <= 1.0


def test_pick_skips_external_and_visited_and_below_fold():
    base = "https://site.com/"
    cands = [
        _cand("https://other.com/x", w=400, h=400, text="external"),
        _cand("https://site.com/seen", w=400, h=400, text="seen"),
        _cand("https://site.com/low", y=760, w=400, h=100, text="below fold"),
        _cand("https://site.com/good", y=300, w=120, h=90, text="good"),
    ]
    visited = {normalize_url("https://site.com/seen")}
    t = pick_walk_target(cands, base, visited)
    assert t["href"] == "https://site.com/good"


def test_pick_skips_denylisted_hrefs():
    base = "https://site.com/"
    cands = [_cand("https://site.com/logout", w=400, h=400, text="Logout")]
    assert pick_walk_target(cands, base, set()) is None


def test_pick_returns_none_when_no_candidates():
    assert pick_walk_target([], "https://site.com/", set()) is None


from video_capture import _walk_with_page


class _FakeWalkPage:
    """Minimal page stub: programmed anchors per URL; goto follows them."""
    def __init__(self, anchors_by_url):
        self._anchors = anchors_by_url
        self.url = ""

    async def goto(self, url, **kw):
        self.url = url

    async def evaluate(self, script, *args):
        if "scrollTo" in script:
            return None
        if "a[href]" in script:                # COLLECT_ANCHORS_JS
            return self._anchors.get(self.url, [])
        return {}                              # extract_site_context internals

    async def screenshot(self, **kw):
        return b"PNG:" + self.url.encode()

    async def title(self):
        return "Title " + self.url

    async def wait_for_timeout(self, ms):
        return None


async def _noop_guard(url):
    return None


async def test_walk_follows_links_until_no_target():
    anchors = {
        "https://s.com/": [{"href": "https://s.com/a", "x": 100, "y": 300, "w": 300, "h": 200, "text": "A"}],
        "https://s.com/a": [{"href": "https://s.com/b", "x": 100, "y": 300, "w": 300, "h": 200, "text": "B"}],
        "https://s.com/b": [],   # dead end
    }
    page = _FakeWalkPage(anchors)
    frames, walk, ctx = await _walk_with_page(
        page, "https://s.com/", max_pages=4, guard=_noop_guard, vw=1280, vh=800, settle_ms=0)
    assert len(frames) == 3
    assert [w["url"] for w in walk] == ["https://s.com/", "https://s.com/a", "https://s.com/b"]
    assert walk[0]["click"]["label"] == "A"
    assert walk[2]["click"] is None            # last page has no onward click


async def test_walk_dedupes_and_respects_max_pages():
    # Every page links back to home -> must stop via visited-dedupe, not loop.
    anchors = {
        "https://s.com/": [{"href": "https://s.com/x", "x": 100, "y": 300, "w": 300, "h": 200, "text": "X"}],
        "https://s.com/x": [{"href": "https://s.com/", "x": 100, "y": 300, "w": 300, "h": 200, "text": "Home"}],
    }
    page = _FakeWalkPage(anchors)
    frames, walk, ctx = await _walk_with_page(
        page, "https://s.com/", max_pages=4, guard=_noop_guard, vw=1280, vh=800, settle_ms=0)
    assert len(frames) == 2                     # home, x, then x's only link is visited -> stop
    assert walk[1]["click"] is None


async def test_walk_truncated_by_max_pages_has_no_dangling_click():
    # Unbroken chain of 5 distinct same-origin pages, but max_pages=3 cuts it
    # short. The last shown page's click must be forced to None, since the
    # page it would point at was never captured.
    anchors = {
        "https://s.com/": [{"href": "https://s.com/a", "x": 100, "y": 300, "w": 300, "h": 200, "text": "A"}],
        "https://s.com/a": [{"href": "https://s.com/b", "x": 100, "y": 300, "w": 300, "h": 200, "text": "B"}],
        "https://s.com/b": [{"href": "https://s.com/c", "x": 100, "y": 300, "w": 300, "h": 200, "text": "C"}],
        "https://s.com/c": [{"href": "https://s.com/d", "x": 100, "y": 300, "w": 300, "h": 200, "text": "D"}],
        "https://s.com/d": [],   # dead end (never reached at max_pages=3)
    }
    page = _FakeWalkPage(anchors)
    frames, walk, ctx = await _walk_with_page(
        page, "https://s.com/", max_pages=3, guard=_noop_guard, vw=1280, vh=800, settle_ms=0)
    assert len(frames) == 3
    assert walk[0]["click"] is not None
    assert walk[-1]["click"] is None

