"""Unit tests for worker/ssrf.py's blocklist logic (check-time SSRF protection).

Uses IP literals throughout, deliberately — is_url_blocked() resolves hostnames via
socket.getaddrinfo(), and a numeric IP address resolves locally without any real DNS query,
so these tests have no network dependency and can't flake on DNS.
"""

import pytest

from ssrf import is_url_blocked


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://127.0.0.1/",
        "http://10.1.2.3/",
        "http://172.16.5.5/",
        "http://192.168.0.10/",
        "http://169.254.169.254/",  # cloud metadata endpoint
    ],
)
def test_blocked_ranges(url):
    blocked, reason = is_url_blocked(url)
    assert blocked is True
    assert reason


def test_public_ip_literal_allowed():
    blocked, reason = is_url_blocked("http://1.1.1.1/")
    assert blocked is False
    assert reason is None


def test_missing_hostname_blocked():
    blocked, reason = is_url_blocked("http:///path")
    assert blocked is True
