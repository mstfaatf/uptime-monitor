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
from routers import auth, targets


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

app.include_router(auth.router)
app.include_router(targets.router)


@app.get("/health")
async def health():
    """Health check for load balancers and orchestration."""
    return {"status": "ok"}
