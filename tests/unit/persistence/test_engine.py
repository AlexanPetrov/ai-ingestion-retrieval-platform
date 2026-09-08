"""Unit tests for async PostgreSQL engine configuration."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ai_ingestion_retrieval_platform.core.config import Settings
from ai_ingestion_retrieval_platform.persistence.engine import (
    close_database,
    create_database_engine,
    get_session_factory,
)


def test_create_database_engine_rejects_empty_url() -> None:
    settings = Settings(
        database_enabled=False,
        database_url=" ",
    )

    with pytest.raises(ValueError) as exc_info:
        create_database_engine(settings)

    assert str(exc_info.value) == (
        "database_url is required when persistence is enabled"
    )


@pytest.mark.asyncio
async def test_create_engine_and_session_factory() -> None:
    settings = Settings(
        database_enabled=True,
        database_url=(
            "postgresql+asyncpg://user:password@localhost:5432/test_database"
        ),
        database_pool_size=3,
        database_pool_timeout_seconds=4.0,
        database_connect_timeout_seconds=6.0,
        database_echo_sql=False,
    )

    engine = create_database_engine(settings)

    try:
        assert engine.url.drivername == "postgresql+asyncpg"
        assert engine.url.database == "test_database"

        session_factory = get_session_factory(engine)
        session = session_factory()

        try:
            assert isinstance(session, AsyncSession)

            assert session.sync_session.expire_on_commit is False
            assert session.sync_session.autoflush is False

        finally:
            await session.close()

    finally:
        await close_database(engine)
