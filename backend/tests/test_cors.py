"""CORS allowlist behavior: allow_credentials=True means the origin allowlist must be exact,
never a wildcard — verifies CORSMiddleware is actually wired to settings.cors_origins_list
(config.py's default is "http://localhost:3000"), not the old hardcoded single-origin list.
"""


async def test_preflight_from_allowed_origin_succeeds(client):
    response = await client.options(
        "/auth/me",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers["access-control-allow-credentials"] == "true"


async def test_preflight_from_disallowed_origin_rejected(client):
    response = await client.options(
        "/auth/me",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


async def test_actual_request_from_disallowed_origin_gets_no_cors_headers(client):
    # Not a preflight -- CORSMiddleware still runs for simple requests and omits
    # Access-Control-Allow-Origin when the Origin isn't in the allowlist, so the browser's
    # own same-origin policy blocks the response from being read cross-site.
    response = await client.get("/health", headers={"Origin": "https://evil.example"})
    assert response.status_code == 200  # the request itself still succeeds server-side
    assert "access-control-allow-origin" not in response.headers
