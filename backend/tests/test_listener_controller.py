"""realtime.ListenerController: when the LISTEN connection is open, and the catch-up replay.

The open/close tests drive step() with a fake clock and a fake connection (no real LISTEN). The
catch-up and startup tests use the real _handle_notification against the real test database,
with email and webhook sending mocked, to prove a check committed while LISTEN was closed (or
while the API was restarting) still gets its alert, and that replaying it sends nothing twice.
"""

import asyncio
import contextlib
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

import activity
import realtime
from database import engine
from realtime import (
    CATCHUP_BATCH_SIZE,
    LISTEN_BURST_WINDOW_SECONDS,
    LISTEN_LEAD_SECONDS,
    LISTEN_NOTIFY_QUIET_SECONDS,
    LISTEN_WATCHING_QUIET_SECONDS,
    STARTUP_REPLAY_SECONDS,
    WORKER_BURST_MAX_SECONDS,
    HandledCheck,
    ListenerController,
)

INTERVAL = 900
BASE = 1_791_115_200  # a multiple of INTERVAL
MID = BASE + 450  # halfway between bursts: outside every burst window
BOUNDARY = BASE + INTERVAL
assert BASE % INTERVAL == 0
assert BASE + WORKER_BURST_MAX_SECONDS + LISTEN_NOTIFY_QUIET_SECONDS < MID < BASE + INTERVAL - LISTEN_LEAD_SECONDS


class FakeConn:
    def __init__(self):
        self.closed = False
        self.callback = None

    def is_closed(self):
        return self.closed

    async def add_listener(self, channel, callback):
        assert channel == realtime.NOTIFY_CHANNEL
        self.callback = callback

    async def close(self):
        self.closed = True

    def notify(self, payload):
        self.callback(self, 1, realtime.NOTIFY_CHANNEL, payload)


class Harness:
    """A controller wired to a fake clock, fake connections, and recording fakes. `results`
    maps a notification payload to the HandledCheck the fake handler returns for it."""

    def __init__(self, *, start=MID, watching=None, handle=None, rows=None, start_watermark=0, results=None):
        self.t = start
        self.watching_flag = False
        self.connections: list[FakeConn] = []
        self.connect_failures = 0
        self.handled: list[str] = []
        self.rows = rows or []
        self.queries: list[tuple[int, int]] = []
        self.results = results or {}

        async def connect():
            if self.connect_failures:
                self.connect_failures -= 1
                raise OSError("connection refused")
            conn = FakeConn()
            self.connections.append(conn)
            return conn

        async def default_handle(payload):
            self.handled.append(payload)
            return self.results.get(payload)

        async def fetch_start():
            return start_watermark

        async def fetch_after(after_id, limit):
            self.queries.append((after_id, limit))
            return [r for r in self.rows if r[0] > after_id][:limit]

        self.controller = ListenerController(
            burst_interval=INTERVAL,
            connect=connect,
            watching=watching or (lambda: self.watching_flag),
            handle=handle or default_handle,
            fetch_start_watermark=fetch_start,
            fetch_checks_after=fetch_after,
            now=lambda: self.t,
        )

    async def at(self, t):
        self.t = t
        await self.controller.step()
        return self.controller.is_open

    async def notify_at(self, t, payload):
        """Deliver a NOTIFY at time t on the open connection and let its handler finish."""
        self.t = t
        self.conn.notify(payload)
        await self.drain()

    @property
    def conn(self) -> FakeConn:
        return self.connections[-1]

    async def drain(self):
        """Let handler tasks spawned by NOTIFY callbacks finish."""
        while self.controller._tasks:
            await asyncio.gather(*list(self.controller._tasks))


# --- Burst window ---------------------------------------------------------------------------


def test_window_constants():
    assert LISTEN_LEAD_SECONDS == 10
    assert LISTEN_BURST_WINDOW_SECONDS == 60
    assert LISTEN_NOTIFY_QUIET_SECONDS == 30
    assert LISTEN_WATCHING_QUIET_SECONDS == 120
    assert WORKER_BURST_MAX_SECONDS == 90  # mirrors worker/scheduler.py's BURST_MAX_SECONDS
    assert STARTUP_REPLAY_SECONDS == 600


async def test_opens_at_boundary_minus_lead_and_closes_after_the_burst_window():
    h = Harness(start=MID)
    await h.controller.initialize_watermark()
    assert await h.at(MID) is False
    assert await h.at(BOUNDARY - LISTEN_LEAD_SECONDS - 1) is False
    assert await h.at(BOUNDARY - LISTEN_LEAD_SECONDS) is True
    assert len(h.connections) == 1
    assert await h.at(BOUNDARY + LISTEN_BURST_WINDOW_SECONDS) is True
    assert await h.at(BOUNDARY + LISTEN_BURST_WINDOW_SECONDS + 1) is False
    assert h.connections[0].closed


async def test_a_healthy_burst_closes_at_the_end_of_the_window():
    h = Harness(start=MID, results={"5:local": HandledCheck(101, retry_pending=False)})
    await h.controller.initialize_watermark()
    await h.at(BOUNDARY)
    await h.notify_at(BOUNDARY + 1, "5:local")  # the burst's NOTIFYs land within a second
    assert await h.at(BOUNDARY + LISTEN_BURST_WINDOW_SECONDS) is True
    assert await h.at(BOUNDARY + LISTEN_BURST_WINDOW_SECONDS + 1) is False


async def test_a_notify_keeps_it_open_for_the_notify_quiet_period_only():
    h = Harness(start=MID, results={"5:local": HandledCheck(101, retry_pending=False)})
    await h.controller.initialize_watermark()
    await h.at(BOUNDARY)
    late = BOUNDARY + 55
    await h.notify_at(late, "5:local")
    assert await h.at(late + LISTEN_NOTIFY_QUIET_SECONDS - 1) is True  # past the window, in quiet
    assert await h.at(late + LISTEN_NOTIFY_QUIET_SECONDS) is False


async def test_closed_between_bursts_when_nothing_is_happening():
    h = Harness(start=MID)
    await h.controller.initialize_watermark()
    for t in range(BASE + LISTEN_BURST_WINDOW_SECONDS + 1, BASE + INTERVAL - LISTEN_LEAD_SECONDS, 30):
        assert await h.at(t) is False
    assert h.connections == []


# --- Long bursts: in-burst retries --------------------------------------------------------------


async def test_a_pending_in_burst_retry_holds_listen_until_cap_plus_quiet():
    """A target that just started failing is retried after ~30s, then ~60s more: the retries can
    be more than the 30s notify quiet period apart and later than the 60s window. LISTEN must
    stay open until 30s after the last one, which can't be later than the worker's cap."""
    h = Harness(
        start=MID,
        results={
            "7:local:first": HandledCheck(201, retry_pending=True),
            "7:local:second": HandledCheck(202, retry_pending=True),
            "7:local:last": HandledCheck(203, retry_pending=False),
        },
    )
    await h.controller.initialize_watermark()
    await h.at(BOUNDARY)
    await h.notify_at(BOUNDARY + 1, "7:local:first")  # fails: 1st failure, retry in ~30s
    await h.notify_at(BOUNDARY + 35, "7:local:second")  # fails again: retry in ~60s
    # Past the 60s window and 50s after the last NOTIFY: still held for the coming retry.
    assert await h.at(BOUNDARY + 85) is True
    hold_end = BOUNDARY + WORKER_BURST_MAX_SECONDS + LISTEN_NOTIFY_QUIET_SECONDS
    assert await h.at(hold_end - 1) is True
    # The last pass started just inside the cap; its check finished a few seconds later.
    last = BOUNDARY + 95
    await h.notify_at(last, "7:local:last")
    assert await h.at(hold_end + 1) is True  # past the hold, inside the last NOTIFY's quiet
    assert await h.at(last + LISTEN_NOTIFY_QUIET_SECONDS - 1) is True
    assert await h.at(last + LISTEN_NOTIFY_QUIET_SECONDS) is False  # 30s after the last NOTIFY
    assert len(h.connections) == 1  # held the whole time, never closed and reopened


async def test_a_late_notify_in_a_long_burst_extends_past_the_hold():
    h = Harness(start=MID, results={"7:local": HandledCheck(201, retry_pending=True)})
    await h.controller.initialize_watermark()
    await h.at(BOUNDARY)
    await h.notify_at(BOUNDARY + 1, "7:local")
    # The last pass started near the cap and its check took a while to finish.
    await h.notify_at(BOUNDARY + 110, "7:local")
    assert await h.at(BOUNDARY + 110 + LISTEN_NOTIFY_QUIET_SECONDS - 1) is True
    assert await h.at(BOUNDARY + 110 + LISTEN_NOTIFY_QUIET_SECONDS) is False


async def test_a_long_failing_target_does_not_extend_the_burst():
    """Past the 2nd consecutive failure the worker won't retry within the burst, so there's
    nothing to wait for."""
    h = Harness(start=MID, results={"8:local": HandledCheck(301, retry_pending=False)})
    await h.controller.initialize_watermark()
    await h.at(BOUNDARY)
    await h.notify_at(BOUNDARY + 1, "8:local")
    assert await h.at(BOUNDARY + LISTEN_BURST_WINDOW_SECONDS + 1) is False


async def test_a_retry_pending_check_outside_any_burst_adds_no_hold():
    """In live mode (mid-interval) watching keeps LISTEN open; no burst hold applies."""
    h = Harness(start=MID, results={"7:local": HandledCheck(201, retry_pending=True)})
    await h.controller.initialize_watermark()
    h.watching_flag = True
    await h.at(MID)
    await h.notify_at(MID + 1, "7:local")
    h.watching_flag = False
    assert await h.at(MID + 2) is True  # watching quiet period
    assert await h.at(MID + 1 + LISTEN_WATCHING_QUIET_SECONDS) is False


# --- Watching ---------------------------------------------------------------------------------


async def test_opens_immediately_when_the_first_sse_subscriber_connects(monkeypatch):
    h = Harness(start=MID, watching=realtime.is_watching)
    monkeypatch.setattr(realtime, "_controller", h.controller)
    activity.reset()
    assert await h.at(MID) is False

    queue = realtime.subscribe(31337)
    try:
        assert h.controller._wake.is_set()  # subscribe() woke the controller; no tick needed
        assert await h.at(MID) is True
    finally:
        realtime.unsubscribe(31337, queue)


async def test_opens_immediately_on_cookie_activity(monkeypatch):
    h = Harness(start=MID, watching=realtime.is_watching)
    monkeypatch.setattr(realtime, "_controller", h.controller)
    activity.reset()
    activity.add_listener(realtime._wake_listener)
    try:
        assert await h.at(MID) is False
        activity.record_cookie_activity()  # what a cookie-authenticated request does
        assert h.controller._wake.is_set()
        assert await h.at(MID) is True
    finally:
        activity.remove_listener(realtime._wake_listener)
        activity.reset()


async def test_stays_open_while_watching_then_closes_after_the_watching_quiet_period():
    """Someone on the detail or settings page: watching is true (cookie activity) but there's
    no SSE stream and, for a while, no NOTIFY. Workers are in live mode, so LISTEN stays open,
    and for 120s after (workers take up to two 30s polls to leave live mode)."""
    h = Harness(start=MID)
    await h.controller.initialize_watermark()
    h.watching_flag = True
    assert await h.at(MID) is True
    for t in range(MID, MID + 600, 10):
        assert await h.at(t) is True
    stopped = MID + 600
    assert await h.at(stopped) is True  # last moment watching is observed true
    h.watching_flag = False
    assert await h.at(stopped + LISTEN_WATCHING_QUIET_SECONDS - 1) is True
    after = stopped + LISTEN_WATCHING_QUIET_SECONDS + 1
    assert await h.at(after) is h.controller.in_burst_window(after)
    assert len(h.connections) == 1


async def test_the_two_quiet_periods_are_independent():
    """A NOTIFY only buys 30s; watching ending buys 120s."""
    h = Harness(start=MID, results={"5:local": HandledCheck(101, retry_pending=False)})
    await h.controller.initialize_watermark()
    h.watching_flag = True
    await h.at(MID)
    h.watching_flag = False
    await h.at(MID)  # watching last observed true just before this
    await h.notify_at(MID + 100, "5:local")
    assert await h.at(MID + LISTEN_WATCHING_QUIET_SECONDS - 1) is True  # both still in effect
    assert await h.at(MID + 100 + LISTEN_NOTIFY_QUIET_SECONDS - 1) is True  # notify quiet only
    assert await h.at(MID + 100 + LISTEN_NOTIFY_QUIET_SECONDS) is False


async def test_never_closes_while_a_notification_is_being_handled():
    release = asyncio.Event()
    handled = []

    async def slow_handle(payload):
        await release.wait()
        handled.append(payload)
        return None

    h = Harness(start=MID, handle=slow_handle)
    await h.controller.initialize_watermark()
    h.watching_flag = True
    await h.at(MID)
    h.watching_flag = False
    h.conn.notify("9:eu-west")
    await asyncio.sleep(0)
    later = MID + 3 * LISTEN_WATCHING_QUIET_SECONDS
    assert not h.controller.in_burst_window(later)
    assert await h.at(later) is True
    release.set()
    await h.drain()
    assert handled == ["9:eu-west"]
    assert await h.at(later) is False


# --- Reconnect ------------------------------------------------------------------------------


async def test_reconnects_every_second_while_it_should_be_open():
    h = Harness(start=MID)
    await h.controller.initialize_watermark()
    h.watching_flag = True
    h.connect_failures = 2
    assert await h.at(MID) is False  # attempt 1 fails
    assert await h.at(MID + 0.5) is False  # too soon to retry
    assert await h.at(MID + 1) is False  # attempt 2 fails
    assert await h.at(MID + 2) is True  # attempt 3 succeeds
    assert len(h.connections) == 1

    h.conn.closed = True  # the connection drops
    assert await h.at(MID + 3) is True
    assert len(h.connections) == 2


async def test_every_open_and_reconnect_runs_a_catch_up():
    h = Harness(start=MID, start_watermark=10)
    await h.controller.initialize_watermark()
    h.watching_flag = True
    await h.at(MID)
    h.conn.closed = True
    await h.at(MID + 1)
    assert [after for after, _ in h.queries] == [10, 10]


# --- Catch-up mechanics ---------------------------------------------------------------------


async def test_catch_up_replays_in_batches_once_per_pair_in_id_order():
    pairs = [(1, "local"), (2, "local"), (1, "eu-west")]
    rows = [(i, *pairs[i % 3]) for i in range(1, 1201)]
    h = Harness(start=MID, rows=rows, start_watermark=0)
    await h.controller.initialize_watermark()
    h.watching_flag = True
    await h.at(MID)

    assert [after for after, _ in h.queries] == [0, 500, 1000]  # batched, looped until caught up
    assert all(limit == CATCHUP_BATCH_SIZE for _, limit in h.queries)
    assert len(h.handled) == 9  # each pair once per batch, not once per check
    # Batch 1 (ids 1-500): newest ids are 498 (1:local), 499 (2:local), 500 (1:eu-west).
    assert h.handled[:3] == ["1:local", "2:local", "1:eu-west"]
    assert h.controller.watermark == 1200


async def test_a_handled_notify_advances_the_watermark():
    h = Harness(start=MID, start_watermark=10, results={"3:local": HandledCheck(77, retry_pending=False)})
    await h.controller.initialize_watermark()
    h.watching_flag = True
    await h.at(MID)
    await h.notify_at(MID, "3:local")
    assert h.controller.watermark == 77


async def test_startup_runs_a_catch_up_even_when_listen_is_not_due():
    """Between bursts, nobody watching: LISTEN stays closed, but the startup replay still
    handles whatever the last few minutes wrote (e.g. a burst interrupted by this restart)."""
    h = Harness(start=MID, rows=[(41, 7, "local"), (42, 7, "eu-west")], start_watermark=40)
    task = asyncio.create_task(h.controller.run())
    try:
        for _ in range(50):
            await asyncio.sleep(0.01)
            if len(h.handled) == 2:
                break
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    assert h.handled == ["7:local", "7:eu-west"]
    assert h.connections == []  # replayed without opening LISTEN
    assert h.controller.watermark == 42


# --- Catch-up end to end: alerts --------------------------------------------------------------


async def _insert_check(target_id: int, **values) -> int:
    row = {
        "target_id": target_id,
        "checked_at": datetime.now(timezone.utc),
        "status_code": 200,
        "latency_ms": 100,
        "is_up": True,
        "error": None,
        "region": "local",
        "tls_cert_expires_at": None,
    }
    row.update(values)
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                INSERT INTO checks (target_id, checked_at, status_code, latency_ms, is_up, error, region,
                                    tls_cert_expires_at)
                VALUES (:target_id, :checked_at, :status_code, :latency_ms, :is_up, :error, :region,
                        :tls_cert_expires_at)
                RETURNING id
                """
            ),
            row,
        )
        return result.scalar_one()


async def _insert_webhook(user_id: int) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO webhooks (user_id, url, secret, alert_on_downtime, alert_on_cert_expiry, enabled) "
                "VALUES (:user_id, 'http://8.8.8.8/hook', 'test-secret', true, true, true)"
            ),
            {"user_id": user_id},
        )


def _real_controller(clock):
    """Real _handle_notification and real database queries; only the connection is fake."""

    async def connect():
        return FakeConn()

    return ListenerController(burst_interval=INTERVAL, connect=connect, watching=lambda: False, now=lambda: clock["t"])


async def _open_and_close(controller, clock):
    clock["t"] = BOUNDARY  # a burst boundary: open (and catch up)
    await controller.step()
    assert controller.is_open
    clock["t"] = MID + INTERVAL  # between bursts, nothing recent: close
    await controller.step()
    assert not controller.is_open


async def test_checks_missed_while_closed_get_their_alerts_and_replays_send_nothing_twice(client):
    registered = await client.post("/auth/register", json={"email": "catchup@example.com", "password": "pw"})
    user_id = registered.json()["id"]
    created = await client.post("/targets", json={"url": "https://example.com/catchup"})
    target_id = created.json()["id"]
    await _insert_webhook(user_id)

    clock = {"t": MID}
    controller = _real_controller(clock)
    await controller.initialize_watermark()
    queue = realtime.subscribe(user_id)
    try:
        with patch("realtime.send_email", new=AsyncMock(return_value=True)) as email, patch(
            "realtime.send_webhook", new=AsyncMock(return_value=True)
        ) as webhook:
            # 1. Goes down while LISTEN is closed: nobody hears the NOTIFY.
            down_id = await _insert_check(target_id, is_up=False, status_code=None, latency_ms=None, error="timeout")
            assert not controller.is_open
            await _open_and_close(controller, clock)
            assert email.await_count == 1 and "down" in email.await_args.args[1].lower()
            assert webhook.await_count == 1 and webhook.await_args.args[2]["event"] == "target.down"
            assert controller.watermark == down_id
            pushed = queue.get_nowait()
            assert pushed["type"] == "check_update" and pushed["target"]["latest_checks"]["local"]["is_up"] is False

            # 2. Recovers while closed.
            up_id = await _insert_check(target_id, is_up=True)
            await _open_and_close(controller, clock)
            assert email.await_count == 2 and "back up" in email.await_args.args[1]
            assert webhook.await_count == 2 and webhook.await_args.args[2]["event"] == "target.up"

            # 3. Certificate starts expiring while closed.
            await _insert_check(target_id, is_up=True, tls_cert_expires_at=datetime.now(timezone.utc) + timedelta(days=5))
            await _open_and_close(controller, clock)
            assert email.await_count == 3
            assert webhook.await_count == 3 and webhook.await_args.args[2]["event"] == "target.cert_expiring"

            # 4. Replay everything from before the outage: all three were already alerted.
            controller.watermark = down_id - 1
            await _open_and_close(controller, clock)
            assert email.await_count == 3
            assert webhook.await_count == 3
            assert controller.watermark > up_id
            while not queue.empty():
                assert queue.get_nowait()["target"]["id"] == target_id
    finally:
        realtime.unsubscribe(user_id, queue)


async def test_startup_watermark_is_the_newest_check_older_than_the_replay_window(client):
    await client.post("/auth/register", json={"email": "startup-wm@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/startup-wm"})
    target_id = created.json()["id"]
    now = datetime.now(timezone.utc)
    old_id = await _insert_check(target_id, checked_at=now - timedelta(seconds=STARTUP_REPLAY_SECONDS + 300))
    older_still = await _insert_check(target_id, checked_at=now - timedelta(seconds=STARTUP_REPLAY_SECONDS + 900))
    await _insert_check(target_id, checked_at=now - timedelta(seconds=60))  # recent: to be replayed

    controller = _real_controller({"t": MID})
    await controller.initialize_watermark()
    # The newest *old* check, by id, even though a lower id was inserted later with an older time.
    assert controller.watermark == max(old_id, older_still)


async def test_an_api_restart_during_a_burst_replays_its_checks_with_no_duplicate_alerts(client):
    """The burst wrote a down check while the API was restarting. The new process's startup
    replay alerts on it; a second restart replays it again and sends nothing new."""
    registered = await client.post("/auth/register", json={"email": "restart@example.com", "password": "pw"})
    user_id = registered.json()["id"]
    created = await client.post("/targets", json={"url": "https://example.com/restart"})
    target_id = created.json()["id"]
    await _insert_webhook(user_id)
    down_id = await _insert_check(target_id, is_up=False, status_code=None, latency_ms=None, error="timeout")

    async def start_process():
        """What run() does at startup, without its endless loop."""
        controller = _real_controller({"t": MID})
        await controller.initialize_watermark()
        await controller._catch_up()
        return controller

    with patch("realtime.send_email", new=AsyncMock(return_value=True)) as email, patch(
        "realtime.send_webhook", new=AsyncMock(return_value=True)
    ) as webhook:
        first = await start_process()
        assert first.watermark >= down_id
        assert email.await_count == 1 and "down" in email.await_args.args[1].lower()
        assert webhook.await_count == 1 and webhook.await_args.args[2]["event"] == "target.down"

        await start_process()  # restarted again within the replay window
        assert email.await_count == 1
        assert webhook.await_count == 1


async def test_handle_notification_reports_the_check_id_and_whether_a_retry_may_follow(client):
    await client.post("/auth/register", json={"email": "returns-id@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/returns-id"})
    target_id = created.json()["id"]

    async def set_failures(region, failures):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO target_region_schedule (target_id, region, next_check_at, consecutive_failures) "
                    "VALUES (:t, :r, now(), :f) ON CONFLICT (target_id, region) "
                    "DO UPDATE SET consecutive_failures = :f"
                ),
                {"t": target_id, "r": region, "f": failures},
            )

    with patch("realtime.send_email", new=AsyncMock(return_value=True)), patch(
        "realtime.send_webhook", new=AsyncMock(return_value=True)
    ):
        up_id = await _insert_check(target_id, region="eu-west")
        assert await realtime._handle_notification(f"{target_id}:eu-west") == HandledCheck(up_id, False)

        await set_failures("local", 1)
        down_id = await _insert_check(target_id, region="local", is_up=False, status_code=None, error="timeout")
        assert await realtime._handle_notification(f"{target_id}:local") == HandledCheck(down_id, True)

        await set_failures("local", 3)  # failing for a while: no in-burst retry
        assert await realtime._handle_notification(f"{target_id}:local") == HandledCheck(down_id, False)

        assert await realtime._handle_notification("999999:local") is None


@pytest.fixture(autouse=True)
def _no_module_controller(monkeypatch):
    """Keep the process-wide controller hook from leaking between tests."""
    monkeypatch.setattr(realtime, "_controller", None)
    yield
