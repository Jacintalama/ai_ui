"""SSRF guard: only public http(s) URLs pass; private/loopback/link-local/
metadata hosts are blocked (literal IPs need no DNS; hostnames are resolved)."""
from handlers.url_guard import is_safe_public_url, _is_blocked_ip


def test_blocked_ip_classifier():
    for bad in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1",
                "169.254.169.254", "::1", "0.0.0.0", "fd00::1"):
        assert _is_blocked_ip(bad) is True, bad
    for ok in ("8.8.8.8", "1.1.1.1", "93.184.216.34"):
        assert _is_blocked_ip(ok) is False, ok


def test_scheme_and_host_rules():
    assert is_safe_public_url("ftp://example.com") is False       # scheme
    assert is_safe_public_url("file:///etc/passwd") is False
    assert is_safe_public_url("notaurl") is False                 # no host
    assert is_safe_public_url("") is False


def test_literal_ip_urls_need_no_dns():
    assert is_safe_public_url("http://169.254.169.254/latest/meta-data") is False
    assert is_safe_public_url("http://127.0.0.1:8080/") is False
    assert is_safe_public_url("https://10.0.0.5/") is False
    assert is_safe_public_url("https://[::1]/") is False


def test_hostname_resolution(monkeypatch):
    # resolver returns (family, type, proto, canonname, sockaddr) tuples
    def fake(host, port, *a, **k):
        ip = {"public.example": "93.184.216.34", "evil.example": "10.1.2.3"}[host]
        return [(2, 1, 6, "", (ip, 0))]
    monkeypatch.setattr("handlers.url_guard.socket.getaddrinfo", fake)
    assert is_safe_public_url("https://public.example/x") is True
    assert is_safe_public_url("http://public.example/x") is True   # http allowed
    assert is_safe_public_url("https://evil.example/x") is False    # resolves private


def test_unresolvable_host_is_blocked(monkeypatch):
    def boom(host, port, *a, **k):
        raise OSError("nxdomain")
    monkeypatch.setattr("handlers.url_guard.socket.getaddrinfo", boom)
    assert is_safe_public_url("https://nope.invalid/") is False
