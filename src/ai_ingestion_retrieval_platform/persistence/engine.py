"""Async SQLAlchemy engine and session-factory configuration."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ai_ingestion_retrieval_platform.core.config import Settings


def create_database_engine(settings: Settings) -> AsyncEngine:
    """Create the application-scoped asynchronous PostgreSQL engine.

    Engine creation configures the connection pool but does not immediately
    establish a database connection. Connections are checked out lazily when
    database work is performed.

    Args:
        settings: Runtime database configuration.

    Returns:
        Configured AsyncEngine.

    Raises:
        ValueError: If the configured database URL is empty.
    """
    database_url = settings.database_url.strip()

    if not database_url:
        raise ValueError("database_url is required when persistence is enabled")

    return create_async_engine(
        database_url,
        echo=settings.database_echo_sql,
        pool_size=settings.database_pool_size,
        max_overflow=0,
        pool_timeout=settings.database_pool_timeout_seconds,
        pool_pre_ping=True,
        connect_args={
            "timeout": settings.database_connect_timeout_seconds,
            "server_settings": {
                "application_name": ("ai-ingestion-retrieval-platform"),
            },
        },
    )


def get_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Create the application-scoped asynchronous session factory.

    Each call to the returned factory creates an independent AsyncSession.
    AsyncSession instances must not be shared between concurrent asyncio tasks.

    Args:
        engine: Application-scoped asynchronous database engine.

    Returns:
        Reusable asynchronous session factory.
    """
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def close_database(engine: AsyncEngine) -> None:
    """Dispose the database engine and close pooled connections."""
    await engine.dispose()
