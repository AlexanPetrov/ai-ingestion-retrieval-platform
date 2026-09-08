"""FastAPI app factory, lifespan wiring, and router registration."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from ai_ingestion_retrieval_platform.api.dependencies.rate_limit import (
    close_rate_limiter,
    initialize_rate_limiter,
)
from ai_ingestion_retrieval_platform.api.routes.health import router as health_router
from ai_ingestion_retrieval_platform.api.routes.ingestion import (
    router as ingestion_router,
)
from ai_ingestion_retrieval_platform.api.routes.metrics import router as metrics_router
from ai_ingestion_retrieval_platform.core.config import Settings, get_settings
from ai_ingestion_retrieval_platform.core.logging import configure_logging
from ai_ingestion_retrieval_platform.middleware.request_logging import (
    RequestLoggingMiddleware,
)
from ai_ingestion_retrieval_platform.persistence import (
    close_database,
    create_database_engine,
    get_session_factory,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if settings is None:
        settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        """Own application-scoped runtime resources."""
        configure_logging(settings)

        client_timeout = httpx.Timeout(
            connect=settings.http_timeout_connect_seconds,
            read=settings.http_timeout_read_seconds,
            write=settings.http_timeout_write_seconds,
            pool=settings.http_timeout_pool_seconds,
        )

        client_limits = httpx.Limits(
            max_connections=settings.http_max_connections,
            max_keepalive_connections=settings.http_max_keepalive_connections,
            keepalive_expiry=settings.http_keepalive_expiry_seconds,
        )

        db_engine: AsyncEngine | None = None

        async with httpx.AsyncClient(
            timeout=client_timeout,
            limits=client_limits,
            follow_redirects=False,
        ) as http_client:
            app.state.http_client = http_client

            try:
                if settings.database_enabled:
                    db_engine = create_database_engine(settings)

                    app.state.db_engine = db_engine
                    app.state.db_session_factory = get_session_factory(
                        db_engine,
                    )
                else:
                    app.state.db_engine = None
                    app.state.db_session_factory = None

                initialize_rate_limiter(
                    app,
                    settings,
                )

                yield

            finally:
                await close_rate_limiter(app)

                if db_engine is not None:
                    await close_database(db_engine)

                app.state.db_engine = None
                app.state.db_session_factory = None
                app.state.http_client = None

    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
    )

    app.state.settings = settings
    app.state.http_client = None
    app.state.db_engine = None
    app.state.db_session_factory = None

    app.add_middleware(RequestLoggingMiddleware)

    app.include_router(
        health_router,
        tags=["health"],
    )
    app.include_router(
        ingestion_router,
        prefix="/ingestion",
        tags=["ingestion"],
    )
    app.include_router(
        metrics_router,
        tags=["metrics"],
    )

    return app
