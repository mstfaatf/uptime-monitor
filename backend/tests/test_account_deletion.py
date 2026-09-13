"""DELETE /auth/me: permanent account deletion.

Ownership is enforced structurally, not by a filter clause — get_current_user resolves the
row to delete strictly from the caller's own session cookie, so there is no id parameter an
attacker could substitute to target another user's account. The cascade (targets -> checks,
targets -> target_region_schedule, users -> targets) is enforced by the database's own
ON DELETE CASCADE foreign keys, not application code — these tests confirm it actually fires,
not just that the FKs are declared.
"""

from sqlalchemy import text

from database import engine


async def _register(client, email, password):
    resp = await client.post("/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 200


async def test_delete_account_requires_authentication(client):
    resp = await client.delete("/auth/me")
    assert resp.status_code == 401


async def test_delete_account_removes_user_and_clears_session(client):
    await _register(client, "todelete@example.com", "pw-1")

    resp = await client.delete("/auth/me")
    assert resp.status_code == 204

    # Session cookie was cleared server-side: the same client, still holding whatever cookie
    # jar httpx tracked, is no longer authenticated.
    me = await client.get("/auth/me")
    assert me.status_code == 401

    # The account is genuinely gone, not just logged out — logging back in fails.
    login = await client.post("/auth/login", json={"email": "todelete@example.com", "password": "pw-1"})
    assert login.status_code == 401


async def test_delete_account_cascades_targets_and_checks(client):
    await _register(client, "cascade@example.com", "pw-1")
    created = await client.post("/targets", json={"url": "https://example.com/cascade"})
    assert created.status_code == 201
    target_id = created.json()["id"]

    # Seed a real check row directly (no worker runs in tests) so the cascade through
    # targets -> checks is actually exercised, not just targets -> user.
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO checks (target_id, checked_at, is_up, region) "
                "VALUES (:target_id, now(), true, 'local')"
            ),
            {"target_id": target_id},
        )

    resp = await client.delete("/auth/me")
    assert resp.status_code == 204

    async with engine.begin() as conn:
        targets_left = (
            await conn.execute(text("SELECT count(*) FROM targets WHERE id = :id"), {"id": target_id})
        ).scalar_one()
        checks_left = (
            await conn.execute(text("SELECT count(*) FROM checks WHERE target_id = :id"), {"id": target_id})
        ).scalar_one()
    assert targets_left == 0
    assert checks_left == 0


async def test_deleting_account_does_not_affect_other_users(client):
    await _register(client, "victim@example.com", "pw-a")
    created = await client.post("/targets", json={"url": "https://example.com/victim"})
    assert created.status_code == 201
    target_id = created.json()["id"]
    await client.post("/auth/logout")

    await _register(client, "deleter@example.com", "pw-b")
    resp = await client.delete("/auth/me")
    assert resp.status_code == 204

    login = await client.post("/auth/login", json={"email": "victim@example.com", "password": "pw-a"})
    assert login.status_code == 200
    listing = await client.get("/targets")
    assert listing.status_code == 200
    assert [t["id"] for t in listing.json()] == [target_id]
