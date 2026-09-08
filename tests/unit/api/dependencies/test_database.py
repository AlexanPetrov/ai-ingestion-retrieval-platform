"""Unit tests for database FastAPI dependencies."""

from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI, HTTPException, Request
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from ai_ingestion_retrieval_platform.api.dependencies.database import (
    get_database_session,
    get_database_session_factory,
)


def _request_for_app(app: FastAPI) -> Request:
    return Request(
        {
            "type": "http",
            "app": app,
            "headers": [],
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "server": ("test", 80),
            "client": ("127.0.0.1", 12345),
            "scheme": "http",
        }
    )


def test_get_database_session_factory_returns_app_factory() -> None:
    app = FastAPI()

    session_factory = async_sessionmaker(
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    app.state.db_session_factory = session_factory

    request = _request_for_app(app)

    result = get_database_session_factory(request)

    assert result is session_factory


def test_get_database_session_factory_returns_503_when_unavailable() -> None:
    app = FastAPI()
    app.state.db_session_factory = None

    request = _request_for_app(app)

    with pytest.raises(HTTPException) as exc_info:
        get_database_session_factory(request)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Persistence is not enabled"


@pytest.mark.asyncio
async def test_get_database_session_yields_async_session() -> None:
    session_factory = async_sessionmaker(
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    generator: AsyncGenerator[AsyncSession] = get_database_session(session_factory)

    session = await anext(generator)

    assert isinstance(session, AsyncSession)

    await generator.aclose()
