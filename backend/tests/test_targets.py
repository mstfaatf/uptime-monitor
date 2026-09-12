"""URL normalization and duplicate-target rejection (409)."""


async def test_duplicate_normalized_url_rejected(client):
    await client.post("/auth/register", json={"email": "dupe@example.com", "password": "pw"})

    first = await client.post("/targets", json={"url": "https://example.com/path/"})
    assert first.status_code == 201

    # Trailing-slash-only difference — normalize_url() should treat these as the same target.
    dup = await client.post("/targets", json={"url": "https://example.com/path"})
    assert dup.status_code == 409


async def test_different_users_can_monitor_the_same_url(client):
    await client.post("/auth/register", json={"email": "same-url-a@example.com", "password": "pw"})
    first = await client.post("/targets", json={"url": "https://example.com/shared"})
    assert first.status_code == 201
    await client.post("/auth/logout")

    await client.post("/auth/register", json={"email": "same-url-b@example.com", "password": "pw"})
    second = await client.post("/targets", json={"url": "https://example.com/shared"})
    assert second.status_code == 201  # uniqueness is scoped per-user, not global


async def test_delete_target_removes_it(client):
    await client.post("/auth/register", json={"email": "deleter@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/to-delete"})
    assert created.status_code == 201
    target_id = created.json()["id"]

    deleted = await client.delete(f"/targets/{target_id}")
    assert deleted.status_code == 204

    listing = await client.get("/targets")
    assert listing.json() == []


async def test_invalid_scheme_rejected(client):
    await client.post("/auth/register", json={"email": "badscheme@example.com", "password": "pw"})
    resp = await client.post("/targets", json={"url": "ftp://example.com/file"})
    assert resp.status_code in (400, 422)
