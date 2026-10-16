"""realtime.ListenerController: when the LISTEN connection is open, and the catch-up replay.

The open/close tests drive step() with a fake clock and a fake connection (no real LISTEN). The
catch-up tests use the real _handle_notification against the real test database, with email and
webhook sending mocked, to prove a check committed while LISTEN was closed still gets its alert,
and that replaying it sends nothing twice.
"""

import asyncio
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
    LISTEN_QUIET_SECONDS,
    ListenerController,
)

INTERVAL = 900
BASE = 1_791_115_200  # a multiple of INTERVAL
MID = BASE + 450  # halfway between bursts: outside every burst window
assert BASE % INTERVAL == 0
assert BASE + LISTEN_BURST_WINDOW_SECONDS < MID < BASE + INTERVAL - LISTEN_LEAD_SECONDS


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
    """A controller wired to a fake clock, fake connections, and recording fakes."""

    def __init__(self, *, start=MID, watching=None, handle=None, rows=None, max_check_id=0):
        self.t = start
        self.watching_flag = False
        self.connections: list[FakeConn] = []
        self.connect_failures = 0
        self.handled: list[str] = []
        self.rows = rows or []
        self.queries: list[tuple[int, int]] = []

        async def connect():
            if self.connect_failures:
                self.connect_failures -= 1
                raise OSError("connection refused")
            conn = FakeConn()
            self.connections.append(conn)
            return conn

        async def default_handle(payload):
            self.handled.append(payload)
            return None

        async def fetch_max():
            return max_check_id

        async def fetch_after(after_id, limit):
            self.queries.append((after_id, limit))
            return [r for r in self.rows if r[0] > after_id][:limit]

        self.controller = ListenerController(
            burst_interval=INTERVAL,
            connect=connect,
            watching=watching or (lambda: self.watching_flag),
            handle=handle or default_handle,
            fetch_max_check_id=fetch_max,
            fetch_checks_after=fetch_after,
            now=lambda: self.t,
        )

    async def at(self, t):
        self.t = t
        await self.controller.step()
        return self.controller.is_open

    @property
    def conn(self) -> FakeConn:
        return self.connections[-1]

    async def drain(self):
        """Let handler tasks spawned by NOTIFY callbacks finish."""
        while self.controller._tasks:
            await asyncio.gather(*list(self.controller._tasks))


# --- Burst window ---------------------------------------------------------------------------


async def test_opens_at_boundary_minus_lead_and_closes_after_the_burst_window():
    h = Harness(start=MID)
    await h.controller.initialize_watermark()
    assert await h.at(MID) is False
    boundary = BASE + INTERVAL
    assert await h.at(boundary - LISTEN_LEAD_SECONDS - 1) is False
    assert await h.at(boundary - LISTEN_LEAD_SECONDS) is True
    assert len(h.connections) == 1
    assert await h.at(boundary + LISTEN_BURST_WINDOW_SECONDS) is True
    assert await h.at(boundary + LISTEN_BURST_WINDOW_SECONDS + 1) is False
    assert h.connections[0].closed


async def test_a_notify_keeps_it_open_for_the_quiet_period():
    h = Harness(start=MID)
    await h.controller.initialize_watermark()
    boundary = BASE + INTERVAL
    await h.at(boundary)
    notify_at = boundary + 100
    h.t = notify_at
    h.conn.notify("5:local")
    await h.drain()
    assert h.handled == ["5:local"]
    assert await h.at(boundary + LISTEN_BURST_WINDOW_SECONDS + 1) is True  # window over, quiet not
    assert await h.at(notify_at + LISTEN_QUIET_SECONDS - 1) is True
    assert await h.at(notify_at + LISTEN_QUIET_SECONDS) is False


async def test_closed_between_bursts_when_nothing_is_happening():
    h = Harness(start=MID)
    await h.controller.initialize_watermark()
    for t in range(BASE + LISTEN_BURST_WINDOW_SECONDS + 1, BASE + INTERVAL - LISTEN_LEAD_SECONDS, 30):
        assert await h.at(t) is False
    assert h.connections == []


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


async def test_stays_open_while_watching_with_no_sse_and_no_notify_then_closes_after_quiet():
    """Someone on the detail or settings page: watching is true (cookie activity) but there's
    no SSE stream and, for a while, no NOTIFY. Workers are in live mode, so LISTEN stays open."""
    h = Harness(start=MID)
    await h.controller.initialize_watermark()
    h.watching_flag = True
    assert await h.at(MID) is True
    # Ten minutes of watching, well past every quiet period, across a burst boundary and out.
    for t in range(MID, MID + 600, 10):
        assert await h.at(t) is True
    stopped = MID + 600
    assert await h.at(stopped) is True  # last moment watching is observed true
    h.watching_flag = False
    # Workers may still be in live mode until two of their polls say otherwise.
    assert await h.at(stopped + LISTEN_QUIET_SECONDS - 1) is True
    assert await h.at(stopped + LISTEN_QUIET_SECONDS + 1) is (
        h.controller.in_burst_window(stopped + LISTEN_QUIET_SECONDS + 1)
    )
    assert len(h.connections) == 1  # never dropped and reopened along the way


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
    # Far past every reason to be open except the running handler.
    later = MID + 3 * LISTEN_QUIET_SECONDS
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
    h = Harness(start=MID, max_check_id=10)
    await h.controller.initialize_watermark()
    h.watching_flag = True
    await h.at(MID)
    h.conn.closed = True
    await h.at(MID + 1)
    assert [after for after, _ in h.queries] == [10, 10]


# --- Catch-up mechanics ---------------------------------------------------------------------


async def test_catch_up_replays_in_batches_once_per_pair_in_id_order():
    # 1200 checks alternating over three (target, region) pairs, then the watermark at 0.
    pairs = [(1, "local"), (2, "local"), (1, "eu-west")]
    rows = [(i, *pairs[i % 3]) for i in range(1, 1201)]
    h = Harness(start=MID, rows=rows, max_check_id=0)
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
    async def handle(payload):
        return 77

    h = Harness(start=MID, handle=handle, max_check_id=10)
    await h.controller.initialize_watermark()
    h.watching_flag = True
    await h.at(MID)
    h.conn.notify("3:local")
    await h.drain()
    assert h.controller.watermark == 77


async def test_watermark_starts_at_the_latest_check_so_a_restart_replays_nothing():
    h = Harness(start=MID, rows=[(i, 1, "local") for i in range(1, 51)], max_check_id=50)
    await h.controller.initialize_watermark()
    h.watching_flag = True
    await h.at(MID)
    assert h.handled == []


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
    clock["t"] = BASE + INTERVAL  # a burst boundary: open (and catch up)
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
            # A replayed SSE push is just the same current state again.
            while not queue.empty():
                assert queue.get_nowait()["target"]["id"] == target_id
    finally:
        realtime.unsubscribe(user_id, queue)


async def test_handle_notification_returns_the_handled_check_id(client):
    await client.post("/auth/register", json={"email": "returns-id@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/returns-id"})
    target_id = created.json()["id"]
    check_id = await _insert_check(target_id, region="eu-west")
    with patch("realtime.send_email", new=AsyncMock(return_value=True)), patch(
        "realtime.send_webhook", new=AsyncMock(return_value=True)
    ):
        assert await realtime._handle_notification(f"{target_id}:eu-west") == check_id
        assert await realtime._handle_notification("999999:local") is None


@pytest.fixture(autouse=True)
def _no_module_controller(monkeypatch):
    """Keep the process-wide controller hook from leaking between tests."""
    monkeypatch.setattr(realtime, "_controller", None)
    yield
