"""Coverage for the API-key auth dependency (auth/api_key.py) as used against real routes:
scope enforcement, ownership-via-key, the per-key rate limit, and cursor pagination on
GET /targets/{id}/checks (Phase 6, prompt 6.7). CRUD for /api-keys itself lives in
test_api_keys.py.
"""

from datetime import datetime, timezone

from sqlalchemy import text

from database import engine


async def _register_and_create_key(client, email, scope="read", logout=True):
    """Register, create an API key of the given scope, and (by default) log out so the
    client's cookie is cleared — isolating tests that want to prove the key alone is
    sufficient, not a lingering cookie. Returns the raw key."""
    await client.post("/auth/register", json={"email": email, "password": "pw"})
    created = await client.post("/api-keys", json={"name": "Test key", "scope": scope})
    raw_key = created.json()["key"]
    if logout:
        await client.post("/auth/logout")
    return raw_key


async def _insert_check(target_id: int, region: str = "local", **overrides) -> int:
    values = {
        "target_id": target_id,
        "checked_at": datetime.now(timezone.utc),
        "status_code": 200,
        "latency_ms": 100,
        "is_up": True,
        "error": None,
        "region": region,
    }
    values.update(overrides)
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                INSERT INTO checks (target_id, checked_at, status_code, latency_ms, is_up, error, region)
                VALUES (:target_id, :checked_at, :status_code, :latency_ms, :is_up, :error, :region)
                RETURNING id
                """
            ),
            values,
        )
        return result.scalar_one()


async def _bulk_insert_checks(target_id: int, count: int, region: str = "local") -> None:
    """Fast bulk insert via generate_series — used only for the pagination-cap test, where
    creating thousands of rows one at a time would be needlessly slow."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO checks (target_id, checked_at, status_code, latency_ms, is_up, error, region)
                SELECT :target_id, now() - (n || ' seconds')::interval, 200, 100, true, NULL, :region
                FROM generate_series(1, :count) AS n
                """
            ),
            {"target_id": target_id, "region": region, "count": count},
        )


# --- Basic key validity ---


async def test_valid_key_succeeds_on_a_read_endpoint(client):
    raw_key = await _register_and_create_key(client, "keyvalid@example.com")
    resp = await client.get("/targets", headers={"Authorization": f"Bearer {raw_key}"})
    assert resp.status_code == 200


async def test_unknown_key_is_rejected(client):
    resp = await client.get("/targets", headers={"Authorization": "Bearer um_totally-made-up-key"})
    assert resp.status_code == 401


async def test_revoked_key_is_rejected(client):
    await client.post("/auth/register", json={"email": "keyrevoked@example.com", "password": "pw"})
    created = await client.post("/api-keys", json={"name": "To revoke"})
    raw_key = created.json()["key"]
    key_id = created.json()["id"]
    await client.delete(f"/api-keys/{key_id}")
    await client.post("/auth/logout")

    resp = await client.get("/targets", headers={"Authorization": f"Bearer {raw_key}"})
    assert resp.status_code == 401


async def test_malformed_bearer_header_is_rejected_not_silently_ignored(client):
    """An explicitly-presented (but empty/garbage) Bearer token must fail honestly, not
    silently fall back to "unauthenticated" in a way that could be confused with a missing
    header."""
    resp = await client.get("/targets", headers={"Authorization": "Bearer "})
    assert resp.status_code == 401


async def test_non_bearer_authorization_header_falls_back_to_cookie(client):
    """Only a well-formed `Bearer <token>` header is treated as a key attempt — anything else
    (e.g. Basic auth) is simply not a key, so a request carrying it (with a valid cookie
    session also present) must still succeed via the cookie, not 401 on the unrecognized
    scheme."""
    await client.post("/auth/register", json={"email": "keynonbearer@example.com", "password": "pw"})
    resp = await client.get("/targets", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert resp.status_code == 200


async def test_no_authorization_header_falls_back_to_cookie_normally(client):
    await client.post("/auth/register", json={"email": "keynoheader@example.com", "password": "pw"})
    resp = await client.get("/targets")
    assert resp.status_code == 200


async def test_no_key_and_no_cookie_is_unauthenticated(client):
    resp = await client.get("/targets")
    assert resp.status_code == 401


# --- Scope enforcement ---


async def test_read_scope_key_can_read(client):
    raw_key = await _register_and_create_key(client, "keyreadok@example.com", scope="read")
    headers = {"Authorization": f"Bearer {raw_key}"}
    assert (await client.get("/targets", headers=headers)).status_code == 200


async def test_read_scope_key_cannot_create_a_target(client):
    raw_key = await _register_and_create_key(client, "keyreadonly@example.com", scope="read")
    headers = {"Authorization": f"Bearer {raw_key}"}
    resp = await client.post("/targets", json={"url": "https://example.com/via-read-key"}, headers=headers)
    assert resp.status_code == 403
    assert "scope" in resp.json()["detail"].lower()


async def test_read_scope_key_cannot_manage_webhooks(client):
    raw_key = await _register_and_create_key(client, "keyreadwebhook@example.com", scope="read")
    headers = {"Authorization": f"Bearer {raw_key}"}
    assert (await client.get("/webhooks", headers=headers)).status_code == 403
    assert (
        await client.post("/webhooks", json={"url": "https://example.com/hook"}, headers=headers)
    ).status_code == 403


async def test_full_scope_key_can_create_pause_and_delete_a_target(client):
    raw_key = await _register_and_create_key(client, "keyfullops@example.com", scope="full")
    headers = {"Authorization": f"Bearer {raw_key}"}

    created = await client.post("/targets", json={"url": "https://example.com/via-full-key"}, headers=headers)
    assert created.status_code == 201
    target_id = created.json()["id"]

    paused = await client.post(f"/targets/{target_id}/pause", headers=headers)
    assert paused.status_code == 200
    assert paused.json()["paused"] is True

    deleted = await client.delete(f"/targets/{target_id}", headers=headers)
    assert deleted.status_code == 204


async def test_full_scope_key_also_covers_read_operations(client):
    """'full' is a strict superset of 'read' — a full-scope key must succeed on the
    read-scoped endpoints too, not just the write ones."""
    raw_key = await _register_and_create_key(client, "keyfullread@example.com", scope="full")
    headers = {"Authorization": f"Bearer {raw_key}"}
    assert (await client.get("/targets", headers=headers)).status_code == 200


async def test_full_scope_key_can_manage_webhooks(client):
    raw_key = await _register_and_create_key(client, "keyfullwebhook@example.com", scope="full")
    headers = {"Authorization": f"Bearer {raw_key}"}
    created = await client.post("/webhooks", json={"url": "https://example.com/hook"}, headers=headers)
    assert created.status_code == 201
    assert (await client.get("/webhooks", headers=headers)).status_code == 200


async def test_read_scope_key_can_read_target_checks_and_export_endpoints(client):
    await client.post("/auth/register", json={"email": "keyreadeverything@example.com", "password": "pw"})
    created_target = await client.post("/targets", json={"url": "https://example.com/read-everything"})
    target_id = created_target.json()["id"]
    await _insert_check(target_id)
    created_key = await client.post("/api-keys", json={"name": "Read key", "scope": "read"})
    raw_key = created_key.json()["key"]
    await client.post("/auth/logout")

    headers = {"Authorization": f"Bearer {raw_key}"}
    assert (await client.get(f"/targets/{target_id}", headers=headers)).status_code == 200
    assert (await client.get(f"/targets/{target_id}/checks?region=local", headers=headers)).status_code == 200
    assert (await client.get(f"/targets/{target_id}/export?region=local", headers=headers)).status_code == 200


# --- Ownership via key ---


async def test_key_cannot_access_another_users_targets(client):
    await client.post("/auth/register", json={"email": "keyowner@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/key-owner-only"})
    target_id = created.json()["id"]
    await client.post("/auth/logout")

    raw_key = await _register_and_create_key(client, "keyintruder@example.com", scope="full")
    headers = {"Authorization": f"Bearer {raw_key}"}

    assert (await client.get(f"/targets/{target_id}", headers=headers)).status_code == 404
    assert (await client.get(f"/targets/{target_id}/checks?region=local", headers=headers)).status_code == 404
    assert (await client.get(f"/targets/{target_id}/export?region=local", headers=headers)).status_code == 404
    assert (await client.post(f"/targets/{target_id}/pause", headers=headers)).status_code == 404
    assert (await client.delete(f"/targets/{target_id}", headers=headers)).status_code == 404

    # And the key's own list never surfaces the other user's target at all.
    listing = await client.get("/targets", headers=headers)
    assert listing.json() == []


async def test_key_only_ever_sees_its_own_owners_targets_in_list(client):
    await client.post("/auth/register", json={"email": "keylistowner@example.com", "password": "pw"})
    await client.post("/targets", json={"url": "https://example.com/key-list-owner"})
    created_key = await client.post("/api-keys", json={"name": "Owner key"})
    raw_key = created_key.json()["key"]

    resp = await client.get("/targets", headers={"Authorization": f"Bearer {raw_key}"})
    assert len(resp.json()) == 1
    assert resp.json()[0]["url"] == "https://example.com/key-list-owner"


# --- Rate limiting ---


async def test_key_scoped_rate_limit_fires_after_sixty_per_minute(client):
    raw_key = await _register_and_create_key(client, "keyratelimit@example.com")
    headers = {"Authorization": f"Bearer {raw_key}"}

    for _ in range(60):
        resp = await client.get("/targets", headers=headers)
        assert resp.status_code == 200
    limited = await client.get("/targets", headers=headers)
    assert limited.status_code == 429


async def test_key_scoped_rate_limit_does_not_affect_cookie_auth_on_the_same_route(client):
    """The core proof this is keyed by the API key, not by IP: exhausting a key's quota from
    this test client must not also exhaust the IP-keyed budget a cookie-authenticated request
    from the very same client would fall back to if the keying were wrong."""
    await client.post("/auth/register", json={"email": "keyratelimitcookie@example.com", "password": "pw"})
    created = await client.post("/api-keys", json={"name": "Rate limit key"})
    raw_key = created.json()["key"]
    headers = {"Authorization": f"Bearer {raw_key}"}

    for _ in range(60):
        resp = await client.get("/targets", headers=headers)
        assert resp.status_code == 200
    assert (await client.get("/targets", headers=headers)).status_code == 429

    # Same client (same IP under the hood), cookie still attached from registration — must
    # succeed, proving the 60-request budget just exhausted was the key's own, not the IP's.
    cookie_resp = await client.get("/targets")
    assert cookie_resp.status_code == 200


async def test_different_api_keys_have_independent_rate_limits(client):
    await client.post("/auth/register", json={"email": "keyratelimitindependent@example.com", "password": "pw"})
    key_a = (await client.post("/api-keys", json={"name": "Key A"})).json()["key"]
    key_b = (await client.post("/api-keys", json={"name": "Key B"})).json()["key"]

    for _ in range(60):
        resp = await client.get("/targets", headers={"Authorization": f"Bearer {key_a}"})
        assert resp.status_code == 200
    assert (await client.get("/targets", headers={"Authorization": f"Bearer {key_a}"})).status_code == 429

    still_ok = await client.get("/targets", headers={"Authorization": f"Bearer {key_b}"})
    assert still_ok.status_code == 200


# --- Pagination on GET /targets/{id}/checks ---


async def test_pagination_ignored_entirely_for_cookie_authenticated_requests(client):
    await client.post("/auth/register", json={"email": "keypagcookie@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/pag-cookie"})
    target_id = created.json()["id"]
    for _ in range(3):
        await _insert_check(target_id)

    resp = await client.get(f"/targets/{target_id}/checks", params={"region": "local", "limit": 2})
    assert resp.status_code == 200
    assert len(resp.json()) == 2  # the existing, unpaginated limit behavior — unchanged
    assert "x-next-cursor" not in resp.headers  # never signaled for cookie auth, even though more rows exist


async def test_pagination_covers_every_row_exactly_once_via_cursor(client):
    """Walks every page with limit=2 across 5 known-inserted checks and confirms the full
    traversal returns every row exactly once, none duplicated, none skipped, in ascending
    order — the core "pagination returns correct pages" proof."""
    await client.post("/auth/register", json={"email": "keypagexact@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/pag-exact"})
    target_id = created.json()["id"]
    for i in range(5):
        await _insert_check(target_id, latency_ms=100 + i)
    raw_key = (await client.post("/api-keys", json={"name": "Pagination key exact"})).json()["key"]
    await client.post("/auth/logout")
    headers = {"Authorization": f"Bearer {raw_key}"}

    all_latencies: list[int] = []
    cursor = None
    for _ in range(10):
        params = {"region": "local", "limit": 2}
        if cursor is not None:
            params["cursor"] = cursor
        resp = await client.get(f"/targets/{target_id}/checks", params=params, headers=headers)
        page = resp.json()
        all_latencies.extend(c["latency_ms"] for c in page)
        next_cursor = resp.headers.get("x-next-cursor")
        if next_cursor is None:
            break
        cursor = int(next_cursor)

    assert all_latencies == [100, 101, 102, 103, 104]  # every row, exactly once, in order


async def test_pagination_respects_the_max_size_cap(client):
    """2005 real rows, requested with a limit far above the 2000 cap — the response must be
    clamped to exactly 2000, with a next-cursor signaling the remaining 5."""
    await client.post("/auth/register", json={"email": "keypagcap@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/pag-cap"})
    target_id = created.json()["id"]
    await _bulk_insert_checks(target_id, 2005)
    raw_key = (await client.post("/api-keys", json={"name": "Cap key"})).json()["key"]
    await client.post("/auth/logout")

    resp = await client.get(
        f"/targets/{target_id}/checks",
        params={"region": "local", "limit": 5000},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 2000  # clamped, not 5000 and not all 2005
    assert "x-next-cursor" in resp.headers  # 5 rows remain beyond the cap
