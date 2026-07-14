"""Health check routes for service liveness and readiness."""

import httpx
from fastapi import APIRouter, HTTPException, Request

from ai_ingestion_retrieval_platform.api.dependencies.rate_limit import (
    is_rate_limit_storage_ready,
)

router = APIRouter()


@router.get("/health/live")
async def liveness_check() -> dict[str, str]:
    """Return whether the FastAPI process is responding."""
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness_check(request: Request) -> dict[str, str]:
    """Return whether required application resources are available."""
    http_client = getattr(request.app.state, "http_client", None)

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

    return {"status": "ready"}


@router.get("/health", include_in_schema=False)
async def health_check() -> dict[str, str]:
    """Keep the original health route as a liveness alias."""
    return await liveness_check()
