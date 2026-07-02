"""FastAPI app factory, lifespan wiring, and router registration."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

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


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
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

        async with httpx.AsyncClient(
            timeout=client_timeout,
            limits=client_limits,
            follow_redirects=False,
        ) as client:
            app.state.http_client = client
            yield

        app.state.http_client = None

    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
    )

    app.state.settings = settings

    app.add_middleware(RequestLoggingMiddleware)

    app.include_router(health_router, tags=["health"])
    app.include_router(ingestion_router, prefix="/ingestion", tags=["ingestion"])
    app.include_router(metrics_router, tags=["metrics"])

    return app
