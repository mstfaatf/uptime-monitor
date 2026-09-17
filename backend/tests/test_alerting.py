"""Coverage for backend/realtime.py's alert-evaluation logic (prompt 4.6): downtime and
cert-expiry alerting, wired into _handle_notification. Extended in Phase 6 prompt 6.6 with
webhook fan-out coverage — see the "webhook fan-out" section below, which is the core proof
that the eligibility/fan-out restructuring actually decoupled webhook delivery from the
user's *email* preference toggle (building webhooks against the pre-6.6 shape would have
wrongly coupled the two).

Hermetic by construction, not by luck: mail.send_email and webhooks.send_webhook (both
imported into realtime's own namespace) are mocked in every test here via
`patch("realtime.send_email", ...)` / `patch("realtime.send_webhook", ...)`. This matters
concretely in this environment — a genuine RESEND_API_KEY is configured in this project's own
.env (needed for manual delivery verification), so without mocking, this suite would attempt
real network calls to Resend and could actually send real email as a side effect of running
pytest. That must never happen; the same reasoning applies to webhook delivery, which would
otherwise make a real outbound HTTP request.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import text

import realtime
from database import engine


async def _insert_check(target_id: int, region: str = "local", **overrides) -> None:
    values = {
        "target_id": target_id,
        "checked_at": datetime.now(timezone.utc),
        "status_code": 200,
        "latency_ms": 100,
        "is_up": True,
        "error": None,
        "region": region,
        "tls_cert_expires_at": None,
        "tls_cert_issuer": None,
    }
    values.update(overrides)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO checks (
                    target_id, checked_at, status_code, latency_ms, is_up, error, region,
                    tls_cert_expires_at, tls_cert_issuer
                ) VALUES (
                    :target_id, :checked_at, :status_code, :latency_ms, :is_up, :error, :region,
                    :tls_cert_expires_at, :tls_cert_issuer
                )
                """
            ),
            values,
        )


async def _insert_alert_history(
    target_id: int,
    region: str,
    alert_type: str,
    last_state: str,
    last_sent_at: datetime,
    last_cert_expires_at: datetime | None = None,
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO alert_history (target_id, region, alert_type, last_state, last_sent_at, last_cert_expires_at)
                VALUES (:target_id, :region, :alert_type, :last_state, :last_sent_at, :last_cert_expires_at)
                """
            ),
            {
                "target_id": target_id,
                "region": region,
                "alert_type": alert_type,
                "last_state": last_state,
                "last_sent_at": last_sent_at,
                "last_cert_expires_at": last_cert_expires_at,
            },
        )


async def _get_alert_history(target_id: int, region: str, alert_type: str):
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "SELECT last_state, last_sent_at, last_cert_expires_at FROM alert_history "
                "WHERE target_id = :target_id AND region = :region AND alert_type = :alert_type"
            ),
            {"target_id": target_id, "region": region, "alert_type": alert_type},
        )
        return result.mappings().first()


async def _insert_webhook(
    user_id: int,
    url: str = "http://8.8.8.8/hook",
    secret: str = "test-secret",
    alert_on_downtime: bool = True,
    alert_on_cert_expiry: bool = True,
    enabled: bool = True,
) -> int:
    """Raw SQL, not POST /webhooks — needed to construct states the API can't (a disabled
    webhook; WebhookCreate has no `enabled` field, per routers/webhooks.py's own docstring
    reasoning). Uses a real IP literal for the default URL, matching this codebase's
    established SSRF-test convention — is_url_blocked() isn't mocked in these tests and does a
    real DNS lookup, so a made-up hostname would fail resolution rather than exercising the
    fan-out logic under test."""
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                INSERT INTO webhooks (user_id, url, secret, alert_on_downtime, alert_on_cert_expiry, enabled)
                VALUES (:user_id, :url, :secret, :alert_on_downtime, :alert_on_cert_expiry, :enabled)
                RETURNING id
                """
            ),
            {
                "user_id": user_id,
                "url": url,
                "secret": secret,
                "alert_on_downtime": alert_on_downtime,
                "alert_on_cert_expiry": alert_on_cert_expiry,
                "enabled": enabled,
            },
        )
        return result.scalar_one()


async def test_downtime_alert_fires_on_first_down_transition(client):
    await client.post("/auth/register", json={"email": "down1@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/down1"})
    target_id = created.json()["id"]
    await _insert_check(target_id, is_up=False, status_code=None, latency_ms=None, error="Connection timed out")

    with patch("realtime.send_email", new=AsyncMock(return_value=True)) as mock_send:
        await realtime._handle_notification(f"{target_id}:local")

    mock_send.assert_awaited_once()
    assert mock_send.call_args[0][0] == "down1@example.com"
    row = await _get_alert_history(target_id, "local", "downtime")
    assert row["last_state"] == "down"


async def test_downtime_alert_suppressed_while_still_down(client):
    await client.post("/auth/register", json={"email": "down2@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/down2"})
    target_id = created.json()["id"]
    await _insert_alert_history(target_id, "local", "downtime", "down", datetime.now(timezone.utc) - timedelta(hours=1))
    await _insert_check(target_id, is_up=False, status_code=None, latency_ms=None, error="Connection timed out")

    with patch("realtime.send_email", new=AsyncMock(return_value=True)) as mock_send:
        await realtime._handle_notification(f"{target_id}:local")

    mock_send.assert_not_awaited()


async def test_downtime_alert_suppressed_within_cooldown_even_after_recovery(client):
    """A target that recovered (last_state='up') very recently, then failed again, must not
    re-trigger before the cooldown from the last email of any kind — the flapping dampener."""
    await client.post("/auth/register", json={"email": "down3@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/down3"})
    target_id = created.json()["id"]
    await _insert_alert_history(target_id, "local", "downtime", "up", datetime.now(timezone.utc) - timedelta(seconds=30))
    await _insert_check(target_id, is_up=False, status_code=None, latency_ms=None, error="Connection timed out")

    with patch("realtime.send_email", new=AsyncMock(return_value=True)) as mock_send:
        await realtime._handle_notification(f"{target_id}:local")

    mock_send.assert_not_awaited()


async def test_downtime_alert_fires_again_after_cooldown_elapses(client):
    await client.post("/auth/register", json={"email": "down4@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/down4"})
    target_id = created.json()["id"]
    await _insert_alert_history(target_id, "local", "downtime", "up", datetime.now(timezone.utc) - timedelta(seconds=1000))
    await _insert_check(target_id, is_up=False, status_code=None, latency_ms=None, error="Connection timed out")

    with patch("realtime.send_email", new=AsyncMock(return_value=True)) as mock_send:
        await realtime._handle_notification(f"{target_id}:local")

    mock_send.assert_awaited_once()
    row = await _get_alert_history(target_id, "local", "downtime")
    assert row["last_state"] == "down"


async def test_recovery_email_sent_when_target_comes_back_up(client):
    await client.post("/auth/register", json={"email": "recover1@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/recover1"})
    target_id = created.json()["id"]
    await _insert_alert_history(target_id, "local", "downtime", "down", datetime.now(timezone.utc) - timedelta(minutes=5))
    await _insert_check(target_id, is_up=True, status_code=200, latency_ms=150)

    with patch("realtime.send_email", new=AsyncMock(return_value=True)) as mock_send:
        await realtime._handle_notification(f"{target_id}:local")

    mock_send.assert_awaited_once()
    assert "back up" in mock_send.call_args[0][1]
    row = await _get_alert_history(target_id, "local", "downtime")
    assert row["last_state"] == "up"


async def test_no_recovery_email_when_never_alerted(client):
    await client.post("/auth/register", json={"email": "nevereverdown@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/never-down"})
    target_id = created.json()["id"]
    await _insert_check(target_id, is_up=True, status_code=200, latency_ms=150)

    with patch("realtime.send_email", new=AsyncMock(return_value=True)) as mock_send:
        await realtime._handle_notification(f"{target_id}:local")

    mock_send.assert_not_awaited()


async def test_downtime_alert_gated_on_user_preference(client):
    await client.post("/auth/register", json={"email": "nodownalerts@example.com", "password": "pw"})
    await client.patch("/auth/preferences", json={"alert_on_downtime": False})
    created = await client.post("/targets", json={"url": "https://example.com/no-down-alerts"})
    target_id = created.json()["id"]
    await _insert_check(target_id, is_up=False, status_code=None, latency_ms=None, error="Connection timed out")

    with patch("realtime.send_email", new=AsyncMock(return_value=True)) as mock_send:
        await realtime._handle_notification(f"{target_id}:local")

    mock_send.assert_not_awaited()
    assert await _get_alert_history(target_id, "local", "downtime") is None  # gated before any bookkeeping


async def test_cert_expiry_alert_fires_when_first_crossing_threshold(client):
    await client.post("/auth/register", json={"email": "cert1@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/cert1"})
    target_id = created.json()["id"]
    expires_at = datetime.now(timezone.utc) + timedelta(days=9)
    await _insert_check(target_id, tls_cert_expires_at=expires_at, tls_cert_issuer="CN=R3")

    with patch("realtime.send_email", new=AsyncMock(return_value=True)) as mock_send:
        await realtime._handle_notification(f"{target_id}:local")

    mock_send.assert_awaited_once()
    row = await _get_alert_history(target_id, "local", "cert_expiry")
    assert row["last_state"] == "expiring"


async def test_cert_expiry_alert_not_fired_above_threshold(client):
    await client.post("/auth/register", json={"email": "cert2@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/cert2"})
    target_id = created.json()["id"]
    expires_at = datetime.now(timezone.utc) + timedelta(days=60)
    await _insert_check(target_id, tls_cert_expires_at=expires_at, tls_cert_issuer="CN=R3")

    with patch("realtime.send_email", new=AsyncMock(return_value=True)) as mock_send:
        await realtime._handle_notification(f"{target_id}:local")

    mock_send.assert_not_awaited()


async def test_cert_expiry_alert_suppressed_within_reminder_cooldown(client):
    await client.post("/auth/register", json={"email": "cert3@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/cert3"})
    target_id = created.json()["id"]
    expires_at = datetime.now(timezone.utc) + timedelta(days=9)
    await _insert_alert_history(
        target_id, "local", "cert_expiry", "expiring", datetime.now(timezone.utc) - timedelta(hours=1), expires_at
    )
    await _insert_check(target_id, tls_cert_expires_at=expires_at, tls_cert_issuer="CN=R3")

    with patch("realtime.send_email", new=AsyncMock(return_value=True)) as mock_send:
        await realtime._handle_notification(f"{target_id}:local")

    mock_send.assert_not_awaited()


async def test_cert_expiry_alert_fires_again_after_reminder_cooldown_elapses(client):
    await client.post("/auth/register", json={"email": "cert4@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/cert4"})
    target_id = created.json()["id"]
    expires_at = datetime.now(timezone.utc) + timedelta(days=9)
    await _insert_alert_history(
        target_id, "local", "cert_expiry", "expiring", datetime.now(timezone.utc) - timedelta(days=4), expires_at
    )
    await _insert_check(target_id, tls_cert_expires_at=expires_at, tls_cert_issuer="CN=R3")

    with patch("realtime.send_email", new=AsyncMock(return_value=True)) as mock_send:
        await realtime._handle_notification(f"{target_id}:local")

    mock_send.assert_awaited_once()


async def test_cert_expiry_alert_fires_immediately_after_renewal_even_within_cooldown(client):
    """A changed tls_cert_expires_at (a renewal) resets eligibility right away, regardless of
    the reminder cooldown — it's a genuinely new expiry window worth its own first alert."""
    await client.post("/auth/register", json={"email": "cert5@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/cert5"})
    target_id = created.json()["id"]
    old_expiry = datetime.now(timezone.utc) + timedelta(days=9)
    new_expiry = datetime.now(timezone.utc) + timedelta(days=10)  # renewed; still <=14 for this test
    await _insert_alert_history(
        target_id, "local", "cert_expiry", "expiring", datetime.now(timezone.utc) - timedelta(hours=1), old_expiry
    )
    await _insert_check(target_id, tls_cert_expires_at=new_expiry, tls_cert_issuer="CN=R3")

    with patch("realtime.send_email", new=AsyncMock(return_value=True)) as mock_send:
        await realtime._handle_notification(f"{target_id}:local")

    mock_send.assert_awaited_once()


async def test_cert_expiry_alert_gated_on_user_preference(client):
    await client.post("/auth/register", json={"email": "nocertalerts@example.com", "password": "pw"})
    await client.patch("/auth/preferences", json={"alert_on_cert_expiry": False})
    created = await client.post("/targets", json={"url": "https://example.com/no-cert-alerts"})
    target_id = created.json()["id"]
    expires_at = datetime.now(timezone.utc) + timedelta(days=9)
    await _insert_check(target_id, tls_cert_expires_at=expires_at, tls_cert_issuer="CN=R3")

    with patch("realtime.send_email", new=AsyncMock(return_value=True)) as mock_send:
        await realtime._handle_notification(f"{target_id}:local")

    mock_send.assert_not_awaited()


async def test_alerting_is_region_scoped(client):
    """A down alert for one region must never fire for, or write bookkeeping about, another
    region of the same target — each region gets its own alert_history row and its own
    independent evaluation, matching the Phase 2 never-collapse-regions rule."""
    await client.post("/auth/register", json={"email": "regions@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/regions"})
    target_id = created.json()["id"]
    await _insert_check(target_id, region="local", is_up=False, status_code=None, latency_ms=None, error="timeout")
    await _insert_check(target_id, region="eu-west", is_up=True, status_code=200, latency_ms=100)

    with patch("realtime.send_email", new=AsyncMock(return_value=True)) as mock_send:
        await realtime._handle_notification(f"{target_id}:local")

    mock_send.assert_awaited_once()  # only local's down alert; nothing about eu-west
    local_row = await _get_alert_history(target_id, "local", "downtime")
    eu_row = await _get_alert_history(target_id, "eu-west", "downtime")
    assert local_row["last_state"] == "down"
    assert eu_row is None  # eu-west was never evaluated by this notification at all


async def test_failed_downtime_send_is_not_recorded_as_alerted(client):
    """Found live in prompt 4.6.1: a real Resend failure (send_email returning False, not
    raising) was being silently recorded as 'already alerted', permanently suppressing the
    real alert with no retry even after the underlying problem was fixed. A failed send must
    leave no alert_history row behind, so the very next check retries it."""
    await client.post("/auth/register", json={"email": "sendfails1@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/send-fails-1"})
    target_id = created.json()["id"]
    await _insert_check(target_id, is_up=False, status_code=None, latency_ms=None, error="Connection timed out")

    with patch("realtime.send_email", new=AsyncMock(return_value=False)) as mock_send:
        await realtime._handle_notification(f"{target_id}:local")

    mock_send.assert_awaited_once()
    assert await _get_alert_history(target_id, "local", "downtime") is None


async def test_failed_recovery_send_is_not_recorded_as_alerted(client):
    await client.post("/auth/register", json={"email": "sendfails2@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/send-fails-2"})
    target_id = created.json()["id"]
    sent_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    await _insert_alert_history(target_id, "local", "downtime", "down", sent_at)
    await _insert_check(target_id, is_up=True, status_code=200, latency_ms=150)

    with patch("realtime.send_email", new=AsyncMock(return_value=False)) as mock_send:
        await realtime._handle_notification(f"{target_id}:local")

    mock_send.assert_awaited_once()
    row = await _get_alert_history(target_id, "local", "downtime")
    assert row["last_state"] == "down"  # unchanged — the failed recovery send didn't fake success
    assert row["last_sent_at"].replace(tzinfo=timezone.utc) == sent_at


async def test_failed_cert_expiry_send_is_not_recorded_as_alerted(client):
    await client.post("/auth/register", json={"email": "sendfails3@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/send-fails-3"})
    target_id = created.json()["id"]
    expires_at = datetime.now(timezone.utc) + timedelta(days=9)
    await _insert_check(target_id, tls_cert_expires_at=expires_at, tls_cert_issuer="CN=R3")

    with patch("realtime.send_email", new=AsyncMock(return_value=False)) as mock_send:
        await realtime._handle_notification(f"{target_id}:local")

    mock_send.assert_awaited_once()
    assert await _get_alert_history(target_id, "local", "cert_expiry") is None


async def test_sse_push_still_delivers_when_alert_evaluation_raises(client):
    """The core requirement of this prompt: a Resend/alert-evaluation failure must never block
    or corrupt the SSE push, which is _handle_notification's primary purpose. Forces a failure
    deep inside send_email (mocked to raise) and confirms the subscribed queue still receives
    the full, correct check_update payload."""
    register = await client.post("/auth/register", json={"email": "ssefail@example.com", "password": "pw"})
    user_id = register.json()["id"]
    created = await client.post("/targets", json={"url": "https://example.com/sse-fail"})
    target_id = created.json()["id"]
    await _insert_check(target_id, is_up=False, status_code=None, latency_ms=None, error="timeout")

    queue = realtime.subscribe(user_id)
    try:
        with patch("realtime.send_email", new=AsyncMock(side_effect=RuntimeError("forced failure"))):
            await realtime._handle_notification(f"{target_id}:local")

        message = queue.get_nowait()
        assert message["type"] == "check_update"
        assert message["target"]["id"] == target_id
        assert message["target"]["latest_checks"]["local"]["is_up"] is False
    finally:
        realtime.unsubscribe(user_id, queue)

    # The failed evaluation must not have left a half-written alert_history row behind either.
    assert await _get_alert_history(target_id, "local", "downtime") is None


# --- Webhook fan-out (Phase 6, prompt 6.6) ---
#
# The core thing every test in this section proves, one way or another: webhook delivery is
# independent of the user's *email* alert preference — email and webhooks are two separate
# channels fanned out to after a single, channel-agnostic eligibility check, not two names for
# the same code path. Building webhooks against the pre-6.6 shape (email-send and eligibility
# fused together) would have made this impossible to prove, because there would have been no
# way to enable a webhook without also enabling email.


async def test_webhook_fires_on_downtime_independently_of_email_toggle(client):
    register = await client.post("/auth/register", json={"email": "webhookdown1@example.com", "password": "pw"})
    user_id = register.json()["id"]
    await client.patch("/auth/preferences", json={"alert_on_downtime": False})  # email off
    created = await client.post("/targets", json={"url": "https://example.com/webhook-down1"})
    target_id = created.json()["id"]
    await _insert_webhook(user_id)
    await _insert_check(target_id, is_up=False, status_code=None, latency_ms=None, error="Connection timed out")

    with (
        patch("realtime.send_email", new=AsyncMock(return_value=True)) as mock_email,
        patch("realtime.send_webhook", new=AsyncMock(return_value=True)) as mock_webhook,
    ):
        await realtime._handle_notification(f"{target_id}:local")

    mock_email.assert_not_awaited()  # the whole point: email stayed off
    mock_webhook.assert_awaited_once()
    payload = mock_webhook.call_args[0][2]
    assert payload["event"] == "target.down"
    assert payload["target"]["id"] == target_id
    row = await _get_alert_history(target_id, "local", "downtime")
    assert row["last_state"] == "down"


async def test_webhook_fires_on_recovery_independently_of_email_toggle(client):
    register = await client.post("/auth/register", json={"email": "webhookrecover1@example.com", "password": "pw"})
    user_id = register.json()["id"]
    await client.patch("/auth/preferences", json={"alert_on_downtime": False})
    created = await client.post("/targets", json={"url": "https://example.com/webhook-recover1"})
    target_id = created.json()["id"]
    await _insert_webhook(user_id)
    await _insert_alert_history(target_id, "local", "downtime", "down", datetime.now(timezone.utc) - timedelta(minutes=5))
    await _insert_check(target_id, is_up=True, status_code=200, latency_ms=150)

    with (
        patch("realtime.send_email", new=AsyncMock(return_value=True)) as mock_email,
        patch("realtime.send_webhook", new=AsyncMock(return_value=True)) as mock_webhook,
    ):
        await realtime._handle_notification(f"{target_id}:local")

    mock_email.assert_not_awaited()
    mock_webhook.assert_awaited_once()
    payload = mock_webhook.call_args[0][2]
    assert payload["event"] == "target.up"
    row = await _get_alert_history(target_id, "local", "downtime")
    assert row["last_state"] == "up"


async def test_webhook_fires_on_cert_expiry_independently_of_email_toggle(client):
    register = await client.post("/auth/register", json={"email": "webhookcert1@example.com", "password": "pw"})
    user_id = register.json()["id"]
    await client.patch("/auth/preferences", json={"alert_on_cert_expiry": False})
    created = await client.post("/targets", json={"url": "https://example.com/webhook-cert1"})
    target_id = created.json()["id"]
    await _insert_webhook(user_id)
    expires_at = datetime.now(timezone.utc) + timedelta(days=9)
    await _insert_check(target_id, tls_cert_expires_at=expires_at, tls_cert_issuer="CN=R3")

    with (
        patch("realtime.send_email", new=AsyncMock(return_value=True)) as mock_email,
        patch("realtime.send_webhook", new=AsyncMock(return_value=True)) as mock_webhook,
    ):
        await realtime._handle_notification(f"{target_id}:local")

    mock_email.assert_not_awaited()
    mock_webhook.assert_awaited_once()
    payload = mock_webhook.call_args[0][2]
    assert payload["event"] == "target.cert_expiring"
    row = await _get_alert_history(target_id, "local", "cert_expiry")
    assert row["last_state"] == "expiring"


async def test_webhook_respects_cooldown_same_as_email(client):
    """The channel-agnostic eligibility check (cooldown/alert_history) applies before fan-out
    — a webhook doesn't get its own independent cooldown clock, it shares the one eligibility
    decision with email."""
    register = await client.post("/auth/register", json={"email": "webhookcooldown1@example.com", "password": "pw"})
    user_id = register.json()["id"]
    created = await client.post("/targets", json={"url": "https://example.com/webhook-cooldown1"})
    target_id = created.json()["id"]
    await _insert_webhook(user_id)
    await _insert_alert_history(target_id, "local", "downtime", "up", datetime.now(timezone.utc) - timedelta(seconds=30))
    await _insert_check(target_id, is_up=False, status_code=None, latency_ms=None, error="Connection timed out")

    with (
        patch("realtime.send_email", new=AsyncMock(return_value=True)) as mock_email,
        patch("realtime.send_webhook", new=AsyncMock(return_value=True)) as mock_webhook,
    ):
        await realtime._handle_notification(f"{target_id}:local")

    mock_email.assert_not_awaited()
    mock_webhook.assert_not_awaited()  # suppressed by the same cooldown, not just email


async def test_disabled_webhook_never_fires(client):
    register = await client.post("/auth/register", json={"email": "webhookdisabled1@example.com", "password": "pw"})
    user_id = register.json()["id"]
    created = await client.post("/targets", json={"url": "https://example.com/webhook-disabled1"})
    target_id = created.json()["id"]
    await _insert_webhook(user_id, enabled=False)
    await _insert_check(target_id, is_up=False, status_code=None, latency_ms=None, error="Connection timed out")

    with (
        patch("realtime.send_email", new=AsyncMock(return_value=True)),
        patch("realtime.send_webhook", new=AsyncMock(return_value=True)) as mock_webhook,
    ):
        await realtime._handle_notification(f"{target_id}:local")

    mock_webhook.assert_not_awaited()


async def test_webhook_downtime_toggle_off_does_not_suppress_its_own_cert_expiry_alert(client):
    """Per-webhook, per-alert-type independence: a webhook with alert_on_downtime=False must
    still fire for cert-expiry — the two toggles are genuinely independent, not one global
    on/off."""
    register = await client.post("/auth/register", json={"email": "webhooktypes1@example.com", "password": "pw"})
    user_id = register.json()["id"]
    created = await client.post("/targets", json={"url": "https://example.com/webhook-types1"})
    target_id = created.json()["id"]
    await _insert_webhook(user_id, alert_on_downtime=False, alert_on_cert_expiry=True)
    expires_at = datetime.now(timezone.utc) + timedelta(days=9)
    await _insert_check(target_id, tls_cert_expires_at=expires_at, tls_cert_issuer="CN=R3")

    with patch("realtime.send_webhook", new=AsyncMock(return_value=True)) as mock_webhook:
        await realtime._handle_notification(f"{target_id}:local")

    mock_webhook.assert_awaited_once()
    assert mock_webhook.call_args[0][2]["event"] == "target.cert_expiring"


async def test_webhook_downtime_toggle_off_suppresses_downtime_alert(client):
    register = await client.post("/auth/register", json={"email": "webhooktypes2@example.com", "password": "pw"})
    user_id = register.json()["id"]
    created = await client.post("/targets", json={"url": "https://example.com/webhook-types2"})
    target_id = created.json()["id"]
    await _insert_webhook(user_id, alert_on_downtime=False)
    await _insert_check(target_id, is_up=False, status_code=None, latency_ms=None, error="timeout")

    with patch("realtime.send_webhook", new=AsyncMock(return_value=True)) as mock_webhook:
        await realtime._handle_notification(f"{target_id}:local")

    mock_webhook.assert_not_awaited()


async def test_alert_history_recorded_once_when_both_email_and_webhook_fire(client):
    register = await client.post("/auth/register", json={"email": "webhookboth1@example.com", "password": "pw"})
    user_id = register.json()["id"]
    created = await client.post("/targets", json={"url": "https://example.com/webhook-both1"})
    target_id = created.json()["id"]
    await _insert_webhook(user_id)
    await _insert_check(target_id, is_up=False, status_code=None, latency_ms=None, error="timeout")

    with (
        patch("realtime.send_email", new=AsyncMock(return_value=True)) as mock_email,
        patch("realtime.send_webhook", new=AsyncMock(return_value=True)) as mock_webhook,
    ):
        await realtime._handle_notification(f"{target_id}:local")

    mock_email.assert_awaited_once()
    mock_webhook.assert_awaited_once()
    async with engine.begin() as conn:
        result = await conn.execute(
            text("SELECT count(*) FROM alert_history WHERE target_id = :target_id"), {"target_id": target_id}
        )
        assert result.scalar_one() == 1  # exactly one bookkeeping row, not one per channel


async def test_alert_history_recorded_when_only_the_webhook_channel_succeeds(client):
    """"At least one channel delivered" is the bar for bookkeeping — a failed email alongside
    a successful webhook still counts as alerted, per the documented multi-channel
    generalization of the original single-channel rule."""
    register = await client.post("/auth/register", json={"email": "webhookonly1@example.com", "password": "pw"})
    user_id = register.json()["id"]
    created = await client.post("/targets", json={"url": "https://example.com/webhook-only1"})
    target_id = created.json()["id"]
    await _insert_webhook(user_id)
    await _insert_check(target_id, is_up=False, status_code=None, latency_ms=None, error="timeout")

    with (
        patch("realtime.send_email", new=AsyncMock(return_value=False)),
        patch("realtime.send_webhook", new=AsyncMock(return_value=True)),
    ):
        await realtime._handle_notification(f"{target_id}:local")

    row = await _get_alert_history(target_id, "local", "downtime")
    assert row is not None
    assert row["last_state"] == "down"


async def test_no_bookkeeping_when_every_channel_fails(client):
    register = await client.post("/auth/register", json={"email": "webhookallfail1@example.com", "password": "pw"})
    user_id = register.json()["id"]
    created = await client.post("/targets", json={"url": "https://example.com/webhook-allfail1"})
    target_id = created.json()["id"]
    await _insert_webhook(user_id)
    await _insert_check(target_id, is_up=False, status_code=None, latency_ms=None, error="timeout")

    with (
        patch("realtime.send_email", new=AsyncMock(return_value=False)),
        patch("realtime.send_webhook", new=AsyncMock(return_value=False)),
    ):
        await realtime._handle_notification(f"{target_id}:local")

    assert await _get_alert_history(target_id, "local", "downtime") is None


async def test_multiple_webhooks_each_fire_independently(client):
    register = await client.post("/auth/register", json={"email": "webhookmulti1@example.com", "password": "pw"})
    user_id = register.json()["id"]
    created = await client.post("/targets", json={"url": "https://example.com/webhook-multi1"})
    target_id = created.json()["id"]
    await _insert_webhook(user_id, url="http://8.8.8.8/hook-a")
    await _insert_webhook(user_id, url="http://1.1.1.1/hook-b")
    await _insert_check(target_id, is_up=False, status_code=None, latency_ms=None, error="timeout")

    with patch("realtime.send_webhook", new=AsyncMock(return_value=True)) as mock_webhook:
        await realtime._handle_notification(f"{target_id}:local")

    assert mock_webhook.await_count == 2
    called_urls = {call.args[0] for call in mock_webhook.call_args_list}
    assert called_urls == {"http://8.8.8.8/hook-a", "http://1.1.1.1/hook-b"}
