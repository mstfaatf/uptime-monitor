"""FastAPI application entrypoint."""

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

import realtime
from config import settings
from rate_limit import limiter
from routers import auth, tags, targets


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run the Postgres LISTEN loop for the whole app lifetime, so realtime.py can push check
    updates to connected SSE clients as soon as the worker commits them."""
    listener_task = asyncio.create_task(realtime.run_listener())
    try:
        yield
    finally:
        listener_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await listener_task


app = FastAPI(title="Uptime Monitor API", lifespan=lifespan)

app.state.limiter = limiter


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """429 with a clear, specific message instead of slowapi's generic default."""
    return JSONResponse(
        status_code=429,
        content={"detail": f"Too many requests — rate limit is {exc.detail}. Please try again shortly."},
    )


app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Minimal, standard hardening headers on every response. This API only ever serves JSON
    (the frontend is a separate app on Vercel), so there's no HTML/script surface here for a
    full CSP to matter — just the baseline headers relevant to any HTTP API:
    - X-Content-Type-Options: stops a browser from MIME-sniffing a JSON response as something
      else (e.g. HTML) and executing it.
    - X-Frame-Options: DENY — this API should never be framed by anything.
    - Referrer-Policy: don't leak the full request URL (which can carry auth-adjacent query
      params) to a cross-origin destination via the Referer header.
    """
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


app.include_router(auth.router)
app.include_router(targets.router)
app.include_router(tags.router)


@app.get("/health")
async def health():
    """Health check for load balancers and orchestration."""
    return {"status": "ok"}
