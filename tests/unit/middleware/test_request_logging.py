"""Unit tests for ASGI request logging middleware behavior and metrics emission."""

from uuid import UUID

import pytest

from ai_ingestion_retrieval_platform.middleware import (
    request_logging as middleware_module,
)


class _FakeCounter:
    def __init__(self) -> None:
        self.inc_calls: list[dict[str, str]] = []

    def labels(self, **labels: str) -> _FakeCounter:
        self._current_labels = labels
        return self

    def inc(self) -> None:
        self.inc_calls.append(dict(self._current_labels))


class _FakeHistogram:
    def __init__(self) -> None:
        self.observe_calls: list[tuple[dict[str, str], float]] = []

    def labels(self, **labels: str) -> _FakeHistogram:
        self._current_labels = labels
        return self

    def observe(self, value: float) -> None:
        self.observe_calls.append((dict(self._current_labels), value))


async def _receive() -> dict[str, object]:
    return {
        "type": "http.request",
        "body": b"",
        "more_body": False,
    }


@pytest.mark.asyncio
async def test_middleware_uses_existing_request_id_and_records_success_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_counter = _FakeCounter()
    fake_histogram = _FakeHistogram()

    monkeypatch.setattr(middleware_module, "HTTP_REQUESTS_TOTAL", fake_counter)
    monkeypatch.setattr(
        middleware_module,
        "HTTP_REQUEST_DURATION_SECONDS",
        fake_histogram,
    )

    async def app(_scope: dict[str, object], _receive: object, send: object) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 204,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    middleware = middleware_module.RequestLoggingMiddleware(app)
    sent_messages: list[dict[str, object]] = []

    async def send(message: dict[str, object]) -> None:
        sent_messages.append(message)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/health",
        "headers": [(b"x-request-id", b"req-123")],
    }

    await middleware(scope, _receive, send)

    response_start = next(
        msg for msg in sent_messages if msg["type"] == "http.response.start"
    )
    assert (b"x-request-id", b"req-123") in response_start["headers"]

    assert fake_counter.inc_calls == [
        {"method": "GET", "path": "/health", "status_code": "204"},
    ]
    assert fake_histogram.observe_calls
    assert fake_histogram.observe_calls[0][0] == {"method": "GET", "path": "/health"}


@pytest.mark.asyncio
async def test_middleware_generates_request_id_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_counter = _FakeCounter()
    fake_histogram = _FakeHistogram()

    monkeypatch.setattr(middleware_module, "HTTP_REQUESTS_TOTAL", fake_counter)
    monkeypatch.setattr(
        middleware_module,
        "HTTP_REQUEST_DURATION_SECONDS",
        fake_histogram,
    )

    async def app(_scope: dict[str, object], _receive: object, send: object) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})

    middleware = middleware_module.RequestLoggingMiddleware(app)
    sent_messages: list[dict[str, object]] = []

    async def send(message: dict[str, object]) -> None:
        sent_messages.append(message)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/ingestion",
        "headers": [],
    }

    await middleware(scope, _receive, send)

    response_start = next(
        msg for msg in sent_messages if msg["type"] == "http.response.start"
    )
    headers = dict(response_start["headers"])
    generated = headers[b"x-request-id"].decode()

    UUID(generated)


@pytest.mark.asyncio
async def test_middleware_uses_normalized_route_path_for_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_counter = _FakeCounter()
    fake_histogram = _FakeHistogram()

    monkeypatch.setattr(middleware_module, "HTTP_REQUESTS_TOTAL", fake_counter)
    monkeypatch.setattr(
        middleware_module,
        "HTTP_REQUEST_DURATION_SECONDS",
        fake_histogram,
    )

    async def app(scope: dict[str, object], _receive: object, send: object) -> None:
        scope["route"] = type("Route", (), {"path": "/documents/{document_id}"})()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})

    middleware = middleware_module.RequestLoggingMiddleware(app)

    async def send(_message: dict[str, object]) -> None:
        return

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/documents/123",
        "headers": [],
    }

    await middleware(scope, _receive, send)

    assert fake_counter.inc_calls == [
        {
            "method": "GET",
            "path": "/documents/{document_id}",
            "status_code": "200",
        }
    ]
    assert fake_histogram.observe_calls
    assert fake_histogram.observe_calls[0][0] == {
        "method": "GET",
        "path": "/documents/{document_id}",
    }


@pytest.mark.asyncio
async def test_middleware_records_500_metrics_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_counter = _FakeCounter()
    fake_histogram = _FakeHistogram()

    monkeypatch.setattr(middleware_module, "HTTP_REQUESTS_TOTAL", fake_counter)
    monkeypatch.setattr(
        middleware_module,
        "HTTP_REQUEST_DURATION_SECONDS",
        fake_histogram,
    )

    async def app(_scope: dict[str, object], _receive: object, _send: object) -> None:
        raise RuntimeError("boom")

    middleware = middleware_module.RequestLoggingMiddleware(app)

    async def send(_message: dict[str, object]) -> None:
        return

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/ingestion/urls/preview",
        "headers": [],
    }

    with pytest.raises(RuntimeError, match="boom"):
        await middleware(scope, _receive, send)

    assert fake_counter.inc_calls == [
        {
            "method": "POST",
            "path": "/ingestion/urls/preview",
            "status_code": "500",
        }
    ]
    assert fake_histogram.observe_calls
    assert fake_histogram.observe_calls[0][0] == {
        "method": "POST",
        "path": "/ingestion/urls/preview",
    }


@pytest.mark.asyncio
async def test_middleware_passthrough_for_non_http_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_counter = _FakeCounter()
    fake_histogram = _FakeHistogram()

    monkeypatch.setattr(middleware_module, "HTTP_REQUESTS_TOTAL", fake_counter)
    monkeypatch.setattr(
        middleware_module,
        "HTTP_REQUEST_DURATION_SECONDS",
        fake_histogram,
    )

    app_called = {"value": False}

    async def app(scope: dict[str, object], _receive: object, send: object) -> None:
        app_called["value"] = True
        await send({"type": "lifespan.startup.complete"})
        assert scope["type"] == "lifespan"

    middleware = middleware_module.RequestLoggingMiddleware(app)
    sent_messages: list[dict[str, object]] = []

    async def send(message: dict[str, object]) -> None:
        sent_messages.append(message)

    scope = {
        "type": "lifespan",
    }

    await middleware(scope, _receive, send)

    assert app_called["value"] is True
    assert sent_messages == [{"type": "lifespan.startup.complete"}]
    assert fake_counter.inc_calls == []
    assert fake_histogram.observe_calls == []
