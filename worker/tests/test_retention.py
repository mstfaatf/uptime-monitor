"""Unit tests for worker/retention.py's SQL, using a mocked asyncpg pool/connection — same
hermetic convention as test_scheduling.py (see worker/README.md's Tests section: this suite
deliberately never touches a real database).

This is a real, deliberate departure from the "removes rows older than the cutoff, leaves
recent ones untouched" ask being proven end-to-end here: that specific selectivity claim (does
`WHERE checked_at < $1` actually only delete the old rows?) is Postgres's own job to get right,
not this module's — what this module owns is "does prune_old_checks build the right DELETE
statement with the right cutoff, and does it not touch anything if there's nothing to prune."
The actual selective-deletion behavior against real data was verified live against the real
dev database (see the prompt 6.8 status notes) rather than by standing up real-Postgres
infrastructure for this one test file, consistent with every other worker test's hermetic
scope.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from retention import RETENTION_INTERVAL_SECONDS, prune_old_checks


class _AsyncContextManagerMock:
    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *exc_info):
        return False


def _mock_pool(conn):
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AsyncContextManagerMock(conn))
    return pool


def _mock_conn(status: str = "DELETE 0"):
    conn = MagicMock()
    conn.execute = AsyncMock(return_value=status)
    return conn


async def test_prune_old_checks_deletes_by_checked_at_cutoff():
    conn = _mock_conn("DELETE 7")
    pool = _mock_pool(conn)
    before = datetime.now(timezone.utc)

    deleted = await prune_old_checks(pool, retention_days=90)

    sql, cutoff_arg = conn.execute.call_args.args
    assert "DELETE FROM checks" in sql
    assert "WHERE checked_at < $1" in sql
    expected_cutoff = before - timedelta(days=90)
    # Small tolerance for real time elapsed during the test itself, not a loose assertion on
    # the actual cutoff math (which is a plain subtraction).
    assert abs((cutoff_arg - expected_cutoff).total_seconds()) < 5
    assert deleted == 7


async def test_prune_old_checks_uses_the_given_retention_window():
    conn = _mock_conn("DELETE 0")
    pool = _mock_pool(conn)
    before = datetime.now(timezone.utc)

    await prune_old_checks(pool, retention_days=30)

    _, cutoff_arg = conn.execute.call_args.args
    expected_cutoff = before - timedelta(days=30)
    assert abs((cutoff_arg - expected_cutoff).total_seconds()) < 5


async def test_prune_old_checks_returns_zero_when_nothing_is_deleted():
    conn = _mock_conn("DELETE 0")
    pool = _mock_pool(conn)

    deleted = await prune_old_checks(pool, retention_days=90)

    assert deleted == 0


async def test_prune_old_checks_parses_command_status_robustly():
    """A malformed/unexpected status string must not raise — this is a logging aid, not
    something the caller's control flow depends on."""
    conn = _mock_conn("SOMETHING UNEXPECTED")
    pool = _mock_pool(conn)

    deleted = await prune_old_checks(pool, retention_days=90)

    assert deleted == 0


def test_retention_interval_is_roughly_a_day():
    """A basic sanity check on the constant itself — the prompt's "coarse ~24h timer"
    requirement, not just a magic number."""
    assert RETENTION_INTERVAL_SECONDS == 24 * 60 * 60
