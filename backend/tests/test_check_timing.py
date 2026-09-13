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
        "region": "local",
    }
    values.update(overrides)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO checks (
                    target_id, checked_at, status_code, latency_ms, is_up, error,
                    dns_ms, tcp_ms, tls_ms, ttfb_ms, tls_cert_expires_at, tls_cert_issuer, region
                ) VALUES (
                    :target_id, :checked_at, :status_code, :latency_ms, :is_up, :error,
                    :dns_ms, :tcp_ms, :tls_ms, :ttfb_ms, :tls_cert_expires_at, :tls_cert_issuer, :region
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
    latest = resp.json()[0]["latest_checks"]["local"]
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
    latest = resp.json()[0]["latest_checks"]["local"]
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
    latest = resp.json()[0]["latest_checks"]["local"]
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
    latest = resp.json()[0]["latest_checks"]["local"]
    assert latest["tls_cert_days_remaining"] < 0


async def _insert_schedule_row(target_id: int, region: str, consecutive_failures: int) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO target_region_schedule (target_id, region, next_check_at, consecutive_failures)
                VALUES (:target_id, :region, now(), :consecutive_failures)
                """
            ),
            {"target_id": target_id, "region": region, "consecutive_failures": consecutive_failures},
        )


async def test_status_exposes_consecutive_failures_from_schedule_row(client):
    """Prompt 4.4: consecutive_failures is read from target_region_schedule (a table the API
    never queried before this), joined on (target_id, region) from the latest check's own
    region — not a fixed column of the target."""
    await client.post("/auth/register", json={"email": "failures@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/failures"})
    target_id = created.json()["id"]

    await _insert_schedule_row(target_id, "local", consecutive_failures=2)
    await _insert_check(target_id, is_up=False, status_code=None, latency_ms=None, error="Connection timed out")

    resp = await client.get("/targets/status")
    latest = resp.json()[0]["latest_checks"]["local"]
    assert latest["consecutive_failures"] == 2


async def test_status_consecutive_failures_null_without_a_schedule_row(client):
    """No target_region_schedule row exists yet (e.g. immediately after target creation, before
    any worker has picked it up) — consecutive_failures must be null, not 0 or missing."""
    await client.post("/auth/register", json={"email": "noschedule@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/no-schedule"})
    target_id = created.json()["id"]

    await _insert_check(target_id)  # no matching target_region_schedule row inserted

    resp = await client.get("/targets/status")
    latest = resp.json()[0]["latest_checks"]["local"]
    assert latest["consecutive_failures"] is None


async def test_target_detail_and_checks_history_expose_consecutive_failures_correctly(client):
    """GET /targets/{id} (latest per region) should carry the live schedule reading; GET
    /targets/{id}/checks (historical rows) should not fabricate one for a past check."""
    await client.post("/auth/register", json={"email": "detailfailures@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/detail-failures"})
    target_id = created.json()["id"]

    await _insert_schedule_row(target_id, "local", consecutive_failures=1)
    await _insert_check(target_id, is_up=False, status_code=None, latency_ms=None, error="Connection timed out")

    detail = await client.get(f"/targets/{target_id}")
    assert detail.status_code == 200
    assert detail.json()["latest_checks"]["local"]["consecutive_failures"] == 1

    history = await client.get(f"/targets/{target_id}/checks?region=local")
    assert history.status_code == 200
    assert history.json()[0]["consecutive_failures"] is None
