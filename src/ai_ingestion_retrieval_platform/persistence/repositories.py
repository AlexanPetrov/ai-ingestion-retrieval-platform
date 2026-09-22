"""Async repository for persisted ingestion data access."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ai_ingestion_retrieval_platform.persistence.models import (
    IngestionRecord,
    ParsedDocument,
    Source,
)


@dataclass(frozen=True)
class SourceResult:
    """Result of resolving a persisted source."""

    source_id: UUID


@dataclass(frozen=True)
class IngestionRecordResult:
    """Result of creating an ingestion record."""

    ingestion_record_id: UUID


@dataclass(frozen=True)
class ParsedDocumentResult:
    """Result of creating a parsed document."""

    parsed_document_id: UUID


@dataclass(frozen=True)
class ParsedContentIdentityResult:
    """Identity metadata for one successfully parsed persisted document."""

    parsed_document_id: UUID
    content_sha256: str


class IngestionRepository:
    """Database operations for persisted ingestion workflows.

    The repository owns SQL construction and ORM persistence operations.

    It does not commit or roll back transactions. Transaction ownership belongs
    to the service layer so one complete ingestion operation can succeed or fail
    atomically.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to an active asynchronous database session."""
        self._session = session

    async def get_or_create_source(
        self,
        *,
        url: str,
    ) -> SourceResult:
        """Resolve the stable Source row for a URL.

        Concurrent attempts to persist the same URL are handled atomically by
        PostgreSQL's unique constraint and ON CONFLICT behavior.

        Existing sources have last_seen_at refreshed. New sources receive their
        normal database defaults for created_at and last_seen_at.

        Args:
            url: Canonical URL represented by the Source.

        Returns:
            SourceResult containing the stable source identifier.
        """
        statement = (
            insert(Source)
            .values(url=url)
            .on_conflict_do_update(
                constraint="uq_source_url",
                set_={
                    "last_seen_at": func.now(),
                },
            )
            .returning(Source.id)
        )

        result = await self._session.execute(statement)

        return SourceResult(
            source_id=result.scalar_one(),
        )

    async def create_ingestion_record(
        self,
        *,
        source_id: UUID,
        ingestion_mode: str,
        batch_id: UUID | None,
        batch_position: int | None,
        request_id: str | None,
        client_ip: str | None,
        http_status: int | None,
        http_status_reason: str | None,
        final_url: str | None,
        response_content_type: str | None,
        response_content_length: int | None,
        fetch_elapsed_ms: int | None,
        fetch_error_code: str | None,
        fetch_error_message: str | None,
        retry_attempts: int,
        fetched_at: datetime | None = None,
        parser_name: str | None = None,
        parser_version: str | None = None,
        parse_elapsed_ms: int | None = None,
        parse_error_code: str | None = None,
        parse_error_message: str | None = None,
    ) -> IngestionRecordResult:
        """Create one immutable persisted-ingestion audit record.

        Fetch and parser metadata belongs to this record because it describes
        one specific ingestion attempt rather than the stable Source.

        The record is flushed so its generated identifier is available to the
        caller. The transaction is not committed here.

        Args:
            source_id: Stable Source being ingested.
            ingestion_mode: Either ``raw`` or ``parsed``.
            batch_id: Batch identifier for batch ingestion, otherwise None.
            batch_position: Zero-based original batch position, otherwise None.
            request_id: HTTP request correlation identifier.
            client_ip: Client network address for audit correlation.
            http_status: Final upstream HTTP status when available.
            http_status_reason: Upstream HTTP reason phrase when available.
            final_url: Final validated URL after redirects, when available.
            response_content_type: Final response Content-Type.
            response_content_length: Actual admitted response body size.
            fetch_elapsed_ms: Fetch duration in milliseconds.
            fetch_error_code: Normalized fetch error code on failure.
            fetch_error_message: Safe fetch error description on failure.
            retry_attempts: Number of retries performed.
            fetched_at: Time the fetch attempt completed.
            parser_name: Parser implementation identifier for parsed ingestion.
            parser_version: Parser implementation version when available.
            parse_elapsed_ms: Parser duration in milliseconds.
            parse_error_code: Normalized parser error code on failure.
            parse_error_message: Safe parser error description on failure.

        Returns:
            IngestionRecordResult containing the new audit-record identifier.
        """
        record = IngestionRecord(
            source_id=source_id,
            ingestion_mode=ingestion_mode,
            batch_id=batch_id,
            batch_position=batch_position,
            request_id=request_id,
            client_ip=client_ip,
            http_status=http_status,
            http_status_reason=http_status_reason,
            final_url=final_url,
            response_content_type=response_content_type,
            response_content_length=response_content_length,
            fetch_elapsed_ms=fetch_elapsed_ms,
            fetch_error_code=fetch_error_code,
            fetch_error_message=fetch_error_message,
            retry_attempts=retry_attempts,
            parser_name=parser_name,
            parser_version=parser_version,
            parse_elapsed_ms=parse_elapsed_ms,
            parse_error_code=parse_error_code,
            parse_error_message=parse_error_message,
        )

        if fetched_at is not None:
            record.fetched_at = fetched_at

        self._session.add(record)
        await self._session.flush()

        return IngestionRecordResult(
            ingestion_record_id=record.id,
        )

    async def create_parsed_document(
        self,
        *,
        ingestion_record_id: UUID,
        content_type: str,
        char_length: int,
        text_content: str,
        content_sha256: str,
    ) -> ParsedDocumentResult:
        """Persist successful parser output for one ingestion attempt.

        Failed parsing does not create a ParsedDocument. Its failure metadata is
        stored on the corresponding IngestionRecord instead.

        Args:
            ingestion_record_id: Parsed ingestion attempt that produced content.
            content_type: Normalized parsed document content type.
            char_length: Character count of the persisted text.
            text_content: Full admitted parser output.
            content_sha256: SHA-256 of the exact UTF-8 encoded persisted text.

        Returns:
            ParsedDocumentResult containing the generated document identifier.
        """
        document = ParsedDocument(
            ingestion_record_id=ingestion_record_id,
            content_type=content_type,
            char_length=char_length,
            text_content=text_content,
            content_sha256=content_sha256,
        )

        self._session.add(document)
        await self._session.flush()

        return ParsedDocumentResult(
            parsed_document_id=document.id,
        )

    async def get_source_by_url(
        self,
        *,
        url: str,
    ) -> Source | None:
        """Retrieve a Source by its canonical URL."""
        statement = select(Source).where(Source.url == url)

        result = await self._session.execute(statement)

        return result.scalar_one_or_none()

    async def get_source_by_id(
        self,
        *,
        source_id: UUID,
    ) -> Source | None:
        """Retrieve a Source by identifier."""
        statement = select(Source).where(Source.id == source_id)

        result = await self._session.execute(statement)

        return result.scalar_one_or_none()

    async def get_ingestion_record_by_id(
        self,
        *,
        ingestion_record_id: UUID,
    ) -> IngestionRecord | None:
        """Retrieve one ingestion audit record by identifier."""
        statement = select(IngestionRecord).where(
            IngestionRecord.id == ingestion_record_id
        )

        result = await self._session.execute(statement)

        return result.scalar_one_or_none()

    async def get_ingestion_records_by_batch_id(
        self,
        *,
        batch_id: UUID,
    ) -> list[IngestionRecord]:
        """Retrieve a batch in its original request order."""
        statement = (
            select(IngestionRecord)
            .where(IngestionRecord.batch_id == batch_id)
            .order_by(IngestionRecord.batch_position.asc())
        )

        result = await self._session.execute(statement)

        return list(result.scalars().all())

    async def get_parsed_document_by_id(
        self,
        *,
        parsed_document_id: UUID,
    ) -> ParsedDocument | None:
        """Retrieve one successfully parsed document by identifier."""
        statement = select(ParsedDocument).where(
            ParsedDocument.id == parsed_document_id
        )

        result = await self._session.execute(statement)

        return result.scalar_one_or_none()

    async def get_parsed_document_for_ingestion(
        self,
        *,
        ingestion_record_id: UUID,
    ) -> ParsedDocument | None:
        """Retrieve successful parser output for an ingestion attempt."""
        statement = select(ParsedDocument).where(
            ParsedDocument.ingestion_record_id == ingestion_record_id
        )

        result = await self._session.execute(statement)

        return result.scalar_one_or_none()

    async def get_latest_parsed_content_identity_for_source(
        self,
        *,
        source_id: UUID,
    ) -> ParsedContentIdentityResult | None:
        """Return identity metadata for the latest successful parse of a Source.

        Raw ingestions, failed fetches, and failed parses are naturally excluded
        because a successful ParsedDocument must exist. The explicit parsed-mode
        predicate additionally protects the semantic contract against invalid
        application data.

        The latest successful parse is determined by ingestion timestamp. The
        parsed-document creation timestamp and identifier provide deterministic
        tie-breaking if timestamps are equal.

        Args:
            source_id: Stable Source whose latest successful parsed content is
                requested.

        Returns:
            ParsedContentIdentityResult for the latest successful parse, or None
            when the Source has no successfully persisted parsed document.
        """
        statement = (
            select(
                ParsedDocument.id,
                ParsedDocument.content_sha256,
            )
            .join(
                IngestionRecord,
                ParsedDocument.ingestion_record_id == IngestionRecord.id,
            )
            .where(
                IngestionRecord.source_id == source_id,
                IngestionRecord.ingestion_mode == "parsed",
            )
            .order_by(
                IngestionRecord.ingested_at.desc(),
                ParsedDocument.created_at.desc(),
                ParsedDocument.id.desc(),
            )
            .limit(1)
        )

        result = await self._session.execute(statement)
        row = result.one_or_none()

        if row is None:
            return None

        parsed_document_id, content_sha256 = row

        return ParsedContentIdentityResult(
            parsed_document_id=parsed_document_id,
            content_sha256=content_sha256,
        )
