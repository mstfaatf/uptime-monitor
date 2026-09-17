"""POST/GET /tags and DELETE /tags/{id} (Phase 6, prompt 6.4). Attaching/detaching a tag to a
target, and the ?tag= filter on GET /targets, are covered separately in
test_target_tags.py — this file is tag CRUD only.
"""


async def _register(client, email="tagger@example.com"):
    resp = await client.post("/auth/register", json={"email": email, "password": "pw"})
    assert resp.status_code == 200


async def test_create_and_list_tags(client):
    await _register(client)
    created = await client.post("/tags", json={"name": "production"})
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "production"
    assert "id" in body and "created_at" in body

    listing = await client.get("/tags")
    assert listing.status_code == 200
    names = [t["name"] for t in listing.json()]
    assert names == ["production"]


async def test_tags_are_listed_alphabetically(client):
    await _register(client)
    for name in ("zeta", "alpha", "mu"):
        assert (await client.post("/tags", json={"name": name})).status_code == 201

    listing = await client.get("/tags")
    assert [t["name"] for t in listing.json()] == ["alpha", "mu", "zeta"]


async def test_duplicate_tag_name_for_same_user_rejected(client):
    await _register(client)
    first = await client.post("/tags", json={"name": "staging"})
    assert first.status_code == 201
    dupe = await client.post("/tags", json={"name": "staging"})
    assert dupe.status_code == 409


async def test_same_tag_name_allowed_for_different_users(client):
    await _register(client, "tagger-a@example.com")
    assert (await client.post("/tags", json={"name": "shared-name"})).status_code == 201
    await client.post("/auth/logout")

    await _register(client, "tagger-b@example.com")
    # Uniqueness is per-user, not global — same convention as target URL uniqueness.
    assert (await client.post("/tags", json={"name": "shared-name"})).status_code == 201


async def test_empty_tag_name_rejected(client):
    await _register(client)
    resp = await client.post("/tags", json={"name": "   "})
    assert resp.status_code == 400


async def test_overlong_tag_name_rejected(client):
    await _register(client)
    resp = await client.post("/tags", json={"name": "x" * 101})
    assert resp.status_code == 400


async def test_delete_tag_removes_it(client):
    await _register(client)
    created = await client.post("/tags", json={"name": "temporary"})
    tag_id = created.json()["id"]

    deleted = await client.delete(f"/tags/{tag_id}")
    assert deleted.status_code == 204

    listing = await client.get("/tags")
    assert listing.json() == []


async def test_user_cannot_list_or_delete_another_users_tags(client):
    await _register(client, "tag-owner@example.com")
    created = await client.post("/tags", json={"name": "owner-only"})
    tag_id = created.json()["id"]
    await client.post("/auth/logout")

    await _register(client, "tag-intruder@example.com")
    listing = await client.get("/tags")
    assert listing.status_code == 200
    assert listing.json() == []  # never sees the other user's tag

    delete_resp = await client.delete(f"/tags/{tag_id}")
    # 404, not 403 — same "can't confirm the id even exists" pattern as every other
    # ownership-scoped endpoint in this app.
    assert delete_resp.status_code == 404

    await client.post("/auth/logout")
    login = await client.post("/auth/login", json={"email": "tag-owner@example.com", "password": "pw"})
    assert login.status_code == 200
    still_there = await client.get("/tags")
    assert [t["name"] for t in still_there.json()] == ["owner-only"]


async def test_tag_endpoints_require_authentication(client):
    assert (await client.get("/tags")).status_code == 401
    assert (await client.post("/tags", json={"name": "x"})).status_code == 401
    assert (await client.delete("/tags/1")).status_code == 401
