"""Unit tests for worker/main.py's persistence/scheduling SQL, using a mocked asyncpg
connection — no real database needed, consistent with the rest of worker/tests/ (see
worker/README.md's Tests section: this suite deliberately stays hermetic, unlike backend/tests/
which runs against a real Postgres test database).

The main gap these close: nothing previously asserted that insert_check's SQL column list and
its positional argument list stay in the same order — a mismatch there would silently write
wrong data to the wrong columns without any existing test catching it, since test_timing.py and
test_checker_redirects.py only exercise checker.py's pure result-dict building, never what
main.py actually sends to the database."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import main


def _mock_conn():
    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.fetch = AsyncMock()
    return conn


async def test_insert_check_passes_all_columns_in_matching_order():
    conn = _mock_conn()
    checked_at = datetime.now(timezone.utc)
    cert_expires = checked_at + timedelta(days=30)

    await main.insert_check(
        conn,
        target_id=1,
        checked_at=checked_at,
        status_code=200,
        latency_ms=123,
        is_up=True,
        error=None,
        dns_ms=1,
        tcp_ms=2,
        tls_ms=3,
        ttfb_ms=4,
        tls_cert_expires_at=cert_expires,
        tls_cert_issuer="commonName=Test",
    )

    sql, *params = conn.execute.call_args.args
    assert "INSERT INTO checks" in sql
    assert params == [1, checked_at, 200, 123, True, None, 1, 2, 3, 4, cert_expires, "commonName=Test"]


async def test_insert_check_normalizes_empty_error_to_none():
    conn = _mock_conn()
    await main.insert_check(
        conn,
        target_id=1,
        checked_at=datetime.now(timezone.utc),
        status_code=None,
        latency_ms=None,
        is_up=False,
        error="",  # falsy but not None — insert_check should still store NULL, not ""
        dns_ms=None,
        tcp_ms=None,
        tls_ms=None,
        ttfb_ms=None,
        tls_cert_expires_at=None,
        tls_cert_issuer=None,
    )
    _, *params = conn.execute.call_args.args
    assert params[5] is None  # error is the 6th positional column


async def test_get_due_targets_queries_next_check_at_and_returns_dicts():
    conn = _mock_conn()
    conn.fetch.return_value = [{"id": 1, "url": "https://example.com", "consecutive_failures": 0}]

    rows = await main.get_due_targets(conn)

    sql = conn.fetch.call_args.args[0]
    assert "next_check_at <= now()" in sql
    assert rows == [{"id": 1, "url": "https://example.com", "consecutive_failures": 0}]


async def test_reschedule_target_on_success_resets_failures_and_uses_normal_interval():
    conn = _mock_conn()
    before = datetime.now(timezone.utc)

    await main.reschedule_target(conn, target_id=1, is_up=True, consecutive_failures_before=3)

    sql, target_id, next_check_at = conn.execute.call_args.args
    assert "consecutive_failures = 0" in sql
    assert target_id == 1
    expected = before + timedelta(seconds=main.settings.CHECK_INTERVAL_SECONDS)
    assert abs((next_check_at - expected).total_seconds()) < 2


async def test_reschedule_target_on_failure_increments_and_backs_off():
    conn = _mock_conn()
    before = datetime.now(timezone.utc)

    await main.reschedule_target(conn, target_id=1, is_up=False, consecutive_failures_before=2)

    sql, target_id, new_failures, next_check_at = conn.execute.call_args.args
    assert "consecutive_failures = $2" in sql
    assert target_id == 1
    assert new_failures == 3  # incremented from 2
    delay = (next_check_at - before).total_seconds()
    # failure #3 -> unjittered 120s (30 * 2^2), +/-20% jitter => roughly [96, 144]; padded
    # slightly for test execution time.
    assert 90 <= delay <= 150
