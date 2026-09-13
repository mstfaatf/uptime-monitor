"""Auth flow: register, login, logout, /auth/me, duplicate email, wrong password."""


async def test_register_login_me_logout_roundtrip(client):
    register = await client.post(
        "/auth/register", json={"email": "alice@example.com", "password": "correct-horse-1"}
    )
    assert register.status_code == 200
    body = register.json()
    assert body["email"] == "alice@example.com"
    assert "id" in body

    me = await client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"

    logout = await client.post("/auth/logout")
    assert logout.status_code == 200

    me_after_logout = await client.get("/auth/me")
    assert me_after_logout.status_code == 401

    login = await client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "correct-horse-1"}
    )
    assert login.status_code == 200
    assert login.json()["email"] == "alice@example.com"

    me_after_login = await client.get("/auth/me")
    assert me_after_login.status_code == 200


async def test_duplicate_email_registration_rejected(client):
    await client.post("/auth/register", json={"email": "bob@example.com", "password": "pw1"})
    dup = await client.post("/auth/register", json={"email": "bob@example.com", "password": "pw2"})
    assert dup.status_code == 400


async def test_login_wrong_password_rejected(client):
    await client.post("/auth/register", json={"email": "carol@example.com", "password": "correct-pw"})
    await client.post("/auth/logout")
    bad = await client.post("/auth/login", json={"email": "carol@example.com", "password": "wrong-pw"})
    assert bad.status_code == 401


async def test_login_unknown_email_rejected(client):
    resp = await client.post("/auth/login", json={"email": "nobody@example.com", "password": "whatever"})
    assert resp.status_code == 401


async def test_me_without_session_rejected(client):
    resp = await client.get("/auth/me")
    assert resp.status_code == 401


async def test_new_user_defaults_to_alerts_enabled(client):
    register = await client.post("/auth/register", json={"email": "dana@example.com", "password": "pw"})
    body = register.json()
    assert body["alert_on_downtime"] is True
    assert body["alert_on_cert_expiry"] is True


async def test_change_password_roundtrip(client):
    await client.post("/auth/register", json={"email": "erin@example.com", "password": "old-pw-1"})

    change = await client.post(
        "/auth/change-password", json={"current_password": "old-pw-1", "new_password": "new-pw-1"}
    )
    assert change.status_code == 200

    await client.post("/auth/logout")

    old_login = await client.post("/auth/login", json={"email": "erin@example.com", "password": "old-pw-1"})
    assert old_login.status_code == 401

    new_login = await client.post("/auth/login", json={"email": "erin@example.com", "password": "new-pw-1"})
    assert new_login.status_code == 200


async def test_change_password_rejects_wrong_current_password(client):
    await client.post("/auth/register", json={"email": "frank@example.com", "password": "actual-pw"})

    resp = await client.post(
        "/auth/change-password", json={"current_password": "wrong-pw", "new_password": "new-pw"}
    )
    assert resp.status_code == 401

    # Confirm the password was NOT changed.
    await client.post("/auth/logout")
    login = await client.post("/auth/login", json={"email": "frank@example.com", "password": "actual-pw"})
    assert login.status_code == 200


async def test_change_password_requires_authentication(client):
    resp = await client.post(
        "/auth/change-password", json={"current_password": "x", "new_password": "y"}
    )
    assert resp.status_code == 401


async def test_update_preferences_partial_update(client):
    await client.post("/auth/register", json={"email": "grace@example.com", "password": "pw"})

    resp = await client.patch("/auth/preferences", json={"alert_on_downtime": False})
    assert resp.status_code == 200
    body = resp.json()
    assert body["alert_on_downtime"] is False
    assert body["alert_on_cert_expiry"] is True  # untouched by the partial update

    resp2 = await client.patch("/auth/preferences", json={"alert_on_cert_expiry": False})
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["alert_on_downtime"] is False  # earlier change persisted
    assert body2["alert_on_cert_expiry"] is False


async def test_update_preferences_requires_authentication(client):
    resp = await client.patch("/auth/preferences", json={"alert_on_downtime": False})
    assert resp.status_code == 401
