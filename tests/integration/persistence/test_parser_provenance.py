"""PostgreSQL integration tests for persisted parser provenance."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_ingestion_retrieval_platform.api.dependencies.database import (
    get_database_session,
)
from ai_ingestion_retrieval_platform.core.config import Settings
from ai_ingestion_retrieval_platform.main import create_app
from ai_ingestion_retrieval_platform.persistence.models import (
    IngestionRecord,
    ParsedDocument,
)
from ai_ingestion_retrieval_platform.services import (
    parsing as parsing_service,
)
from ai_ingestion_retrieval_platform.services import (
    persistence as persistence_service,
)


def _fetch_response(
    *,
    content: bytes,
    content_type: str,
) -> httpx.Response:
    """Return one admitted upstream response for parse-ingestion tests."""

    return httpx.Response(
        status_code=200,
        headers={
            "content-type": content_type,
        },
        content=content,
        request=httpx.Request(
            "GET",
            "https://example.com/document",
        ),
    )


@pytest.mark.asyncio
async def test_parse_ingest_persists_successful_parser_provenance(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful parse ingestion must persist its actual parser provenance."""

    response = _fetch_response(
        content=b"<html><body><h1>Hello</h1></body></html>",
        content_type="text/html",
    )

    fetch_mock = AsyncMock(
        return_value=response,
    )

    monkeypatch.setattr(
        persistence_service,
        "fetch_url",
        fetch_mock,
    )

    settings = Settings(
        rate_limit_enabled=False,
        ingestion_auth_enabled=False,
        database_enabled=False,
    )

    app = create_app(settings)

    async def database_session_dependency() -> AsyncGenerator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_database_session] = database_session_dependency

    async with httpx.AsyncClient() as shared_client:
        app.state.http_client = shared_client

        transport = httpx.ASGITransport(
            app=app,
        )

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            api_response = await client.post(
                "/ingestion/url/parse-ingest",
                headers={
                    "x-request-id": "parser-provenance-success",
                },
                json={
                    "url": "https://example.com/document",
                },
            )

    app.state.http_client = None

    assert api_response.status_code == 200

    payload = api_response.json()

    ingestion_record = await db_session.scalar(
        select(IngestionRecord).where(
            IngestionRecord.id == payload["ingestion_record_id"]
        )
    )

    assert ingestion_record is not None
    assert ingestion_record.parser_name == parsing_service.HTML_PARSER_NAME
    assert ingestion_record.parser_version == parsing_service.HTML_PARSER_VERSION
    assert ingestion_record.parse_error_code is None
    assert ingestion_record.parse_error_message is None

    parsed_document = await db_session.scalar(
        select(ParsedDocument).where(ParsedDocument.id == payload["parsed_document_id"])
    )

    assert parsed_document is not None
    assert parsed_document.ingestion_record_id == ingestion_record.id
    assert parsed_document.text_content == "Hello"

    fetch_mock.assert_awaited_once()

    await response.aclose()


@pytest.mark.asyncio
async def test_parse_ingest_persists_known_parser_failure_provenance(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Known parser failures must retain provenance without a document row."""

    response = _fetch_response(
        content=b"not a real pdf",
        content_type="application/pdf",
    )

    fetch_mock = AsyncMock(
        return_value=response,
    )

    monkeypatch.setattr(
        persistence_service,
        "fetch_url",
        fetch_mock,
    )

    settings = Settings(
        rate_limit_enabled=False,
        ingestion_auth_enabled=False,
        database_enabled=False,
    )

    app = create_app(settings)

    async def database_session_dependency() -> AsyncGenerator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_database_session] = database_session_dependency

    async with httpx.AsyncClient() as shared_client:
        app.state.http_client = shared_client

        transport = httpx.ASGITransport(
            app=app,
        )

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            api_response = await client.post(
                "/ingestion/url/parse-ingest",
                headers={
                    "x-request-id": "parser-provenance-failure",
                },
                json={
                    "url": "https://example.com/document",
                },
            )

    app.state.http_client = None

    assert api_response.status_code == 400

    ingestion_record = await db_session.scalar(
        select(IngestionRecord).where(
            IngestionRecord.request_id == "parser-provenance-failure"
        )
    )

    assert ingestion_record is not None
    assert ingestion_record.parser_name == parsing_service.PDF_PARSER_NAME
    assert ingestion_record.parser_version == parsing_service.PDF_PARSER_VERSION
    assert ingestion_record.parse_error_code is not None
    assert ingestion_record.parse_error_message is not None

    parsed_document = await db_session.scalar(
        select(ParsedDocument).where(
            ParsedDocument.ingestion_record_id == ingestion_record.id
        )
    )

    assert parsed_document is None

    fetch_mock.assert_awaited_once()

    await response.aclose()
