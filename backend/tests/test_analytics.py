"""Coverage for backend/analytics.py (percentiles, MTTR) and GET /targets/{id}/analytics
(Phase 6, prompt 6.5). Pure-function tests use a lightweight fake Check / raw incident dicts,
matching test_export.py's established pattern for compute_sla/compute_incidents. Endpoint-level
tests run against the real test database via the `client` fixture, inserting checks at precise
offsets to exercise each window boundary.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from analytics import _compute_mttr, _percentile, compute_region_analytics
from database import engine


class _FakeCheck:
    """Same minimal stand-in as test_export.py's — compute_region_analytics only ever touches
    .checked_at/.is_up/.latency_ms."""

    def __init__(self, checked_at, is_up, latency_ms=None):
        self.checked_at = checked_at
        self.is_up = is_up
        self.latency_ms = latency_ms


def _t(minutes: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minutes)


# --- _percentile ---


def test_percentile_empty_is_none():
    assert _percentile([], 50) is None


def test_percentile_single_value():
    assert _percentile([42], 50) == 42
    assert _percentile([42], 99) == 42


def test_percentile_known_values():
    # Verified independently against the linear-interpolation formula this function
    # implements (numpy's default / Excel's PERCENTILE.INC): p50=55, p95=96 (95.5 rounds to
    # the nearest even integer — Python 3's banker's rounding), p99=99.
    values = sorted([10, 20, 30, 40, 50, 60, 70, 80, 90, 100])
    assert _percentile(values, 50) == 55
    assert _percentile(values, 95) == 96
    assert _percentile(values, 99) == 99


def test_percentile_all_identical_values():
    assert _percentile([100, 100, 100], 50) == 100
    assert _percentile([100, 100, 100], 99) == 100


# --- _compute_mttr ---


def test_mttr_no_incidents():
    mttr, count = _compute_mttr([], window_start=_t(0))
    assert mttr is None
    assert count == 0


def test_mttr_single_resolved_incident_within_window():
    incidents = [{"start": _t(10), "end": _t(20), "duration": timedelta(minutes=10)}]
    mttr, count = _compute_mttr(incidents, window_start=_t(0))
    assert mttr == 600.0  # 10 minutes in seconds
    assert count == 1


def test_mttr_resolved_incident_recovered_before_window_is_excluded():
    """An incident that started AND recovered entirely before window_start has no overlap
    with the window at all."""
    incidents = [{"start": _t(-100), "end": _t(-90), "duration": timedelta(minutes=10)}]
    mttr, count = _compute_mttr(incidents, window_start=_t(0))
    assert mttr is None
    assert count == 0


def test_mttr_incident_started_before_window_uses_full_duration_not_clipped():
    """The context-check scenario: an incident that began before window_start but recovered
    after it counts with its TRUE (longer) duration, not one truncated at the window edge."""
    incidents = [{"start": _t(-30), "end": _t(10), "duration": timedelta(minutes=40)}]
    mttr, count = _compute_mttr(incidents, window_start=_t(0))
    assert mttr == 40 * 60  # the full 40 minutes, not the 10 minutes inside the window
    assert count == 1


def test_mttr_unresolved_incident_counted_up_to_now(monkeypatch):
    """An unresolved incident (end=None) is counted up to "now," not excluded — see
    analytics.py's _compute_mttr docstring for the reasoning."""
    fixed_now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr("analytics.datetime", _FixedDatetime)

    incident_start = fixed_now - timedelta(minutes=5)
    incidents = [{"start": incident_start, "end": None, "duration": None}]
    mttr, count = _compute_mttr(incidents, window_start=fixed_now - timedelta(hours=1))
    assert mttr == 300.0  # 5 minutes, measured up to the fixed "now"
    assert count == 1


def test_mttr_mix_of_resolved_and_unresolved():
    window_start = _t(0)
    incidents = [
        {"start": _t(-50), "end": _t(-40), "duration": timedelta(minutes=10)},  # before window: excluded
        {"start": _t(10), "end": _t(20), "duration": timedelta(minutes=10)},  # resolved, in window: 600s
        {"start": _t(30), "end": None, "duration": None},  # unresolved: counted up to "now"
    ]
    mttr, count = _compute_mttr(incidents, window_start=window_start)
    assert count == 2  # the pre-window incident is excluded; the other two both count
    # Can't assert an exact value for the unresolved incident (depends on real wall-clock
    # "now" relative to the year-2026 fixture), but the mean must be >= the resolved
    # incident's own 600s contribution, and finite.
    assert mttr >= 600.0


# --- compute_region_analytics (pure function, synthetic Checks) ---


def test_compute_region_analytics_basic_shape():
    window_start = _t(0)
    window_checks = [
        _FakeCheck(_t(1), True, latency_ms=100),
        _FakeCheck(_t(2), True, latency_ms=200),
        _FakeCheck(_t(3), False, latency_ms=None),
    ]
    result = compute_region_analytics(window_checks, context_check=None, window_start=window_start)
    assert result["total_checks"] == 3
    assert round(result["uptime_percent"], 2) == 66.67
    assert result["latency_p50_ms"] is not None
    assert result["incident_count"] == 1  # the trailing down check is an ongoing incident


def test_compute_region_analytics_context_check_extends_incident_before_window():
    """Without the context check, the down streak starting inside the window would look like
    a fresh incident beginning at _t(5) instead of the true, earlier start at _t(-10)."""
    window_start = _t(0)
    context_check = _FakeCheck(_t(-10), False, latency_ms=None)  # already down before the window opened
    window_checks = [
        _FakeCheck(_t(5), False, latency_ms=None),
        _FakeCheck(_t(10), True, latency_ms=50),  # recovers inside the window
    ]
    result = compute_region_analytics(window_checks, context_check, window_start)
    assert result["incident_count"] == 1
    # 20 minutes (from _t(-10) to _t(10)), not 5 minutes (from _t(5) to _t(10)).
    assert result["mttr_seconds"] == 20 * 60

    # And uptime_percent/latency stats are NOT influenced by the context check — only
    # window_checks (2 checks: one down, one up).
    assert result["total_checks"] == 2
    assert result["uptime_percent"] == 50.0


def test_compute_region_analytics_no_checks_has_null_stats():
    result = compute_region_analytics([], context_check=None, window_start=_t(0))
    assert result["total_checks"] == 0
    assert result["uptime_percent"] is None
    assert result["latency_p50_ms"] is None
    assert result["mttr_seconds"] is None
    assert result["incident_count"] == 0


# --- GET /targets/{id}/analytics (real DB via the client fixture) ---


async def _insert_check(target_id: int, region: str, checked_at: datetime, is_up: bool, latency_ms=None) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO checks (target_id, checked_at, status_code, latency_ms, is_up, error, region)
                VALUES (:target_id, :checked_at, :status_code, :latency_ms, :is_up, :error, :region)
                """
            ),
            {
                "target_id": target_id,
                "checked_at": checked_at,
                "status_code": 200 if is_up else None,
                "latency_ms": latency_ms if latency_ms is not None else (100 if is_up else None),
                "is_up": is_up,
                "error": None if is_up else "Connection timed out",
                "region": region,
            },
        )


async def _register_and_create_target(client, email, url):
    resp = await client.post("/auth/register", json={"email": email, "password": "pw"})
    assert resp.status_code == 200
    created = await client.post("/targets", json={"url": url})
    assert created.status_code == 201
    return created.json()["id"]


async def test_analytics_requires_authentication(client):
    resp = await client.get("/targets/1/analytics")
    assert resp.status_code == 401


async def test_analytics_404s_for_another_users_target(client):
    target_id = await _register_and_create_target(client, "analytics-a@example.com", "https://example.com/analytics-a")
    await client.post("/auth/logout")

    await client.post("/auth/register", json={"email": "analytics-b@example.com", "password": "pw"})
    resp = await client.get(f"/targets/{target_id}/analytics")
    assert resp.status_code == 404


async def test_analytics_rejects_invalid_window(client):
    target_id = await _register_and_create_target(client, "analytics-badwin@example.com", "https://example.com/analytics-badwin")
    resp = await client.get(f"/targets/{target_id}/analytics", params={"window": "12h"})
    assert resp.status_code == 400
    assert "window" in resp.json()["detail"].lower()


async def test_analytics_defaults_to_7d(client):
    target_id = await _register_and_create_target(client, "analytics-default@example.com", "https://example.com/analytics-default")
    await _insert_check(target_id, "local", datetime.now(timezone.utc), True)

    resp = await client.get(f"/targets/{target_id}/analytics")
    assert resp.status_code == 200
    assert resp.json()["window"] == "7d"
    assert "local" in resp.json()["regions"]


async def test_analytics_region_absent_when_no_checks_in_window(client):
    target_id = await _register_and_create_target(client, "analytics-absent@example.com", "https://example.com/analytics-absent")
    resp = await client.get(f"/targets/{target_id}/analytics", params={"window": "24h"})
    assert resp.status_code == 200
    assert resp.json()["regions"] == {}


async def test_analytics_keeps_regions_independent(client):
    target_id = await _register_and_create_target(client, "analytics-regions@example.com", "https://example.com/analytics-regions")
    now = datetime.now(timezone.utc)
    await _insert_check(target_id, "us-east", now, True, latency_ms=100)
    await _insert_check(target_id, "eu-west", now, False)

    resp = await client.get(f"/targets/{target_id}/analytics", params={"window": "24h"})
    assert resp.status_code == 200
    regions = resp.json()["regions"]
    assert regions["us-east"]["uptime_percent"] == 100.0
    assert regions["eu-west"]["uptime_percent"] == 0.0
    # Neither region's stats leak into the other's.
    assert regions["us-east"]["total_checks"] == 1
    assert regions["eu-west"]["total_checks"] == 1


async def test_analytics_window_boundary_24h(client):
    target_id = await _register_and_create_target(client, "analytics-win24@example.com", "https://example.com/analytics-win24")
    now = datetime.now(timezone.utc)
    await _insert_check(target_id, "local", now - timedelta(hours=23, minutes=59), True)  # just inside
    await _insert_check(target_id, "local", now - timedelta(hours=24, minutes=1), True)  # just outside

    resp = await client.get(f"/targets/{target_id}/analytics", params={"window": "24h"})
    assert resp.json()["regions"]["local"]["total_checks"] == 1


async def test_analytics_window_boundary_7d(client):
    target_id = await _register_and_create_target(client, "analytics-win7d@example.com", "https://example.com/analytics-win7d")
    now = datetime.now(timezone.utc)
    await _insert_check(target_id, "local", now - timedelta(days=6, hours=23), True)  # just inside
    await _insert_check(target_id, "local", now - timedelta(days=7, hours=1), True)  # just outside

    resp = await client.get(f"/targets/{target_id}/analytics", params={"window": "7d"})
    assert resp.json()["regions"]["local"]["total_checks"] == 1


async def test_analytics_window_boundary_30d(client):
    target_id = await _register_and_create_target(client, "analytics-win30d@example.com", "https://example.com/analytics-win30d")
    now = datetime.now(timezone.utc)
    await _insert_check(target_id, "local", now - timedelta(days=29, hours=23), True)  # just inside
    await _insert_check(target_id, "local", now - timedelta(days=30, hours=1), True)  # just outside

    resp = await client.get(f"/targets/{target_id}/analytics", params={"window": "30d"})
    assert resp.json()["regions"]["local"]["total_checks"] == 1


async def test_analytics_window_boundary_90d(client):
    target_id = await _register_and_create_target(client, "analytics-win90d@example.com", "https://example.com/analytics-win90d")
    now = datetime.now(timezone.utc)
    await _insert_check(target_id, "local", now - timedelta(days=89, hours=23), True)  # just inside
    await _insert_check(target_id, "local", now - timedelta(days=90, hours=1), True)  # just outside

    resp = await client.get(f"/targets/{target_id}/analytics", params={"window": "90d"})
    assert resp.json()["regions"]["local"]["total_checks"] == 1


async def test_analytics_latency_percentiles_from_real_checks(client):
    target_id = await _register_and_create_target(client, "analytics-latency@example.com", "https://example.com/analytics-latency")
    now = datetime.now(timezone.utc)
    for i, latency in enumerate([10, 20, 30, 40, 50, 60, 70, 80, 90, 100]):
        await _insert_check(target_id, "local", now - timedelta(minutes=i), True, latency_ms=latency)

    resp = await client.get(f"/targets/{target_id}/analytics", params={"window": "24h"})
    region = resp.json()["regions"]["local"]
    assert region["latency_p50_ms"] == 55
    assert region["latency_p95_ms"] == 96
    assert region["latency_p99_ms"] == 99


async def test_analytics_mttr_with_resolved_and_unresolved_incidents(client):
    target_id = await _register_and_create_target(client, "analytics-mttr@example.com", "https://example.com/analytics-mttr")
    now = datetime.now(timezone.utc)

    # A resolved incident: down for 10 minutes, then recovers.
    await _insert_check(target_id, "local", now - timedelta(hours=2), True)
    await _insert_check(target_id, "local", now - timedelta(hours=1, minutes=50), False)
    await _insert_check(target_id, "local", now - timedelta(hours=1, minutes=40), True)

    # An unresolved incident: down now, no recovery yet (the most recent check).
    await _insert_check(target_id, "local", now - timedelta(minutes=5), False)

    resp = await client.get(f"/targets/{target_id}/analytics", params={"window": "24h"})
    region = resp.json()["regions"]["local"]
    assert region["incident_count"] == 2
    # Resolved incident contributed 600s; the unresolved one contributed ~300s (5 minutes) up
    # to "now" — the mean should land somewhere around (600 + ~300) / 2 = ~450, with generous
    # tolerance for real wall-clock time elapsed during the test itself.
    assert 400 < region["mttr_seconds"] < 500
