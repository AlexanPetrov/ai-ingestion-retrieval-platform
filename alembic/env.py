"""Alembic migration environment for the async PostgreSQL database."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from ai_ingestion_retrieval_platform.core.config import Settings
from ai_ingestion_retrieval_platform.persistence.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_database_url() -> str:
    """Return the async PostgreSQL URL from application settings."""
    settings = Settings()

    if not settings.database_enabled:
        raise RuntimeError("DATABASE_ENABLED must be true to run database migrations")

    return settings.database_url


def run_migrations_offline() -> None:
    """Run migrations without creating a live database connection."""
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={
            "paramstyle": "named",
        },
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations using an established synchronous connection wrapper."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create a temporary async engine and run online migrations."""
    configuration = config.get_section(
        config.config_ini_section,
    )

    if configuration is None:
        raise RuntimeError(
            f"Alembic configuration section {config.config_ini_section!r} was not found"
        )

    configuration["sqlalchemy.url"] = get_database_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)

    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations against a live PostgreSQL database."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
