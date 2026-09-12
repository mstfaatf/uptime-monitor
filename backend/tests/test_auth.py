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
