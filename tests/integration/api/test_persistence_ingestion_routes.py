"""Integration tests for persisted-ingestion API route contracts."""

from collections.abc import AsyncGenerator
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import HTTPException
from pydantic import AnyHttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from ai_ingestion_retrieval_platform.api.dependencies.database import (
    get_database_session,
    get_database_session_factory,
)
from ai_ingestion_retrieval_platform.api.routes import (
    ingestion as ingestion_routes,
)
from ai_ingestion_retrieval_platform.core.config import Settings
from ai_ingestion_retrieval_platform.main import create_app
from ai_ingestion_retrieval_platform.schemas.ingestion import (
    UrlIngestionPreview,
    UrlParsedIngestionPreview,
)


class _SessionContext:
    """Async context manager producing one isolated fake session."""

    def __init__(
        self,
        factory: _SessionFactory,
    ) -> None:
        self._factory = factory

    async def __aenter__(self) -> AsyncSession:
        session = cast(
            AsyncSession,
            object(),
        )

        self._factory.sessions.append(session)

        return session

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        return None


class _SessionFactory:
    """Minimal session factory used by persisted batch-route tests."""

    def __init__(self) -> None:
        self.sessions: list[AsyncSession] = []

    def __call__(self) -> _SessionContext:
        return _SessionContext(self)


async def _single_session_dependency() -> AsyncGenerator[AsyncSession]:
    """Yield one fake request-scoped database session."""
    yield cast(
        AsyncSession,
        object(),
    )


@pytest.mark.asyncio
async def test_url_ingest_route_returns_persisted_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        rate_limit_enabled=False,
        ingestion_auth_enabled=False,
        database_enabled=False,
    )

    app = create_app(settings)

    app.dependency_overrides[get_database_session] = _single_session_dependency

    ingestion_record_id = uuid4()
    source_id = uuid4()

    captured: dict[str, object] = {}

    async def fake_ingest_url(
        url: AnyHttpUrl,
        _client: httpx.AsyncClient,
        _session: AsyncSession,
        url_timeout: float | None = None,
        app_settings: Settings | None = None,
        request_id: str | None = None,
        client_ip: str | None = None,
        batch_id: UUID | None = None,
        batch_position: int | None = None,
    ) -> tuple[UUID, UUID, UrlIngestionPreview]:
        captured["url"] = str(url)
        captured["url_timeout"] = url_timeout
        captured["app_settings"] = app_settings
        captured["request_id"] = request_id
        captured["client_ip"] = client_ip
        captured["batch_id"] = batch_id
        captured["batch_position"] = batch_position

        return (
            ingestion_record_id,
            source_id,
            UrlIngestionPreview(
                url=str(url),
                status_code=200,
                content_type="text/plain",
                content_length=5,
                elapsed_ms=3.0,
                preview="hello",
            ),
        )

    monkeypatch.setattr(
        ingestion_routes,
        "ingest_url",
        fake_ingest_url,
    )

    async with httpx.AsyncClient() as shared_client:
        app.state.http_client = shared_client

        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/ingestion/url/ingest",
                headers={
                    "x-request-id": "request-raw-123",
                },
                json={
                    "url": "https://example.com",
                },
            )

    app.state.http_client = None

    assert response.status_code == 200

    assert response.json() == {
        "url": "https://example.com/",
        "ingestion_record_id": str(ingestion_record_id),
        "source_id": str(source_id),
        "status_code": 200,
        "content_type": "text/plain",
        "content_length": 5,
        "elapsed_ms": 3.0,
        "preview": "hello",
    }

    assert captured["url"] == "https://example.com/"
    assert captured["app_settings"] is settings
    assert captured["request_id"] == "request-raw-123"
    assert captured["batch_id"] is None
    assert captured["batch_position"] is None


@pytest.mark.asyncio
async def test_url_parse_ingest_route_returns_persisted_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        rate_limit_enabled=False,
        ingestion_auth_enabled=False,
        database_enabled=False,
    )

    app = create_app(settings)

    app.dependency_overrides[get_database_session] = _single_session_dependency

    ingestion_record_id = uuid4()
    source_id = uuid4()
    parsed_document_id = uuid4()

    captured: dict[str, object] = {}

    async def fake_ingest_parsed_url(
        url: AnyHttpUrl,
        _client: httpx.AsyncClient,
        _session: AsyncSession,
        url_timeout: float | None = None,
        app_settings: Settings | None = None,
        request_id: str | None = None,
        client_ip: str | None = None,
        batch_id: UUID | None = None,
        batch_position: int | None = None,
    ) -> tuple[
        UUID,
        UUID,
        UUID,
        UrlParsedIngestionPreview,
    ]:
        captured["url"] = str(url)
        captured["url_timeout"] = url_timeout
        captured["app_settings"] = app_settings
        captured["request_id"] = request_id
        captured["client_ip"] = client_ip
        captured["batch_id"] = batch_id
        captured["batch_position"] = batch_position

        return (
            ingestion_record_id,
            source_id,
            parsed_document_id,
            UrlParsedIngestionPreview(
                url=str(url),
                status_code=200,
                content_type="text/html",
                content_length=11,
                elapsed_ms=4.0,
                parsed_content_type="text/html",
                parsed_char_length=5,
                parsed_preview="hello",
            ),
        )

    monkeypatch.setattr(
        ingestion_routes,
        "ingest_parsed_url",
        fake_ingest_parsed_url,
    )

    async with httpx.AsyncClient() as shared_client:
        app.state.http_client = shared_client

        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/ingestion/url/parse-ingest",
                headers={
                    "x-request-id": "request-parsed-123",
                },
                json={
                    "url": "https://example.com/document",
                },
            )

    app.state.http_client = None

    assert response.status_code == 200

    assert response.json() == {
        "url": "https://example.com/document",
        "ingestion_record_id": str(ingestion_record_id),
        "source_id": str(source_id),
        "parsed_document_id": str(parsed_document_id),
        "status_code": 200,
        "content_type": "text/html",
        "content_length": 11,
        "elapsed_ms": 4.0,
        "parsed_content_type": "text/html",
        "parsed_char_length": 5,
        "parsed_preview": "hello",
    }

    assert captured["app_settings"] is settings
    assert captured["request_id"] == "request-parsed-123"
    assert captured["batch_id"] is None
    assert captured["batch_position"] is None


@pytest.mark.asyncio
async def test_url_ingest_route_returns_503_when_persistence_is_disabled() -> None:
    settings = Settings(
        rate_limit_enabled=False,
        ingestion_auth_enabled=False,
        database_enabled=False,
    )

    app = create_app(settings)

    async with httpx.AsyncClient() as shared_client:
        app.state.http_client = shared_client

        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/ingestion/url/ingest",
                json={
                    "url": "https://example.com",
                },
            )

    app.state.http_client = None

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Persistence is not enabled",
    }


@pytest.mark.asyncio
async def test_urls_ingest_route_preserves_order_and_partial_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        rate_limit_enabled=False,
        ingestion_auth_enabled=False,
        database_enabled=False,
        default_max_concurrency=2,
    )

    app = create_app(settings)

    session_factory = _SessionFactory()

    async def fake_session_factory_dependency() -> _SessionFactory:
        return session_factory

    app.dependency_overrides[get_database_session_factory] = (
        fake_session_factory_dependency
    )

    first_ingestion_id = uuid4()
    first_source_id = uuid4()

    observed_batch_ids: list[UUID] = []
    observed_positions: list[int] = []
    observed_sessions: list[AsyncSession] = []

    async def fake_ingest_url(
        url: AnyHttpUrl,
        _client: httpx.AsyncClient,
        session: AsyncSession,
        url_timeout: float | None = None,
        app_settings: Settings | None = None,
        request_id: str | None = None,
        client_ip: str | None = None,
        batch_id: UUID | None = None,
        batch_position: int | None = None,
    ) -> tuple[UUID, UUID, UrlIngestionPreview]:
        assert url_timeout is None
        assert app_settings is settings
        assert request_id == "batch-request-123"
        assert batch_id is not None
        assert batch_position is not None

        observed_batch_ids.append(batch_id)
        observed_positions.append(batch_position)
        observed_sessions.append(session)

        if batch_position == 1:
            raise HTTPException(
                status_code=502,
                detail="Second URL failed",
            )

        return (
            first_ingestion_id,
            first_source_id,
            UrlIngestionPreview(
                url=str(url),
                status_code=200,
                content_type="text/plain",
                content_length=2,
                elapsed_ms=1.0,
                preview="ok",
            ),
        )

    monkeypatch.setattr(
        ingestion_routes,
        "ingest_url",
        fake_ingest_url,
    )

    async with httpx.AsyncClient() as shared_client:
        app.state.http_client = shared_client

        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/ingestion/urls/ingest",
                headers={
                    "x-request-id": "batch-request-123",
                },
                json={
                    "urls": [
                        "https://example.com/one",
                        "https://example.com/two",
                    ],
                    "max_concurrency": 2,
                },
            )

    app.state.http_client = None

    assert response.status_code == 200

    payload = response.json()

    response_batch_id = UUID(payload["batch_id"])

    assert len(payload["results"]) == 2

    first_result = payload["results"][0]
    second_result = payload["results"][1]

    assert first_result["url"] == "https://example.com/one"
    assert first_result["success"] is True
    assert first_result["error"] is None

    assert first_result["data"]["ingestion_record_id"] == str(first_ingestion_id)
    assert first_result["data"]["source_id"] == str(first_source_id)

    assert second_result["url"] == "https://example.com/two"
    assert second_result["success"] is False
    assert second_result["data"] is None
    assert second_result["error"] is not None
    assert second_result["error"]["status_code"] == 502

    assert sorted(observed_positions) == [0, 1]

    assert len(observed_batch_ids) == 2
    assert set(observed_batch_ids) == {
        response_batch_id,
    }

    assert len(session_factory.sessions) == 2
    assert len(observed_sessions) == 2

    assert observed_sessions[0] is not observed_sessions[1]


@pytest.mark.asyncio
async def test_urls_parse_ingest_route_preserves_order_and_partial_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        rate_limit_enabled=False,
        ingestion_auth_enabled=False,
        database_enabled=False,
        default_max_concurrency=2,
    )

    app = create_app(settings)

    session_factory = _SessionFactory()

    async def fake_session_factory_dependency() -> _SessionFactory:
        return session_factory

    app.dependency_overrides[get_database_session_factory] = (
        fake_session_factory_dependency
    )

    first_ingestion_id = uuid4()
    first_source_id = uuid4()
    first_document_id = uuid4()

    observed_batch_ids: list[UUID] = []
    observed_positions: list[int] = []
    observed_sessions: list[AsyncSession] = []

    async def fake_ingest_parsed_url(
        url: AnyHttpUrl,
        _client: httpx.AsyncClient,
        session: AsyncSession,
        url_timeout: float | None = None,
        app_settings: Settings | None = None,
        request_id: str | None = None,
        client_ip: str | None = None,
        batch_id: UUID | None = None,
        batch_position: int | None = None,
    ) -> tuple[
        UUID,
        UUID,
        UUID,
        UrlParsedIngestionPreview,
    ]:
        assert url_timeout is None
        assert app_settings is settings
        assert request_id == "parsed-batch-request-123"
        assert batch_id is not None
        assert batch_position is not None

        observed_batch_ids.append(batch_id)
        observed_positions.append(batch_position)
        observed_sessions.append(session)

        if batch_position == 1:
            raise HTTPException(
                status_code=415,
                detail="Second document could not be parsed",
            )

        return (
            first_ingestion_id,
            first_source_id,
            first_document_id,
            UrlParsedIngestionPreview(
                url=str(url),
                status_code=200,
                content_type="text/html",
                content_length=12,
                elapsed_ms=2.0,
                parsed_content_type="text/html",
                parsed_char_length=5,
                parsed_preview="hello",
            ),
        )

    monkeypatch.setattr(
        ingestion_routes,
        "ingest_parsed_url",
        fake_ingest_parsed_url,
    )

    async with httpx.AsyncClient() as shared_client:
        app.state.http_client = shared_client

        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/ingestion/urls/parse-ingest",
                headers={
                    "x-request-id": "parsed-batch-request-123",
                },
                json={
                    "urls": [
                        "https://example.com/one",
                        "https://example.com/two",
                    ],
                    "max_concurrency": 2,
                },
            )

    app.state.http_client = None

    assert response.status_code == 200

    payload = response.json()

    response_batch_id = UUID(payload["batch_id"])

    assert len(payload["results"]) == 2

    first_result = payload["results"][0]
    second_result = payload["results"][1]

    assert first_result["url"] == "https://example.com/one"
    assert first_result["success"] is True
    assert first_result["error"] is None

    assert first_result["data"]["ingestion_record_id"] == str(first_ingestion_id)
    assert first_result["data"]["source_id"] == str(first_source_id)
    assert first_result["data"]["parsed_document_id"] == str(first_document_id)

    assert second_result["url"] == "https://example.com/two"
    assert second_result["success"] is False
    assert second_result["data"] is None
    assert second_result["error"] is not None
    assert second_result["error"]["status_code"] == 415

    assert sorted(observed_positions) == [0, 1]

    assert len(observed_batch_ids) == 2
    assert set(observed_batch_ids) == {
        response_batch_id,
    }

    assert len(session_factory.sessions) == 2
    assert len(observed_sessions) == 2

    assert observed_sessions[0] is not observed_sessions[1]
