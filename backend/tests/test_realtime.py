"""Tests for realtime.py's pub/sub — the piece that guarantees a user only ever receives push
updates for their own targets (Phase 1 prompt 1.5). The LISTEN/reconnect loop itself
(run_listener) isn't exercised here — it needs a live Postgres LISTEN connection and is
covered by manual verification against the real stack instead."""

import asyncio

import realtime


async def test_publish_only_reaches_the_subscribed_user():
    """The core ownership guarantee: publishing to user A's id must never reach user B's
    queue, even if both are subscribed at the same time."""
    queue_a = realtime.subscribe(1001)
    queue_b = realtime.subscribe(1002)
    try:
        realtime._publish(1001, {"type": "check_update", "target": {"id": 1}})

        assert queue_a.get_nowait() == {"type": "check_update", "target": {"id": 1}}
        assert queue_b.empty()
    finally:
        realtime.unsubscribe(1001, queue_a)
        realtime.unsubscribe(1002, queue_b)


async def test_publish_with_no_subscribers_is_a_harmless_noop():
    realtime._publish(999999, {"type": "check_update", "target": {"id": 1}})  # must not raise


async def test_unsubscribe_stops_further_delivery():
    queue = realtime.subscribe(2001)
    realtime.unsubscribe(2001, queue)

    realtime._publish(2001, {"type": "check_update", "target": {"id": 1}})

    assert queue.empty()
    assert 2001 not in realtime._subscribers  # the now-empty entry is cleaned up, not leaked


async def test_a_user_can_have_multiple_connections_and_both_receive_the_update():
    queue_1 = realtime.subscribe(3001)
    queue_2 = realtime.subscribe(3001)
    try:
        realtime._publish(3001, {"type": "check_update", "target": {"id": 1}})

        assert not queue_1.empty()
        assert not queue_2.empty()
    finally:
        realtime.unsubscribe(3001, queue_1)
        realtime.unsubscribe(3001, queue_2)


async def test_handle_notification_resolves_owner_and_publishes_full_status_payload(client):
    """End-to-end against the real test DB: a real target + check row, notified by id, must
    reach only its actual owner's queue with the same shape GET /targets/status returns."""
    register = await client.post("/auth/register", json={"email": "realtime@example.com", "password": "pw"})
    user_id = register.json()["id"]
    created = await client.post("/targets", json={"url": "https://example.com/realtime"})
    target_id = created.json()["id"]

    other_queue = realtime.subscribe(user_id + 999999)  # some other, unrelated user
    my_queue = realtime.subscribe(user_id)
    try:
        await realtime._handle_notification(f"{target_id}:local")

        assert other_queue.empty()
        message = my_queue.get_nowait()
        assert message["type"] == "check_update"
        assert message["region"] == "local"
        assert message["target"]["id"] == target_id
        assert message["target"]["latest_checks"] == {}  # no check inserted yet, in any region
    finally:
        realtime.unsubscribe(user_id, my_queue)
        realtime.unsubscribe(user_id + 999999, other_queue)


async def test_handle_notification_ignores_payload_missing_region():
    await realtime._handle_notification("not-an-integer")  # no ":region" suffix — must not raise


async def test_handle_notification_ignores_non_numeric_target_id():
    await realtime._handle_notification("not-an-integer:local")  # must not raise


async def test_handle_notification_for_a_deleted_target_is_a_noop(client):
    """A target can be deleted between the NOTIFY firing and this handler running — there's
    no owner left to push to, and this must not crash the listener."""
    await client.post("/auth/register", json={"email": "vanished@example.com", "password": "pw"})
    created = await client.post("/targets", json={"url": "https://example.com/vanishing"})
    target_id = created.json()["id"]
    await client.delete(f"/targets/{target_id}")

    await realtime._handle_notification(f"{target_id}:local")  # must not raise
