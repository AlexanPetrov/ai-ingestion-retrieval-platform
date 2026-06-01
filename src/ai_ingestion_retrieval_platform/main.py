from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from ai_ingestion_retrieval_platform.api.routes.health import router as health_router
from ai_ingestion_retrieval_platform.api.routes.ingestion import router as ingestion_router
from ai_ingestion_retrieval_platform.core.http_client import set_http_client
from ai_ingestion_retrieval_platform.core.logging import configure_logging
from ai_ingestion_retrieval_platform.middleware.request_logging import (
    RequestLoggingMiddleware,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(5.0),
        follow_redirects=True,
    ) as client:
        set_http_client(client)
        yield


app = FastAPI(
    title="AI Ingestion & Retrieval Platform",
    lifespan=lifespan,
)

app.add_middleware(RequestLoggingMiddleware)

app.include_router(health_router, tags=["health"])
app.include_router(ingestion_router, prefix="/ingestion", tags=["ingestion"])