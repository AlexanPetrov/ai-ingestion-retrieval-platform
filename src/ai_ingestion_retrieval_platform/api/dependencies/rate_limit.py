"""Reusable inbound API rate-limit dependencies."""

from dataclasses import dataclass
from math import ceil
from time import time

from fastapi import FastAPI, HTTPException, Request
from limits import RateLimitItemPerSecond
from limits.aio.strategies import MovingWindowRateLimiter
from limits.storage import storage_from_string

from ai_ingestion_retrieval_platform.api.dependencies.settings import (
    get_app_settings,
)
from ai_ingestion_retrieval_platform.core.config import Settings
from ai_ingestion_retrieval_platform.core.metrics import (
    INBOUND_RATE_LIMIT_STORAGE_ERROR_TOTAL,
    INBOUND_RATE_LIMIT_TOTAL,
)


@dataclass(frozen=True)
class RateLimitPolicy:
    name: str
    requests: int
    window_seconds: int


def _validate_rate_limit_cost(cost: int) -> int:
    if cost < 1:
        raise ValueError("rate limit cost must be at least 1")

    return cost


def _to_async_redis_url(redis_url: str) -> str:
    if redis_url.startswith("async+"):
        return redis_url

    if redis_url.startswith(("redis://", "rediss://")):
        return f"async+{redis_url}"

    return redis_url


def _get_client_key(request: Request) -> str:
    # Do not trust X-Forwarded-For until a trusted proxy is configured.
    if request.client is None:
        return "unknown-client"

    return request.client.host


def _create_rate_limiter(
    app: FastAPI,
    storage_url: str,
) -> MovingWindowRateLimiter:
    """Create and store the shared application rate limiter."""
    storage = storage_from_string(storage_url)
    limiter = MovingWindowRateLimiter(storage)

    app.state.rate_limiter = limiter
    app.state.rate_limiter_storage = storage
    app.state.rate_limiter_storage_url = storage_url

    return limiter


def _get_rate_limiter(
    request: Request,
    settings: Settings,
) -> MovingWindowRateLimiter:
    storage_url = _to_async_redis_url(settings.rate_limit_redis_url)

    cached_url = getattr(request.app.state, "rate_limiter_storage_url", None)
    limiter = getattr(request.app.state, "rate_limiter", None)

    if isinstance(limiter, MovingWindowRateLimiter) and cached_url == storage_url:
        return limiter

    return _create_rate_limiter(request.app, storage_url)


def initialize_rate_limiter(
    app: FastAPI,
    settings: Settings,
) -> None:
    """Initialize shared rate-limit storage during application startup."""
    app.state.rate_limiter = None
    app.state.rate_limiter_storage = None
    app.state.rate_limiter_storage_url = None

    if not settings.rate_limit_enabled:
        return

    storage_url = _to_async_redis_url(settings.rate_limit_redis_url)
    _create_rate_limiter(app, storage_url)


async def close_rate_limiter(app: FastAPI) -> None:
    """Clear shared rate-limiter references during application shutdown."""
    app.state.rate_limiter = None
    app.state.rate_limiter_storage = None
    app.state.rate_limiter_storage_url = None


async def is_rate_limit_storage_ready(request: Request) -> bool:
    """Return whether required rate-limit storage is available."""
    settings = get_app_settings(request)

    if not settings.rate_limit_enabled:
        return True

    if settings.rate_limit_fail_open:
        return True

    try:
        limiter = _get_rate_limiter(request, settings)
        return bool(await limiter.storage.check())
    except Exception:
        return False


async def _get_retry_after_seconds(
    limiter: MovingWindowRateLimiter,
    limit: RateLimitItemPerSecond,
    identifiers: tuple[str, ...],
    fallback_seconds: int,
) -> int:
    window = await limiter.get_window_stats(limit, *identifiers)
    retry_after = ceil(window.reset_time - time())

    return max(1, retry_after or fallback_seconds)


async def enforce_rate_limit(
    request: Request,
    policy: RateLimitPolicy,
    cost: int = 1,
) -> None:
    settings = get_app_settings(request)

    if not settings.rate_limit_enabled:
        return

    cost = _validate_rate_limit_cost(cost)

    limit = RateLimitItemPerSecond(policy.requests, policy.window_seconds)
    identifiers = (
        settings.rate_limit_key_prefix,
        policy.name,
        _get_client_key(request),
    )

    try:
        limiter = _get_rate_limiter(request, settings)
        allowed = await limiter.hit(limit, *identifiers, cost=cost)

        if allowed:
            INBOUND_RATE_LIMIT_TOTAL.labels(
                policy=policy.name,
                result="allowed",
            ).inc()
            return

        INBOUND_RATE_LIMIT_TOTAL.labels(
            policy=policy.name,
            result="blocked",
        ).inc()

        retry_after = await _get_retry_after_seconds(
            limiter=limiter,
            limit=limit,
            identifiers=identifiers,
            fallback_seconds=policy.window_seconds,
        )

    except Exception as exc:
        INBOUND_RATE_LIMIT_STORAGE_ERROR_TOTAL.labels(policy=policy.name).inc()

        if settings.rate_limit_fail_open:
            return

        raise HTTPException(
            status_code=503,
            detail="Rate limit storage unavailable",
        ) from exc

    raise HTTPException(
        status_code=429,
        detail="Rate limit exceeded",
        headers={"Retry-After": str(retry_after)},
    )


async def enforce_url_preview_rate_limit(
    request: Request,
    cost: int,
) -> None:
    settings = get_app_settings(request)

    await enforce_rate_limit(
        request=request,
        policy=RateLimitPolicy(
            name="url-preview",
            requests=settings.rate_limit_url_preview_requests,
            window_seconds=settings.rate_limit_url_preview_window_seconds,
        ),
        cost=cost,
    )


async def enforce_batch_preview_rate_limit(
    request: Request,
    cost: int,
) -> None:
    settings = get_app_settings(request)

    await enforce_rate_limit(
        request=request,
        policy=RateLimitPolicy(
            name="batch-preview",
            requests=settings.rate_limit_batch_preview_requests,
            window_seconds=settings.rate_limit_batch_preview_window_seconds,
        ),
        cost=cost,
    )
