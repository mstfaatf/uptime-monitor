"""POST/GET /api-keys and DELETE /api-keys/{id} (Phase 6, prompt 6.7). Auth-dependency/scope/
ownership-via-key/rate-limit/pagination behavior lives in test_api_key_auth.py — this file is
CRUD for the /api-keys router itself, which is cookie-only (see routers/api_keys.py's module
docstring: a key can never manage other keys, at any scope).
"""


async def _register(client, email="apikeytest@example.com"):
    resp = await client.post("/auth/register", json={"email": email, "password": "pw"})
    assert resp.status_code == 200


async def test_create_and_list_api_key(client):
    await _register(client)
    created = await client.post("/api-keys", json={"name": "CI integration"})
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "CI integration"
    assert body["scope"] == "read"  # default
    assert body["revoked_at"] is None
    assert body["last_used_at"] is None
    assert body["key"].startswith("um_")
    assert body["key_prefix"] == body["key"][:12]

    listing = await client.get("/api-keys")
    assert listing.status_code == 200
    assert len(listing.json()) == 1
    assert "key" not in listing.json()[0]  # raw key never returned again
    assert "key_hash" not in listing.json()[0]


async def test_create_api_key_with_full_scope(client):
    await _register(client)
    created = await client.post("/api-keys", json={"name": "Full access", "scope": "full"})
    assert created.status_code == 201
    assert created.json()["scope"] == "full"


async def test_create_api_key_rejects_invalid_scope(client):
    await _register(client)
    resp = await client.post("/api-keys", json={"name": "Bad scope", "scope": "admin"})
    assert resp.status_code == 400


async def test_create_api_key_rejects_empty_name(client):
    await _register(client)
    resp = await client.post("/api-keys", json={"name": "   "})
    assert resp.status_code == 400


async def test_each_created_key_is_unique(client):
    await _register(client)
    first = await client.post("/api-keys", json={"name": "Key A"})
    second = await client.post("/api-keys", json={"name": "Key B"})
    assert first.json()["key"] != second.json()["key"]
    assert first.json()["key_prefix"] != second.json()["key_prefix"]


async def test_revoke_api_key_sets_revoked_at_and_keeps_it_listed(client):
    await _register(client)
    created = await client.post("/api-keys", json={"name": "To revoke"})
    key_id = created.json()["id"]

    revoked = await client.delete(f"/api-keys/{key_id}")
    assert revoked.status_code == 204

    listing = await client.get("/api-keys")
    assert len(listing.json()) == 1  # still listed — soft delete, not removed
    assert listing.json()[0]["revoked_at"] is not None


async def test_revoke_is_idempotent(client):
    await _register(client)
    created = await client.post("/api-keys", json={"name": "Double revoke"})
    key_id = created.json()["id"]

    first = await client.delete(f"/api-keys/{key_id}")
    second = await client.delete(f"/api-keys/{key_id}")
    assert first.status_code == 204
    assert second.status_code == 204


async def test_user_cannot_list_or_revoke_another_users_api_key(client):
    await _register(client, "apikey-owner@example.com")
    created = await client.post("/api-keys", json={"name": "Owner's key"})
    key_id = created.json()["id"]
    await client.post("/auth/logout")

    await _register(client, "apikey-intruder@example.com")
    listing = await client.get("/api-keys")
    assert listing.json() == []  # never sees the other user's key

    revoke_resp = await client.delete(f"/api-keys/{key_id}")
    assert revoke_resp.status_code == 404  # not 403 — can't confirm the id even exists

    await client.post("/auth/logout")
    await client.post("/auth/login", json={"email": "apikey-owner@example.com", "password": "pw"})
    still_there = await client.get("/api-keys")
    assert still_there.json()[0]["revoked_at"] is None  # the intruder's failed attempt did nothing


async def test_api_key_endpoints_require_authentication(client):
    assert (await client.get("/api-keys")).status_code == 401
    assert (await client.post("/api-keys", json={"name": "x"})).status_code == 401
    assert (await client.delete("/api-keys/1")).status_code == 401


async def test_api_key_cannot_be_used_to_manage_api_keys(client):
    """The prompt's explicit rule: API-key auth can never manage API keys themselves, at
    either scope. routers/api_keys.py depends on the plain cookie-only get_current_user, so a
    Bearer header here is simply never consulted at all — with no cookie present, this must
    401 exactly like any other unauthenticated request, even a 'full'-scope key attached."""
    await _register(client)
    created = await client.post("/api-keys", json={"name": "Full key", "scope": "full"})
    raw_key = created.json()["key"]
    await client.post("/auth/logout")  # clear the cookie — key alone must not be enough here

    headers = {"Authorization": f"Bearer {raw_key}"}
    assert (await client.get("/api-keys", headers=headers)).status_code == 401
    assert (await client.post("/api-keys", json={"name": "y"}, headers=headers)).status_code == 401
    assert (await client.delete("/api-keys/1", headers=headers)).status_code == 401


async def test_api_key_creation_rate_limited_after_ten_per_minute(client):
    await _register(client)
    for i in range(10):
        resp = await client.post("/api-keys", json={"name": f"Key {i}"})
        assert resp.status_code == 201
    limited = await client.post("/api-keys", json={"name": "Overflow"})
    assert limited.status_code == 429
