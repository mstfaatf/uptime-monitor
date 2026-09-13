"""Coverage for the forgot-password flow (prompt 4.7): POST /auth/forgot-password and
POST /auth/reset-password.

Hermetic — routers.auth.send_email is mocked in every test, same reasoning as
test_alerting.py/test_mail.py: a genuine RESEND_API_KEY is configured in this project's own
.env, so without mocking this suite would attempt real network calls to Resend.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import text

from database import engine


async def _get_token_hash_for(email: str) -> str | None:
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                SELECT prt.token_hash FROM password_reset_tokens prt
                JOIN users u ON u.id = prt.user_id
                WHERE u.email = :email
                ORDER BY prt.created_at DESC LIMIT 1
                """
            ),
            {"email": email},
        )
        row = result.first()
        return row[0] if row else None


async def _extract_reset_token_from_email_body(mock_send) -> str:
    """The token itself is never stored in plaintext, so tests recover it the same way a real
    user would — read it back out of the email body send_email was called with."""
    body = mock_send.call_args[0][2]
    # "Reset your password: {url}?token=<token>\n"
    line = next(line for line in body.splitlines() if "token=" in line)
    return line.rsplit("token=", 1)[1]


async def test_forgot_password_for_existing_account_sends_email_and_creates_token(client):
    await client.post("/auth/register", json={"email": "forgot1@example.com", "password": "old-pw"})
    await client.post("/auth/logout")

    with patch("routers.auth.send_email", new=AsyncMock(return_value=True)) as mock_send:
        resp = await client.post("/auth/forgot-password", json={"email": "forgot1@example.com"})

    assert resp.status_code == 200
    mock_send.assert_awaited_once()
    assert mock_send.call_args[0][0] == "forgot1@example.com"
    assert await _get_token_hash_for("forgot1@example.com") is not None


async def test_forgot_password_for_unknown_email_returns_identical_generic_response(client):
    """Anti-enumeration: the response must be indistinguishable from the real-account case,
    and no email/token should be generated for an account that doesn't exist."""
    with patch("routers.auth.send_email", new=AsyncMock(return_value=True)) as mock_send:
        real_resp = await client.post("/auth/forgot-password", json={"email": "unknownemail@example.com"})

    assert real_resp.status_code == 200
    assert real_resp.json() == {"detail": "If that email is registered, a password reset link has been sent."}
    mock_send.assert_not_awaited()


async def test_reset_password_with_valid_token_changes_password(client):
    await client.post("/auth/register", json={"email": "reset1@example.com", "password": "old-pw-1"})
    await client.post("/auth/logout")

    with patch("routers.auth.send_email", new=AsyncMock(return_value=True)) as mock_send:
        await client.post("/auth/forgot-password", json={"email": "reset1@example.com"})
    token = await _extract_reset_token_from_email_body(mock_send)

    resp = await client.post("/auth/reset-password", json={"token": token, "new_password": "new-pw-1"})
    assert resp.status_code == 200

    old_login = await client.post("/auth/login", json={"email": "reset1@example.com", "password": "old-pw-1"})
    assert old_login.status_code == 401
    new_login = await client.post("/auth/login", json={"email": "reset1@example.com", "password": "new-pw-1"})
    assert new_login.status_code == 200


async def test_reset_password_token_cannot_be_reused(client):
    await client.post("/auth/register", json={"email": "reset2@example.com", "password": "old-pw-1"})
    await client.post("/auth/logout")

    with patch("routers.auth.send_email", new=AsyncMock(return_value=True)) as mock_send:
        await client.post("/auth/forgot-password", json={"email": "reset2@example.com"})
    token = await _extract_reset_token_from_email_body(mock_send)

    first = await client.post("/auth/reset-password", json={"token": token, "new_password": "new-pw-1"})
    assert first.status_code == 200

    second = await client.post("/auth/reset-password", json={"token": token, "new_password": "new-pw-2"})
    assert second.status_code == 400


async def test_reset_password_rejects_expired_token(client):
    await client.post("/auth/register", json={"email": "reset3@example.com", "password": "old-pw-1"})
    await client.post("/auth/logout")

    with patch("routers.auth.send_email", new=AsyncMock(return_value=True)) as mock_send:
        await client.post("/auth/forgot-password", json={"email": "reset3@example.com"})
    token = await _extract_reset_token_from_email_body(mock_send)

    # Backdate the token's expiry directly — the flow has no way to fast-forward a real hour.
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE password_reset_tokens SET expires_at = :expired WHERE user_id = "
                 "(SELECT id FROM users WHERE email = :email)"),
            {"expired": datetime.now(timezone.utc) - timedelta(minutes=1), "email": "reset3@example.com"},
        )

    resp = await client.post("/auth/reset-password", json={"token": token, "new_password": "new-pw-1"})
    assert resp.status_code == 400


async def test_reset_password_rejects_bogus_token(client):
    resp = await client.post("/auth/reset-password", json={"token": "not-a-real-token", "new_password": "pw"})
    assert resp.status_code == 400


async def test_reset_password_invalidates_other_outstanding_tokens_for_the_same_user(client):
    await client.post("/auth/register", json={"email": "reset4@example.com", "password": "old-pw-1"})
    await client.post("/auth/logout")

    with patch("routers.auth.send_email", new=AsyncMock(return_value=True)) as mock_send:
        await client.post("/auth/forgot-password", json={"email": "reset4@example.com"})
    first_token = await _extract_reset_token_from_email_body(mock_send)

    with patch("routers.auth.send_email", new=AsyncMock(return_value=True)) as mock_send2:
        await client.post("/auth/forgot-password", json={"email": "reset4@example.com"})
    second_token = await _extract_reset_token_from_email_body(mock_send2)

    used = await client.post("/auth/reset-password", json={"token": second_token, "new_password": "new-pw-1"})
    assert used.status_code == 200

    stale = await client.post("/auth/reset-password", json={"token": first_token, "new_password": "new-pw-2"})
    assert stale.status_code == 400


async def test_forgot_password_rate_limited_at_3_per_minute(client):
    with patch("routers.auth.send_email", new=AsyncMock(return_value=True)):
        for _ in range(3):
            resp = await client.post("/auth/forgot-password", json={"email": "ratelimit1@example.com"})
            assert resp.status_code == 200
        fourth = await client.post("/auth/forgot-password", json={"email": "ratelimit1@example.com"})
    assert fourth.status_code == 429


async def test_reset_password_rate_limited_at_5_per_minute(client):
    for _ in range(5):
        resp = await client.post("/auth/reset-password", json={"token": "bogus", "new_password": "pw"})
        assert resp.status_code == 400
    sixth = await client.post("/auth/reset-password", json={"token": "bogus", "new_password": "pw"})
    assert sixth.status_code == 429
