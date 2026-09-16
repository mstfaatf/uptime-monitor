"""Shared pytest fixtures: test-database setup/isolation, HTTP client, rate-limiter reset.

Runs against a real Postgres database (a dedicated "<name>_test" database on the same server
as DATABASE_URL, not the dev database) rather than SQLite — the schema uses Postgres-specific
DDL (postgresql_ops index on checks.checked_at) and the app talks to Postgres via asyncpg in
production, so testing against SQLite would exercise a different SQL dialect than what actually
ships. The tradeoff is tests need a reachable Postgres server; see backend/README.md for how to
point them at one.
"""

import os

# Must happen before any app module is imported: config.py builds its module-level Settings()
# singleton at import time (raising if JWT_SECRET is unset), and database.py builds its async
# engine from settings.DATABASE_URL at import time.
os.environ.setdefault("JWT_SECRET", "pytest-secret-do-not-use-in-production")
os.environ.setdefault("ENVIRONMENT", "development")
# Not a real secret — this suite never encrypts anything meaningful, it just needs *a*
# validly-shaped Fernet key so security/crypto.py's module-level Fernet(...) construction
# doesn't raise. Same fail-fast-at-import-time reasoning as JWT_SECRET above.
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "rb6dazPc4DmaBkvWvYNyP6LnsEdNoJCNeUbyTxwvY7o=")


def _test_database_url() -> str:
    """
    Use TEST_DATABASE_URL if set; otherwise derive one from DATABASE_URL by pointing at a
    "_test"-suffixed database on the same server. Either way, tests never touch the same
    database as local dev / docker-compose's `db` service.
    """
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    base = os.environ.get("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/uptime")
    prefix, _, dbname = base.rpartition("/")
    if dbname.endswith("_test"):
        return base
    return f"{prefix}/{dbname}_test"


os.environ["DATABASE_URL"] = _test_database_url()

from pathlib import Path  # noqa: E402

import psycopg2  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _sync_url(url: str) -> str:
    """Alembic/psycopg2 need the sync driver; the app config uses the async one."""
    if url.startswith("postgresql+asyncpg"):
        return url.replace("postgresql+asyncpg", "postgresql", 1)
    return url


def _ensure_database_exists(sync_url: str) -> None:
    """Postgres has no `CREATE DATABASE IF NOT EXISTS`, so check pg_database first."""
    prefix, _, dbname = sync_url.rpartition("/")
    maintenance_url = f"{prefix}/postgres"
    conn = psycopg2.connect(maintenance_url)
    conn.autocommit = True  # CREATE DATABASE can't run inside a transaction block
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{dbname}"')
    finally:
        conn.close()


def _run_migrations() -> None:
    """Migrate the test DB with the same Alembic revisions used in prod — catches drift
    between the models and the migration files that a hand-created schema would miss."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def _test_database():
    """Create the test database (if missing) and migrate it to head, once per test session."""
    _ensure_database_exists(_sync_url(os.environ["DATABASE_URL"]))
    _run_migrations()
    yield


# Import app code only after DATABASE_URL/JWT_SECRET are set above.
from database import engine  # noqa: E402
from main import app  # noqa: E402
from rate_limit import limiter  # noqa: E402


@pytest.fixture(autouse=True)
async def _clean_tables():
    """Isolate tests from each other: wipe all app tables before every test."""
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE users, targets, checks RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """slowapi's limiter is a module-level, in-memory singleton shared across the whole test
    session — without resetting it, one test's requests would count toward another test's
    rate limit, making unrelated tests fail depending on run order."""
    limiter.reset()
    yield


@pytest.fixture
async def client():
    """httpx.AsyncClient wired directly to the FastAPI app (ASGI, in-process) — no real
    network, no separate server process needed. Cookies persist across requests made with
    the same client instance, same as a browser session."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
