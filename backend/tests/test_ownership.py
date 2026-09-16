"""Ownership enforcement (CLAUDE.md rule 1): the most important tests in this suite.

Every endpoint touching targets/checks must filter by the authenticated user's id — user A
must never be able to read, list, or delete user B's targets, regardless of how they try.
There was zero regression coverage for this before Phase 0 prompt 0.6.
"""


async def _register(client, email, password):
    resp = await client.post("/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 200


async def test_user_cannot_list_or_see_status_of_another_users_targets(client):
    await _register(client, "usera@example.com", "pw-a-1")
    created = await client.post("/targets", json={"url": "https://example.com/a"})
    assert created.status_code == 201
    await client.post("/auth/logout")

    await _register(client, "userb@example.com", "pw-b-1")

    listing = await client.get("/targets")
    assert listing.status_code == 200
    assert listing.json() == []

    status_listing = await client.get("/targets/status")
    assert status_listing.status_code == 200
    assert status_listing.json() == []


async def test_user_cannot_delete_another_users_target(client):
    await _register(client, "usera2@example.com", "pw-a-1")
    created = await client.post("/targets", json={"url": "https://example.com/a2"})
    assert created.status_code == 201
    target_id = created.json()["id"]
    await client.post("/auth/logout")

    await _register(client, "userb2@example.com", "pw-b-1")
    delete_resp = await client.delete(f"/targets/{target_id}")
    # 404, not 403 — deliberately indistinguishable from "this target doesn't exist" so a
    # cross-user probe can't even confirm the id is valid.
    assert delete_resp.status_code == 404
    await client.post("/auth/logout")


async def test_user_cannot_view_another_users_target_detail_or_checks(client):
    await _register(client, "usera4@example.com", "pw-a-1")
    created = await client.post("/targets", json={"url": "https://example.com/a4"})
    assert created.status_code == 201
    target_id = created.json()["id"]
    await client.post("/auth/logout")

    await _register(client, "userb4@example.com", "pw-b-1")
    # Same 404-not-403 pattern as delete: a cross-user probe can't even confirm the id exists.
    assert (await client.get(f"/targets/{target_id}")).status_code == 404
    assert (await client.get(f"/targets/{target_id}/checks?region=local")).status_code == 404
    patch_resp = await client.patch(f"/targets/{target_id}", json={"name": "hijacked"})
    assert patch_resp.status_code == 404
    assert (await client.post(f"/targets/{target_id}/pause")).status_code == 404
    assert (await client.post(f"/targets/{target_id}/resume")).status_code == 404
    await client.post("/auth/logout")

    # Confirm it's untouched for the real owner — including that the other user's failed PATCH
    # attempt didn't change anything.
    login = await client.post("/auth/login", json={"email": "usera4@example.com", "password": "pw-a-1"})
    assert login.status_code == 200
    listing = await client.get("/targets")
    assert listing.status_code == 200
    ids = [t["id"] for t in listing.json()]
    assert ids == [target_id]
    assert listing.json()[0]["name"] is None


async def test_anonymous_user_cannot_access_any_target_endpoint(client):
    await _register(client, "usera3@example.com", "pw-a-1")
    created = await client.post("/targets", json={"url": "https://example.com/a3"})
    assert created.status_code == 201
    target_id = created.json()["id"]
    await client.post("/auth/logout")

    assert (await client.get("/targets")).status_code == 401
    assert (await client.get("/targets/status")).status_code == 401
    assert (await client.post("/targets", json={"url": "https://example.com/x"})).status_code == 401
    assert (await client.delete(f"/targets/{target_id}")).status_code == 401
    assert (await client.get(f"/targets/{target_id}")).status_code == 401
    assert (await client.get(f"/targets/{target_id}/checks?region=local")).status_code == 401
    assert (await client.patch(f"/targets/{target_id}", json={"name": "x"})).status_code == 401
    assert (await client.post(f"/targets/{target_id}/pause")).status_code == 401
    assert (await client.post(f"/targets/{target_id}/resume")).status_code == 401
