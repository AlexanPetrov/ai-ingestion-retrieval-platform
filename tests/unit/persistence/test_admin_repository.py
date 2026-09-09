"""Tests for administrative persistence queries."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ai_ingestion_retrieval_platform.persistence.admin_repository import (
    AdminRepository,
    DatabaseStats,
    IngestionDetail,
    IngestionSummary,
    ParsedDocumentDetail,
    ParsedDocumentSummary,
    SourceSummary,
)


@pytest.mark.asyncio
async def test_get_database_stats_returns_entity_counts() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.side_effect = [2, 6, 3]

    repository = AdminRepository(session)

    result = await repository.get_database_stats()

    assert result == DatabaseStats(
        sources=2,
        ingestion_records=6,
        parsed_documents=3,
    )
    assert session.scalar.await_count == 3


@pytest.mark.asyncio
async def test_get_database_stats_converts_none_counts_to_zero() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.side_effect = [None, None, None]

    repository = AdminRepository(session)

    result = await repository.get_database_stats()

    assert result == DatabaseStats(
        sources=0,
        ingestion_records=0,
        parsed_documents=0,
    )
    assert session.scalar.await_count == 3


@pytest.mark.asyncio
async def test_list_sources_returns_source_summaries() -> None:
    session = AsyncMock(spec=AsyncSession)

    created_at = datetime(2026, 9, 9, 8, 0, tzinfo=UTC)
    last_seen_at = datetime(2026, 9, 9, 9, 0, tzinfo=UTC)

    source = SimpleNamespace(
        id="source-123",
        url="https://example.com/",
        created_at=created_at,
        last_seen_at=last_seen_at,
    )

    result = Mock()
    result.scalars.return_value.all.return_value = [source]
    session.execute.return_value = result

    repository = AdminRepository(session)

    sources = await repository.list_sources(limit=50)

    assert sources == [
        SourceSummary(
            id="source-123",
            url="https://example.com/",
            created_at=created_at,
            last_seen_at=last_seen_at,
        )
    ]
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_sources_returns_empty_list_when_no_sources_exist() -> None:
    session = AsyncMock(spec=AsyncSession)

    result = Mock()
    result.scalars.return_value.all.return_value = []
    session.execute.return_value = result

    repository = AdminRepository(session)

    sources = await repository.list_sources(limit=50)

    assert sources == []
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_source_returns_source_summary() -> None:
    session = AsyncMock(spec=AsyncSession)

    created_at = datetime(2026, 9, 9, 8, 0, tzinfo=UTC)
    last_seen_at = datetime(2026, 9, 9, 9, 0, tzinfo=UTC)

    source = SimpleNamespace(
        id="source-123",
        url="https://example.com/",
        created_at=created_at,
        last_seen_at=last_seen_at,
    )

    result = Mock()
    result.scalar_one_or_none.return_value = source
    session.execute.return_value = result

    repository = AdminRepository(session)

    source_summary = await repository.get_source("source-123")

    assert source_summary == SourceSummary(
        id="source-123",
        url="https://example.com/",
        created_at=created_at,
        last_seen_at=last_seen_at,
    )
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_source_returns_none_when_source_does_not_exist() -> None:
    session = AsyncMock(spec=AsyncSession)

    result = Mock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result

    repository = AdminRepository(session)

    source_summary = await repository.get_source("missing-source")

    assert source_summary is None
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_ingestions_returns_ingestion_summaries() -> None:
    session = AsyncMock(spec=AsyncSession)

    ingested_at = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)

    ingestion_record = SimpleNamespace(
        id="ingestion-123",
        source_id="source-123",
        ingestion_mode="parsed",
        batch_id="batch-123",
        batch_position=0,
        ingested_at=ingested_at,
    )

    result = Mock()
    result.scalars.return_value.all.return_value = [ingestion_record]
    session.execute.return_value = result

    repository = AdminRepository(session)

    ingestions = await repository.list_ingestions(limit=50)

    assert ingestions == [
        IngestionSummary(
            id="ingestion-123",
            source_id="source-123",
            ingestion_mode="parsed",
            batch_id="batch-123",
            batch_position=0,
            ingested_at=ingested_at,
        )
    ]
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_ingestions_supports_non_batch_records() -> None:
    session = AsyncMock(spec=AsyncSession)

    ingested_at = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)

    ingestion_record = SimpleNamespace(
        id="ingestion-123",
        source_id="source-123",
        ingestion_mode="raw",
        batch_id=None,
        batch_position=None,
        ingested_at=ingested_at,
    )

    result = Mock()
    result.scalars.return_value.all.return_value = [ingestion_record]
    session.execute.return_value = result

    repository = AdminRepository(session)

    ingestions = await repository.list_ingestions(limit=50)

    assert ingestions == [
        IngestionSummary(
            id="ingestion-123",
            source_id="source-123",
            ingestion_mode="raw",
            batch_id=None,
            batch_position=None,
            ingested_at=ingested_at,
        )
    ]


@pytest.mark.asyncio
async def test_list_ingestions_returns_empty_list_when_none_exist() -> None:
    session = AsyncMock(spec=AsyncSession)

    result = Mock()
    result.scalars.return_value.all.return_value = []
    session.execute.return_value = result

    repository = AdminRepository(session)

    ingestions = await repository.list_ingestions(limit=50)

    assert ingestions == []
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_ingestion_returns_ingestion_detail() -> None:
    session = AsyncMock(spec=AsyncSession)

    fetched_at = datetime(2026, 9, 9, 9, 59, tzinfo=UTC)
    ingested_at = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)

    ingestion_record = SimpleNamespace(
        id="ingestion-123",
        source_id="source-123",
        ingestion_mode="parsed",
        batch_id="batch-123",
        batch_position=2,
        request_id="request-123",
        client_ip="203.0.113.10",
        http_status=200,
        http_status_reason="OK",
        final_url=None,
        response_content_type="text/html",
        response_content_length=1024,
        fetch_elapsed_ms=125,
        fetch_error_code=None,
        fetch_error_message=None,
        retry_attempts=0,
        fetched_at=fetched_at,
        parser_name=None,
        parser_version=None,
        parse_elapsed_ms=25,
        parse_error_code=None,
        parse_error_message=None,
        ingested_at=ingested_at,
    )

    result = Mock()
    result.one_or_none.return_value = (
        ingestion_record,
        "document-123",
    )
    session.execute.return_value = result

    repository = AdminRepository(session)

    ingestion = await repository.get_ingestion("ingestion-123")

    assert ingestion == IngestionDetail(
        id="ingestion-123",
        source_id="source-123",
        parsed_document_id="document-123",
        ingestion_mode="parsed",
        batch_id="batch-123",
        batch_position=2,
        request_id="request-123",
        client_ip="203.0.113.10",
        http_status=200,
        http_status_reason="OK",
        final_url=None,
        response_content_type="text/html",
        response_content_length=1024,
        fetch_elapsed_ms=125,
        fetch_error_code=None,
        fetch_error_message=None,
        retry_attempts=0,
        fetched_at=fetched_at,
        parser_name=None,
        parser_version=None,
        parse_elapsed_ms=25,
        parse_error_code=None,
        parse_error_message=None,
        ingested_at=ingested_at,
    )

    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_ingestion_returns_none_when_ingestion_does_not_exist() -> None:
    session = AsyncMock(spec=AsyncSession)

    result = Mock()
    result.one_or_none.return_value = None
    session.execute.return_value = result

    repository = AdminRepository(session)

    ingestion = await repository.get_ingestion("missing-ingestion")

    assert ingestion is None
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_documents_returns_document_summaries() -> None:
    session = AsyncMock(spec=AsyncSession)

    first_created_at = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)
    second_created_at = datetime(2026, 9, 9, 9, 0, tzinfo=UTC)

    first_document = SimpleNamespace(
        id="document-2",
        ingestion_record_id="ingestion-2",
        content_type="text/html",
        char_length=1200,
        created_at=first_created_at,
    )
    second_document = SimpleNamespace(
        id="document-1",
        ingestion_record_id="ingestion-1",
        content_type="text/plain",
        char_length=500,
        created_at=second_created_at,
    )

    scalars = Mock()
    scalars.all.return_value = [
        first_document,
        second_document,
    ]

    result = Mock()
    result.scalars.return_value = scalars
    session.execute.return_value = result

    repository = AdminRepository(session)

    documents = await repository.list_documents(limit=10)

    assert documents == [
        ParsedDocumentSummary(
            id="document-2",
            ingestion_record_id="ingestion-2",
            content_type="text/html",
            char_length=1200,
            created_at=first_created_at,
        ),
        ParsedDocumentSummary(
            id="document-1",
            ingestion_record_id="ingestion-1",
            content_type="text/plain",
            char_length=500,
            created_at=second_created_at,
        ),
    ]

    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_documents_returns_empty_list() -> None:
    session = AsyncMock(spec=AsyncSession)

    scalars = Mock()
    scalars.all.return_value = []

    result = Mock()
    result.scalars.return_value = scalars
    session.execute.return_value = result

    repository = AdminRepository(session)

    documents = await repository.list_documents(limit=50)

    assert documents == []
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_document_returns_document_detail() -> None:
    session = AsyncMock(spec=AsyncSession)

    created_at = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)

    document = SimpleNamespace(
        id="document-123",
        ingestion_record_id="ingestion-123",
        content_type="text/html",
        char_length=24,
        text_content="Persisted parsed content.",
        created_at=created_at,
    )

    result = Mock()
    result.scalar_one_or_none.return_value = document
    session.execute.return_value = result

    repository = AdminRepository(session)

    parsed_document = await repository.get_document("document-123")

    assert parsed_document == ParsedDocumentDetail(
        id="document-123",
        ingestion_record_id="ingestion-123",
        content_type="text/html",
        char_length=24,
        text_content="Persisted parsed content.",
        created_at=created_at,
    )

    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_document_returns_none_when_document_does_not_exist() -> None:
    session = AsyncMock(spec=AsyncSession)

    result = Mock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result

    repository = AdminRepository(session)

    document = await repository.get_document("missing-document")

    assert document is None
    session.execute.assert_awaited_once()
