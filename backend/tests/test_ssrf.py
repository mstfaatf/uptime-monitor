"""SSRF blocking at target-creation time (backend/security/ssrf.py, POST /targets)."""

import pytest


async def test_public_url_is_allowed(client):
    await client.post("/auth/register", json={"email": "ssrf-ok@example.com", "password": "pw"})
    resp = await client.post("/targets", json={"url": "https://example.com"})
    assert resp.status_code == 201


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/",  # cloud metadata endpoint — the classic SSRF target
    ],
)
async def test_blocked_ranges_rejected_at_creation(client, url):
    await client.post("/auth/register", json={"email": "ssrf-block@example.com", "password": "pw"})
    resp = await client.post("/targets", json={"url": url})
    assert resp.status_code == 400
    assert "cannot be monitored" in resp.json()["detail"]
