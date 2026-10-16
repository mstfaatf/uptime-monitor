"""GET /targets/stream: holds no database connection while streaming, and per-user filtering.

httpx's ASGITransport buffers a whole response before returning it, so it can't be used for an
endless SSE stream. These tests drive the ASGI app directly instead: send the request, read
body chunks as they arrive, then send http.disconnect to end the stream.

The "no connection held" check queries pg_stat_activity from a separate, differently-named
connection while a stream is open. Request-path connections are tagged application_name="api"
(database.py), so any row with that name during the stream is a connection the app is holding
on the stream's behalf.
"""

import asyncio
import contextlib
import json

import asyncpg

import realtime
from config import settings
from database import REQUEST_APPLICATION_NAME
from main import app


class _OpenStream:
    """A /targets/stream request in flight against the ASGI app."""

    def __init__(self, cookie: str | None):
        headers = [(b"host", b"testserver")]
        if cookie:
            headers.append((b"cookie", cookie.encode()))
        self._scope = {
            "type": "http",
            # spec_version 2.3: Starlette's StreamingResponse then watches receive() for
            # http.disconnect and stops the stream as soon as it arrives.
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/targets/stream",
            "raw_path": b"/targets/stream",
            "query_string": b"",
            "root_path": "",
            "headers": headers,
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }
        self._messages: asyncio.Queue = asyncio.Queue()
        self._disconnect = asyncio.Event()
        self._request_sent = False
        self._task: asyncio.Task | None = None

    async def _receive(self):
        if not self._request_sent:
            self._request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await self._disconnect.wait()
        return {"type": "http.disconnect"}

    async def _send(self, message):
        await self._messages.put(message)

    async def start(self) -> int:
        """Start the request and return the response status code."""
        self._task = asyncio.create_task(app(self._scope, self._receive, self._send))
        start = await asyncio.wait_for(self._messages.get(), timeout=5)
        assert start["type"] == "http.response.start"
        return start["status"]

    async def next_chunk(self, timeout: float = 5) -> str:
        while True:
            message = await asyncio.wait_for(self._messages.get(), timeout=timeout)
            if message["type"] == "http.response.body" and message.get("body"):
                return message["body"].decode()

    async def close(self) -> None:
        self._disconnect.set()
        if self._task is None:
            return
        try:
            await asyncio.wait_for(self._task, timeout=5)
        except asyncio.TimeoutError:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task


async def _register(client, email: str) -> tuple[int, str]:
    """Register a user with a fresh cookie jar; return (user_id, Cookie header value)."""
    client.cookies.clear()
    response = await client.post("/auth/register", json={"email": email, "password": "pw-123456"})
    assert response.status_code in (200, 201), response.text
    cookie = f"{settings.COOKIE_NAME}={client.cookies.get(settings.COOKIE_NAME)}"
    client.cookies.clear()
    return response.json()["id"], cookie


async def _app_connections() -> list[asyncpg.Record]:
    """Every request-path connection the app currently has open to the test database."""
    probe = await asyncpg.connect(
        settings.asyncpg_database_url, server_settings={"application_name": "pytest-probe"}
    )
    try:
        return await probe.fetch(
            "SELECT pid, state, application_name FROM pg_stat_activity "
            "WHERE datname = current_database() AND application_name = $1",
            REQUEST_APPLICATION_NAME,
        )
    finally:
        await probe.close()


async def test_open_stream_holds_no_database_connection(client):
    _, cookie = await _register(client, "sse-noconn@example.com")
    stream = _OpenStream(cookie)
    try:
        assert await stream.start() == 200
        assert await stream.next_chunk() == ": connected\n\n"
        # The stream is now open and idle, waiting on its queue.
        assert await _app_connections() == []
    finally:
        await stream.close()


async def test_stream_subscribes_while_open_and_unsubscribes_on_disconnect(client):
    user_id, cookie = await _register(client, "sse-sub@example.com")
    stream = _OpenStream(cookie)
    try:
        await stream.start()
        await stream.next_chunk()
        assert user_id in realtime._subscribers
    finally:
        await stream.close()
    assert user_id not in realtime._subscribers


async def test_stream_delivers_only_the_owners_events(client):
    user_a, cookie_a = await _register(client, "sse-a@example.com")
    user_b, cookie_b = await _register(client, "sse-b@example.com")
    stream_a, stream_b = _OpenStream(cookie_a), _OpenStream(cookie_b)
    try:
        await stream_a.start()
        await stream_b.start()
        assert await stream_a.next_chunk() == ": connected\n\n"
        assert await stream_b.next_chunk() == ": connected\n\n"

        payload = {"type": "check_update", "region": "local", "target": {"id": 123, "user": "a"}}
        realtime._publish(user_a, payload)

        chunk = await stream_a.next_chunk()
        assert chunk.startswith("data: ")
        assert json.loads(chunk[len("data: "):].strip()) == payload

        # B's stream gets nothing (the next keep-alive is 15s away, so silence here means
        # nothing was forwarded, not that a keep-alive happened to land).
        try:
            leaked = await stream_b.next_chunk(timeout=1)
        except asyncio.TimeoutError:
            leaked = None
        assert leaked is None
        assert await _app_connections() == []
    finally:
        await stream_a.close()
        await stream_b.close()
    assert user_a not in realtime._subscribers and user_b not in realtime._subscribers


async def test_stream_requires_authentication(client):
    client.cookies.clear()
    response = await client.get("/targets/stream")
    assert response.status_code == 401


async def test_stream_rejects_an_invalid_session_cookie(client):
    client.cookies.clear()
    client.cookies.set(settings.COOKIE_NAME, "not-a-real-token")
    response = await client.get("/targets/stream")
    client.cookies.clear()
    assert response.status_code == 401
