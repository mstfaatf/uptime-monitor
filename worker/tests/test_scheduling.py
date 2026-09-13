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


class _FakeTransaction:
    """Stands in for asyncpg's Connection.transaction() async context manager."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


def _mock_conn():
    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.fetch = AsyncMock()
    conn.transaction = MagicMock(return_value=_FakeTransaction())
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
        region="us-east",
    )

    sql, *params = conn.execute.call_args.args
    assert "INSERT INTO checks" in sql
    assert params == [1, checked_at, 200, 123, True, None, 1, 2, 3, 4, cert_expires, "commonName=Test", "us-east"]


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
        region="local",
    )
    _, *params = conn.execute.call_args.args
    assert params[5] is None  # error is the 6th positional column


async def test_claim_due_targets_backfills_schedule_rows_before_claiming():
    conn = _mock_conn()
    conn.fetch.return_value = []

    await main.claim_due_targets(conn, "us-east")

    # ensure_schedule_rows() must run before the claim SELECT — it's the fix for a target
    # (new, or a brand-new region against pre-existing targets) having no schedule row yet.
    backfill_sql, backfill_region = conn.execute.call_args_list[0].args
    assert "INSERT INTO target_region_schedule" in backfill_sql
    assert "ON CONFLICT" in backfill_sql
    assert backfill_region == "us-east"
    # Precisely the anti-join that limits the backfill to targets actually missing a row for
    # this region — not a plain INSERT that could duplicate or clobber an existing schedule.
    assert "LEFT JOIN target_region_schedule trs" in backfill_sql
    assert "WHERE trs.target_id IS NULL" in backfill_sql


async def test_ensure_schedule_rows_new_rows_are_due_immediately():
    """A target missing a schedule row for this region gets one seeded as due right now
    (next_check_at = now()), not scheduled out into the future — matching the old
    targets.next_check_at server-default behavior of checking a brand-new target right away."""
    conn = _mock_conn()

    await main.ensure_schedule_rows(conn, "us-east")

    backfill_sql, backfill_region = conn.execute.call_args.args
    assert "SELECT t.id, $1, now(), 0" in backfill_sql
    assert backfill_region == "us-east"


async def test_claim_due_targets_selects_for_update_skip_locked_and_stamps_claim():
    conn = _mock_conn()
    conn.fetch.return_value = [{"id": 1, "url": "https://example.com", "consecutive_failures": 0}]

    rows = await main.claim_due_targets(conn, "us-east")

    select_sql, region_arg, ttl_arg = conn.fetch.call_args.args
    assert "target_region_schedule" in select_sql
    assert "next_check_at <= now()" in select_sql
    # Precisely the self-heal clause from 2.2/2.5: a stale claim (older than CLAIM_TTL_SECONDS)
    # must be treated as due, not just a NULL one — a looser "claimed_at" substring check
    # wouldn't catch a regression that dropped the "OR ... stale" half and left a target
    # permanently stuck once claimed.
    assert "trs.claimed_at IS NULL OR trs.claimed_at < now() - make_interval(secs => $2)" in select_sql
    assert "FOR UPDATE OF trs SKIP LOCKED" in select_sql
    assert region_arg == "us-east"
    assert ttl_arg == main.CLAIM_TTL_SECONDS

    # Second execute() call is the claim stamp (the first, asserted separately above, is the
    # ensure_schedule_rows backfill).
    update_sql, update_region, ids_arg = conn.execute.call_args_list[1].args
    assert "UPDATE target_region_schedule SET claimed_at = now()" in update_sql
    assert update_region == "us-east"
    assert ids_arg == [1]

    assert rows == [{"id": 1, "url": "https://example.com", "consecutive_failures": 0}]


async def test_claim_due_targets_does_not_stamp_claim_when_nothing_is_due():
    conn = _mock_conn()
    conn.fetch.return_value = []

    rows = await main.claim_due_targets(conn, "us-east")

    assert rows == []
    # Only the ensure_schedule_rows backfill executed — no claim-stamp UPDATE since nothing
    # came back from the SELECT.
    assert conn.execute.call_count == 1


async def test_reschedule_target_on_success_resets_failures_and_uses_normal_interval():
    conn = _mock_conn()
    before = datetime.now(timezone.utc)

    await main.reschedule_target(conn, target_id=1, region="us-east", is_up=True, consecutive_failures_before=3)

    sql, target_id, region, next_check_at = conn.execute.call_args.args
    assert "UPDATE target_region_schedule" in sql
    assert "consecutive_failures = 0" in sql
    assert "claimed_at = NULL" in sql
    assert target_id == 1
    assert region == "us-east"
    expected = before + timedelta(seconds=main.settings.CHECK_INTERVAL_SECONDS)
    assert abs((next_check_at - expected).total_seconds()) < 2


async def test_reschedule_target_on_failure_increments_and_backs_off():
    conn = _mock_conn()
    before = datetime.now(timezone.utc)

    await main.reschedule_target(conn, target_id=1, region="us-east", is_up=False, consecutive_failures_before=2)

    sql, target_id, region, new_failures, next_check_at = conn.execute.call_args.args
    assert "UPDATE target_region_schedule" in sql
    assert "consecutive_failures = $3" in sql
    assert "claimed_at = NULL" in sql
    assert target_id == 1
    assert region == "us-east"
    assert new_failures == 3  # incremented from 2
    delay = (next_check_at - before).total_seconds()
    # failure #3 -> unjittered 120s (30 * 2^2), +/-20% jitter => roughly [96, 144]; padded
    # slightly for test execution time.
    assert 90 <= delay <= 150
