"""Reusable inbound API rate-limit dependencies."""

from dataclasses import dataclass
from math import ceil
from time import time

from fastapi import HTTPException, Request
from limits import RateLimitItemPerSecond
from limits.aio.strategies import MovingWindowRateLimiter
from limits.storage import storage_from_string

from ai_ingestion_retrieval_platform.core.config import Settings, get_settings
from ai_ingestion_retrieval_platform.core.metrics import (
    INBOUND_RATE_LIMIT_STORAGE_ERROR_TOTAL,
    INBOUND_RATE_LIMIT_TOTAL,
)


@dataclass(frozen=True)
class RateLimitPolicy:
    name: str
    requests: int
    window_seconds: int


def _get_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)

    if isinstance(settings, Settings):
        return settings

    return get_settings()


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


def _get_rate_limiter(
    request: Request,
    settings: Settings,
) -> MovingWindowRateLimiter:
    storage_url = _to_async_redis_url(settings.rate_limit_redis_url)

    cached_url = getattr(request.app.state, "rate_limiter_storage_url", None)
    limiter = getattr(request.app.state, "rate_limiter", None)

    if isinstance(limiter, MovingWindowRateLimiter) and cached_url == storage_url:
        return limiter

    storage = storage_from_string(storage_url)
    limiter = MovingWindowRateLimiter(storage)

    request.app.state.rate_limiter = limiter
    request.app.state.rate_limiter_storage = storage
    request.app.state.rate_limiter_storage_url = storage_url

    return limiter


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
) -> None:
    settings = _get_settings(request)

    if not settings.rate_limit_enabled:
        return

    limit = RateLimitItemPerSecond(policy.requests, policy.window_seconds)
    identifiers = (
        settings.rate_limit_key_prefix,
        policy.name,
        _get_client_key(request),
    )

    try:
        limiter = _get_rate_limiter(request, settings)
        allowed = await limiter.hit(limit, *identifiers)

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


async def rate_limit_url_preview(request: Request) -> None:
    settings = _get_settings(request)

    await enforce_rate_limit(
        request=request,
        policy=RateLimitPolicy(
            name="url-preview",
            requests=settings.rate_limit_url_preview_requests,
            window_seconds=settings.rate_limit_url_preview_window_seconds,
        ),
    )


async def rate_limit_batch_preview(request: Request) -> None:
    settings = _get_settings(request)

    await enforce_rate_limit(
        request=request,
        policy=RateLimitPolicy(
            name="batch-preview",
            requests=settings.rate_limit_batch_preview_requests,
            window_seconds=settings.rate_limit_batch_preview_window_seconds,
        ),
    )
