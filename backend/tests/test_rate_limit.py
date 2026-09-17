"""Rate limiting on login, register, and target creation (slowapi, Phase 0 fix #4), plus the
tag/target-edit/API-key write endpoints that had no limit at all before the Phase 6, prompt
6.10 security audit closed that gap (see routers/tags.py, routers/targets.py, and
routers/api_keys.py's module docstrings for exactly which endpoints and why)."""


async def test_login_rate_limited_after_five_per_minute(client):
    for _ in range(5):
        resp = await client.post("/auth/login", json={"email": "nope@example.com", "password": "wrong"})
        assert resp.status_code == 401
    limited = await client.post("/auth/login", json={"email": "nope@example.com", "password": "wrong"})
    assert limited.status_code == 429
    assert "rate limit" in limited.json()["detail"].lower()


async def test_register_rate_limited_after_three_per_minute(client):
    for i in range(3):
        resp = await client.post("/auth/register", json={"email": f"reg{i}@example.com", "password": "pw"})
        assert resp.status_code == 200
    limited = await client.post("/auth/register", json={"email": "reg-overflow@example.com", "password": "pw"})
    assert limited.status_code == 429


async def test_target_creation_rate_limited_after_ten_per_minute(client):
    await client.post("/auth/register", json={"email": "ratelimited-targets@example.com", "password": "pw"})
    for i in range(10):
        resp = await client.post("/targets", json={"url": f"https://example.com/{i}"})
        assert resp.status_code == 201
    limited = await client.post("/targets", json={"url": "https://example.com/overflow"})
    assert limited.status_code == 429


async def test_change_password_rate_limited_after_five_per_minute(client):
    await client.post("/auth/register", json={"email": "ratelimited-pwchange@example.com", "password": "pw"})
    for _ in range(5):
        resp = await client.post(
            "/auth/change-password", json={"current_password": "wrong", "new_password": "new"}
        )
        assert resp.status_code == 401
    limited = await client.post(
        "/auth/change-password", json={"current_password": "wrong", "new_password": "new"}
    )
    assert limited.status_code == 429


async def test_tag_creation_rate_limited_after_ten_per_minute(client):
    await client.post("/auth/register", json={"email": "ratelimited-tagcreate@example.com", "password": "pw"})
    for i in range(10):
        resp = await client.post("/tags", json={"name": f"tag{i}"})
        assert resp.status_code == 201
    limited = await client.post("/tags", json={"name": "overflow"})
    assert limited.status_code == 429


async def test_tag_deletion_rate_limited_after_sixty_per_minute(client):
    await client.post("/auth/register", json={"email": "ratelimited-tagdelete@example.com", "password": "pw"})
    created = await client.post("/tags", json={"name": "delete-me"})
    tag_id = created.json()["id"]
    # Idempotent (see routers/tags.py's delete_tag docstring) — repeatedly deleting the same,
    # already-gone id still counts against the rate limit, so no need for 60 distinct tags.
    for _ in range(60):
        resp = await client.delete(f"/tags/{tag_id}")
        assert resp.status_code in (204, 404)
    limited = await client.delete(f"/tags/{tag_id}")
    assert limited.status_code == 429


async def test_tag_rename_rate_limited_after_sixty_per_minute(client):
    await client.post("/auth/register", json={"email": "ratelimited-tagrename@example.com", "password": "pw"})
    created = await client.post("/tags", json={"name": "rename-me"})
    tag_id = created.json()["id"]
    for _ in range(60):
        resp = await client.patch(f"/tags/{tag_id}", json={"name": "rename-me"})
        assert resp.status_code == 200
    limited = await client.patch(f"/tags/{tag_id}", json={"name": "rename-me"})
    assert limited.status_code == 429


async def test_target_patch_rate_limited_after_sixty_per_minute(client):
    await client.post("/auth/register", json={"email": "ratelimited-targetpatch@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/patch-limit"})
    target_id = created.json()["id"]
    for _ in range(60):
        resp = await client.patch(f"/targets/{target_id}", json={"name": "renamed"})
        assert resp.status_code == 200
    limited = await client.patch(f"/targets/{target_id}", json={"name": "renamed-again"})
    assert limited.status_code == 429


async def test_target_resume_rate_limited_after_sixty_per_minute(client):
    await client.post("/auth/register", json={"email": "ratelimited-targetresume@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/resume-limit"})
    target_id = created.json()["id"]
    # resume_target is idempotent even on a never-paused target (see its docstring).
    for _ in range(60):
        resp = await client.post(f"/targets/{target_id}/resume")
        assert resp.status_code == 200
    limited = await client.post(f"/targets/{target_id}/resume")
    assert limited.status_code == 429


async def test_tag_attach_rate_limited_after_sixty_per_minute(client):
    await client.post("/auth/register", json={"email": "ratelimited-tagattach@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/attach-limit"})
    target_id = created.json()["id"]
    tag = await client.post("/tags", json={"name": "attach-me"})
    tag_id = tag.json()["id"]
    for _ in range(60):
        resp = await client.post(f"/targets/{target_id}/tags", json={"tag_id": tag_id})
        assert resp.status_code == 200
    limited = await client.post(f"/targets/{target_id}/tags", json={"tag_id": tag_id})
    assert limited.status_code == 429


async def test_tag_detach_rate_limited_after_sixty_per_minute(client):
    await client.post("/auth/register", json={"email": "ratelimited-tagdetach@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/detach-limit"})
    target_id = created.json()["id"]
    tag = await client.post("/tags", json={"name": "detach-me"})
    tag_id = tag.json()["id"]
    await client.post(f"/targets/{target_id}/tags", json={"tag_id": tag_id})
    for _ in range(60):
        resp = await client.delete(f"/targets/{target_id}/tags/{tag_id}")
        assert resp.status_code == 204
    limited = await client.delete(f"/targets/{target_id}/tags/{tag_id}")
    assert limited.status_code == 429


async def test_api_key_revocation_rate_limited_after_sixty_per_minute(client):
    await client.post("/auth/register", json={"email": "ratelimited-keyrevoke@example.com", "password": "pw"})
    created = await client.post("/api-keys", json={"name": "revoke-limit-key"})
    api_key_id = created.json()["id"]
    # Idempotent (see routers/api_keys.py's revoke_api_key docstring).
    for _ in range(60):
        resp = await client.delete(f"/api-keys/{api_key_id}")
        assert resp.status_code == 204
    limited = await client.delete(f"/api-keys/{api_key_id}")
    assert limited.status_code == 429
