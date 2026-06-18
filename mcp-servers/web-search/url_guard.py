"""Block SSRF targets before fetching a user-supplied URL."""
import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURLError(ValueError):
    pass


def _ip_is_blocked(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return (
        addr.is_private or addr.is_loopback or addr.is_link_local
        or addr.is_reserved or addr.is_multicast or addr.is_unspecified
    )


def assert_safe_url(url: str) -> None:
    """Raise UnsafeURLError unless `url` is public http(s)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError("only http(s) URLs are allowed")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL has no host")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"cannot resolve host: {exc}") from exc
    for info in infos:
        ip = info[4][0]
        if _ip_is_blocked(ip):
            raise UnsafeURLError(f"blocked internal/loopback address: {ip}")


async def safe_get(client, url: str, *, headers=None, max_redirects: int = 5):
    """GET `url` following redirects MANUALLY, re-validating every hop.

    httpx's follow_redirects=True only validated the first URL, so a public URL
    that 30x-redirects to an internal address bypassed assert_safe_url(). Here
    each hop's target is checked before it is fetched. The client MUST be
    created without follow_redirects (the default) so we control every hop.
    """
    current = url
    for _ in range(max_redirects + 1):
        assert_safe_url(current)
        resp = await client.get(current, headers=headers, follow_redirects=False)
        location = resp.headers.get("location")
        if resp.is_redirect and location:
            current = str(resp.url.join(location))  # resolve relative redirects
            continue
        return resp
    raise UnsafeURLError("too many redirects")
