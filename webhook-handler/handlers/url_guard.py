"""SSRF-safe URL validation for user-supplied capture URLs.

Allows only public http(s) URLs. Blocks private / loopback / link-local /
reserved / multicast / unspecified IPs, including the cloud metadata address
169.254.169.254 - whether the URL uses a literal IP or a hostname that resolves
to one. Used before handing a user URL to the headless-browser capture.
"""
import ipaddress
import socket
from urllib.parse import urlparse


def _is_blocked_ip(ip_str: str) -> bool:
    """True if the address is anything but a normal public unicast address."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparseable -> treat as unsafe
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
        or ip.is_multicast or ip.is_unspecified
    )


def is_safe_public_url(url: str) -> bool:
    """True only for a public http(s) URL. Literal-IP hosts are checked directly;
    hostnames are DNS-resolved and rejected if ANY answer is a non-public IP.
    Any parse/resolution error -> unsafe (fail closed)."""
    try:
        p = urlparse((url or "").strip())
    except Exception:  # noqa: BLE001
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = p.hostname
    if not host:
        return False
    # Literal IP (v4 or v6, possibly bracketed) -> no DNS needed.
    try:
        ipaddress.ip_address(host)
        return not _is_blocked_ip(host)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:  # noqa: BLE001 - DNS failure -> unsafe
        return False
    if not infos:
        return False
    return all(not _is_blocked_ip(info[4][0]) for info in infos)
