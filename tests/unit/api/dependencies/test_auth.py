"""Unit tests for ingestion-route authentication behavior."""

import httpx
import pytest
from fastapi import Depends, FastAPI

from ai_ingestion_retrieval_platform.api.dependencies.auth import (
    AUTHENTICATION_NOT_CONFIGURED_DETAIL,
    AUTHENTICATION_REQUIRED_DETAIL,
    require_ingestion_auth,
)
from ai_ingestion_retrieval_platform.core.config import Settings


def _create_test_app(settings: Settings) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings

    @app.get("/protected", dependencies=[Depends(require_ingestion_auth)])
    async def protected_route() -> dict[str, str]:
        return {"status": "ok"}

    return app


async def _get_protected_route(
    settings: Settings,
    authorization: str | None = None,
) -> httpx.Response:
    app = _create_test_app(settings)
    headers = {}

    if authorization is not None:
        headers["Authorization"] = authorization

    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        return await client.get("/protected", headers=headers)


@pytest.mark.asyncio
async def test_require_ingestion_auth_allows_requests_when_disabled() -> None:
    response = await _get_protected_route(
        Settings(
            ingestion_auth_enabled=False,
            ingestion_auth_token=None,
        )
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_require_ingestion_auth_allows_valid_bearer_token() -> None:
    response = await _get_protected_route(
        Settings(
            ingestion_auth_enabled=True,
            ingestion_auth_token="expected-token",
        ),
        authorization="Bearer expected-token",
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
@pytest.mark.parametrize("configured_token", [None, "", "   "])
async def test_require_ingestion_auth_fails_closed_when_token_is_not_configured(
    configured_token: str | None,
) -> None:
    response = await _get_protected_route(
        Settings(
            ingestion_auth_enabled=True,
            ingestion_auth_token=configured_token,
        ),
        authorization="Bearer any-token",
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": AUTHENTICATION_NOT_CONFIGURED_DETAIL,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "",
        "Basic expected-token",
        "Bearer",
        "Bearer ",
        "Bearer wrong-token",
    ],
)
async def test_require_ingestion_auth_rejects_missing_malformed_or_invalid_token(
    authorization: str | None,
) -> None:
    response = await _get_protected_route(
        Settings(
            ingestion_auth_enabled=True,
            ingestion_auth_token="expected-token",
        ),
        authorization=authorization,
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": AUTHENTICATION_REQUIRED_DETAIL,
    }
    assert response.headers["www-authenticate"] == "Bearer"
