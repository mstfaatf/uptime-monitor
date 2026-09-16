"""POST /targets/{id}/pause and /resume, plus check_interval_seconds validation (Phase 6,
prompt 6.3). What actually happens to a paused/resumed target's scheduling is worker-owned and
tested in worker/tests/test_scheduling.py (the claim query excludes paused targets;
reschedule_target respects a custom interval) — this file covers the API contract: the
paused/check_interval_seconds fields themselves, ownership enforcement, and that /resume
genuinely forces target_region_schedule.next_check_at to "now," not just flips a flag.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from database import engine


async def _register(client, email="pauser@example.com"):
    resp = await client.post("/auth/register", json={"email": email, "password": "pw"})
    assert resp.status_code == 200


async def _create_target(client, url="https://example.com/pausable", **extra):
    resp = await client.post("/targets", json={"url": url, **extra})
    assert resp.status_code == 201
    return resp.json()


async def _insert_schedule_row(target_id: int, region: str, next_check_at) -> None:
    """Simulate a target that a real worker has already checked at least once (backend never
    creates these rows itself — see target_region_schedule.py's docstring)."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO target_region_schedule (target_id, region, next_check_at, consecutive_failures)
                VALUES (:target_id, :region, :next_check_at, 0)
                """
            ),
            {"target_id": target_id, "region": region, "next_check_at": next_check_at},
        )


async def _schedule_next_check_at(target_id: int, region: str):
    async with engine.begin() as conn:
        result = await conn.execute(
            text("SELECT next_check_at FROM target_region_schedule WHERE target_id = :target_id AND region = :region"),
            {"target_id": target_id, "region": region},
        )
        row = result.first()
        return row[0] if row else None


async def test_pause_sets_paused_true(client):
    await _register(client)
    target = await _create_target(client)
    assert target["paused"] is False

    resp = await client.post(f"/targets/{target['id']}/pause")
    assert resp.status_code == 200
    assert resp.json()["paused"] is True


async def test_pause_is_idempotent(client):
    await _register(client)
    target = await _create_target(client)

    first = await client.post(f"/targets/{target['id']}/pause")
    second = await client.post(f"/targets/{target['id']}/pause")
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["paused"] is True


async def test_resume_sets_paused_false(client):
    await _register(client)
    target = await _create_target(client)
    await client.post(f"/targets/{target['id']}/pause")

    resp = await client.post(f"/targets/{target['id']}/resume")
    assert resp.status_code == 200
    assert resp.json()["paused"] is False


async def test_resume_forces_next_check_at_to_now_across_regions(client):
    """The real point of /resume: a target paused for a long time (or one whose schedule was
    left far in the future by backoff) must be picked up immediately, not wait out whatever
    next_check_at a real worker last wrote — proven here by seeding a stale future timestamp in
    two regions and confirming both are reset to ~now by a single /resume call."""
    await _register(client)
    target = await _create_target(client)
    far_future = datetime.now(timezone.utc) + timedelta(hours=1)
    await _insert_schedule_row(target["id"], "us-east", far_future)
    await _insert_schedule_row(target["id"], "eu-west", far_future)

    resp = await client.post(f"/targets/{target['id']}/resume")
    assert resp.status_code == 200

    for region in ("us-east", "eu-west"):
        next_check_at = await _schedule_next_check_at(target["id"], region)
        assert next_check_at is not None
        assert next_check_at < far_future
        assert (datetime.now(timezone.utc) - next_check_at).total_seconds() < 10


async def test_resume_on_a_never_paused_target_still_forces_recheck(client):
    """Resume is safe (and still useful) to call on a target that isn't currently paused —
    e.g. "check this right now" — rather than requiring pause-then-resume as a ritual."""
    await _register(client)
    target = await _create_target(client)
    far_future = datetime.now(timezone.utc) + timedelta(hours=1)
    await _insert_schedule_row(target["id"], "local", far_future)

    resp = await client.post(f"/targets/{target['id']}/resume")
    assert resp.status_code == 200
    assert resp.json()["paused"] is False

    next_check_at = await _schedule_next_check_at(target["id"], "local")
    assert next_check_at < far_future


async def test_pause_and_resume_are_ownership_enforced(client):
    await _register(client, "pause-owner@example.com")
    target = await _create_target(client, "https://example.com/owner-only")
    await client.post("/auth/logout")

    await _register(client, "pause-intruder@example.com")
    pause_resp = await client.post(f"/targets/{target['id']}/pause")
    resume_resp = await client.post(f"/targets/{target['id']}/resume")
    # 404, not 403 — same "can't confirm the id even exists" pattern as every other
    # target-scoped endpoint.
    assert pause_resp.status_code == 404
    assert resume_resp.status_code == 404


async def test_pause_and_resume_require_authentication(client):
    await _register(client)
    target = await _create_target(client)
    await client.post("/auth/logout")

    assert (await client.post(f"/targets/{target['id']}/pause")).status_code == 401
    assert (await client.post(f"/targets/{target['id']}/resume")).status_code == 401


async def test_create_target_with_check_interval_seconds(client):
    await _register(client)
    target = await _create_target(client, "https://example.com/fast-check", check_interval_seconds=60)
    assert target["check_interval_seconds"] == 60


async def test_create_target_with_too_low_check_interval_rejected(client):
    await _register(client)
    resp = await client.post(
        "/targets", json={"url": "https://example.com/too-fast", "check_interval_seconds": 5}
    )
    assert resp.status_code == 400


async def test_patch_can_set_and_clear_check_interval_seconds(client):
    await _register(client)
    target = await _create_target(client)

    set_resp = await client.patch(f"/targets/{target['id']}", json={"check_interval_seconds": 120})
    assert set_resp.status_code == 200
    assert set_resp.json()["check_interval_seconds"] == 120

    clear_resp = await client.patch(f"/targets/{target['id']}", json={"check_interval_seconds": None})
    assert clear_resp.status_code == 200
    assert clear_resp.json()["check_interval_seconds"] is None


async def test_patch_with_too_low_check_interval_rejected(client):
    await _register(client)
    target = await _create_target(client)

    resp = await client.patch(f"/targets/{target['id']}", json={"check_interval_seconds": 10})
    assert resp.status_code == 400
