"""Pydantic response schemas for persisted ingestion operations."""

from typing import Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from ai_ingestion_retrieval_platform.schemas.ingestion import (
    UrlIngestionError,
)


class UrlIngestedPreview(BaseModel):
    """Successful persisted raw ingestion result."""

    url: str

    ingestion_record_id: UUID = Field(
        description="Identifier for this specific persisted ingestion attempt.",
    )

    source_id: UUID = Field(
        description="Stable identifier for the external source URL.",
    )

    status_code: int
    content_type: str | None
    content_length: int
    elapsed_ms: float
    preview: str


class UrlParsedIngestedPreview(BaseModel):
    """Successful persisted parsed ingestion result."""

    url: str

    ingestion_record_id: UUID = Field(
        description="Identifier for this specific persisted ingestion attempt.",
    )

    source_id: UUID = Field(
        description="Stable identifier for the external source URL.",
    )

    parsed_document_id: UUID = Field(
        description="Identifier for the successfully persisted parsed document.",
    )

    status_code: int
    content_type: str | None
    content_length: int
    elapsed_ms: float

    parsed_content_type: str
    parsed_char_length: int
    parsed_preview: str


class UrlIngestedBatchResult(BaseModel):
    """Result for one URL within a persisted raw-ingestion batch."""

    url: str
    success: bool
    data: UrlIngestedPreview | None = None
    error: UrlIngestionError | None = None

    @model_validator(mode="after")
    def validate_result_shape(self) -> Self:
        """Require exactly one of data or error based on success."""
        if self.success:
            if self.data is None:
                raise ValueError("successful batch result requires data")

            if self.error is not None:
                raise ValueError("successful batch result cannot contain an error")

        else:
            if self.data is not None:
                raise ValueError("failed batch result cannot contain data")

            if self.error is None:
                raise ValueError("failed batch result requires an error")

        return self


class UrlParsedIngestedBatchResult(BaseModel):
    """Result for one URL within a persisted parsed-ingestion batch."""

    url: str
    success: bool
    data: UrlParsedIngestedPreview | None = None
    error: UrlIngestionError | None = None

    @model_validator(mode="after")
    def validate_result_shape(self) -> Self:
        """Require exactly one of data or error based on success."""
        if self.success:
            if self.data is None:
                raise ValueError("successful batch result requires data")

            if self.error is not None:
                raise ValueError("successful batch result cannot contain an error")

        else:
            if self.data is not None:
                raise ValueError("failed batch result cannot contain data")

            if self.error is None:
                raise ValueError("failed batch result requires an error")

        return self


class BatchIngestResponse(BaseModel):
    """Response for one persisted raw-ingestion batch."""

    batch_id: UUID = Field(
        description="Identifier shared by every ingestion attempt in this batch.",
    )

    results: list[UrlIngestedBatchResult] = Field(
        description="Per-URL results in original request order.",
    )


class BatchParsedIngestResponse(BaseModel):
    """Response for one persisted parsed-ingestion batch."""

    batch_id: UUID = Field(
        description="Identifier shared by every ingestion attempt in this batch.",
    )

    results: list[UrlParsedIngestedBatchResult] = Field(
        description="Per-URL results in original request order.",
    )
