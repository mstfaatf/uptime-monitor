"""GET /targets/{id} and GET /targets/{id}/checks — added in Phase 3 prompt 3.6 to back the
frontend detail page's chart/heatmap/incident-timeline/cert panel. Ownership enforcement itself
is covered in test_ownership.py; this file covers response shape and query behavior."""

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


async def test_get_target_detail_returns_404_for_nonexistent_target(client):
    await client.post("/auth/register", json={"email": "detail404@example.com", "password": "pw"})
    resp = await client.get("/targets/999999")
    assert resp.status_code == 404


async def test_get_target_detail_returns_empty_dict_when_no_checks_yet(client):
    await client.post("/auth/register", json={"email": "detailempty@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/detail-empty"})
    target_id = created.json()["id"]

    resp = await client.get(f"/targets/{target_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == target_id
    assert body["latest_checks"] == {}


async def test_get_target_detail_reports_each_region_independently(client):
    await client.post("/auth/register", json={"email": "detailregions@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/detail-regions"})
    target_id = created.json()["id"]

    await _insert_check(target_id, region="local", is_up=True, latency_ms=100)
    await _insert_check(target_id, region="eu-west", is_up=False, latency_ms=None, status_code=None)

    resp = await client.get(f"/targets/{target_id}")
    assert resp.status_code == 200
    checks = resp.json()["latest_checks"]
    assert checks["local"]["is_up"] is True
    assert checks["local"]["latency_ms"] == 100
    assert checks["eu-west"]["is_up"] is False
    # No aggregate/collapsed field anywhere in the response.
    assert "is_up" not in resp.json()
    assert "status" not in resp.json()


async def test_get_target_checks_requires_region_query_param(client):
    await client.post("/auth/register", json={"email": "checksnoregion@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/checks-noregion"})
    target_id = created.json()["id"]

    resp = await client.get(f"/targets/{target_id}/checks")
    assert resp.status_code == 422  # missing required query param


async def test_get_target_checks_returns_404_for_nonexistent_target(client):
    await client.post("/auth/register", json={"email": "checks404@example.com", "password": "pw"})
    resp = await client.get("/targets/999999/checks?region=local")
    assert resp.status_code == 404


async def test_get_target_checks_filters_by_region_and_orders_oldest_first(client):
    await client.post("/auth/register", json={"email": "checksorder@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/checks-order"})
    target_id = created.json()["id"]

    now = datetime.now(timezone.utc)
    await _insert_check(target_id, region="local", checked_at=now - timedelta(minutes=10), latency_ms=100)
    await _insert_check(target_id, region="local", checked_at=now - timedelta(minutes=5), latency_ms=200)
    await _insert_check(target_id, region="local", checked_at=now, latency_ms=300)
    await _insert_check(target_id, region="eu-west", checked_at=now, latency_ms=999)

    resp = await client.get(f"/targets/{target_id}/checks?region=local")
    assert resp.status_code == 200
    body = resp.json()
    assert [c["latency_ms"] for c in body] == [100, 200, 300]
    assert all(c["region"] == "local" for c in body)


async def test_get_target_checks_respects_limit(client):
    await client.post("/auth/register", json={"email": "checkslimit@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/checks-limit"})
    target_id = created.json()["id"]

    now = datetime.now(timezone.utc)
    for i in range(5):
        await _insert_check(target_id, region="local", checked_at=now - timedelta(minutes=5 - i), latency_ms=i)

    resp = await client.get(f"/targets/{target_id}/checks?region=local&limit=2")
    assert resp.status_code == 200
    assert len(resp.json()) == 2
