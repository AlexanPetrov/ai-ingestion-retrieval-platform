"""Protected Prometheus metrics endpoint."""

import secrets

from fastapi import APIRouter, Header, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from ai_ingestion_retrieval_platform.api.dependencies.settings import (
    get_app_settings,
)

router = APIRouter()


def _is_authorized(authorization: str, metrics_token: str) -> bool:
    prefix = "Bearer "

    if not authorization.startswith(prefix):
        return False

    token = authorization[len(prefix) :].strip()
    return bool(token) and secrets.compare_digest(token, metrics_token)


@router.get("/metrics", include_in_schema=False)
async def metrics(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Response:
    settings = get_app_settings(request)

    if not settings.metrics_enabled:
        raise HTTPException(status_code=404, detail="Not found")

    if not settings.metrics_token:
        raise HTTPException(status_code=404, detail="Not found")

    if not authorization or not _is_authorized(authorization, settings.metrics_token):
        raise HTTPException(status_code=404, detail="Not found")

    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
