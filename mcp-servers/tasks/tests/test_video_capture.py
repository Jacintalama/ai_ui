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
def test_assert_capturable_rejects(url):
    with pytest.raises(CaptureError):
        assert_capturable(url)


def test_assert_capturable_allows_public_ip_literal():
    # A public IP literal resolves to itself — no DNS needed, safe offline.
    assert assert_capturable("https://1.1.1.1/") == "https://1.1.1.1/"


def test_capture_enabled_default_true(monkeypatch):
    monkeypatch.delenv("VIDEO_CAPTURE_ENABLED", raising=False)
    assert capture_enabled() is True
    monkeypatch.setenv("VIDEO_CAPTURE_ENABLED", "false")
    assert capture_enabled() is False
