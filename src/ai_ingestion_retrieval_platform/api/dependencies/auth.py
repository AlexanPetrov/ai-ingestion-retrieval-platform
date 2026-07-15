"""Authentication dependency for protected ingestion routes."""

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ai_ingestion_retrieval_platform.api.dependencies.settings import (
    get_app_settings,
)

AUTHENTICATION_REQUIRED_DETAIL = "Authentication required"
AUTHENTICATION_NOT_CONFIGURED_DETAIL = (
    "Ingestion authentication is enabled but no token is configured"
)

_ingestion_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="IngestionBearerAuth",
    description="Bearer token required for ingestion API routes.",
)

BearerCredentialsDependency = Annotated[
    HTTPAuthorizationCredentials | None,
    Depends(_ingestion_bearer),
]


def _raise_unauthorized() -> None:
    raise HTTPException(
        status_code=401,
        detail=AUTHENTICATION_REQUIRED_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_ingestion_auth(
    request: Request,
    credentials: BearerCredentialsDependency,
) -> None:
    """Require the configured bearer token when ingestion auth is enabled."""
    settings = get_app_settings(request)

    if not settings.ingestion_auth_enabled:
        return

    expected_token = settings.ingestion_auth_token

    if expected_token is None or not expected_token.strip():
        raise HTTPException(
            status_code=503,
            detail=AUTHENTICATION_NOT_CONFIGURED_DETAIL,
        )

    if credentials is None:
        _raise_unauthorized()

    if not secrets.compare_digest(credentials.credentials, expected_token):
        _raise_unauthorized()
