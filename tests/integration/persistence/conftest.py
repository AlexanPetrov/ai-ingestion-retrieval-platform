"""Fixtures for destructive PostgreSQL persistence integration tests."""

import os
import subprocess
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
)

from ai_ingestion_retrieval_platform.core.config import Settings
from ai_ingestion_retrieval_platform.persistence.engine import (
    close_database,
    create_database_engine,
    get_session_factory,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]

TEST_DATABASE_ENV = "TEST_DATABASE_URL"


def _require_safe_test_database_url() -> str:
    """Return an explicitly configured, clearly named test database URL."""
    database_url = os.getenv(TEST_DATABASE_ENV)

    if not database_url:
        pytest.skip(
            f"{TEST_DATABASE_ENV} is not configured; "
            "PostgreSQL integration tests are skipped"
        )

    parsed_url = make_url(database_url)

    if parsed_url.drivername != "postgresql+asyncpg":
        pytest.fail(
            f"{TEST_DATABASE_ENV} must use the postgresql+asyncpg SQLAlchemy driver"
        )

    database_name = parsed_url.database

    if not database_name:
        pytest.fail(f"{TEST_DATABASE_ENV} must include a database name")

    normalized_parts = database_name.lower().replace("-", "_").split("_")

    if "test" not in normalized_parts:
        pytest.fail(
            "Refusing destructive integration tests because the database "
            f"name {database_name!r} does not contain a separate 'test' "
            "component"
        )

    return database_url


@pytest.fixture(scope="session")
def migrated_test_database() -> str:
    """Run Alembic migrations against the dedicated PostgreSQL test DB."""
    database_url = _require_safe_test_database_url()

    environment = os.environ.copy()
    environment["DATABASE_ENABLED"] = "true"
    environment["DATABASE_URL"] = database_url

    subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "head",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
    )

    return database_url


@pytest_asyncio.fixture
async def postgres_engine(
    migrated_test_database: str,
) -> AsyncGenerator[AsyncEngine]:
    """Create an application-configured engine for the test database."""
    settings = Settings(
        rate_limit_enabled=False,
        database_enabled=True,
        database_url=migrated_test_database,
        database_pool_size=5,
        database_pool_timeout_seconds=5.0,
        database_connect_timeout_seconds=5.0,
        database_echo_sql=False,
    )

    engine = create_database_engine(settings)

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

        yield engine

    finally:
        await close_database(engine)


async def _truncate_persistence_tables(
    engine: AsyncEngine,
) -> None:
    """Remove all application persistence rows from the dedicated test DB."""
    async with engine.begin() as connection:
        await connection.execute(
            text("TRUNCATE TABLE parsed_document, ingestion_record, source CASCADE")
        )


@pytest_asyncio.fixture(autouse=True)
async def clean_postgres_database(
    postgres_engine: AsyncEngine,
) -> AsyncGenerator[None]:
    """Give every PostgreSQL integration test an empty persistence schema."""
    await _truncate_persistence_tables(postgres_engine)

    try:
        yield

    finally:
        await _truncate_persistence_tables(postgres_engine)


@pytest_asyncio.fixture
async def db_session(
    postgres_engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession]:
    """Yield one real AsyncSession connected to the PostgreSQL test DB."""
    session_factory = get_session_factory(postgres_engine)

    async with session_factory() as session:
        yield session
