"""Decides when the worker checks targets: continuously while someone is watching the site,
in short clock-aligned bursts while nobody is.

The production database scales to zero only after several minutes with no queries and no open
connections. Checking continuously (a claim query every SCHEDULER_TICK_SECONDS) keeps it awake
around the clock, so the worker has two modes:

Live mode, while GET /internal/watching says someone is watching: the long-standing loop. One
long-lived connection pool, a claim pass every SCHEDULER_TICK_SECONDS, targets checked on their
normal interval or backoff. The backend is asked again every LIVE_POLL_SECONDS, and the worker
only leaves live mode after two "not watching" answers in a row, so a page reload doesn't flip
it back and forth.

Idle mode, otherwise: the worker holds no database connection at all. It sleeps until the next
multiple of BURST_INTERVAL_SECONDS since the Unix epoch. Every region computes the same
instants from its own clock, so all of them are awake at the same time and the database's awake
windows overlap instead of stacking. At each boundary it opens a fresh pool (min_size=0), runs
a burst, and retires the pool. Between bursts it only asks the backend whether anyone is
watching, every IDLE_POLL_SECONDS, which never touches the database; a "yes" switches to live
mode at once.

A burst's first claim pass accepts targets due within EARLY_DUE_GRACE_SECONDS, so a target that
comes due seconds after the boundary isn't left waiting a whole interval. Later passes use the
exact due time, so a target that just failed still waits out its backoff before being retried.
The burst keeps going only while a target that just started failing (at most
IN_BURST_RETRY_MAX_FAILURES consecutive failures) is due again before BURST_MAX_SECONDS have
passed, which gives it one or two quick confirmations. Targets that have been failing for a long
time wait for a later burst, and a healthy burst ends right after its first pass.

Neither mode, nor switching between them, writes next_check_at: reschedule_target (main.py)
keeps writing each target's normal interval or backoff after every check in both modes. A
target that went stale during idle mode therefore already has next_check_at in the past and is
picked up by the first live tick.

Retention runs from here too, on the first claim pass after each UTC midnight (the 00:00 burst
in idle mode). The last-run date starts at today, so a restart never triggers a prune.
"""

import asyncio
import contextlib
import logging
import math
import time
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Live mode's claim-pass spacing. Much shorter than CHECK_INTERVAL_SECONDS: a failing target's
# backoff can be as short as ~30s (backoff.py), and a coarse tick would flatten that to "retry
# whenever the next tick happens to land". A claim query against the indexed schedule table is
# trivial at this scale.
SCHEDULER_TICK_SECONDS = 5
IDLE_POLL_SECONDS = 15
LIVE_POLL_SECONDS = 30
LIVE_EXIT_FALSE_POLLS = 2
BURST_MAX_SECONDS = 90
EARLY_DUE_GRACE_SECONDS = 60
# Only a target on its 1st or 2nd consecutive failure can have a backoff retry (about 30s, then
# about 60s, see backoff.py) that lands inside one burst. Longer-failing targets back off about 15
# minutes at a time and simply wait for a later burst; counting them would keep bursts open for
# whichever of them happens to come due during the window.
IN_BURST_RETRY_MAX_FAILURES = 2
POOL_CLOSE_TIMEOUT_SECONDS = 10


def next_burst_boundary(now: float, interval: int) -> float:
    """The first multiple of `interval` seconds since the Unix epoch that is >= now."""
    return math.ceil(now / interval) * interval


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


async def retire_pool(pool: Any) -> None:
    """Close a pool, waiting up to POOL_CLOSE_TIMEOUT_SECONDS for connections to be released,
    then terminating whatever is left."""
    try:
        await asyncio.wait_for(pool.close(), timeout=POOL_CLOSE_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        logger.warning("Connection pool didn't close within %ss; terminating it", POOL_CLOSE_TIMEOUT_SECONDS)
        pool.terminate()


class Scheduler:
    """Runs the idle/live mode loop. Every database touch goes through the injected callables,
    which is what lets the tests prove when (and whether) the database is used:

    - create_pool(min_size) -> pool; min_size is None for the live pool (asyncpg's default)
    - run_cycle(pool, grace_seconds) -> number of targets claimed and checked
    - seconds_until_failing_due(pool) -> seconds until the next target that just started
      failing (see IN_BURST_RETRY_MAX_FAILURES) is due, or None
    - prune(pool) -> rows deleted
    - watching() -> bool, must never raise for normal failures (see watching.py)
    """

    def __init__(
        self,
        *,
        region: str,
        burst_interval: int,
        create_pool: Callable[[int | None], Awaitable[Any]],
        run_cycle: Callable[[Any, int], Awaitable[int]],
        seconds_until_failing_due: Callable[[Any], Awaitable[float | None]],
        prune: Callable[[Any], Awaitable[int]],
        watching: Callable[[], Awaitable[bool]],
        now: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        today: Callable[[], date] = _utc_today,
        retire: Callable[[Any], Awaitable[None]] = retire_pool,
    ):
        self.region = region
        self.burst_interval = burst_interval
        self._create_pool = create_pool
        self._run_cycle = run_cycle
        self._seconds_until_failing_due = seconds_until_failing_due
        self._prune = prune
        self._watching_probe = watching
        self._now = now
        self._sleep = sleep
        self._today = today
        self._retire = retire
        self._last_prune_date = today()
        self.mode = "idle"

    async def _watching(self) -> bool:
        """The probe already turns every expected failure into False; this guards against the
        unexpected, so no failure can ever leave the worker in (or move it into) live mode."""
        try:
            return (await self._watching_probe()) is True
        except Exception:
            logger.exception("[region=%s] Watching check raised; treating the site as unwatched", self.region)
            return False

    async def _maybe_prune(self, pool: Any) -> None:
        today = self._today()
        if today == self._last_prune_date:
            return
        self._last_prune_date = today
        try:
            deleted = await self._prune(pool)
            logger.info("[region=%s] Retention: pruned %d old check row(s)", self.region, deleted)
        except Exception:
            logger.exception("[region=%s] Retention sweep failed", self.region)

    async def run_forever(self) -> None:
        while True:
            await self._run_idle()
            await self._run_live()

    async def _run_idle(self) -> None:
        """Returns as soon as someone is watching. Holds no database connection except during
        a burst."""
        self.mode = "idle"
        if await self._watching():
            return
        last_burst: float | None = None
        while True:
            boundary = next_burst_boundary(self._now(), self.burst_interval)
            if last_burst is not None and boundary <= last_burst:
                # A burst that finished within the same instant it started would otherwise land
                # on the boundary it just ran and repeat it forever.
                boundary = last_burst + self.burst_interval
            logger.info(
                "[region=%s] Idle mode: next burst at %s",
                self.region,
                datetime.fromtimestamp(boundary, timezone.utc).strftime("%H:%M:%S"),
            )
            while self._now() < boundary:
                await self._sleep(min(IDLE_POLL_SECONDS, boundary - self._now()))
                if self._now() < boundary and await self._watching():
                    return
            await self._run_burst(boundary)
            last_burst = boundary
            if await self._watching():
                return

    async def _run_burst(self, started_at: float) -> None:
        deadline = started_at + BURST_MAX_SECONDS
        pool = None
        try:
            pool = await self._create_pool(0)
            grace = EARLY_DUE_GRACE_SECONDS
            checked = 0
            while True:
                try:
                    checked += await self._run_cycle(pool, grace)
                except Exception:
                    logger.exception("[region=%s] Burst claim pass failed", self.region)
                grace = 0
                await self._maybe_prune(pool)
                remaining = deadline - self._now()
                if remaining <= 0:
                    break
                wait = await self._seconds_until_failing_due(pool)
                if wait is None or wait >= remaining:
                    break
                await self._sleep(max(wait, SCHEDULER_TICK_SECONDS))
                if self._now() >= deadline:
                    break
            logger.info("[region=%s] Burst finished: %d check(s)", self.region, checked)
        except Exception:
            logger.exception("[region=%s] Burst failed", self.region)
        finally:
            if pool is not None:
                await self._retire(pool)

    async def _run_live(self) -> None:
        """Returns after two consecutive "not watching" answers, once the current claim pass
        (and every check it started) has finished and the pool is closed."""
        self.mode = "live"
        logger.info("[region=%s] Live mode: someone is watching, checking continuously", self.region)
        pool = None
        try:
            pool = await self._create_pool(None)
            next_poll = self._now() + LIVE_POLL_SECONDS
            false_answers = 0
            while True:
                try:
                    await self._run_cycle(pool, 0)
                except Exception:
                    logger.exception("[region=%s] Cycle failed", self.region)
                await self._maybe_prune(pool)
                if self._now() >= next_poll:
                    next_poll = self._now() + LIVE_POLL_SECONDS
                    if await self._watching():
                        false_answers = 0
                    else:
                        false_answers += 1
                        if false_answers >= LIVE_EXIT_FALSE_POLLS:
                            logger.info("[region=%s] Nobody watching; leaving live mode", self.region)
                            return
                await self._sleep(SCHEDULER_TICK_SECONDS)
        except Exception:
            # Can't even open a pool: wait a tick rather than spinning, then fall back to idle,
            # which re-checks watching and tries again from there.
            logger.exception("[region=%s] Live mode failed", self.region)
            with contextlib.suppress(Exception):
                await self._sleep(SCHEDULER_TICK_SECONDS)
        finally:
            if pool is not None:
                await self._retire(pool)
