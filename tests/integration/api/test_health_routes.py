"""Integration tests for health check routes."""

import asyncio

import httpx
import pytest
from sqlalchemy.exc import SQLAlchemyError

from ai_ingestion_retrieval_platform.api.routes import (
    health as health_routes,
)
from ai_ingestion_retrieval_platform.core.config import Settings
from ai_ingestion_retrieval_platform.main import create_app


class _FakeConnection:
    """Minimal async database connection for readiness tests."""

    def __init__(
        self,
        *,
        error: Exception | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self.error = error
        self.delay_seconds = delay_seconds
        self.executed = False

    async def execute(
        self,
        _statement: object,
    ) -> None:
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)

        if self.error is not None:
            raise self.error

        self.executed = True


class _FakeConnectionContext:
    """Async context manager returned by the fake engine."""

    def __init__(
        self,
        connection: _FakeConnection,
    ) -> None:
        self.connection = connection

    async def __aenter__(self) -> _FakeConnection:
        return self.connection

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        return None


class _FakeAsyncEngine:
    """Minimal AsyncEngine stand-in for readiness tests."""

    def __init__(
        self,
        connection: _FakeConnection,
    ) -> None:
        self.connection = connection

    def connect(self) -> _FakeConnectionContext:
        return _FakeConnectionContext(
            self.connection,
        )


def _database_settings(
    *,
    readiness_timeout: float = 2.0,
) -> Settings:
    """Return settings with persistence enabled for health tests."""
    return Settings(
        rate_limit_enabled=False,
        database_enabled=True,
        database_url=(
            "postgresql+asyncpg://user:password@localhost:5432/test_database"
        ),
        database_readiness_timeout_seconds=readiness_timeout,
    )


@pytest.mark.asyncio
async def test_liveness_route_returns_ok() -> None:
    app = create_app(
        Settings(
            rate_limit_enabled=False,
        )
    )

    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/health/live",
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
    }


@pytest.mark.asyncio
async def test_readiness_route_returns_ready_when_resources_are_available() -> None:
    app = create_app(
        Settings(
            rate_limit_enabled=False,
        )
    )

    async with httpx.AsyncClient() as shared_client:
        app.state.http_client = shared_client

        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/health/ready",
            )

    app.state.http_client = None

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
    }


@pytest.mark.asyncio
async def test_readiness_route_returns_503_when_http_client_is_missing() -> None:
    app = create_app(
        Settings(
            rate_limit_enabled=False,
        )
    )

    app.state.http_client = None

    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/health/ready",
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "HTTP client unavailable",
    }


@pytest.mark.asyncio
async def test_original_health_route_remains_available() -> None:
    app = create_app(
        Settings(
            rate_limit_enabled=False,
        )
    )

    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/health",
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
    }


@pytest.mark.asyncio
async def test_readiness_route_returns_503_when_http_client_is_closed() -> None:
    app = create_app(
        Settings(
            rate_limit_enabled=False,
        )
    )

    shared_client = httpx.AsyncClient()
    await shared_client.aclose()

    app.state.http_client = shared_client

    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/health/ready",
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "HTTP client unavailable",
    }


@pytest.mark.asyncio
async def test_readiness_route_returns_503_when_required_redis_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(
        Settings(
            rate_limit_enabled=True,
            rate_limit_fail_open=False,
        )
    )

    async def fake_storage_ready(
        _request: object,
    ) -> bool:
        return False

    monkeypatch.setattr(
        health_routes,
        "is_rate_limit_storage_ready",
        fake_storage_ready,
    )

    async with httpx.AsyncClient() as shared_client:
        app.state.http_client = shared_client

        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/health/ready",
            )

    app.state.http_client = None

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Rate limit storage unavailable",
    }


@pytest.mark.asyncio
async def test_readiness_route_returns_ready_when_database_is_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _database_settings()
    app = create_app(settings)

    connection = _FakeConnection()
    engine = _FakeAsyncEngine(connection)

    # health.py performs an AsyncEngine type check. Replace the imported
    # symbol with our test implementation so the route exercises the real
    # database-readiness branch without opening a PostgreSQL connection.
    monkeypatch.setattr(
        health_routes,
        "AsyncEngine",
        _FakeAsyncEngine,
    )

    app.state.db_engine = engine

    async with httpx.AsyncClient() as shared_client:
        app.state.http_client = shared_client

        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/health/ready",
            )

    app.state.http_client = None
    app.state.db_engine = None

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
    }

    assert connection.executed is True


@pytest.mark.asyncio
async def test_readiness_route_returns_503_when_database_engine_is_missing() -> None:
    settings = _database_settings()
    app = create_app(settings)

    app.state.db_engine = None

    async with httpx.AsyncClient() as shared_client:
        app.state.http_client = shared_client

        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/health/ready",
            )

    app.state.http_client = None

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_readiness_route_returns_503_when_database_check_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _database_settings()
    app = create_app(settings)

    connection = _FakeConnection(
        error=SQLAlchemyError(
            "database unavailable",
        ),
    )
    engine = _FakeAsyncEngine(connection)

    monkeypatch.setattr(
        health_routes,
        "AsyncEngine",
        _FakeAsyncEngine,
    )

    app.state.db_engine = engine

    async with httpx.AsyncClient() as shared_client:
        app.state.http_client = shared_client

        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/health/ready",
            )

    app.state.http_client = None
    app.state.db_engine = None

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_readiness_route_returns_503_when_database_check_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _database_settings(
        readiness_timeout=0.001,
    )
    app = create_app(settings)

    connection = _FakeConnection(
        delay_seconds=0.05,
    )
    engine = _FakeAsyncEngine(connection)

    monkeypatch.setattr(
        health_routes,
        "AsyncEngine",
        _FakeAsyncEngine,
    )

    app.state.db_engine = engine

    async with httpx.AsyncClient() as shared_client:
        app.state.http_client = shared_client

        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/health/ready",
            )

    app.state.http_client = None
    app.state.db_engine = None

    assert response.status_code == 503
