"""Unit tests for worker/checker.py's timing-breakdown and TLS-cert extraction helpers
(Phase 1 prompt 1.4). These test the pure post-processing logic directly against synthetic
trace-event dicts and fake response/ssl objects — no real network or httpx internals involved
(that's covered by manual verification against the live stack, since it depends on the exact
shape of real httpcore trace events)."""

from unittest.mock import MagicMock

from checker import _extract_cert, _extract_timings


def test_extract_timings_computes_all_phases():
    events = {
        "connection.connect_tcp.started": 100.0,
        "connection.connect_tcp.complete": 100.05,
        "connection.start_tls.started": 100.05,
        "connection.start_tls.complete": 100.08,
        "http11.send_request_headers.complete": 100.081,
        "http11.send_request_body.complete": 100.082,
        "http11.receive_response_headers.complete": 100.11,
    }

    tcp_ms, tls_ms, ttfb_ms = _extract_timings(events)

    assert tcp_ms == 50
    assert tls_ms == 30
    assert ttfb_ms == 28


def test_extract_timings_missing_tls_phase_for_plain_http():
    events = {
        "connection.connect_tcp.started": 100.0,
        "connection.connect_tcp.complete": 100.02,
        "http11.send_request_headers.complete": 100.021,
        "http11.receive_response_headers.complete": 100.05,
    }

    tcp_ms, tls_ms, ttfb_ms = _extract_timings(events)

    assert tcp_ms == 20
    assert tls_ms is None
    assert ttfb_ms == 29


def test_extract_timings_empty_events_all_none():
    tcp_ms, tls_ms, ttfb_ms = _extract_timings({})
    assert (tcp_ms, tls_ms, ttfb_ms) == (None, None, None)


def _fake_ssl_response(cert: dict | None):
    ssl_object = MagicMock()
    ssl_object.getpeercert.return_value = cert
    network_stream = MagicMock()
    network_stream.get_extra_info.return_value = ssl_object
    resp = MagicMock()
    resp.extensions = {"network_stream": network_stream}
    return resp


def test_extract_cert_parses_expiry_and_issuer():
    cert = {
        "notAfter": "Oct 27 22:17:21 2026 GMT",
        "issuer": (
            (("countryName", "US"),),
            (("organizationName", "SSL Corporation"),),
            (("commonName", "Cloudflare TLS Issuing ECC CA 3"),),
        ),
    }
    resp = _fake_ssl_response(cert)

    expires_at, issuer = _extract_cert(resp, "https://example.com/")

    assert expires_at.isoformat() == "2026-10-27T22:17:21+00:00"
    assert issuer == "countryName=US, organizationName=SSL Corporation, commonName=Cloudflare TLS Issuing ECC CA 3"


def test_extract_cert_returns_none_for_http_url_regardless_of_response():
    resp = _fake_ssl_response({"notAfter": "Oct 27 22:17:21 2026 GMT", "issuer": ()})

    expires_at, issuer = _extract_cert(resp, "http://example.com/")

    assert (expires_at, issuer) == (None, None)


def test_extract_cert_returns_none_when_network_stream_missing():
    resp = MagicMock()
    resp.extensions = {}

    assert _extract_cert(resp, "https://example.com/") == (None, None)


def test_extract_cert_returns_none_when_ssl_object_missing():
    network_stream = MagicMock()
    network_stream.get_extra_info.return_value = None
    resp = MagicMock()
    resp.extensions = {"network_stream": network_stream}

    assert _extract_cert(resp, "https://example.com/") == (None, None)


def test_extract_cert_fails_safe_on_malformed_cert():
    # Missing "notAfter" entirely -> KeyError inside the helper, caught, fails safe.
    resp = _fake_ssl_response({"issuer": ()})

    assert _extract_cert(resp, "https://example.com/") == (None, None)
