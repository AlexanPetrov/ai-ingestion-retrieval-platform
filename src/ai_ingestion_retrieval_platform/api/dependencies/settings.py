"""FastAPI dependency for application-scoped runtime settings."""

from fastapi import Request

from ai_ingestion_retrieval_platform.core.config import Settings


def get_app_settings(request: Request) -> Settings:
    """Return the settings instance owned by the FastAPI application."""
    settings = getattr(request.app.state, "settings", None)

    if not isinstance(settings, Settings):
        raise RuntimeError("Application settings are not initialized")

    return settings
