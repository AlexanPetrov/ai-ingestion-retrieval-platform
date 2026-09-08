"""Integration tests for app startup/shutdown lifecycle and shared resources."""

import httpx
import pytest
from limits.aio.strategies import MovingWindowRateLimiter

from ai_ingestion_retrieval_platform import main as main_module
from ai_ingestion_retrieval_platform.core.config import Settings
from ai_ingestion_retrieval_platform.main import create_app


def _database_settings() -> Settings:
    """Return valid persistence-enabled settings for lifespan tests."""
    return Settings(
        rate_limit_enabled=False,
        database_enabled=True,
        database_url=(
            "postgresql+asyncpg://user:password@localhost:5432/test_database"
        ),
    )


@pytest.mark.asyncio
async def test_lifespan_initializes_and_closes_shared_http_client() -> None:
    app = create_app(
        Settings(
            rate_limit_enabled=False,
        )
    )

    assert (
        getattr(
            app.state,
            "http_client",
            None,
        )
        is None
    )

    async with app.router.lifespan_context(app):
        client = app.state.http_client

        assert isinstance(
            client,
            httpx.AsyncClient,
        )
        assert client.is_closed is False

    assert client.is_closed is True
    assert app.state.http_client is None


@pytest.mark.asyncio
async def test_lifespan_initializes_and_clears_shared_rate_limiter() -> None:
    app = create_app(
        Settings(
            rate_limit_enabled=True,
            rate_limit_redis_url="async+memory://",
        )
    )

    assert (
        getattr(
            app.state,
            "rate_limiter",
            None,
        )
        is None
    )

    async with app.router.lifespan_context(app):
        assert isinstance(
            app.state.rate_limiter,
            MovingWindowRateLimiter,
        )

        assert app.state.rate_limiter_storage is not None
        assert app.state.rate_limiter_storage_url == "async+memory://"

    assert app.state.rate_limiter is None
    assert app.state.rate_limiter_storage is None
    assert app.state.rate_limiter_storage_url is None


@pytest.mark.asyncio
async def test_lifespan_leaves_database_resources_disabled_when_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_database_engine_is_created(
        _settings: Settings,
    ) -> object:
        raise AssertionError(
            "database engine must not be created when persistence is disabled"
        )

    monkeypatch.setattr(
        main_module,
        "create_database_engine",
        fail_if_database_engine_is_created,
    )

    app = create_app(
        Settings(
            rate_limit_enabled=False,
            database_enabled=False,
        )
    )

    async with app.router.lifespan_context(app):
        assert app.state.db_engine is None
        assert app.state.db_session_factory is None

    assert app.state.db_engine is None
    assert app.state.db_session_factory is None


@pytest.mark.asyncio
async def test_lifespan_initializes_and_closes_database_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _database_settings()
    app = create_app(settings)

    fake_engine = object()
    fake_session_factory = object()

    created_with: list[Settings] = []
    factory_engines: list[object] = []
    closed_engines: list[object] = []

    def fake_create_database_engine(
        received_settings: Settings,
    ) -> object:
        created_with.append(
            received_settings,
        )
        return fake_engine

    def fake_get_session_factory(
        received_engine: object,
    ) -> object:
        factory_engines.append(
            received_engine,
        )
        return fake_session_factory

    async def fake_close_database(
        received_engine: object,
    ) -> None:
        closed_engines.append(
            received_engine,
        )

    monkeypatch.setattr(
        main_module,
        "create_database_engine",
        fake_create_database_engine,
    )
    monkeypatch.setattr(
        main_module,
        "get_session_factory",
        fake_get_session_factory,
    )
    monkeypatch.setattr(
        main_module,
        "close_database",
        fake_close_database,
    )

    assert (
        getattr(
            app.state,
            "db_engine",
            None,
        )
        is None
    )

    assert (
        getattr(
            app.state,
            "db_session_factory",
            None,
        )
        is None
    )

    async with app.router.lifespan_context(app):
        assert app.state.db_engine is fake_engine
        assert app.state.db_session_factory is fake_session_factory

        assert created_with == [
            settings,
        ]

        assert factory_engines == [
            fake_engine,
        ]

        assert closed_engines == []

    assert closed_engines == [
        fake_engine,
    ]

    assert app.state.db_engine is None
    assert app.state.db_session_factory is None


@pytest.mark.asyncio
async def test_app_health_routes_work_with_lifespan_enabled() -> None:
    app = create_app(
        Settings(
            rate_limit_enabled=False,
        )
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            live_response = await client.get(
                "/health/live",
            )
            ready_response = await client.get(
                "/health/ready",
            )

    assert live_response.status_code == 200
    assert live_response.json() == {
        "status": "ok",
    }

    assert ready_response.status_code == 200
    assert ready_response.json() == {
        "status": "ready",
    }
