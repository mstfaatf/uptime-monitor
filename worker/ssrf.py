"""SSRF protection: block localhost and private/link-local IP ranges."""

import ipaddress
import socket
from urllib.parse import urlparse


# Blocked ranges per SPEC: localhost, 127.0.0.1, 10/8, 172.16/12, 192.168/16, 169.254/16
_BLOCKED_NETS = [
    ipaddress.ip_network("127.0.0.0/8"),      # loopback
    ipaddress.ip_network("10.0.0.0/8"),       # private
    ipaddress.ip_network("172.16.0.0/12"),    # private
    ipaddress.ip_network("192.168.0.0/16"),   # private
    ipaddress.ip_network("169.254.0.0/16"),   # link-local
]
_BLOCKED_HOSTNAMES = frozenset(("localhost", "localhost."))


def _is_blocked_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    if ip.version == 4:
        for net in _BLOCKED_NETS:
            if ip in net:
                return True
        return False
    # IPv6: block ::1
    return ip.is_loopback


def is_url_blocked(url: str) -> tuple[bool, str | None]:
    """
    Return (True, reason) if the URL should be blocked for SSRF; else (False, None).
    Resolves hostname to IP(s) and blocks if any resolve to blocked ranges.
    """
    try:
        parsed = urlparse(url)
    except Exception as e:
        return True, f"Invalid URL: {e}"
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return True, "Missing hostname"
    if host in _BLOCKED_HOSTNAMES:
        return True, "localhost is not allowed"
    # Resolve hostname to IP(s)
    try:
        for (_, _, _, _, sockaddr) in socket.getaddrinfo(host, None):
            ip_str = sockaddr[0]
            if _is_blocked_ip(ip_str):
                return True, f"Resolved to blocked IP: {ip_str}"
    except socket.gaierror as e:
        return True, f"Resolution failed: {e}"
    return False, None
