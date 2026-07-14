"""Unit tests for inbound API rate-limit dependency behavior."""

import pytest
from fastapi import FastAPI, HTTPException
from starlette.requests import Request

from ai_ingestion_retrieval_platform.api.dependencies import (
    rate_limit as rate_limit_module,
)
from ai_ingestion_retrieval_platform.api.dependencies.rate_limit import (
    RateLimitPolicy,
    enforce_rate_limit,
    initialize_rate_limiter,
    is_rate_limit_storage_ready,
)
from ai_ingestion_retrieval_platform.core.config import Settings


class _FakeCounter:
    def __init__(self) -> None:
        self.inc_calls: list[dict[str, str]] = []

    def labels(self, **labels: str) -> _FakeCounter:
        self._current_labels = labels
        return self

    def inc(self) -> None:
        self.inc_calls.append(dict(self._current_labels))


def _build_request(app: FastAPI, client_host: str = "127.0.0.1") -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/ingestion/url/preview",
        "headers": [],
        "app": app,
        "client": (client_host, 12345),
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_rate_limit_is_noop_when_disabled() -> None:
    app = FastAPI()
    app.state.settings = Settings(rate_limit_enabled=False)
    request = _build_request(app)

    await enforce_rate_limit(
        request=request,
        policy=RateLimitPolicy(
            name="test-limit",
            requests=1,
            window_seconds=60,
        ),
    )

    assert not hasattr(app.state, "rate_limiter")


@pytest.mark.asyncio
async def test_rate_limit_allows_requests_under_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_decision_counter = _FakeCounter()
    monkeypatch.setattr(
        rate_limit_module,
        "INBOUND_RATE_LIMIT_TOTAL",
        fake_decision_counter,
    )

    app = FastAPI()
    app.state.settings = Settings(
        rate_limit_enabled=True,
        rate_limit_redis_url="async+memory://",
    )
    request = _build_request(app)

    await enforce_rate_limit(
        request=request,
        policy=RateLimitPolicy(
            name="test-limit",
            requests=2,
            window_seconds=60,
        ),
    )

    assert fake_decision_counter.inc_calls == [
        {"policy": "test-limit", "result": "allowed"},
    ]


@pytest.mark.asyncio
async def test_rate_limit_rejects_requests_over_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_decision_counter = _FakeCounter()
    monkeypatch.setattr(
        rate_limit_module,
        "INBOUND_RATE_LIMIT_TOTAL",
        fake_decision_counter,
    )

    app = FastAPI()
    app.state.settings = Settings(
        rate_limit_enabled=True,
        rate_limit_redis_url="async+memory://",
    )
    request = _build_request(app)

    policy = RateLimitPolicy(
        name="test-limit",
        requests=1,
        window_seconds=60,
    )

    await enforce_rate_limit(request=request, policy=policy)

    with pytest.raises(HTTPException) as exc_info:
        await enforce_rate_limit(request=request, policy=policy)

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "Rate limit exceeded"
    assert exc_info.value.headers is not None
    assert int(exc_info.value.headers["Retry-After"]) >= 1
    assert fake_decision_counter.inc_calls == [
        {"policy": "test-limit", "result": "allowed"},
        {"policy": "test-limit", "result": "blocked"},
    ]


@pytest.mark.asyncio
async def test_rate_limit_separates_clients() -> None:
    app = FastAPI()
    app.state.settings = Settings(
        rate_limit_enabled=True,
        rate_limit_redis_url="async+memory://",
    )

    policy = RateLimitPolicy(
        name="test-limit",
        requests=1,
        window_seconds=60,
    )

    await enforce_rate_limit(
        request=_build_request(app, client_host="127.0.0.1"),
        policy=policy,
    )

    await enforce_rate_limit(
        request=_build_request(app, client_host="127.0.0.2"),
        policy=policy,
    )


@pytest.mark.asyncio
async def test_rate_limit_fails_closed_when_storage_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_storage_error_counter = _FakeCounter()
    monkeypatch.setattr(
        rate_limit_module,
        "INBOUND_RATE_LIMIT_STORAGE_ERROR_TOTAL",
        fake_storage_error_counter,
    )

    app = FastAPI()
    app.state.settings = Settings(
        rate_limit_enabled=True,
        rate_limit_redis_url="unknown://localhost",
        rate_limit_fail_open=False,
    )
    request = _build_request(app)

    with pytest.raises(HTTPException) as exc_info:
        await enforce_rate_limit(
            request=request,
            policy=RateLimitPolicy(
                name="test-limit",
                requests=1,
                window_seconds=60,
            ),
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Rate limit storage unavailable"
    assert fake_storage_error_counter.inc_calls == [
        {"policy": "test-limit"},
    ]


@pytest.mark.asyncio
async def test_rate_limit_can_fail_open_when_storage_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_storage_error_counter = _FakeCounter()
    monkeypatch.setattr(
        rate_limit_module,
        "INBOUND_RATE_LIMIT_STORAGE_ERROR_TOTAL",
        fake_storage_error_counter,
    )

    app = FastAPI()
    app.state.settings = Settings(
        rate_limit_enabled=True,
        rate_limit_redis_url="unknown://localhost",
        rate_limit_fail_open=True,
    )
    request = _build_request(app)

    await enforce_rate_limit(
        request=request,
        policy=RateLimitPolicy(
            name="test-limit",
            requests=1,
            window_seconds=60,
        ),
    )

    assert fake_storage_error_counter.inc_calls == [
        {"policy": "test-limit"},
    ]


def test_initialize_rate_limiter_skips_storage_when_disabled() -> None:
    app = FastAPI()
    settings = Settings(rate_limit_enabled=False)

    initialize_rate_limiter(app, settings)

    assert app.state.rate_limiter is None
    assert app.state.rate_limiter_storage is None
    assert app.state.rate_limiter_storage_url is None


@pytest.mark.asyncio
async def test_rate_limit_storage_is_ready_when_rate_limiting_is_disabled() -> None:
    app = FastAPI()
    app.state.settings = Settings(rate_limit_enabled=False)
    request = _build_request(app)

    assert await is_rate_limit_storage_ready(request) is True


@pytest.mark.asyncio
async def test_rate_limit_storage_is_ready_when_fail_open_is_enabled() -> None:
    app = FastAPI()
    app.state.settings = Settings(
        rate_limit_enabled=True,
        rate_limit_fail_open=True,
        rate_limit_redis_url="unknown://localhost",
    )
    request = _build_request(app)

    assert await is_rate_limit_storage_ready(request) is True


@pytest.mark.asyncio
async def test_rate_limit_storage_is_ready_when_storage_is_available() -> None:
    app = FastAPI()
    app.state.settings = Settings(
        rate_limit_enabled=True,
        rate_limit_fail_open=False,
        rate_limit_redis_url="async+memory://",
    )
    request = _build_request(app)

    assert await is_rate_limit_storage_ready(request) is True


@pytest.mark.asyncio
async def test_rate_limit_storage_is_not_ready_when_required_storage_fails() -> None:
    app = FastAPI()
    app.state.settings = Settings(
        rate_limit_enabled=True,
        rate_limit_fail_open=False,
        rate_limit_redis_url="unknown://localhost",
    )
    request = _build_request(app)

    assert await is_rate_limit_storage_ready(request) is False
