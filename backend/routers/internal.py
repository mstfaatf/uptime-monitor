"""Internal endpoints for the worker services, not for browsers or API-key clients.

GET /internal/watching tells a worker whether anyone is currently using the site, so it can
choose between checking continuously and checking on a slow schedule that lets the database go
idle. It answers entirely from in-process memory (realtime.py's SSE subscribers and
activity.py's last cookie-authenticated request) and must never touch the database: a worker
polling it while nobody is around must not be the thing that keeps the database awake.

Authentication is a shared secret in the X-Internal-Secret header, set as INTERNAL_API_SECRET
on the API and on both workers. Not cookie or API-key auth, and hidden from the OpenAPI schema.
The response is a single boolean with no user information. Neither the secret nor the header
value is ever logged.
"""

import hmac

from fastapi import APIRouter, Header, HTTPException, status

import activity
import realtime
from config import settings

router = APIRouter(prefix="/internal", include_in_schema=False)


@router.get("/watching")
async def watching(x_internal_secret: str | None = Header(default=None, alias="X-Internal-Secret")) -> dict:
    """{"watching": true} if an SSE stream is open or a cookie-authenticated request happened
    within WATCHING_WINDOW_SECONDS, else {"watching": false}.

    404 when INTERNAL_API_SECRET isn't configured, so the endpoint is off by default rather than
    open. 401 for a missing or wrong header, compared in constant time.
    """
    expected = settings.INTERNAL_API_SECRET
    if not expected:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    if x_internal_secret is None or not hmac.compare_digest(x_internal_secret.encode(), expected.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    return {"watching": realtime.has_subscribers() or activity.recently_active()}
