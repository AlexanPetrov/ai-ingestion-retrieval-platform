"""Unit tests for persisted-ingestion response schemas."""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from ai_ingestion_retrieval_platform.schemas.ingestion import (
    UrlIngestionError,
)
from ai_ingestion_retrieval_platform.schemas.persistence import (
    BatchIngestResponse,
    BatchParsedIngestResponse,
    UrlIngestedBatchResult,
    UrlIngestedPreview,
    UrlParsedIngestedBatchResult,
    UrlParsedIngestedPreview,
)


def _raw_preview() -> UrlIngestedPreview:
    return UrlIngestedPreview(
        url="https://example.com/",
        ingestion_record_id=uuid4(),
        source_id=uuid4(),
        status_code=200,
        content_type="text/plain",
        content_length=5,
        elapsed_ms=1.0,
        preview="hello",
    )


def _parsed_preview() -> UrlParsedIngestedPreview:
    return UrlParsedIngestedPreview(
        url="https://example.com/",
        ingestion_record_id=uuid4(),
        source_id=uuid4(),
        parsed_document_id=uuid4(),
        status_code=200,
        content_type="text/html",
        content_length=12,
        elapsed_ms=2.0,
        parsed_content_type="text/html",
        parsed_char_length=5,
        parsed_preview="hello",
    )


def _error() -> UrlIngestionError:
    return UrlIngestionError(
        code="fetch_failed",
        message="URL fetch failed",
        status_code=502,
    )


def test_raw_success_batch_result_accepts_data_only() -> None:
    data = _raw_preview()

    result = UrlIngestedBatchResult(
        url=data.url,
        success=True,
        data=data,
        error=None,
    )

    assert result.data is data
    assert result.error is None


def test_raw_failure_batch_result_accepts_error_only() -> None:
    error = _error()

    result = UrlIngestedBatchResult(
        url="https://example.com/",
        success=False,
        data=None,
        error=error,
    )

    assert result.data is None
    assert result.error is error


@pytest.mark.parametrize(
    ("success", "with_data", "with_error"),
    [
        (True, False, False),
        (True, True, True),
        (False, True, False),
        (False, False, False),
    ],
)
def test_raw_batch_result_rejects_invalid_shapes(
    success: bool,
    with_data: bool,
    with_error: bool,
) -> None:
    with pytest.raises(ValidationError):
        UrlIngestedBatchResult(
            url="https://example.com/",
            success=success,
            data=_raw_preview() if with_data else None,
            error=_error() if with_error else None,
        )


def test_parsed_success_batch_result_accepts_data_only() -> None:
    data = _parsed_preview()

    result = UrlParsedIngestedBatchResult(
        url=data.url,
        success=True,
        data=data,
        error=None,
    )

    assert result.data is data
    assert result.error is None


def test_parsed_failure_batch_result_accepts_error_only() -> None:
    error = _error()

    result = UrlParsedIngestedBatchResult(
        url="https://example.com/",
        success=False,
        data=None,
        error=error,
    )

    assert result.data is None
    assert result.error is error


@pytest.mark.parametrize(
    ("success", "with_data", "with_error"),
    [
        (True, False, False),
        (True, True, True),
        (False, True, False),
        (False, False, False),
    ],
)
def test_parsed_batch_result_rejects_invalid_shapes(
    success: bool,
    with_data: bool,
    with_error: bool,
) -> None:
    with pytest.raises(ValidationError):
        UrlParsedIngestedBatchResult(
            url="https://example.com/",
            success=success,
            data=_parsed_preview() if with_data else None,
            error=_error() if with_error else None,
        )


def test_raw_batch_response_uses_uuid_batch_id() -> None:
    batch_id = uuid4()
    data = _raw_preview()

    response = BatchIngestResponse(
        batch_id=batch_id,
        results=[
            UrlIngestedBatchResult(
                url=data.url,
                success=True,
                data=data,
            )
        ],
    )

    assert isinstance(response.batch_id, UUID)
    assert response.batch_id == batch_id


def test_parsed_batch_response_uses_uuid_batch_id() -> None:
    batch_id = uuid4()
    data = _parsed_preview()

    response = BatchParsedIngestResponse(
        batch_id=batch_id,
        results=[
            UrlParsedIngestedBatchResult(
                url=data.url,
                success=True,
                data=data,
            )
        ],
    )

    assert isinstance(response.batch_id, UUID)
    assert response.batch_id == batch_id
