"""Async SQLAlchemy engine and session management."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from config import settings

# application_name tags request-path connections in pg_stat_activity, separately from the
# LISTEN connection ("api-listen", realtime.py) and the workers ("worker-<region>").
REQUEST_APPLICATION_NAME = "api"

# NullPool: every session opens its own connection and really closes it when the session
# ends, instead of parking it in a pool. SQLAlchemy's default QueuePool has no idle timeout,
# so connections it kept around stayed open to the database indefinitely between requests.
# The production database scales to zero only when the app holds no connections, so a pool
# that never lets go keeps it awake. The cost is one connection setup per request, made cheap
# in production by the database provider's own server-side pooler, which is what DATABASE_URL
# points at there.
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    poolclass=NullPool,
    connect_args={"server_settings": {"application_name": REQUEST_APPLICATION_NAME}},
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    """Dependency that yields an async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
