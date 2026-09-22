"""Application workflows for fetching, parsing, and persisting URL ingestion."""

from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID

import httpx
import structlog
from fastapi import HTTPException
from pydantic import AnyHttpUrl
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ai_ingestion_retrieval_platform.core.config import Settings
from ai_ingestion_retrieval_platform.core.content_identity import (
    calculate_content_sha256,
)
from ai_ingestion_retrieval_platform.persistence.repositories import (
    IngestionRepository,
)
from ai_ingestion_retrieval_platform.schemas.ingestion import (
    UrlIngestionPreview,
    UrlParsedIngestionPreview,
)
from ai_ingestion_retrieval_platform.schemas.parsing import ParseRequest
from ai_ingestion_retrieval_platform.services.fetching import (
    fetch_url,
    resolve_settings,
)
from ai_ingestion_retrieval_platform.services.ingestion import (
    build_ingestion_error,
)
from ai_ingestion_retrieval_platform.services.parsing import (
    ParserHTTPException,
    parse_document,
)

logger = structlog.get_logger()


def _elapsed_ms(started_at: float) -> int:
    """Return elapsed monotonic time in whole milliseconds."""
    return max(0, round((perf_counter() - started_at) * 1000))


def _get_parser_failure_provenance(
    exc: HTTPException,
) -> tuple[str | None, str | None]:
    """Return parser provenance carried by an expected parser failure."""

    if isinstance(exc, ParserHTTPException):
        return (
            exc.parser_name,
            exc.parser_version,
        )

    return (
        None,
        None,
    )


async def _persist_fetch_failure(
    *,
    session: AsyncSession,
    url: str,
    ingestion_mode: str,
    request_id: str | None,
    client_ip: str | None,
    batch_id: UUID | None,
    batch_position: int | None,
    fetch_elapsed_ms: int,
    error_code: str,
    error_message: str,
) -> tuple[UUID, UUID]:
    """Persist one failed fetch attempt.

    Failure auditing is itself part of persistent ingestion. If the database
    write fails, the endpoint reports a persistence failure rather than
    pretending the failed ingestion attempt was recorded.
    """
    repository = IngestionRepository(session)

    try:
        async with session.begin():
            source = await repository.get_or_create_source(
                url=url,
            )

            ingestion = await repository.create_ingestion_record(
                source_id=source.source_id,
                ingestion_mode=ingestion_mode,
                batch_id=batch_id,
                batch_position=batch_position,
                request_id=request_id,
                client_ip=client_ip,
                http_status=None,
                http_status_reason=None,
                final_url=None,
                response_content_type=None,
                response_content_length=None,
                fetch_elapsed_ms=fetch_elapsed_ms,
                fetch_error_code=error_code,
                fetch_error_message=error_message,
                retry_attempts=0,
                fetched_at=datetime.now(UTC),
            )

        return (
            ingestion.ingestion_record_id,
            source.source_id,
        )

    except SQLAlchemyError as exc:
        logger.exception(
            "ingestion_failure_audit_persistence_failed",
            request_id=request_id,
            ingestion_mode=ingestion_mode,
        )
        raise HTTPException(
            status_code=503,
            detail="Persistence unavailable",
        ) from exc


async def ingest_url(
    url: AnyHttpUrl,
    client: httpx.AsyncClient,
    session: AsyncSession,
    url_timeout: float | None = None,
    app_settings: Settings | None = None,
    request_id: str | None = None,
    client_ip: str | None = None,
    batch_id: UUID | None = None,
    batch_position: int | None = None,
) -> tuple[UUID, UUID, UrlIngestionPreview]:
    """Fetch one URL and persist the ingestion attempt.

    Network work completes before the database transaction begins so a slow
    upstream request does not hold a database transaction open.
    """
    settings = resolve_settings(app_settings)
    url_str = str(url)

    logger.info(
        "url_ingest_started",
        request_id=request_id,
        batch_id=str(batch_id) if batch_id is not None else None,
        batch_position=batch_position,
    )

    fetch_started_at = perf_counter()

    try:
        response = await fetch_url(
            client,
            url_str,
            url_timeout=url_timeout,
            app_settings=settings,
        )

    except HTTPException as exc:
        fetch_elapsed_ms = _elapsed_ms(fetch_started_at)
        error = build_ingestion_error(exc)

        await _persist_fetch_failure(
            session=session,
            url=url_str,
            ingestion_mode="raw",
            request_id=request_id,
            client_ip=client_ip,
            batch_id=batch_id,
            batch_position=batch_position,
            fetch_elapsed_ms=fetch_elapsed_ms,
            error_code=error.code,
            error_message=error.message,
        )

        logger.warning(
            "url_ingest_fetch_failed",
            request_id=request_id,
            batch_id=str(batch_id) if batch_id is not None else None,
            batch_position=batch_position,
            error_code=error.code,
            fetch_elapsed_ms=fetch_elapsed_ms,
        )
        raise

    except Exception as exc:
        logger.exception(
            "url_ingest_fetch_failed_unexpectedly",
            request_id=request_id,
            batch_id=str(batch_id) if batch_id is not None else None,
            batch_position=batch_position,
        )
        raise HTTPException(
            status_code=502,
            detail="URL fetch failed",
        ) from exc

    fetch_elapsed_ms = _elapsed_ms(fetch_started_at)
    repository = IngestionRepository(session)

    try:
        async with session.begin():
            source = await repository.get_or_create_source(
                url=url_str,
            )

            ingestion = await repository.create_ingestion_record(
                source_id=source.source_id,
                ingestion_mode="raw",
                batch_id=batch_id,
                batch_position=batch_position,
                request_id=request_id,
                client_ip=client_ip,
                http_status=response.status_code,
                http_status_reason=response.reason_phrase,
                # Current fetch contract does not expose a trustworthy
                # canonical final URL independently of pinned-IP fetching.
                final_url=None,
                response_content_type=response.headers.get("content-type"),
                response_content_length=len(response.content),
                fetch_elapsed_ms=fetch_elapsed_ms,
                fetch_error_code=None,
                fetch_error_message=None,
                # Current fetch contract does not expose retry-count metadata.
                retry_attempts=0,
                fetched_at=datetime.now(UTC),
            )

    except SQLAlchemyError as exc:
        logger.exception(
            "url_ingest_persistence_failed",
            request_id=request_id,
            batch_id=str(batch_id) if batch_id is not None else None,
            batch_position=batch_position,
        )
        raise HTTPException(
            status_code=503,
            detail="Persistence unavailable",
        ) from exc

    preview = UrlIngestionPreview(
        url=url_str,
        status_code=response.status_code,
        content_type=response.headers.get("content-type"),
        content_length=len(response.content),
        elapsed_ms=float(fetch_elapsed_ms),
        preview=response.text[: settings.max_preview_text_chars],
    )

    logger.info(
        "url_ingest_completed",
        request_id=request_id,
        ingestion_record_id=str(ingestion.ingestion_record_id),
        source_id=str(source.source_id),
        fetch_elapsed_ms=fetch_elapsed_ms,
    )

    return (
        ingestion.ingestion_record_id,
        source.source_id,
        preview,
    )


async def ingest_parsed_url(
    url: AnyHttpUrl,
    client: httpx.AsyncClient,
    session: AsyncSession,
    url_timeout: float | None = None,
    app_settings: Settings | None = None,
    request_id: str | None = None,
    client_ip: str | None = None,
    batch_id: UUID | None = None,
    batch_position: int | None = None,
) -> tuple[UUID, UUID, UUID, UrlParsedIngestionPreview]:
    """Fetch, parse, and persist one URL.

    Fetching and parsing happen before a database transaction is opened.
    Successful parsing creates the IngestionRecord and ParsedDocument in one
    atomic transaction.

    Parse failures create an IngestionRecord containing parser failure metadata
    but do not create a ParsedDocument.
    """
    settings = resolve_settings(app_settings)
    url_str = str(url)

    logger.info(
        "url_parse_ingest_started",
        request_id=request_id,
        batch_id=str(batch_id) if batch_id is not None else None,
        batch_position=batch_position,
    )

    fetch_started_at = perf_counter()

    try:
        response = await fetch_url(
            client,
            url_str,
            url_timeout=url_timeout,
            max_bytes=settings.max_parse_bytes,
            allowed_content_types=settings.allowed_parse_content_types,
            app_settings=settings,
        )

    except HTTPException as exc:
        fetch_elapsed_ms = _elapsed_ms(fetch_started_at)
        error = build_ingestion_error(exc)

        await _persist_fetch_failure(
            session=session,
            url=url_str,
            ingestion_mode="parsed",
            request_id=request_id,
            client_ip=client_ip,
            batch_id=batch_id,
            batch_position=batch_position,
            fetch_elapsed_ms=fetch_elapsed_ms,
            error_code=error.code,
            error_message=error.message,
        )

        logger.warning(
            "url_parse_ingest_fetch_failed",
            request_id=request_id,
            batch_id=str(batch_id) if batch_id is not None else None,
            batch_position=batch_position,
            error_code=error.code,
            fetch_elapsed_ms=fetch_elapsed_ms,
        )
        raise

    except Exception as exc:
        logger.exception(
            "url_parse_ingest_fetch_failed_unexpectedly",
            request_id=request_id,
            batch_id=str(batch_id) if batch_id is not None else None,
            batch_position=batch_position,
        )
        raise HTTPException(
            status_code=502,
            detail="URL fetch failed",
        ) from exc

    fetch_elapsed_ms = _elapsed_ms(fetch_started_at)
    parse_started_at = perf_counter()

    try:
        parsed = await parse_document(
            ParseRequest(
                content=response.content,
                content_type=(
                    response.headers.get("content-type") or "application/octet-stream"
                ),
                source_url=url_str,
            ),
            settings=settings,
        )

    except HTTPException as exc:
        parse_elapsed_ms = _elapsed_ms(parse_started_at)
        error = build_ingestion_error(exc)
        parser_name, parser_version = _get_parser_failure_provenance(exc)

        repository = IngestionRepository(session)

        try:
            async with session.begin():
                source = await repository.get_or_create_source(
                    url=url_str,
                )

                await repository.create_ingestion_record(
                    source_id=source.source_id,
                    ingestion_mode="parsed",
                    batch_id=batch_id,
                    batch_position=batch_position,
                    request_id=request_id,
                    client_ip=client_ip,
                    http_status=response.status_code,
                    http_status_reason=response.reason_phrase,
                    final_url=None,
                    response_content_type=response.headers.get("content-type"),
                    response_content_length=len(response.content),
                    fetch_elapsed_ms=fetch_elapsed_ms,
                    fetch_error_code=None,
                    fetch_error_message=None,
                    retry_attempts=0,
                    fetched_at=datetime.now(UTC),
                    parser_name=parser_name,
                    parser_version=parser_version,
                    parse_elapsed_ms=parse_elapsed_ms,
                    parse_error_code=error.code,
                    parse_error_message=error.message,
                )

        except SQLAlchemyError as db_exc:
            logger.exception(
                "url_parse_failure_audit_persistence_failed",
                request_id=request_id,
                batch_id=str(batch_id) if batch_id is not None else None,
                batch_position=batch_position,
            )
            raise HTTPException(
                status_code=503,
                detail="Persistence unavailable",
            ) from db_exc

        logger.warning(
            "url_parse_ingest_parse_failed",
            request_id=request_id,
            batch_id=str(batch_id) if batch_id is not None else None,
            batch_position=batch_position,
            error_code=error.code,
            parse_elapsed_ms=parse_elapsed_ms,
        )
        raise

    except Exception as exc:
        logger.exception(
            "url_parse_ingest_parse_failed_unexpectedly",
            request_id=request_id,
            batch_id=str(batch_id) if batch_id is not None else None,
            batch_position=batch_position,
        )
        raise HTTPException(
            status_code=502,
            detail="Document parsing failed",
        ) from exc

    parse_elapsed_ms = _elapsed_ms(parse_started_at)
    content_sha256 = calculate_content_sha256(parsed.text)
    repository = IngestionRepository(session)

    try:
        async with session.begin():
            source = await repository.get_or_create_source(
                url=url_str,
            )

            ingestion = await repository.create_ingestion_record(
                source_id=source.source_id,
                ingestion_mode="parsed",
                batch_id=batch_id,
                batch_position=batch_position,
                request_id=request_id,
                client_ip=client_ip,
                http_status=response.status_code,
                http_status_reason=response.reason_phrase,
                final_url=None,
                response_content_type=response.headers.get("content-type"),
                response_content_length=len(response.content),
                fetch_elapsed_ms=fetch_elapsed_ms,
                fetch_error_code=None,
                fetch_error_message=None,
                retry_attempts=0,
                fetched_at=datetime.now(UTC),
                parser_name=parsed.parser_name,
                parser_version=parsed.parser_version,
                parse_elapsed_ms=parse_elapsed_ms,
                parse_error_code=None,
                parse_error_message=None,
            )

            document = await repository.create_parsed_document(
                ingestion_record_id=ingestion.ingestion_record_id,
                content_type=parsed.content_type,
                char_length=parsed.char_length,
                text_content=parsed.text,
                content_sha256=content_sha256,
            )

    except SQLAlchemyError as exc:
        logger.exception(
            "url_parse_ingest_persistence_failed",
            request_id=request_id,
            batch_id=str(batch_id) if batch_id is not None else None,
            batch_position=batch_position,
        )
        raise HTTPException(
            status_code=503,
            detail="Persistence unavailable",
        ) from exc

    preview = UrlParsedIngestionPreview(
        url=url_str,
        status_code=response.status_code,
        content_type=response.headers.get("content-type"),
        content_length=len(response.content),
        elapsed_ms=float(fetch_elapsed_ms),
        parsed_content_type=parsed.content_type,
        parsed_char_length=parsed.char_length,
        parsed_preview=parsed.text[: settings.max_preview_text_chars],
    )

    logger.info(
        "url_parse_ingest_completed",
        request_id=request_id,
        ingestion_record_id=str(ingestion.ingestion_record_id),
        source_id=str(source.source_id),
        parsed_document_id=str(document.parsed_document_id),
        fetch_elapsed_ms=fetch_elapsed_ms,
        parse_elapsed_ms=parse_elapsed_ms,
    )

    return (
        ingestion.ingestion_record_id,
        source.source_id,
        document.parsed_document_id,
        preview,
    )
