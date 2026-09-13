"""Rate limiting on login, register, and target creation (slowapi, Phase 0 fix #4)."""


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
