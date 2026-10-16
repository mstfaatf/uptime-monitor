"""Idle/live scheduling (scheduler.py) and the watching probe (watching.py), with a fake clock.

Every database touch the scheduler makes goes through injected callables (create_pool,
run_cycle, seconds_until_failing_due, prune, retire), so recording fakes for those show exactly
when the database is used. The fake clock's sleep() advances time instantly. No real database,
network, or waiting, consistent with the rest of worker/tests/.
"""

import asyncio
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import main
import scheduler as sched
from scheduler import (
    BURST_MAX_SECONDS,
    EARLY_DUE_GRACE_SECONDS,
    IDLE_POLL_SECONDS,
    LIVE_POLL_SECONDS,
    SCHEDULER_TICK_SECONDS,
    Scheduler,
    next_burst_boundary,
)
from watching import SECRET_HEADER, WARNING_INTERVAL_SECONDS, WatchingProbe

INTERVAL = 900
# A multiple of INTERVAL, so boundaries are BASE + k * INTERVAL. 2026-10-16T12:00:00Z.
BASE = 1_791_115_200
assert BASE % INTERVAL == 0


class _Stop(BaseException):
    """Ends a test run. A BaseException (like asyncio.CancelledError) so the scheduler's own
    `except Exception` recovery paths can't swallow it and keep looping."""


class FakeClock:
    def __init__(self, start: float, stop_at: float):
        self.t = start
        self.stop_at = stop_at

    def now(self) -> float:
        return self.t

    def today(self):
        return datetime.fromtimestamp(self.t, timezone.utc).date()

    async def sleep(self, seconds: float) -> None:
        assert seconds >= 0
        self.t += seconds
        if self.t >= self.stop_at:
            raise _Stop()
        await asyncio.sleep(0)


class FakeDb:
    """Records every database-facing call with the fake time it happened at."""

    def __init__(self, clock: FakeClock, cycle_seconds: float = 2.0, claimed: int = 3, failing_due=None):
        self.clock = clock
        self.cycle_seconds = cycle_seconds
        self.claimed = claimed
        self.failing_due = failing_due or (lambda now: None)
        self.events: list[tuple[float, str, object]] = []
        self.open_pools = 0

    def _record(self, kind, detail=None):
        self.events.append((self.clock.t, kind, detail))

    async def create_pool(self, min_size):
        self.open_pools += 1
        self._record("create", min_size)
        return object()

    async def retire(self, pool):
        self.open_pools -= 1
        self._record("close")

    async def run_cycle(self, pool, grace):
        self._record("cycle", grace)
        self.clock.t += self.cycle_seconds  # checks take time
        return self.claimed

    async def seconds_until_failing_due(self, pool):
        self._record("failing_due")
        return self.failing_due(self.clock.t)

    async def prune(self, pool):
        self._record("prune")
        return 0

    def kinds(self, kind):
        return [e for e in self.events if e[1] == kind]


def _scheduler(clock: FakeClock, db: FakeDb, watching, region="local", interval=INTERVAL) -> Scheduler:
    async def probe():
        return watching()

    return Scheduler(
        region=region,
        burst_interval=interval,
        create_pool=db.create_pool,
        run_cycle=db.run_cycle,
        seconds_until_failing_due=db.seconds_until_failing_due,
        prune=db.prune,
        watching=probe,
        now=clock.now,
        sleep=clock.sleep,
        today=clock.today,
        retire=db.retire,
    )


async def _run(s: Scheduler) -> None:
    with pytest.raises(_Stop):
        await s.run_forever()


def _sequence(*answers, then=False):
    """A watching() stand-in returning the given answers in order, then `then` forever."""
    calls = iter(answers)
    return lambda: next(calls, then)


# --- Boundaries ---------------------------------------------------------------------------


def test_boundaries_are_epoch_aligned_multiples():
    assert next_burst_boundary(BASE, INTERVAL) == BASE  # exactly on a boundary: that boundary
    assert next_burst_boundary(BASE + 0.001, INTERVAL) == BASE + INTERVAL
    assert next_burst_boundary(BASE + 899.9, INTERVAL) == BASE + INTERVAL
    assert next_burst_boundary(BASE + 900, INTERVAL) == BASE + INTERVAL


async def test_both_regions_burst_at_identical_times_regardless_of_start_time():
    """Two workers in different regions, started at different moments, wake at the same
    instants, so their awake windows overlap instead of stacking."""
    burst_starts = {}
    for region, start_offset in (("us-east", 37), ("eu-west", 612)):
        clock = FakeClock(BASE + start_offset, stop_at=BASE + 3 * INTERVAL + 200)
        db = FakeDb(clock)
        await _run(_scheduler(clock, db, lambda: False, region=region))
        burst_starts[region] = [t for t, _, _ in db.kinds("create")]

    assert burst_starts["us-east"] == burst_starts["eu-west"] == [
        BASE + INTERVAL,
        BASE + 2 * INTERVAL,
        BASE + 3 * INTERVAL,
    ]


# --- Idle mode holds no connection between bursts ---------------------------------------


async def test_idle_mode_makes_no_database_calls_between_bursts():
    clock = FakeClock(BASE + 10, stop_at=BASE + 4 * INTERVAL + 300)
    db = FakeDb(clock)
    polls = []

    def watching():
        polls.append(clock.t)
        return False

    await _run(_scheduler(clock, db, watching))

    assert len(db.kinds("create")) == 4
    for t, kind, detail in db.events:
        burst_start = (t // INTERVAL) * INTERVAL
        # Every database touch happens inside a burst window, never between bursts.
        assert 0 <= t - burst_start <= BURST_MAX_SECONDS + SCHEDULER_TICK_SECONDS, (t, kind)
        if kind == "create":
            assert detail == 0  # idle-mode pools open no connection until used
    # Every burst's pool was closed again; nothing held open at the end.
    assert len(db.kinds("close")) == len(db.kinds("create"))
    assert db.open_pools == 0
    # Between bursts the worker still polls the backend every IDLE_POLL_SECONDS (no database).
    between = [p for p in polls if BASE + INTERVAL + BURST_MAX_SECONDS < p < BASE + 2 * INTERVAL]
    assert len(between) >= (INTERVAL - BURST_MAX_SECONDS) // IDLE_POLL_SECONDS - 1
    assert max(b - a for a, b in zip(between, between[1:])) <= IDLE_POLL_SECONDS


# --- Mode switching -------------------------------------------------------------------------


async def test_watching_starts_live_mode_immediately_between_bursts():
    clock = FakeClock(BASE + 100, stop_at=BASE + 140)
    db = FakeDb(clock, cycle_seconds=0.5)
    # Not watching at first; someone opens the dashboard before the second idle poll.
    await _run(_scheduler(clock, db, _sequence(False, True, then=True)))

    creates = db.kinds("create")
    assert creates[0][2] is None  # live pool (asyncpg default size), not a burst pool
    assert creates[0][0] == BASE + 100 + IDLE_POLL_SECONDS  # right after the "yes", no boundary wait
    first_cycle = db.kinds("cycle")[0]
    assert first_cycle[0] == creates[0][0]  # first claim pass at once
    live_cycle_times = [t for t, _, _ in db.kinds("cycle")]
    spacing = {round(b - a, 3) for a, b in zip(live_cycle_times, live_cycle_times[1:])}
    assert spacing == {SCHEDULER_TICK_SECONDS + 0.5}  # the 5s tick (plus check time)


async def test_two_consecutive_false_answers_are_needed_to_leave_live_mode():
    clock = FakeClock(BASE + 100, stop_at=BASE + 400)
    db = FakeDb(clock, cycle_seconds=0.1)
    # idle start: True -> live. Live polls: False, True, False, False -> leave.
    await _run(_scheduler(clock, db, _sequence(True, False, True, False, False, then=False)))

    live_start = db.kinds("create")[0][0]
    closes = db.kinds("close")
    assert closes, "live pool was never closed"
    # Left only after the 4th live poll (2 consecutive falses), not after the 1st false.
    assert closes[0][0] >= live_start + 4 * LIVE_POLL_SECONDS
    assert closes[0][0] < live_start + 5 * LIVE_POLL_SECONDS


async def test_leaving_live_mode_finishes_the_current_pass_before_closing_the_pool():
    clock = FakeClock(BASE + 100, stop_at=BASE + 300)
    db = FakeDb(clock, cycle_seconds=3.0)
    await _run(_scheduler(clock, db, _sequence(True, False, False, then=False)))

    close_t = db.kinds("close")[0][0]
    last_cycle_before_close = max(t for t, _, _ in db.kinds("cycle") if t < close_t)
    # The pass that was running had fully finished (its 3s of checks) before the close.
    assert close_t >= last_cycle_before_close + 3.0


# --- Every failure path lands in idle -------------------------------------------------------


def _probe(handler, *, url="http://backend.test", secret="s3cret", clock=None) -> WatchingProbe:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return WatchingProbe(url, secret, client, clock=clock or (lambda: 0.0))


def _raise(exc):
    def handler(request):
        raise exc

    return handler


@pytest.mark.parametrize(
    "probe_kwargs",
    [
        {"url": None},
        {"url": ""},
        {"secret": None},
        {"secret": ""},
    ],
)
async def test_missing_configuration_reads_as_not_watching_without_a_request(probe_kwargs):
    handler = MagicMock(side_effect=AssertionError("no request should be made"))
    assert await _probe(handler, **probe_kwargs)() is False


@pytest.mark.parametrize(
    "handler",
    [
        _raise(httpx.ReadTimeout("timed out")),
        _raise(httpx.ConnectTimeout("timed out")),
        _raise(httpx.ConnectError("refused")),
        _raise(RuntimeError("anything else")),
        lambda request: httpx.Response(500, json={"watching": True}),
        lambda request: httpx.Response(401, json={"detail": "Unauthorized"}),
        lambda request: httpx.Response(404),
        lambda request: httpx.Response(200, text="not json"),
        lambda request: httpx.Response(200, json={"something": True}),
        lambda request: httpx.Response(200, json={"watching": "true"}),
        lambda request: httpx.Response(200, json={"watching": 1}),
        lambda request: httpx.Response(200, json=[True]),
    ],
)
async def test_every_failure_reads_as_not_watching(handler):
    assert await _probe(handler)() is False


async def test_a_well_formed_answer_is_returned_and_the_secret_is_sent_as_a_header():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["secret"] = request.headers.get(SECRET_HEADER)
        return httpx.Response(200, json={"watching": True})

    assert await _probe(handler, url="http://backend.test/")() is True
    assert seen == {"url": "http://backend.test/internal/watching", "secret": "s3cret"}


async def test_failure_warnings_are_rate_limited_and_never_include_the_secret(caplog):
    now = {"t": 0.0}
    probe = _probe(lambda request: httpx.Response(500), secret="very-secret-value", clock=lambda: now["t"])
    caplog.set_level(logging.WARNING, logger="watching")

    for t in (0, 10, 30, 59):
        now["t"] = t
        await probe()
    assert len(caplog.records) == 1
    now["t"] = WARNING_INTERVAL_SECONDS + 1
    await probe()
    assert len(caplog.records) == 2
    assert "very-secret-value" not in caplog.text


async def test_scheduler_never_goes_live_when_the_backend_is_unreachable():
    """End to end through the real probe: a backend that can't be reached keeps the worker in
    idle bursts. It never falls back to the 5s tick."""
    clock = FakeClock(BASE + 10, stop_at=BASE + 2 * INTERVAL + 200)
    db = FakeDb(clock)
    probe = _probe(_raise(httpx.ConnectError("refused")))
    s = Scheduler(
        region="local",
        burst_interval=INTERVAL,
        create_pool=db.create_pool,
        run_cycle=db.run_cycle,
        seconds_until_failing_due=db.seconds_until_failing_due,
        prune=db.prune,
        watching=probe,
        now=clock.now,
        sleep=clock.sleep,
        today=clock.today,
        retire=db.retire,
    )
    await _run(s)

    assert [detail for _, _, detail in db.kinds("create")] == [0, 0]  # two bursts, no live pool
    assert [t for t, _, _ in db.kinds("cycle")] == [BASE + INTERVAL, BASE + 2 * INTERVAL]


async def test_a_probe_that_raises_unexpectedly_still_reads_as_not_watching():
    clock = FakeClock(BASE + 10, stop_at=BASE + INTERVAL + 200)
    db = FakeDb(clock)

    def broken():
        raise RuntimeError("bug")

    await _run(_scheduler(clock, db, broken))
    assert [detail for _, _, detail in db.kinds("create")] == [0]


# --- Bursts ---------------------------------------------------------------------------------


async def test_a_healthy_burst_ends_after_one_pass():
    clock = FakeClock(BASE + 10, stop_at=BASE + INTERVAL + 300)
    db = FakeDb(clock, failing_due=lambda now: None)
    await _run(_scheduler(clock, db, lambda: False))

    assert len(db.kinds("cycle")) == 1
    assert db.kinds("close")[0][0] == BASE + INTERVAL + db.cycle_seconds


async def test_a_burst_that_takes_no_time_is_not_repeated_on_the_same_boundary():
    """Regression: with no time passing during a burst, the next boundary computed from "now"
    is the boundary that just ran, which used to repeat that burst forever."""
    clock = FakeClock(BASE + 10, stop_at=BASE + 3 * INTERVAL + 100)
    db = FakeDb(clock, cycle_seconds=0.0)
    await _run(_scheduler(clock, db, lambda: False))

    assert [t for t, _, _ in db.kinds("cycle")] == [BASE + INTERVAL, BASE + 2 * INTERVAL, BASE + 3 * INTERVAL]


async def test_burst_retries_a_failing_target_whose_backoff_lands_inside_the_burst():
    clock = FakeClock(BASE + 10, stop_at=BASE + INTERVAL + 300)
    boundary = BASE + INTERVAL
    # A target fails in the first pass; its 30s backoff retry comes due at boundary+32, then the
    # next backoff (~60s) lands past the burst cap.
    retry_at = {"t": boundary + 32}

    def failing_due(now):
        if retry_at["t"] is None:
            return None
        return retry_at["t"] - now

    db = FakeDb(clock, failing_due=failing_due)
    original = db.run_cycle

    async def run_cycle(pool, grace):
        result = await original(pool, grace)
        if clock.t > boundary + 30:  # the retry pass: next backoff is beyond the cap
            retry_at["t"] = clock.t + 60
        return result

    db.run_cycle = run_cycle
    await _run(_scheduler(clock, db, lambda: False))

    cycle_times = [t for t, _, _ in db.kinds("cycle")]
    assert cycle_times[0] == boundary
    assert cycle_times[1] == pytest.approx(boundary + 32)
    assert len(cycle_times) == 2


async def test_burst_never_runs_past_its_cap():
    clock = FakeClock(BASE + 10, stop_at=BASE + INTERVAL + 400)
    db = FakeDb(clock, cycle_seconds=2.0, failing_due=lambda now: 0.0)  # always something due
    await _run(_scheduler(clock, db, lambda: False))

    boundary = BASE + INTERVAL
    cycle_times = [t for t, _, _ in db.kinds("cycle")]
    assert len(cycle_times) > 2  # really did keep claiming
    assert max(cycle_times) < boundary + BURST_MAX_SECONDS
    close_t = db.kinds("close")[0][0]
    assert close_t <= boundary + BURST_MAX_SECONDS + SCHEDULER_TICK_SECONDS


async def test_early_due_grace_applies_only_to_the_first_pass_of_an_idle_burst():
    clock = FakeClock(BASE + 10, stop_at=BASE + INTERVAL + 200)
    db = FakeDb(clock, failing_due=lambda now: 0.0)
    # Not watching at start or at any of the 59 idle polls before the boundary; the burst runs;
    # someone is watching from the first poll after it.
    await _run(_scheduler(clock, db, _sequence(False, *[False] * 59, then=True)))

    graces = [(t, detail) for t, _, detail in db.kinds("cycle")]
    burst_end = db.kinds("close")[0][0]
    burst = [g for t, g in graces if t < burst_end]
    live = [g for t, g in graces if t > burst_end]
    assert burst[0] == EARLY_DUE_GRACE_SECONDS
    assert set(burst[1:]) == {0}
    assert live and set(live) == {0}


# --- Retention ------------------------------------------------------------------------------


async def test_retention_runs_once_after_utc_midnight_and_not_on_restart():
    midnight = 1_791_158_400  # 2026-10-17T00:00:00Z
    assert midnight % INTERVAL == 0
    # Start 10 minutes before midnight: the start date is "today", so no prune at startup.
    clock = FakeClock(midnight - 600, stop_at=midnight + 3 * INTERVAL + 100)
    db = FakeDb(clock)
    await _run(_scheduler(clock, db, lambda: False))

    prunes = [t for t, _, _ in db.kinds("prune")]
    assert prunes == [midnight + db.cycle_seconds]  # in the 00:00 burst, after its first pass
    assert len(db.kinds("cycle")) == 4  # the other bursts that day didn't prune


async def test_a_restart_mid_day_never_prunes():
    clock = FakeClock(BASE + 10, stop_at=BASE + 4 * INTERVAL)
    db = FakeDb(clock)
    await _run(_scheduler(clock, db, lambda: False))
    assert db.kinds("prune") == []
    assert len(db.kinds("cycle")) == 3


async def test_retention_runs_once_in_live_mode_across_midnight():
    midnight = 1_791_158_400
    clock = FakeClock(midnight - 20, stop_at=midnight + 120)
    db = FakeDb(clock, cycle_seconds=0.5)
    await _run(_scheduler(clock, db, lambda: True))
    prunes = [t for t, _, _ in db.kinds("prune")]
    assert len(prunes) == 1 and prunes[0] >= midnight


# --- Mode switches never rewrite next_check_at ----------------------------------------------


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc_info):
        return False


async def test_mode_switches_never_write_next_check_at(monkeypatch):
    """Runs the real claim/run_cycle/failing-due SQL (main.py) through idle -> live -> idle
    against a recording connection, with the HTTP check itself stubbed out. Every statement the
    scheduler causes is captured; none of them may write next_check_at. Only reschedule_target,
    after a real check, does that (covered by test_scheduling.py)."""
    row = {
        "id": 7,
        "url": "https://example.com",
        "consecutive_failures": 0,
        "request_method": None,
        "request_headers": None,
        "basic_auth_username": None,
        "basic_auth_password_encrypted": None,
        "keyword_match": None,
        "keyword_match_mode": "contains",
        "check_interval_seconds": None,
    }
    statements: list[str] = []
    claim_graces: list[int] = []
    conn = MagicMock()

    async def execute(sql, *args):
        statements.append(sql)

    async def fetch(sql, *args):
        statements.append(sql)
        claim_graces.append(args[2])
        return [row]

    async def fetchval(sql, *args):
        statements.append(sql)
        return None

    conn.execute = execute
    conn.fetch = fetch
    conn.fetchval = fetchval
    conn.transaction = MagicMock(return_value=_FakeTransaction())
    pool = MagicMock()
    pool.acquire = MagicMock(side_effect=lambda: _Acquire(conn))
    check_one = AsyncMock()
    monkeypatch.setattr(main, "check_one", check_one)

    clock = FakeClock(BASE + 10, stop_at=BASE + INTERVAL + 400)
    closes = []

    async def create_pool(min_size):
        return pool

    async def retire(p):
        closes.append(clock.t)

    async def failing_due(p):
        async with p.acquire() as c:
            return await main.seconds_until_failing_due(c, "local")

    # idle burst at the boundary, then live, then two falses -> back to idle.
    answers = iter([False] + [False] * 59 + [True, True, False, False])

    async def watching():
        return next(answers, False)

    s = Scheduler(
        region="local",
        burst_interval=INTERVAL,
        create_pool=create_pool,
        run_cycle=lambda p, grace: main.run_cycle(p, MagicMock(), grace),
        seconds_until_failing_due=failing_due,
        prune=AsyncMock(return_value=0),
        watching=watching,
        now=clock.now,
        sleep=clock.sleep,
        today=clock.today,
        retire=retire,
    )
    await _run(s)

    assert len(closes) >= 2  # the burst pool and the live pool were both retired
    assert check_one.await_count >= 3  # checks really ran in the burst and in live mode
    assert claim_graces[0] == EARLY_DUE_GRACE_SECONDS and set(claim_graces[1:]) == {0}
    writes = [sql for sql in statements if sql.lstrip().upper().startswith("UPDATE")]
    assert writes, "expected the claim stamp UPDATEs to be captured"
    assert not any("next_check_at" in sql for sql in writes)


def test_scheduler_module_constants_match_the_design():
    assert sched.IDLE_POLL_SECONDS == 15
    assert sched.LIVE_POLL_SECONDS == 30
    assert sched.LIVE_EXIT_FALSE_POLLS == 2
    assert sched.BURST_MAX_SECONDS == 90
    assert sched.EARLY_DUE_GRACE_SECONDS == 60
    assert sched.IN_BURST_RETRY_MAX_FAILURES == 2
    assert sched.SCHEDULER_TICK_SECONDS == 5
