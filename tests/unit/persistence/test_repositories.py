"""Unit tests for async ingestion persistence repository operations."""

from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, MagicMock, create_autospec
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ai_ingestion_retrieval_platform.persistence.models import (
    IngestionRecord,
    ParsedDocument,
    Source,
)
from ai_ingestion_retrieval_platform.persistence.repositories import (
    IngestionRepository,
)


def _mock_session() -> AsyncSession:
    """Return an autospecced AsyncSession for repository unit tests."""
    return cast(
        AsyncSession,
        create_autospec(
            AsyncSession,
            instance=True,
        ),
    )


def _execute_mock(session: AsyncSession) -> AsyncMock:
    """Return the session execute method with its mock type exposed."""
    return cast(AsyncMock, session.execute)


def _flush_mock(session: AsyncSession) -> AsyncMock:
    """Return the session flush method with its mock type exposed."""
    return cast(AsyncMock, session.flush)


def _add_mock(session: AsyncSession) -> MagicMock:
    """Return the session add method with its mock type exposed."""
    return cast(MagicMock, session.add)


@pytest.mark.asyncio
async def test_get_or_create_source_returns_database_id() -> None:
    session = _mock_session()
    source_id = uuid4()

    result_mock = MagicMock()
    result_mock.scalar_one.return_value = source_id

    execute_mock = _execute_mock(session)
    execute_mock.return_value = result_mock

    repository = IngestionRepository(session)

    result = await repository.get_or_create_source(
        url="https://example.com/",
    )

    assert result.source_id == source_id
    execute_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_ingestion_record_adds_and_flushes_record() -> None:
    session = _mock_session()
    repository = IngestionRepository(session)

    source_id = uuid4()
    expected_record_id = uuid4()
    fetched_at = datetime.now(UTC)

    add_mock = _add_mock(session)
    flush_mock = _flush_mock(session)

    async def assign_record_id() -> None:
        record = add_mock.call_args.args[0]
        assert isinstance(record, IngestionRecord)
        record.id = expected_record_id

    flush_mock.side_effect = assign_record_id

    result = await repository.create_ingestion_record(
        source_id=source_id,
        ingestion_mode="parsed",
        batch_id=uuid4(),
        batch_position=1,
        request_id="request-123",
        client_ip="127.0.0.1",
        http_status=200,
        http_status_reason="OK",
        final_url=None,
        response_content_type="text/html",
        response_content_length=10,
        fetch_elapsed_ms=25,
        fetch_error_code=None,
        fetch_error_message=None,
        retry_attempts=0,
        fetched_at=fetched_at,
        parser_name=None,
        parser_version=None,
        parse_elapsed_ms=5,
        parse_error_code=None,
        parse_error_message=None,
    )

    assert result.ingestion_record_id == expected_record_id
    add_mock.assert_called_once()
    flush_mock.assert_awaited_once()

    record = add_mock.call_args.args[0]

    assert isinstance(record, IngestionRecord)
    assert record.source_id == source_id
    assert record.ingestion_mode == "parsed"
    assert record.http_status == 200
    assert record.fetched_at == fetched_at


@pytest.mark.asyncio
async def test_create_parsed_document_adds_and_flushes_document() -> None:
    session = _mock_session()
    repository = IngestionRepository(session)

    ingestion_record_id = uuid4()
    expected_document_id = uuid4()
    content_sha256 = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

    add_mock = _add_mock(session)
    flush_mock = _flush_mock(session)

    async def assign_document_id() -> None:
        document = add_mock.call_args.args[0]
        assert isinstance(document, ParsedDocument)
        document.id = expected_document_id

    flush_mock.side_effect = assign_document_id

    result = await repository.create_parsed_document(
        ingestion_record_id=ingestion_record_id,
        content_type="text/plain",
        char_length=5,
        text_content="hello",
        content_sha256=content_sha256,
    )

    assert result.parsed_document_id == expected_document_id
    add_mock.assert_called_once()
    flush_mock.assert_awaited_once()

    document = add_mock.call_args.args[0]

    assert isinstance(document, ParsedDocument)
    assert document.ingestion_record_id == ingestion_record_id
    assert document.content_type == "text/plain"
    assert document.char_length == 5
    assert document.text_content == "hello"
    assert document.content_sha256 == content_sha256


@pytest.mark.asyncio
async def test_get_source_by_url_returns_source() -> None:
    session = _mock_session()
    repository = IngestionRepository(session)

    source = Source(
        id=uuid4(),
        url="https://example.com/",
    )

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = source

    execute_mock = _execute_mock(session)
    execute_mock.return_value = result_mock

    result = await repository.get_source_by_url(
        url="https://example.com/",
    )

    assert result is source
    execute_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_source_by_id_returns_source() -> None:
    session = _mock_session()
    repository = IngestionRepository(session)

    source_id = uuid4()

    source = Source(
        id=source_id,
        url="https://example.com/",
    )

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = source

    execute_mock = _execute_mock(session)
    execute_mock.return_value = result_mock

    result = await repository.get_source_by_id(
        source_id=source_id,
    )

    assert result is source
    execute_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_ingestion_record_by_id_returns_record() -> None:
    session = _mock_session()
    repository = IngestionRepository(session)

    record_id = uuid4()
    record = MagicMock(spec=IngestionRecord)

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = record

    execute_mock = _execute_mock(session)
    execute_mock.return_value = result_mock

    result = await repository.get_ingestion_record_by_id(
        ingestion_record_id=record_id,
    )

    assert result is record
    execute_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_ingestion_records_by_batch_id_returns_records() -> None:
    session = _mock_session()
    repository = IngestionRepository(session)

    batch_id = uuid4()
    first = MagicMock(spec=IngestionRecord)
    second = MagicMock(spec=IngestionRecord)

    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [
        first,
        second,
    ]

    execute_mock = _execute_mock(session)
    execute_mock.return_value = result_mock

    result = await repository.get_ingestion_records_by_batch_id(
        batch_id=batch_id,
    )

    assert result == [
        first,
        second,
    ]
    execute_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_parsed_document_by_id_returns_document() -> None:
    session = _mock_session()
    repository = IngestionRepository(session)

    document_id = uuid4()
    document = MagicMock(spec=ParsedDocument)

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = document

    execute_mock = _execute_mock(session)
    execute_mock.return_value = result_mock

    result = await repository.get_parsed_document_by_id(
        parsed_document_id=document_id,
    )

    assert result is document
    execute_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_parsed_document_for_ingestion_returns_document() -> None:
    session = _mock_session()
    repository = IngestionRepository(session)

    ingestion_record_id = uuid4()
    document = MagicMock(spec=ParsedDocument)

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = document

    execute_mock = _execute_mock(session)
    execute_mock.return_value = result_mock

    result = await repository.get_parsed_document_for_ingestion(
        ingestion_record_id=ingestion_record_id,
    )

    assert result is document
    execute_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_latest_parsed_content_identity_for_source_returns_latest() -> None:
    session = _mock_session()
    repository = IngestionRepository(session)

    source_id = uuid4()
    parsed_document_id = uuid4()
    content_sha256 = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

    result_mock = MagicMock()
    result_mock.one_or_none.return_value = (
        parsed_document_id,
        content_sha256,
    )

    execute_mock = _execute_mock(session)
    execute_mock.return_value = result_mock

    result = await repository.get_latest_parsed_content_identity_for_source(
        source_id=source_id,
    )

    assert result is not None
    assert result.parsed_document_id == parsed_document_id
    assert result.content_sha256 == content_sha256
    execute_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_latest_parsed_content_identity_for_source_returns_none() -> None:
    session = _mock_session()
    repository = IngestionRepository(session)

    result_mock = MagicMock()
    result_mock.one_or_none.return_value = None

    execute_mock = _execute_mock(session)
    execute_mock.return_value = result_mock

    result = await repository.get_latest_parsed_content_identity_for_source(
        source_id=uuid4(),
    )

    assert result is None
    execute_mock.assert_awaited_once()
