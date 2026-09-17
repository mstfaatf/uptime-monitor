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


async def test_rename_tag(client):
    await _register(client)
    created = await client.post("/tags", json={"name": "staging"})
    tag_id = created.json()["id"]

    renamed = await client.patch(f"/tags/{tag_id}", json={"name": "pre-prod"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "pre-prod"
    assert renamed.json()["id"] == tag_id

    listing = await client.get("/tags")
    assert [t["name"] for t in listing.json()] == ["pre-prod"]


async def test_rename_tag_to_same_name_is_a_no_op_not_a_conflict(client):
    await _register(client)
    created = await client.post("/tags", json={"name": "staging"})
    tag_id = created.json()["id"]

    renamed = await client.patch(f"/tags/{tag_id}", json={"name": "staging"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "staging"


async def test_rename_tag_to_a_name_already_used_by_another_of_the_same_users_tags_rejected(client):
    await _register(client)
    await client.post("/tags", json={"name": "production"})
    created = await client.post("/tags", json={"name": "staging"})
    tag_id = created.json()["id"]

    conflict = await client.patch(f"/tags/{tag_id}", json={"name": "production"})
    assert conflict.status_code == 409

    # The tag being renamed is untouched by the rejected attempt.
    listing = await client.get("/tags")
    names = sorted(t["name"] for t in listing.json())
    assert names == ["production", "staging"]


async def test_rename_tag_empty_or_overlong_name_rejected(client):
    await _register(client)
    created = await client.post("/tags", json={"name": "staging"})
    tag_id = created.json()["id"]

    assert (await client.patch(f"/tags/{tag_id}", json={"name": "   "})).status_code == 400
    assert (await client.patch(f"/tags/{tag_id}", json={"name": "x" * 101})).status_code == 400


async def test_rename_tag_keeps_it_attached_to_its_targets(client):
    await _register(client)
    tag_id = (await client.post("/tags", json={"name": "staging"})).json()["id"]
    target_id = (await client.post("/targets", json={"url": "https://example.com/rename-attached"})).json()["id"]
    attach = await client.post(f"/targets/{target_id}/tags", json={"tag_id": tag_id})
    assert attach.status_code == 200

    await client.patch(f"/tags/{tag_id}", json={"name": "pre-prod"})

    targets = await client.get("/targets")
    target = next(t for t in targets.json() if t["id"] == target_id)
    assert [t["name"] for t in target["tags"]] == ["pre-prod"]


async def test_user_cannot_rename_another_users_tag(client):
    await _register(client, "tag-owner2@example.com")
    tag_id = (await client.post("/tags", json={"name": "owner-only"})).json()["id"]
    await client.post("/auth/logout")

    await _register(client, "tag-intruder2@example.com")
    # 404, not 403 — same "can't confirm the id even exists" pattern as every other
    # ownership-scoped endpoint in this app.
    resp = await client.patch(f"/tags/{tag_id}", json={"name": "hijacked"})
    assert resp.status_code == 404

    await client.post("/auth/logout")
    await client.post("/auth/login", json={"email": "tag-owner2@example.com", "password": "pw"})
    still_there = await client.get("/tags")
    assert [t["name"] for t in still_there.json()] == ["owner-only"]


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
    assert (await client.patch("/tags/1", json={"name": "x"})).status_code == 401
    assert (await client.delete("/tags/1")).status_code == 401
