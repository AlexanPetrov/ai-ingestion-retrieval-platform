import asyncio

from ai_ingestion_retrieval_platform.core.config import get_settings

settings = get_settings()

outbound_fetch_limiter = asyncio.Semaphore(
    settings.global_max_outbound_fetches,
)
