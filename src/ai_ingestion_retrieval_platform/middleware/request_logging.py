from time import perf_counter
from uuid import uuid4

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ai_ingestion_retrieval_platform.core.metrics import (
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_TOTAL,
)

logger = structlog.get_logger()


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        path = scope["path"]
        request_id = self._get_request_id(scope)
        start = perf_counter()
        status_code = 500

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        logger.info(
            "request_started",
            method=method,
            path=path,
        )

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code

            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers

            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)

        except Exception:
            elapsed_seconds = perf_counter() - start
            elapsed_ms = round(elapsed_seconds * 1000, 2)

            HTTP_REQUESTS_TOTAL.labels(
                method=method,
                path=path,
                status_code="500",
            ).inc()

            HTTP_REQUEST_DURATION_SECONDS.labels(
                method=method,
                path=path,
            ).observe(elapsed_seconds)

            logger.exception(
                "request_failed",
                method=method,
                path=path,
                status_code=500,
                elapsed_ms=elapsed_ms,
            )
            raise

        elapsed_seconds = perf_counter() - start
        elapsed_ms = round(elapsed_seconds * 1000, 2)

        HTTP_REQUESTS_TOTAL.labels(
            method=method,
            path=path,
            status_code=str(status_code),
        ).inc()

        HTTP_REQUEST_DURATION_SECONDS.labels(
            method=method,
            path=path,
        ).observe(elapsed_seconds)

        logger.info(
            "request_completed",
            method=method,
            path=path,
            status_code=status_code,
            elapsed_ms=elapsed_ms,
        )

    def _get_request_id(self, scope: Scope) -> str:
        headers = dict(scope.get("headers", []))
        request_id = headers.get(b"x-request-id")

        if request_id:
            return request_id.decode()

        return str(uuid4())
