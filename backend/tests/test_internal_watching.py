"""GET /internal/watching: shared-secret auth, what counts as watching, and no database access."""

import asyncpg
import pytest
from sqlalchemy import event

import activity
import realtime
from config import settings
from database import engine

SECRET = "test-internal-secret"
HEADERS = {"X-Internal-Secret": SECRET}


@pytest.fixture(autouse=True)
def _internal_secret_and_clean_activity(monkeypatch):
    """Configure the secret and start every test with no recorded activity. Other test files
    make cookie-authenticated requests, and activity.py's state is process-wide."""
    monkeypatch.setattr(settings, "INTERNAL_API_SECRET", SECRET)
    activity.reset()
    yield
    activity.reset()


async def _watching(client) -> bool:
    response = await client.get("/internal/watching", headers=HEADERS)
    assert response.status_code == 200
    return response.json()["watching"]


async def _register(client, email: str) -> None:
    response = await client.post("/auth/register", json={"email": email, "password": "pw-123456"})
    assert response.status_code in (200, 201), response.text


@pytest.mark.parametrize("value", [None, ""])
async def test_returns_404_when_secret_is_not_configured(client, monkeypatch, value):
    monkeypatch.setattr(settings, "INTERNAL_API_SECRET", value)
    response = await client.get("/internal/watching", headers=HEADERS)
    assert response.status_code == 404


async def test_missing_header_is_401(client):
    response = await client.get("/internal/watching")
    assert response.status_code == 401


async def test_wrong_header_is_401(client):
    response = await client.get("/internal/watching", headers={"X-Internal-Secret": "not-the-secret"})
    assert response.status_code == 401
    # A prefix of the real secret isn't accepted either.
    response = await client.get("/internal/watching", headers={"X-Internal-Secret": SECRET[:-1]})
    assert response.status_code == 401


async def test_correct_header_returns_only_the_boolean(client):
    response = await client.get("/internal/watching", headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {"watching": False}


async def test_endpoint_is_not_in_the_openapi_schema(client):
    schema = (await client.get("/openapi.json")).json()
    assert not any(path.startswith("/internal") for path in schema["paths"])


async def test_an_sse_subscriber_makes_it_true(client):
    queue = realtime.subscribe(424242)
    try:
        assert await _watching(client) is True
    finally:
        realtime.unsubscribe(424242, queue)
    assert await _watching(client) is False


async def test_a_cookie_request_makes_it_true_until_the_window_expires(client, monkeypatch):
    await _register(client, "watching-cookie@example.com")
    # Registering issues a cookie but isn't itself a cookie-authenticated request.
    assert await _watching(client) is False

    now = 1_000_000.0
    monkeypatch.setattr(activity, "_clock", lambda: now)
    assert (await client.get("/auth/me")).status_code == 200
    assert await _watching(client) is True

    monkeypatch.setattr(activity, "_clock", lambda: now + settings.WATCHING_WINDOW_SECONDS - 1)
    assert await _watching(client) is True

    monkeypatch.setattr(activity, "_clock", lambda: now + settings.WATCHING_WINDOW_SECONDS)
    assert await _watching(client) is False


async def test_unauthenticated_and_failed_requests_leave_it_false(client):
    await _register(client, "watching-failed@example.com")
    client.cookies.clear()

    bad_login = await client.post("/auth/login", json={"email": "watching-failed@example.com", "password": "wrong"})
    assert bad_login.status_code == 401
    assert (await client.get("/auth/me")).status_code == 401  # no cookie at all
    client.cookies.set(settings.COOKIE_NAME, "not-a-real-token")
    assert (await client.get("/auth/me")).status_code == 401  # invalid cookie
    client.cookies.clear()

    assert await _watching(client) is False


async def test_a_successful_login_alone_does_not_count(client):
    await _register(client, "watching-login@example.com")
    client.cookies.clear()
    login = await client.post("/auth/login", json={"email": "watching-login@example.com", "password": "pw-123456"})
    assert login.status_code == 200
    assert await _watching(client) is False


async def test_an_api_key_request_leaves_it_false(client):
    await _register(client, "watching-key@example.com")
    created = await client.post("/api-keys", json={"name": "poller", "scope": "read"})
    assert created.status_code in (200, 201), created.text
    raw_key = created.json()["key"]

    # Creating the key was itself a cookie request; start clean, and drop the cookie so only
    # the key authenticates what follows.
    activity.reset()
    client.cookies.clear()

    bearer = {"Authorization": f"Bearer {raw_key}"}
    assert (await client.get("/targets", headers=bearer)).status_code == 200
    assert (await client.get("/targets", headers=bearer)).status_code == 200
    assert await _watching(client) is False


async def test_makes_no_database_calls(client, monkeypatch):
    """Counts every connection the app's engine opens and every statement it runs, and makes any
    raw asyncpg connect fail, while calling the endpoint in each of its states."""
    activity_counts = {"connects": 0, "statements": 0}

    def on_connect(*_args):
        activity_counts["connects"] += 1

    def on_statement(*_args):
        activity_counts["statements"] += 1

    async def no_raw_connections(*_args, **_kwargs):
        raise AssertionError("GET /internal/watching opened a raw asyncpg connection")

    event.listen(engine.sync_engine, "connect", on_connect)
    event.listen(engine.sync_engine, "before_cursor_execute", on_statement)
    try:
        # Sanity check: the counters do see a request that uses the database.
        await _register(client, "watching-nodb@example.com")
        assert (await client.get("/auth/me")).status_code == 200
        assert activity_counts["connects"] > 0 and activity_counts["statements"] > 0

        activity_counts.update(connects=0, statements=0)
        monkeypatch.setattr(asyncpg, "connect", no_raw_connections)
        monkeypatch.setattr(realtime.asyncpg, "connect", no_raw_connections)

        assert await _watching(client) is True  # recent cookie activity
        activity.reset()
        assert await _watching(client) is False  # nothing
        queue = realtime.subscribe(515151)
        try:
            assert await _watching(client) is True  # open stream
        finally:
            realtime.unsubscribe(515151, queue)
        assert (await client.get("/internal/watching")).status_code == 401
        monkeypatch.setattr(settings, "INTERNAL_API_SECRET", None)
        assert (await client.get("/internal/watching", headers=HEADERS)).status_code == 404
    finally:
        event.remove(engine.sync_engine, "connect", on_connect)
        event.remove(engine.sync_engine, "before_cursor_execute", on_statement)

    assert activity_counts == {"connects": 0, "statements": 0}
