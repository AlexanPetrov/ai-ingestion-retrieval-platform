"""Read and administrative persistence operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_ingestion_retrieval_platform.persistence.models import (
    IngestionRecord,
    ParsedDocument,
    Source,
)


@dataclass(frozen=True, slots=True)
class DatabaseStats:
    """Persisted entity counts."""

    sources: int
    ingestion_records: int
    parsed_documents: int


@dataclass(frozen=True, slots=True)
class DatabasePurgeResult:
    """Counts of application rows removed by a database purge."""

    sources_deleted: int
    ingestion_records_deleted: int
    parsed_documents_deleted: int


@dataclass(frozen=True, slots=True)
class SourceSummary:
    """Administrative source representation."""

    id: str
    url: str
    created_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True, slots=True)
class IngestionSummary:
    """Administrative ingestion-list representation."""

    id: str
    source_id: str
    ingestion_mode: str
    batch_id: str | None
    batch_position: int | None
    ingested_at: datetime


@dataclass(frozen=True, slots=True)
class IngestionDetail:
    """Detailed administrative ingestion representation."""

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
    """Administrative parsed-document-list representation."""

    id: str
    ingestion_record_id: str
    content_type: str
    char_length: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ParsedDocumentDetail:
    """Detailed administrative parsed-document representation."""

    id: str
    ingestion_record_id: str
    content_type: str
    char_length: int
    text_content: str
    created_at: datetime


class AdminRepository:
    """Administrative persistence queries and mutations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_database_stats(self) -> DatabaseStats:
        """Return counts for persisted application entities."""
        source_result = await self._session.execute(
            select(func.count()).select_from(Source)
        )
        ingestion_result = await self._session.execute(
            select(func.count()).select_from(IngestionRecord)
        )
        document_result = await self._session.execute(
            select(func.count()).select_from(ParsedDocument)
        )

        return DatabaseStats(
            sources=source_result.scalar_one(),
            ingestion_records=ingestion_result.scalar_one(),
            parsed_documents=document_result.scalar_one(),
        )

    async def purge_database(self) -> DatabasePurgeResult:
        """Delete all persisted application data.

        The caller owns commit and rollback.

        PostgreSQL table locks prevent concurrent persistence writes from
        changing the dataset between the pre-delete counts and the deletes.
        Parsed documents are removed through the existing database-level
        cascade from ingestion records.
        """
        await self._session.execute(
            text(
                "LOCK TABLE source, ingestion_record, parsed_document "
                "IN ACCESS EXCLUSIVE MODE"
            )
        )

        stats = await self.get_database_stats()

        await self._session.execute(delete(IngestionRecord))
        await self._session.execute(delete(Source))

        return DatabasePurgeResult(
            sources_deleted=stats.sources,
            ingestion_records_deleted=stats.ingestion_records,
            parsed_documents_deleted=stats.parsed_documents,
        )

    async def list_sources(
        self,
        *,
        limit: int,
    ) -> list[SourceSummary]:
        """Return persisted sources ordered newest first."""
        result = await self._session.execute(
            select(Source).order_by(Source.created_at.desc()).limit(limit)
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

    async def get_source(
        self,
        source_id: str,
    ) -> SourceSummary | None:
        """Return one persisted source."""
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

    async def delete_source(
        self,
        source_id: str,
    ) -> bool:
        """Delete one source and report whether it existed.

        The repository does not commit the transaction.

        PostgreSQL remains responsible for enforcing the restrictive
        relationship from ingestion records to sources. A source that
        still has ingestion history therefore cannot be deleted.
        """
        result = await self._session.execute(
            delete(Source).where(Source.id == source_id).returning(Source.id)
        )

        deleted_id = result.scalar_one_or_none()

        return deleted_id is not None

    async def list_ingestions(
        self,
        *,
        limit: int,
    ) -> list[IngestionSummary]:
        """Return persisted ingestion records ordered newest first."""
        result = await self._session.execute(
            select(IngestionRecord)
            .order_by(IngestionRecord.ingested_at.desc())
            .limit(limit)
        )

        ingestions = result.scalars().all()

        return [
            IngestionSummary(
                id=str(ingestion.id),
                source_id=str(ingestion.source_id),
                ingestion_mode=ingestion.ingestion_mode,
                batch_id=(
                    str(ingestion.batch_id) if ingestion.batch_id is not None else None
                ),
                batch_position=ingestion.batch_position,
                ingested_at=ingestion.ingested_at,
            )
            for ingestion in ingestions
        ]

    async def get_ingestion(
        self,
        ingestion_id: str,
    ) -> IngestionDetail | None:
        """Return one persisted ingestion record."""
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

        ingestion = row[0]
        parsed_document_id = row[1]

        return IngestionDetail(
            id=str(ingestion.id),
            source_id=str(ingestion.source_id),
            parsed_document_id=(
                str(parsed_document_id) if parsed_document_id is not None else None
            ),
            ingestion_mode=ingestion.ingestion_mode,
            batch_id=(
                str(ingestion.batch_id) if ingestion.batch_id is not None else None
            ),
            batch_position=ingestion.batch_position,
            request_id=ingestion.request_id,
            client_ip=ingestion.client_ip,
            http_status=ingestion.http_status,
            http_status_reason=ingestion.http_status_reason,
            final_url=ingestion.final_url,
            response_content_type=ingestion.response_content_type,
            response_content_length=ingestion.response_content_length,
            fetch_elapsed_ms=ingestion.fetch_elapsed_ms,
            fetch_error_code=ingestion.fetch_error_code,
            fetch_error_message=ingestion.fetch_error_message,
            retry_attempts=ingestion.retry_attempts,
            fetched_at=ingestion.fetched_at,
            parser_name=ingestion.parser_name,
            parser_version=ingestion.parser_version,
            parse_elapsed_ms=ingestion.parse_elapsed_ms,
            parse_error_code=ingestion.parse_error_code,
            parse_error_message=ingestion.parse_error_message,
            ingested_at=ingestion.ingested_at,
        )

    async def delete_ingestion(
        self,
        ingestion_id: str,
    ) -> bool:
        """Delete one ingestion record and report whether it existed.

        The repository does not commit the transaction. Any linked parsed
        document is removed by the database-level ON DELETE CASCADE.
        """
        result = await self._session.execute(
            delete(IngestionRecord)
            .where(IngestionRecord.id == ingestion_id)
            .returning(IngestionRecord.id)
        )

        deleted_id = result.scalar_one_or_none()

        return deleted_id is not None

    async def list_documents(
        self,
        *,
        limit: int,
    ) -> list[ParsedDocumentSummary]:
        """Return persisted parsed documents ordered newest first."""
        result = await self._session.execute(
            select(ParsedDocument)
            .order_by(ParsedDocument.created_at.desc())
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
        """Return one persisted parsed document."""
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
