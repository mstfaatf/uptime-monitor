"""Coverage for backend/export.py (SLA/incident computation, CSV building) and
GET /targets/{id}/export (prompt 4.8)."""

import csv
import io
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from database import engine
from export import build_csv, compute_incidents, compute_sla


class _FakeCheck:
    """A tiny stand-in for the SQLAlchemy Check model — compute_sla/compute_incidents/build_csv
    only ever touch these attributes, so a plain object avoids needing a real DB row for the
    pure-function unit tests below."""

    def __init__(self, checked_at, is_up, **kwargs):
        self.checked_at = checked_at
        self.is_up = is_up
        self.status_code = kwargs.get("status_code")
        self.latency_ms = kwargs.get("latency_ms")
        self.dns_ms = kwargs.get("dns_ms")
        self.tcp_ms = kwargs.get("tcp_ms")
        self.tls_ms = kwargs.get("tls_ms")
        self.ttfb_ms = kwargs.get("ttfb_ms")
        self.tls_cert_expires_at = kwargs.get("tls_cert_expires_at")
        self.error = kwargs.get("error")


def _t(minutes: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minutes)


def test_compute_sla_empty_is_none():
    assert compute_sla([]) is None


def test_compute_sla_all_up_is_100():
    checks = [_FakeCheck(_t(i), True) for i in range(5)]
    assert compute_sla(checks) == 100.0


def test_compute_sla_mixed():
    checks = [_FakeCheck(_t(0), True), _FakeCheck(_t(1), False), _FakeCheck(_t(2), True), _FakeCheck(_t(3), True)]
    assert compute_sla(checks) == 75.0


def test_compute_incidents_none_when_always_up():
    checks = [_FakeCheck(_t(i), True) for i in range(3)]
    assert compute_incidents(checks) == []


def test_compute_incidents_closed_incident():
    checks = [_FakeCheck(_t(0), True), _FakeCheck(_t(1), False), _FakeCheck(_t(2), False), _FakeCheck(_t(3), True)]
    incidents = compute_incidents(checks)
    assert len(incidents) == 1
    assert incidents[0]["start"] == _t(1)
    assert incidents[0]["end"] == _t(3)
    assert incidents[0]["duration"] == timedelta(minutes=2)


def test_compute_incidents_ongoing_when_still_down():
    checks = [_FakeCheck(_t(0), True), _FakeCheck(_t(1), False)]
    incidents = compute_incidents(checks)
    assert len(incidents) == 1
    assert incidents[0]["end"] is None
    assert incidents[0]["duration"] is None


def test_compute_incidents_chronological_order_multiple():
    checks = [
        _FakeCheck(_t(0), True),
        _FakeCheck(_t(1), False),
        _FakeCheck(_t(2), True),
        _FakeCheck(_t(3), True),
        _FakeCheck(_t(4), False),
        _FakeCheck(_t(5), True),
    ]
    incidents = compute_incidents(checks)
    assert len(incidents) == 2
    assert incidents[0]["start"] == _t(1)  # earliest first — chronological, not reversed
    assert incidents[1]["start"] == _t(4)


def test_build_csv_days_remaining_is_relative_to_checked_at_not_now():
    """The core correctness property flagged in the implementation: a historical row's
    days-remaining must reflect what was true when it was checked, not now()."""
    checked_at = datetime.now(timezone.utc) - timedelta(days=100)
    expires_at = checked_at + timedelta(days=10)  # had 10 days left AT THE TIME
    check = _FakeCheck(checked_at, True, status_code=200, latency_ms=100, tls_cert_expires_at=expires_at)

    csv_text = build_csv("My Target", "https://example.com", "local", None, None, [check])
    rows = list(csv.reader(io.StringIO(csv_text)))
    data_row = rows[-1]
    assert data_row[8] == "10"  # TLS Cert Days Remaining column, not a huge negative number


def test_build_csv_contains_summary_and_data_sections():
    checks = [
        _FakeCheck(_t(0), True, status_code=200, latency_ms=120),
        _FakeCheck(_t(1), False, error="Connection timed out"),
        _FakeCheck(_t(2), True, status_code=200, latency_ms=95),
    ]
    csv_text = build_csv("My Target", "https://example.com", "local", None, None, checks)
    rows = list(csv.reader(io.StringIO(csv_text)))

    assert rows[0] == ["Target", "My Target"]
    assert rows[1] == ["URL", "https://example.com"]
    assert rows[2] == ["Region", "local"]
    sla_row = next(r for r in rows if r and r[0] == "SLA %")
    assert sla_row[1] == "66.67"
    header_row = next(r for r in rows if r and r[0] == "Checked At")
    assert header_row == [
        "Checked At", "Is Up", "Status Code", "Latency (ms)", "DNS (ms)", "TCP (ms)",
        "TLS (ms)", "TTFB (ms)", "TLS Cert Days Remaining", "Error",
    ]
    assert len(rows) - (rows.index(header_row) + 1) == 3  # one data row per check


async def _insert_check(target_id: int, region: str, checked_at: datetime, is_up: bool, **overrides) -> None:
    values = {
        "target_id": target_id,
        "checked_at": checked_at,
        "status_code": 200 if is_up else None,
        "latency_ms": 100 if is_up else None,
        "is_up": is_up,
        "error": None if is_up else "Connection timed out",
        "region": region,
    }
    values.update(overrides)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO checks (target_id, checked_at, status_code, latency_ms, is_up, error, region)
                VALUES (:target_id, :checked_at, :status_code, :latency_ms, :is_up, :error, :region)
                """
            ),
            values,
        )


async def test_export_requires_authentication(client):
    resp = await client.get("/targets/1/export?region=local")
    assert resp.status_code == 401


async def test_export_404s_for_another_users_target(client):
    await client.post("/auth/register", json={"email": "exporta@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/export-a"})
    target_id = created.json()["id"]
    await client.post("/auth/logout")

    await client.post("/auth/register", json={"email": "exportb@example.com", "password": "pw"})
    resp = await client.get(f"/targets/{target_id}/export?region=local")
    assert resp.status_code == 404


async def test_export_rejects_unsupported_format(client):
    await client.post("/auth/register", json={"email": "exportfmt@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/export-fmt"})
    target_id = created.json()["id"]

    resp = await client.get(f"/targets/{target_id}/export?region=local&format=pdf")
    assert resp.status_code == 400
    assert "pdf" in resp.json()["detail"].lower()


async def test_export_requires_region_query_param(client):
    await client.post("/auth/register", json={"email": "exportnoregion@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/export-no-region"})
    target_id = created.json()["id"]

    resp = await client.get(f"/targets/{target_id}/export")
    assert resp.status_code == 422


async def test_export_returns_csv_with_correct_headers_and_content(client):
    await client.post("/auth/register", json={"email": "exportok@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/export-ok"})
    target_id = created.json()["id"]

    await _insert_check(target_id, "local", datetime.now(timezone.utc), True)

    resp = await client.get(f"/targets/{target_id}/export?region=local")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert f'target-{target_id}-local-checks.csv' in resp.headers["content-disposition"]

    rows = list(csv.reader(io.StringIO(resp.text)))
    assert rows[2] == ["Region", "local"]


async def test_export_scopes_to_the_requested_region_only(client):
    await client.post("/auth/register", json={"email": "exportregions@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/export-regions"})
    target_id = created.json()["id"]

    await _insert_check(target_id, "local", datetime.now(timezone.utc), True)
    await _insert_check(target_id, "eu-west", datetime.now(timezone.utc), False)

    resp = await client.get(f"/targets/{target_id}/export?region=local")
    header_row_idx = resp.text.splitlines().index("Checked At,Is Up,Status Code,Latency (ms),DNS (ms),TCP (ms),TLS (ms),TTFB (ms),TLS Cert Days Remaining,Error")
    data_lines = resp.text.splitlines()[header_row_idx + 1:]
    assert len(data_lines) == 1
    assert ",True," in data_lines[0]  # the local (up) check, not eu-west's down one


async def test_export_filters_by_date_range(client):
    await client.post("/auth/register", json={"email": "exportrange@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/export-range"})
    target_id = created.json()["id"]

    now = datetime.now(timezone.utc)
    await _insert_check(target_id, "local", now - timedelta(days=10), True)
    await _insert_check(target_id, "local", now - timedelta(days=1), True)

    from_param = (now - timedelta(days=2)).isoformat()
    resp = await client.get(f"/targets/{target_id}/export", params={"region": "local", "from": from_param})
    assert resp.status_code == 200
    rows = list(csv.reader(io.StringIO(resp.text)))
    total_row = next(r for r in rows if r and r[0] == "Total checks")
    assert total_row[1] == "1"  # only the check inside the range
