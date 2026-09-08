"""Unit tests for persistent ingestion service workflows."""

from time import perf_counter
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from pydantic import AnyHttpUrl, TypeAdapter
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ai_ingestion_retrieval_platform.core.config import Settings
from ai_ingestion_retrieval_platform.persistence.repositories import (
    IngestionRecordResult,
    ParsedDocumentResult,
    SourceResult,
)
from ai_ingestion_retrieval_platform.schemas.parsing import ParsedDocument
from ai_ingestion_retrieval_platform.services import (
    persistence as persistence_service,
)


class _TransactionContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        return None


class _SessionStub:
    def begin(self) -> _TransactionContext:
        return _TransactionContext()


def _session() -> AsyncSession:
    return cast(
        AsyncSession,
        _SessionStub(),
    )


def _url(value: str = "https://example.com/") -> AnyHttpUrl:
    return TypeAdapter(AnyHttpUrl).validate_python(value)


def _response(
    *,
    url: str = "https://example.com/",
    content: bytes = b"hello world",
    content_type: str = "text/plain",
) -> httpx.Response:
    request = httpx.Request(
        "GET",
        url,
    )

    return httpx.Response(
        status_code=200,
        headers={
            "content-type": content_type,
        },
        content=content,
        request=request,
    )


def _repository_mock() -> MagicMock:
    repository = MagicMock()

    repository.get_or_create_source = AsyncMock(
        return_value=SourceResult(
            source_id=uuid4(),
        )
    )

    repository.create_ingestion_record = AsyncMock(
        return_value=IngestionRecordResult(
            ingestion_record_id=uuid4(),
        )
    )

    repository.create_parsed_document = AsyncMock(
        return_value=ParsedDocumentResult(
            parsed_document_id=uuid4(),
        )
    )

    return repository


def test_elapsed_ms_never_returns_negative_value() -> None:
    result = persistence_service._elapsed_ms(perf_counter() + 100.0)

    assert result == 0


@pytest.mark.asyncio
async def test_persist_fetch_failure_creates_audit_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository_mock()

    monkeypatch.setattr(
        persistence_service,
        "IngestionRepository",
        lambda _session: repository,
    )

    ingestion_id, source_id = await persistence_service._persist_fetch_failure(
        session=_session(),
        url="https://example.com/",
        ingestion_mode="raw",
        request_id="request-1",
        client_ip="127.0.0.1",
        batch_id=None,
        batch_position=None,
        fetch_elapsed_ms=10,
        error_code="timeout",
        error_message="URL fetch timed out",
    )

    assert (
        ingestion_id
        == repository.create_ingestion_record.return_value.ingestion_record_id
    )

    assert source_id == repository.get_or_create_source.return_value.source_id

    repository.get_or_create_source.assert_awaited_once_with(
        url="https://example.com/",
    )

    repository.create_ingestion_record.assert_awaited_once()

    await_args = repository.create_ingestion_record.await_args
    assert await_args is not None

    kwargs = await_args.kwargs

    assert kwargs["ingestion_mode"] == "raw"
    assert kwargs["http_status"] is None
    assert kwargs["fetch_error_code"] == "timeout"
    assert kwargs["retry_attempts"] == 0


@pytest.mark.asyncio
async def test_persist_fetch_failure_maps_database_error_to_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository_mock()

    repository.get_or_create_source.side_effect = SQLAlchemyError("database failed")

    monkeypatch.setattr(
        persistence_service,
        "IngestionRepository",
        lambda _session: repository,
    )

    with pytest.raises(HTTPException) as exc_info:
        await persistence_service._persist_fetch_failure(
            session=_session(),
            url="https://example.com/",
            ingestion_mode="raw",
            request_id=None,
            client_ip=None,
            batch_id=None,
            batch_position=None,
            fetch_elapsed_ms=10,
            error_code="timeout",
            error_message="URL fetch timed out",
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Persistence unavailable"


@pytest.mark.asyncio
async def test_ingest_url_persists_successful_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository_mock()

    response = _response(
        content=b"hello world",
    )

    monkeypatch.setattr(
        persistence_service,
        "fetch_url",
        AsyncMock(return_value=response),
    )

    monkeypatch.setattr(
        persistence_service,
        "IngestionRepository",
        lambda _session: repository,
    )

    settings = Settings(
        max_preview_text_chars=5,
    )

    ingestion_id, source_id, preview = await persistence_service.ingest_url(
        url=_url(),
        client=httpx.AsyncClient(),
        session=_session(),
        app_settings=settings,
        request_id="request-123",
        client_ip="127.0.0.1",
    )

    assert (
        ingestion_id
        == repository.create_ingestion_record.return_value.ingestion_record_id
    )

    assert source_id == repository.get_or_create_source.return_value.source_id

    assert preview.status_code == 200
    assert preview.content_length == 11
    assert preview.preview == "hello"

    await_args = repository.create_ingestion_record.await_args
    assert await_args is not None

    kwargs = await_args.kwargs

    assert kwargs["ingestion_mode"] == "raw"
    assert kwargs["http_status"] == 200
    assert kwargs["final_url"] is None
    assert kwargs["retry_attempts"] == 0
    assert kwargs["request_id"] == "request-123"

    await response.aclose()


@pytest.mark.asyncio
async def test_ingest_url_persists_expected_fetch_failure_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_error = HTTPException(
        status_code=504,
        detail="URL fetch timed out",
    )

    monkeypatch.setattr(
        persistence_service,
        "fetch_url",
        AsyncMock(side_effect=fetch_error),
    )

    persist_failure = AsyncMock()

    monkeypatch.setattr(
        persistence_service,
        "_persist_fetch_failure",
        persist_failure,
    )

    with pytest.raises(HTTPException) as exc_info:
        await persistence_service.ingest_url(
            url=_url(),
            client=httpx.AsyncClient(),
            session=_session(),
        )

    assert exc_info.value is fetch_error

    persist_failure.assert_awaited_once()


@pytest.mark.asyncio
async def test_ingest_url_maps_unexpected_fetch_failure_to_502(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        persistence_service,
        "fetch_url",
        AsyncMock(side_effect=RuntimeError("unexpected fetch error")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await persistence_service.ingest_url(
            url=_url(),
            client=httpx.AsyncClient(),
            session=_session(),
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "URL fetch failed"


@pytest.mark.asyncio
async def test_ingest_url_maps_database_failure_to_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository_mock()

    repository.get_or_create_source.side_effect = SQLAlchemyError(
        "database unavailable"
    )

    monkeypatch.setattr(
        persistence_service,
        "fetch_url",
        AsyncMock(return_value=_response()),
    )

    monkeypatch.setattr(
        persistence_service,
        "IngestionRepository",
        lambda _session: repository,
    )

    with pytest.raises(HTTPException) as exc_info:
        await persistence_service.ingest_url(
            url=_url(),
            client=httpx.AsyncClient(),
            session=_session(),
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Persistence unavailable"


@pytest.mark.asyncio
async def test_ingest_parsed_url_persists_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository_mock()

    response = _response(
        content=b"<p>hello world</p>",
        content_type="text/html",
    )

    parsed = ParsedDocument(
        text="hello world",
        content_type="text/html",
        source_url="https://example.com/",
        byte_length=len(response.content),
        char_length=11,
    )

    monkeypatch.setattr(
        persistence_service,
        "fetch_url",
        AsyncMock(return_value=response),
    )

    monkeypatch.setattr(
        persistence_service,
        "parse_document",
        AsyncMock(return_value=parsed),
    )

    monkeypatch.setattr(
        persistence_service,
        "IngestionRepository",
        lambda _session: repository,
    )

    settings = Settings(
        max_preview_text_chars=5,
    )

    (
        ingestion_id,
        source_id,
        document_id,
        preview,
    ) = await persistence_service.ingest_parsed_url(
        url=_url(),
        client=httpx.AsyncClient(),
        session=_session(),
        app_settings=settings,
        request_id="request-parse",
    )

    assert (
        ingestion_id
        == repository.create_ingestion_record.return_value.ingestion_record_id
    )

    assert source_id == repository.get_or_create_source.return_value.source_id

    assert (
        document_id == repository.create_parsed_document.return_value.parsed_document_id
    )

    assert preview.parsed_content_type == "text/html"
    assert preview.parsed_char_length == 11
    assert preview.parsed_preview == "hello"

    repository.create_parsed_document.assert_awaited_once()

    document_await_args = repository.create_parsed_document.await_args
    assert document_await_args is not None

    document_kwargs = document_await_args.kwargs

    assert document_kwargs["content_type"] == "text/html"
    assert document_kwargs["char_length"] == 11
    assert document_kwargs["text_content"] == "hello world"

    await response.aclose()


@pytest.mark.asyncio
async def test_ingest_parsed_url_maps_unexpected_fetch_failure_to_502(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        persistence_service,
        "fetch_url",
        AsyncMock(side_effect=RuntimeError("unexpected fetch error")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await persistence_service.ingest_parsed_url(
            url=_url(),
            client=httpx.AsyncClient(),
            session=_session(),
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "URL fetch failed"


@pytest.mark.asyncio
async def test_ingest_parsed_url_records_parse_failure_without_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository_mock()

    parse_error = HTTPException(
        status_code=415,
        detail="Unsupported content type",
    )

    monkeypatch.setattr(
        persistence_service,
        "fetch_url",
        AsyncMock(
            return_value=_response(
                content=b"hello",
                content_type="text/plain",
            )
        ),
    )

    monkeypatch.setattr(
        persistence_service,
        "parse_document",
        AsyncMock(side_effect=parse_error),
    )

    monkeypatch.setattr(
        persistence_service,
        "IngestionRepository",
        lambda _session: repository,
    )

    with pytest.raises(HTTPException) as exc_info:
        await persistence_service.ingest_parsed_url(
            url=_url(),
            client=httpx.AsyncClient(),
            session=_session(),
        )

    assert exc_info.value is parse_error

    repository.create_ingestion_record.assert_awaited_once()
    repository.create_parsed_document.assert_not_awaited()

    await_args = repository.create_ingestion_record.await_args
    assert await_args is not None

    kwargs = await_args.kwargs

    assert kwargs["ingestion_mode"] == "parsed"
    assert kwargs["parse_error_code"] is not None
    assert kwargs["parse_error_message"] is not None


@pytest.mark.asyncio
async def test_ingest_parsed_url_maps_parse_failure_audit_database_error_to_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository_mock()

    repository.get_or_create_source.side_effect = SQLAlchemyError(
        "database unavailable"
    )

    response = _response(
        content=b"hello",
        content_type="text/plain",
    )

    parse_error = HTTPException(
        status_code=415,
        detail="Unsupported content type",
    )

    monkeypatch.setattr(
        persistence_service,
        "fetch_url",
        AsyncMock(return_value=response),
    )

    monkeypatch.setattr(
        persistence_service,
        "parse_document",
        AsyncMock(side_effect=parse_error),
    )

    monkeypatch.setattr(
        persistence_service,
        "IngestionRepository",
        lambda _session: repository,
    )

    with pytest.raises(HTTPException) as exc_info:
        await persistence_service.ingest_parsed_url(
            url=_url(),
            client=httpx.AsyncClient(),
            session=_session(),
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Persistence unavailable"

    await response.aclose()


@pytest.mark.asyncio
async def test_ingest_parsed_url_maps_unexpected_parse_error_to_502(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        persistence_service,
        "fetch_url",
        AsyncMock(return_value=_response()),
    )

    monkeypatch.setattr(
        persistence_service,
        "parse_document",
        AsyncMock(side_effect=RuntimeError("unexpected parser failure")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await persistence_service.ingest_parsed_url(
            url=_url(),
            client=httpx.AsyncClient(),
            session=_session(),
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "Document parsing failed"


@pytest.mark.asyncio
async def test_ingest_parsed_url_persists_fetch_failure_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_error = HTTPException(
        status_code=504,
        detail="URL fetch timed out",
    )

    monkeypatch.setattr(
        persistence_service,
        "fetch_url",
        AsyncMock(side_effect=fetch_error),
    )

    persist_failure = AsyncMock()

    monkeypatch.setattr(
        persistence_service,
        "_persist_fetch_failure",
        persist_failure,
    )

    with pytest.raises(HTTPException) as exc_info:
        await persistence_service.ingest_parsed_url(
            url=_url(),
            client=httpx.AsyncClient(),
            session=_session(),
        )

    assert exc_info.value is fetch_error

    persist_failure.assert_awaited_once()

    await_args = persist_failure.await_args
    assert await_args is not None

    kwargs = await_args.kwargs

    assert kwargs["ingestion_mode"] == "parsed"


@pytest.mark.asyncio
async def test_ingest_parsed_url_maps_persistence_failure_to_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository_mock()

    repository.get_or_create_source.side_effect = SQLAlchemyError(
        "database unavailable"
    )

    parsed = ParsedDocument(
        text="hello",
        content_type="text/plain",
        source_url="https://example.com/",
        byte_length=5,
        char_length=5,
    )

    monkeypatch.setattr(
        persistence_service,
        "fetch_url",
        AsyncMock(return_value=_response()),
    )

    monkeypatch.setattr(
        persistence_service,
        "parse_document",
        AsyncMock(return_value=parsed),
    )

    monkeypatch.setattr(
        persistence_service,
        "IngestionRepository",
        lambda _session: repository,
    )

    with pytest.raises(HTTPException) as exc_info:
        await persistence_service.ingest_parsed_url(
            url=_url(),
            client=httpx.AsyncClient(),
            session=_session(),
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Persistence unavailable"
