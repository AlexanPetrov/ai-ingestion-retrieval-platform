"""FastAPI dependency for accessing the shared outbound HTTP client."""

import httpx
from fastapi import Request


def get_http_client(request: Request) -> httpx.AsyncClient:
    client = getattr(request.app.state, "http_client", None)

    if not isinstance(client, httpx.AsyncClient):
        raise RuntimeError("HTTP client has not been initialized")

    return client
