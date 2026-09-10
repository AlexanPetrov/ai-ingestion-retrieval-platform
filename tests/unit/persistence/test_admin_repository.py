"""Unit tests for administrative persistence operations."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ai_ingestion_retrieval_platform.persistence.admin_repository import (
    AdminRepository,
    DatabasePurgeResult,
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

    source_result = Mock()
    source_result.scalar_one.return_value = 2

    ingestion_result = Mock()
    ingestion_result.scalar_one.return_value = 6

    document_result = Mock()
    document_result.scalar_one.return_value = 3

    session.execute.side_effect = [
        source_result,
        ingestion_result,
        document_result,
    ]

    repository = AdminRepository(session)

    result = await repository.get_database_stats()

    assert result == DatabaseStats(
        sources=2,
        ingestion_records=6,
        parsed_documents=3,
    )
    assert session.execute.await_count == 3


@pytest.mark.asyncio
async def test_get_database_stats_returns_zero_counts_when_database_is_empty() -> None:
    session = AsyncMock(spec=AsyncSession)

    source_result = Mock()
    source_result.scalar_one.return_value = 0

    ingestion_result = Mock()
    ingestion_result.scalar_one.return_value = 0

    document_result = Mock()
    document_result.scalar_one.return_value = 0

    session.execute.side_effect = [
        source_result,
        ingestion_result,
        document_result,
    ]

    repository = AdminRepository(session)

    result = await repository.get_database_stats()

    assert result == DatabaseStats(
        sources=0,
        ingestion_records=0,
        parsed_documents=0,
    )
    assert session.execute.await_count == 3


@pytest.mark.asyncio
async def test_purge_database_returns_deleted_counts() -> None:
    session = AsyncMock(spec=AsyncSession)

    lock_result = Mock()

    source_count_result = Mock()
    source_count_result.scalar_one.return_value = 2

    ingestion_count_result = Mock()
    ingestion_count_result.scalar_one.return_value = 6

    document_count_result = Mock()
    document_count_result.scalar_one.return_value = 3

    ingestion_delete_result = Mock()
    source_delete_result = Mock()

    session.execute.side_effect = [
        lock_result,
        source_count_result,
        ingestion_count_result,
        document_count_result,
        ingestion_delete_result,
        source_delete_result,
    ]

    repository = AdminRepository(session)

    result = await repository.purge_database()

    assert result == DatabasePurgeResult(
        sources_deleted=2,
        ingestion_records_deleted=6,
        parsed_documents_deleted=3,
    )
    assert session.execute.await_count == 6


@pytest.mark.asyncio
async def test_purge_database_handles_empty_database() -> None:
    session = AsyncMock(spec=AsyncSession)

    lock_result = Mock()

    source_count_result = Mock()
    source_count_result.scalar_one.return_value = 0

    ingestion_count_result = Mock()
    ingestion_count_result.scalar_one.return_value = 0

    document_count_result = Mock()
    document_count_result.scalar_one.return_value = 0

    ingestion_delete_result = Mock()
    source_delete_result = Mock()

    session.execute.side_effect = [
        lock_result,
        source_count_result,
        ingestion_count_result,
        document_count_result,
        ingestion_delete_result,
        source_delete_result,
    ]

    repository = AdminRepository(session)

    result = await repository.purge_database()

    assert result == DatabasePurgeResult(
        sources_deleted=0,
        ingestion_records_deleted=0,
        parsed_documents_deleted=0,
    )
    assert session.execute.await_count == 6


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
async def test_list_sources_returns_empty_list_when_none_exist() -> None:
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

    returned_source = await repository.get_source("source-123")

    assert returned_source == SourceSummary(
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

    returned_source = await repository.get_source("missing-source")

    assert returned_source is None
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_source_returns_true_when_source_exists() -> None:
    session = AsyncMock(spec=AsyncSession)

    result = Mock()
    result.scalar_one_or_none.return_value = "source-123"
    session.execute.return_value = result

    repository = AdminRepository(session)

    deleted = await repository.delete_source("source-123")

    assert deleted is True
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_source_returns_false_when_source_does_not_exist() -> None:
    session = AsyncMock(spec=AsyncSession)

    result = Mock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result

    repository = AdminRepository(session)

    deleted = await repository.delete_source("missing-source")

    assert deleted is False
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_ingestions_returns_ingestion_summaries() -> None:
    session = AsyncMock(spec=AsyncSession)

    ingested_at = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)

    ingestion = SimpleNamespace(
        id="ingestion-123",
        source_id="source-123",
        ingestion_mode="parsed",
        batch_id="batch-123",
        batch_position=0,
        ingested_at=ingested_at,
    )

    result = Mock()
    result.scalars.return_value.all.return_value = [ingestion]
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

    ingestion = SimpleNamespace(
        id="ingestion-123",
        source_id="source-123",
        ingestion_mode="parsed",
        batch_id=None,
        batch_position=None,
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
        ingestion,
        "document-123",
    )
    session.execute.return_value = result

    repository = AdminRepository(session)

    returned_ingestion = await repository.get_ingestion("ingestion-123")

    assert returned_ingestion == IngestionDetail(
        id="ingestion-123",
        source_id="source-123",
        parsed_document_id="document-123",
        ingestion_mode="parsed",
        batch_id=None,
        batch_position=None,
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
async def test_get_ingestion_returns_detail_without_parsed_document() -> None:
    session = AsyncMock(spec=AsyncSession)

    fetched_at = datetime(2026, 9, 9, 9, 59, tzinfo=UTC)
    ingested_at = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)

    ingestion = SimpleNamespace(
        id="ingestion-123",
        source_id="source-123",
        ingestion_mode="raw",
        batch_id=None,
        batch_position=None,
        request_id=None,
        client_ip=None,
        http_status=200,
        http_status_reason="OK",
        final_url=None,
        response_content_type="text/plain",
        response_content_length=100,
        fetch_elapsed_ms=25,
        fetch_error_code=None,
        fetch_error_message=None,
        retry_attempts=0,
        fetched_at=fetched_at,
        parser_name=None,
        parser_version=None,
        parse_elapsed_ms=None,
        parse_error_code=None,
        parse_error_message=None,
        ingested_at=ingested_at,
    )

    result = Mock()
    result.one_or_none.return_value = (
        ingestion,
        None,
    )
    session.execute.return_value = result

    repository = AdminRepository(session)

    returned_ingestion = await repository.get_ingestion("ingestion-123")

    assert returned_ingestion is not None
    assert returned_ingestion.parsed_document_id is None
    assert returned_ingestion.ingestion_mode == "raw"
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_ingestion_returns_none_when_ingestion_does_not_exist() -> None:
    session = AsyncMock(spec=AsyncSession)

    result = Mock()
    result.one_or_none.return_value = None
    session.execute.return_value = result

    repository = AdminRepository(session)

    returned_ingestion = await repository.get_ingestion("missing-ingestion")

    assert returned_ingestion is None
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_ingestion_returns_true_when_ingestion_exists() -> None:
    session = AsyncMock(spec=AsyncSession)

    result = Mock()
    result.scalar_one_or_none.return_value = "ingestion-123"
    session.execute.return_value = result

    repository = AdminRepository(session)

    deleted = await repository.delete_ingestion("ingestion-123")

    assert deleted is True
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_ingestion_returns_false_when_ingestion_does_not_exist() -> None:
    session = AsyncMock(spec=AsyncSession)

    result = Mock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result

    repository = AdminRepository(session)

    deleted = await repository.delete_ingestion("missing-ingestion")

    assert deleted is False
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_documents_returns_document_summaries() -> None:
    session = AsyncMock(spec=AsyncSession)

    created_at = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)

    document = SimpleNamespace(
        id="document-123",
        ingestion_record_id="ingestion-123",
        content_type="text/html",
        char_length=1200,
        created_at=created_at,
    )

    result = Mock()
    result.scalars.return_value.all.return_value = [document]
    session.execute.return_value = result

    repository = AdminRepository(session)

    documents = await repository.list_documents(limit=50)

    assert documents == [
        ParsedDocumentSummary(
            id="document-123",
            ingestion_record_id="ingestion-123",
            content_type="text/html",
            char_length=1200,
            created_at=created_at,
        )
    ]
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_documents_returns_empty_list_when_none_exist() -> None:
    session = AsyncMock(spec=AsyncSession)

    result = Mock()
    result.scalars.return_value.all.return_value = []
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
        content_type="text/plain",
        char_length=25,
        text_content="Persisted parsed content.",
        created_at=created_at,
    )

    result = Mock()
    result.scalar_one_or_none.return_value = document
    session.execute.return_value = result

    repository = AdminRepository(session)

    returned_document = await repository.get_document("document-123")

    assert returned_document == ParsedDocumentDetail(
        id="document-123",
        ingestion_record_id="ingestion-123",
        content_type="text/plain",
        char_length=25,
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

    returned_document = await repository.get_document("missing-document")

    assert returned_document is None
    session.execute.assert_awaited_once()
