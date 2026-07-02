"""Async limiter factories and caches for bounded ingestion work.

These limiters control how many outbound URL fetches the backend sends.

Flow: batch limiter -> global outbound limiter -> per-host limiter -> HTTP request.

Batch limiter controls how many URLs from one batch run at once.
Global limiter controls total outbound fetches in this Python process.
Per-host limiter controls how many fetches hit the same hostname at once.
"""

import asyncio
from weakref import WeakKeyDictionary

from ai_ingestion_retrieval_platform.core.config import Settings, get_settings

_outbound_fetch_limiters: WeakKeyDictionary[
    asyncio.AbstractEventLoop,
    dict[int, asyncio.Semaphore],
] = WeakKeyDictionary()

_host_limiters: WeakKeyDictionary[
    asyncio.AbstractEventLoop,
    dict[str, asyncio.Semaphore],
] = WeakKeyDictionary()

_host_limiter_locks: WeakKeyDictionary[
    asyncio.AbstractEventLoop,
    asyncio.Lock,
] = WeakKeyDictionary()


def _resolve_settings(settings: Settings | None) -> Settings:
    if settings is None:
        return get_settings()

    return settings


def get_outbound_fetch_limiter(settings: Settings | None = None) -> asyncio.Semaphore:
    """Global outbound limit for concurrent fetches in this process."""
    settings = _resolve_settings(settings)

    loop = asyncio.get_running_loop()
    limit = settings.global_max_outbound_fetches

    loop_limiters = _outbound_fetch_limiters.setdefault(loop, {})

    if limit not in loop_limiters:
        loop_limiters[limit] = asyncio.Semaphore(limit)

    return loop_limiters[limit]


def create_batch_limiter(max_concurrency: int) -> asyncio.Semaphore:
    """Per-batch limit for concurrent URL previews in one request."""
    return asyncio.Semaphore(max_concurrency)


async def get_host_limiter(
    hostname: str,
    settings: Settings | None = None,
) -> asyncio.Semaphore:
    """Per-host limit for concurrent fetches to the same hostname."""
    settings = _resolve_settings(settings)

    loop = asyncio.get_running_loop()
    key = hostname.lower()

    lock = _host_limiter_locks.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _host_limiter_locks[loop] = lock

    async with lock:
        host_limiters = _host_limiters.setdefault(loop, {})
        limiter = host_limiters.get(key)

        if limiter is None:
            if len(host_limiters) >= settings.host_limiter_cache_size:
                oldest_key = next(iter(host_limiters))
                del host_limiters[oldest_key]

            limiter = asyncio.Semaphore(settings.host_max_concurrency)
            host_limiters[key] = limiter

        return limiter


def clear_limiters() -> None:
    _outbound_fetch_limiters.clear()
    _host_limiters.clear()
    _host_limiter_locks.clear()
