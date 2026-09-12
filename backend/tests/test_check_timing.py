"""Coverage for the timing-breakdown + TLS cert fields on GET /targets/status (Phase 1
prompt 1.4) — the check row is inserted directly via SQL rather than through the worker,
since these tests exercise the API's read/response layer, not the worker's capture logic
(that's covered in worker/tests/test_timing.py)."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from database import engine


async def _insert_check(target_id: int, **overrides) -> None:
    values = {
        "target_id": target_id,
        "checked_at": datetime.now(timezone.utc),
        "status_code": 200,
        "latency_ms": 123,
        "is_up": True,
        "error": None,
        "dns_ms": 8,
        "tcp_ms": 15,
        "tls_ms": 40,
        "ttfb_ms": 90,
        "tls_cert_expires_at": None,
        "tls_cert_issuer": None,
    }
    values.update(overrides)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO checks (
                    target_id, checked_at, status_code, latency_ms, is_up, error,
                    dns_ms, tcp_ms, tls_ms, ttfb_ms, tls_cert_expires_at, tls_cert_issuer
                ) VALUES (
                    :target_id, :checked_at, :status_code, :latency_ms, :is_up, :error,
                    :dns_ms, :tcp_ms, :tls_ms, :ttfb_ms, :tls_cert_expires_at, :tls_cert_issuer
                )
                """
            ),
            values,
        )


async def test_status_exposes_timing_breakdown(client):
    await client.post("/auth/register", json={"email": "timing@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/timing"})
    target_id = created.json()["id"]

    await _insert_check(target_id, dns_ms=8, tcp_ms=15, tls_ms=40, ttfb_ms=90)

    resp = await client.get("/targets/status")
    assert resp.status_code == 200
    latest = resp.json()[0]["latest_check"]
    assert latest["dns_ms"] == 8
    assert latest["tcp_ms"] == 15
    assert latest["tls_ms"] == 40
    assert latest["ttfb_ms"] == 90


async def test_status_derives_cert_days_remaining_at_read_time(client):
    await client.post("/auth/register", json={"email": "cert@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/cert"})
    target_id = created.json()["id"]

    expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    await _insert_check(
        target_id,
        tls_cert_expires_at=expires_at,
        tls_cert_issuer="commonName=Test CA",
    )

    resp = await client.get("/targets/status")
    latest = resp.json()[0]["latest_check"]
    assert latest["tls_cert_issuer"] == "commonName=Test CA"
    assert latest["tls_cert_expires_at"] is not None
    # Not stored — recomputed from tls_cert_expires_at on every read, so it lands right at 30
    # (allowing a 1-day tolerance for wall-clock drift between insert and assertion).
    assert 29 <= latest["tls_cert_days_remaining"] <= 30


async def test_status_leaves_cert_fields_null_when_check_has_no_cert_data(client):
    await client.post("/auth/register", json={"email": "nocert@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/no-cert"})
    target_id = created.json()["id"]

    await _insert_check(target_id)  # defaults leave tls_cert_* null, e.g. an http:// target

    resp = await client.get("/targets/status")
    latest = resp.json()[0]["latest_check"]
    assert latest["tls_cert_expires_at"] is None
    assert latest["tls_cert_issuer"] is None
    assert latest["tls_cert_days_remaining"] is None


async def test_status_reports_negative_days_remaining_for_an_expired_cert(client):
    await client.post("/auth/register", json={"email": "expired@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/expired"})
    target_id = created.json()["id"]

    expired_at = datetime.now(timezone.utc) - timedelta(days=5)
    await _insert_check(target_id, tls_cert_expires_at=expired_at, tls_cert_issuer="commonName=Test CA")

    resp = await client.get("/targets/status")
    latest = resp.json()[0]["latest_check"]
    assert latest["tls_cert_days_remaining"] < 0
