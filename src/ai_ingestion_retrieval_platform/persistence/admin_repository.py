"""Read-oriented persistence operations for administrative tooling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_ingestion_retrieval_platform.persistence.models import (
    IngestionRecord,
    ParsedDocument,
    Source,
)


@dataclass(frozen=True, slots=True)
class DatabaseStats:
    """Counts of persisted application entities."""

    sources: int
    ingestion_records: int
    parsed_documents: int


@dataclass(frozen=True, slots=True)
class SourceSummary:
    """Administrative summary of a persisted source."""

    id: str
    url: str
    created_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True, slots=True)
class IngestionSummary:
    """Administrative summary of a persisted ingestion record."""

    id: str
    source_id: str
    ingestion_mode: str
    batch_id: str | None
    batch_position: int | None
    ingested_at: datetime


@dataclass(frozen=True, slots=True)
class IngestionDetail:
    """Administrative detail for one persisted ingestion record."""

    id: str
    source_id: str
    parsed_document_id: str | None

    ingestion_mode: str

    batch_id: str | None
    batch_position: int | None

    request_id: str | None
    client_ip: str | None

    http_status: int | None
    http_status_reason: str | None
    final_url: str | None
    response_content_type: str | None
    response_content_length: int | None

    fetch_elapsed_ms: int | None
    fetch_error_code: str | None
    fetch_error_message: str | None
    retry_attempts: int
    fetched_at: datetime

    parser_name: str | None
    parser_version: str | None
    parse_elapsed_ms: int | None
    parse_error_code: str | None
    parse_error_message: str | None

    ingested_at: datetime


@dataclass(frozen=True, slots=True)
class ParsedDocumentSummary:
    """Administrative summary of a persisted parsed document."""

    id: str
    ingestion_record_id: str
    content_type: str
    char_length: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ParsedDocumentDetail:
    """Administrative detail for one persisted parsed document."""

    id: str
    ingestion_record_id: str
    content_type: str
    char_length: int
    text_content: str
    created_at: datetime


class AdminRepository:
    """Database queries used by administrative tooling."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_database_stats(self) -> DatabaseStats:
        """Return counts for the primary persistence entities."""
        source_count = await self._session.scalar(
            select(func.count()).select_from(Source)
        )
        ingestion_record_count = await self._session.scalar(
            select(func.count()).select_from(IngestionRecord)
        )
        parsed_document_count = await self._session.scalar(
            select(func.count()).select_from(ParsedDocument)
        )

        return DatabaseStats(
            sources=source_count or 0,
            ingestion_records=ingestion_record_count or 0,
            parsed_documents=parsed_document_count or 0,
        )

    async def list_sources(self, *, limit: int) -> list[SourceSummary]:
        """Return persisted sources ordered from newest to oldest."""
        result = await self._session.execute(
            select(Source)
            .order_by(
                Source.created_at.desc(),
                Source.id.desc(),
            )
            .limit(limit)
        )

        sources = result.scalars().all()

        return [
            SourceSummary(
                id=str(source.id),
                url=source.url,
                created_at=source.created_at,
                last_seen_at=source.last_seen_at,
            )
            for source in sources
        ]

    async def get_source(self, source_id: str) -> SourceSummary | None:
        """Return one persisted source by ID."""
        result = await self._session.execute(
            select(Source).where(Source.id == source_id)
        )

        source = result.scalar_one_or_none()

        if source is None:
            return None

        return SourceSummary(
            id=str(source.id),
            url=source.url,
            created_at=source.created_at,
            last_seen_at=source.last_seen_at,
        )

    async def list_ingestions(self, *, limit: int) -> list[IngestionSummary]:
        """Return ingestion records ordered from newest to oldest."""
        result = await self._session.execute(
            select(IngestionRecord)
            .order_by(
                IngestionRecord.ingested_at.desc(),
                IngestionRecord.id.desc(),
            )
            .limit(limit)
        )

        ingestion_records = result.scalars().all()

        return [
            IngestionSummary(
                id=str(record.id),
                source_id=str(record.source_id),
                ingestion_mode=record.ingestion_mode,
                batch_id=(
                    str(record.batch_id) if record.batch_id is not None else None
                ),
                batch_position=record.batch_position,
                ingested_at=record.ingested_at,
            )
            for record in ingestion_records
        ]

    async def get_ingestion(
        self,
        ingestion_id: str,
    ) -> IngestionDetail | None:
        """Return one persisted ingestion record by ID."""
        result = await self._session.execute(
            select(
                IngestionRecord,
                ParsedDocument.id,
            )
            .outerjoin(
                ParsedDocument,
                ParsedDocument.ingestion_record_id == IngestionRecord.id,
            )
            .where(IngestionRecord.id == ingestion_id)
        )

        row = result.one_or_none()

        if row is None:
            return None

        record, parsed_document_id = row

        return IngestionDetail(
            id=str(record.id),
            source_id=str(record.source_id),
            parsed_document_id=(
                str(parsed_document_id) if parsed_document_id is not None else None
            ),
            ingestion_mode=record.ingestion_mode,
            batch_id=(str(record.batch_id) if record.batch_id is not None else None),
            batch_position=record.batch_position,
            request_id=record.request_id,
            client_ip=record.client_ip,
            http_status=record.http_status,
            http_status_reason=record.http_status_reason,
            final_url=record.final_url,
            response_content_type=record.response_content_type,
            response_content_length=record.response_content_length,
            fetch_elapsed_ms=record.fetch_elapsed_ms,
            fetch_error_code=record.fetch_error_code,
            fetch_error_message=record.fetch_error_message,
            retry_attempts=record.retry_attempts,
            fetched_at=record.fetched_at,
            parser_name=record.parser_name,
            parser_version=record.parser_version,
            parse_elapsed_ms=record.parse_elapsed_ms,
            parse_error_code=record.parse_error_code,
            parse_error_message=record.parse_error_message,
            ingested_at=record.ingested_at,
        )

    async def list_documents(
        self,
        *,
        limit: int,
    ) -> list[ParsedDocumentSummary]:
        """Return parsed documents ordered from newest to oldest."""
        result = await self._session.execute(
            select(ParsedDocument)
            .order_by(
                ParsedDocument.created_at.desc(),
                ParsedDocument.id.desc(),
            )
            .limit(limit)
        )

        documents = result.scalars().all()

        return [
            ParsedDocumentSummary(
                id=str(document.id),
                ingestion_record_id=str(document.ingestion_record_id),
                content_type=document.content_type,
                char_length=document.char_length,
                created_at=document.created_at,
            )
            for document in documents
        ]

    async def get_document(
        self,
        document_id: str,
    ) -> ParsedDocumentDetail | None:
        """Return one persisted parsed document by ID."""
        result = await self._session.execute(
            select(ParsedDocument).where(ParsedDocument.id == document_id)
        )

        document = result.scalar_one_or_none()

        if document is None:
            return None

        return ParsedDocumentDetail(
            id=str(document.id),
            ingestion_record_id=str(document.ingestion_record_id),
            content_type=document.content_type,
            char_length=document.char_length,
            text_content=document.text_content,
            created_at=document.created_at,
        )
