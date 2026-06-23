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
        frames = await capture_site("https://example.com", max_frames=2)
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
            frames = await capture_site(f"http://127.0.0.1:{port}/", max_frames=4)
        except CaptureError as e:
            pytest.skip(f"chromium not available: {e}")
    finally:
        srv.shutdown()
    assert len(frames) >= 3
    hashes = {hashlib.md5(f).hexdigest() for f in frames}
    assert len(hashes) == len(frames)  # every scrolled frame is different

