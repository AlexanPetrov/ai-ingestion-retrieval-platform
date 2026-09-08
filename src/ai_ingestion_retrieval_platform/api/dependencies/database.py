"""FastAPI dependencies for database session access."""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)


def get_database_session_factory(
    request: Request,
) -> async_sessionmaker[AsyncSession]:
    """Retrieve the application database session factory.

    The session factory is created during application startup and stored on
    app.state. It is safe to reuse for creating independent AsyncSession
    instances.

    Args:
        request: Current FastAPI request.

    Returns:
        Application-scoped async session factory.

    Raises:
        RuntimeError: If database persistence is not initialized.
    """
    session_factory = getattr(
        request.app.state,
        "db_session_factory",
        None,
    )

    if session_factory is None:
        raise HTTPException(
            status_code=503,
            detail="Persistence is not enabled",
        )

    return session_factory


async def get_database_session(
    session_factory: Annotated[
        async_sessionmaker[AsyncSession],
        Depends(get_database_session_factory),
    ],
) -> AsyncGenerator[AsyncSession]:
    """Provide one request-scoped database session.

    This dependency is appropriate when one request performs database work
    sequentially.

    Concurrent tasks must not share the yielded AsyncSession. Batch ingestion
    should instead depend on the session factory and create one session per
    concurrent task.

    Args:
        session_factory: Application-scoped async session factory.

    Yields:
        Independent AsyncSession for the current dependency scope.
    """
    async with session_factory() as session:
        yield session


DatabaseSessionFactoryDependency = Annotated[
    async_sessionmaker[AsyncSession],
    Depends(get_database_session_factory),
]

DatabaseSessionDependency = Annotated[
    AsyncSession,
    Depends(get_database_session),
]
