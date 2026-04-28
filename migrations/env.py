"""Alembic environment.

Migrations are hand-written and run synchronously via psycopg (the sync driver),
even though the application uses asyncpg at runtime. Mixing sync and async in
Alembic adds nothing here — synchronous DDL is simpler.

The DB URL is resolved from the ``DATABASE_URL_SYNC`` env var when set,
falling back to the asyncpg URL with the driver swapped to plain ``psycopg``.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name:
    fileConfig(config.config_file_name)


def _resolve_db_url() -> str:
    sync_url = os.getenv("DATABASE_URL_SYNC")
    if sync_url:
        return sync_url
    async_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://sentinel:sentinel@localhost:15432/sentinelrag",
    )
    return async_url.replace("+asyncpg", "+psycopg").replace(
        "postgresql://", "postgresql+psycopg://", 1
    )


config.set_main_option("sqlalchemy.url", _resolve_db_url())

# We do NOT register MetaData here. Hand-written migrations don't need it,
# and pinning a target_metadata locks us into a coupling that drifts.
target_metadata = None


def run_migrations_offline() -> None:
    """Generate SQL without connecting to a DB (for `alembic upgrade --sql`)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the DB and run migrations."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
