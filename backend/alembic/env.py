"""Alembic environment: uses DATABASE_URL (sync driver for migrations)."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.orm import sessionmaker

from database import Base
from models import (  # noqa: F401 — register with Base.metadata
    AlertHistory,
    Check,
    PasswordResetToken,
    Target,
    TargetRegionSchedule,
    User,
)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Sync URL for Alembic: app uses postgresql+asyncpg, migrations use postgresql (psycopg2).
#
# MIGRATION_DATABASE_URL takes priority over DATABASE_URL when set. This matters in production
# (Neon): DATABASE_URL there is asyncpg-shaped (`?ssl=require`, for the running app's async
# engine) and psycopg2 doesn't understand that query param (`invalid dsn: invalid connection
# option "ssl"`). MIGRATION_DATABASE_URL instead holds Neon's native libpq-shaped string
# (`?sslmode=require&channel_binding=require`), which psycopg2 understands natively and
# asyncpg does not — the two drivers need incompatible query strings, so one URL can't serve
# both. Locally, MIGRATION_DATABASE_URL is never set, so this falls back to the previous
# DATABASE_URL-derived behavior unchanged.
database_url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/uptime"
)
if database_url.startswith("postgresql+asyncpg"):
    database_url = database_url.replace("postgresql+asyncpg", "postgresql", 1)
config.set_main_option("sqlalchemy.url", database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (SQL only, no DB connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect to DB)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
