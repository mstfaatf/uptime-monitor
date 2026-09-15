"""Baseline hardening headers (prompt 5.8) — this API is JSON-only, so these are the standard
headers relevant to any HTTP API rather than a full CSP."""


async def test_response_carries_baseline_security_headers(client):
    response = await client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
