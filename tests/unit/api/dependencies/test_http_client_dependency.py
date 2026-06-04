"""Unit tests for HTTP client dependency resolution from app state."""

import httpx
import pytest
from fastapi import FastAPI
from starlette.requests import Request

from ai_ingestion_retrieval_platform.api.dependencies.http_client import get_http_client


def _build_request(app: FastAPI) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "app": app,
    }
    return Request(scope)


def test_get_http_client_raises_when_not_initialized() -> None:
    app = FastAPI()
    request = _build_request(app)

    with pytest.raises(RuntimeError, match="HTTP client has not been initialized"):
        get_http_client(request)


@pytest.mark.asyncio
async def test_get_http_client_returns_initialized_client() -> None:
    app = FastAPI()

    async with httpx.AsyncClient() as client:
        app.state.http_client = client
        request = _build_request(app)

        resolved_client = get_http_client(request)

    assert resolved_client is client
