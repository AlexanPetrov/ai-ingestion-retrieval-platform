"""Health check routes for service liveness and readiness."""

import asyncio
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ai_ingestion_retrieval_platform.api.dependencies.rate_limit import (
    is_rate_limit_storage_ready,
)
from ai_ingestion_retrieval_platform.api.dependencies.settings import (
    get_app_settings,
)
from ai_ingestion_retrieval_platform.core.config import Settings

router = APIRouter()

AppSettingsDependency = Annotated[
    Settings,
    Depends(get_app_settings),
]


@router.get("/health/live")
async def liveness_check() -> dict[str, str]:
    """Return whether the application process is responding.

    Liveness intentionally does not depend on external services. Dependency
    outages should affect readiness rather than cause the process itself to be
    considered dead.
    """
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness_check(
    request: Request,
    settings: AppSettingsDependency,
) -> dict[str, str]:
    """Return whether required application resources can serve traffic."""
    http_client = getattr(
        request.app.state,
        "http_client",
        None,
    )

    if not isinstance(http_client, httpx.AsyncClient) or http_client.is_closed:
        raise HTTPException(
            status_code=503,
            detail="HTTP client unavailable",
        )

    if not await is_rate_limit_storage_ready(request):
        raise HTTPException(
            status_code=503,
            detail="Rate limit storage unavailable",
        )

    if settings.database_enabled:
        await _check_database_readiness(
            request,
            timeout_seconds=(settings.database_readiness_timeout_seconds),
        )

    return {"status": "ready"}


async def _check_database_readiness(
    request: Request,
    *,
    timeout_seconds: float,
) -> None:
    """Verify that required PostgreSQL connectivity is available."""
    engine = getattr(
        request.app.state,
        "db_engine",
        None,
    )

    if not isinstance(engine, AsyncEngine):
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        )

    try:
        async with asyncio.timeout(timeout_seconds):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))

    except TimeoutError:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        ) from None

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        ) from None


@router.get("/health", include_in_schema=False)
async def health_check() -> dict[str, str]:
    """Keep the legacy health route as a liveness alias."""
    return await liveness_check()
