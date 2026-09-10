"""Administrative service operations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError

from ai_ingestion_retrieval_platform.core.config import Settings
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
from ai_ingestion_retrieval_platform.persistence.engine import (
    close_database,
    create_database_engine,
    get_session_factory,
)

_FOREIGN_KEY_VIOLATION_SQLSTATE = "23503"


class DatabaseNotEnabledError(RuntimeError):
    """Raised when an administrative DB operation is requested while disabled."""


class InvalidAdminLimitError(ValueError):
    """Raised when an administrative list limit is outside the allowed range."""


class InvalidSourceIdError(ValueError):
    """Raised when a source ID is not a valid UUID."""


class SourceNotFoundError(LookupError):
    """Raised when a requested source does not exist."""


class SourceDeletionRestrictedError(RuntimeError):
    """Raised when ingestion history prevents deletion of a source."""


class InvalidIngestionIdError(ValueError):
    """Raised when an ingestion ID is not a valid UUID."""


class IngestionNotFoundError(LookupError):
    """Raised when a requested ingestion record does not exist."""


class InvalidDocumentIdError(ValueError):
    """Raised when a parsed-document ID is not a valid UUID."""


class DocumentNotFoundError(LookupError):
    """Raised when a requested parsed document does not exist."""


class DestructiveOperationNotConfirmedError(ValueError):
    """Raised when a destructive admin operation lacks confirmation."""


def _has_sqlstate(exc: BaseException, sqlstate: str) -> bool:
    """Return whether an exception chain contains the requested SQLSTATE."""
    pending: list[BaseException] = [exc]
    seen: set[int] = set()

    while pending:
        current = pending.pop()
        current_id = id(current)

        if current_id in seen:
            continue

        seen.add(current_id)

        if getattr(current, "sqlstate", None) == sqlstate:
            return True

        original = getattr(current, "orig", None)
        if isinstance(original, BaseException):
            pending.append(original)

        if current.__cause__ is not None:
            pending.append(current.__cause__)

        if current.__context__ is not None:
            pending.append(current.__context__)

    return False


def validate_admin_limit(limit: int) -> int:
    """Validate and return an administrative list limit."""
    if limit < 1 or limit > 500:
        raise InvalidAdminLimitError("Limit must be between 1 and 500.")

    return limit


def validate_source_id(source_id: str) -> str:
    """Validate and normalize a source UUID."""
    try:
        source_uuid = UUID(source_id)
    except ValueError as exc:
        raise InvalidSourceIdError(
            f"Invalid source ID {source_id!r}; expected a UUID."
        ) from exc

    return str(source_uuid)


def validate_ingestion_id(ingestion_id: str) -> str:
    """Validate and normalize an ingestion-record UUID."""
    try:
        ingestion_uuid = UUID(ingestion_id)
    except ValueError as exc:
        raise InvalidIngestionIdError(
            f"Invalid ingestion ID {ingestion_id!r}; expected a UUID."
        ) from exc

    return str(ingestion_uuid)


def validate_document_id(document_id: str) -> str:
    """Validate and normalize a parsed-document UUID."""
    try:
        document_uuid = UUID(document_id)
    except ValueError as exc:
        raise InvalidDocumentIdError(
            f"Invalid document ID {document_id!r}; expected a UUID."
        ) from exc

    return str(document_uuid)


async def get_database_stats(settings: Settings) -> DatabaseStats:
    """Return persistence statistics for the configured database."""
    if not settings.database_enabled:
        raise DatabaseNotEnabledError(
            "Database persistence is disabled. Set DATABASE_ENABLED=true."
        )

    engine = create_database_engine(settings)
    session_factory = get_session_factory(engine)

    try:
        async with session_factory() as session:
            repository = AdminRepository(session)
            return await repository.get_database_stats()
    finally:
        await close_database(engine)


async def purge_database(
    settings: Settings,
    *,
    confirmed: bool,
) -> DatabasePurgeResult:
    """Delete all persisted application data."""
    if not settings.database_enabled:
        raise DatabaseNotEnabledError(
            "Database persistence is disabled. Set DATABASE_ENABLED=true."
        )

    if not confirmed:
        raise DestructiveOperationNotConfirmedError(
            "Database purge requires explicit confirmation. Re-run with --confirm."
        )

    engine = create_database_engine(settings)
    session_factory = get_session_factory(engine)

    try:
        async with session_factory() as session:
            repository = AdminRepository(session)

            try:
                result = await repository.purge_database()
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise
    finally:
        await close_database(engine)


async def list_sources(
    settings: Settings,
    *,
    limit: int,
) -> list[SourceSummary]:
    """Return persisted sources for administrative inspection."""
    if not settings.database_enabled:
        raise DatabaseNotEnabledError(
            "Database persistence is disabled. Set DATABASE_ENABLED=true."
        )

    validated_limit = validate_admin_limit(limit)

    engine = create_database_engine(settings)
    session_factory = get_session_factory(engine)

    try:
        async with session_factory() as session:
            repository = AdminRepository(session)
            return await repository.list_sources(limit=validated_limit)
    finally:
        await close_database(engine)


async def get_source(
    settings: Settings,
    *,
    source_id: str,
) -> SourceSummary:
    """Return one persisted source for administrative inspection."""
    if not settings.database_enabled:
        raise DatabaseNotEnabledError(
            "Database persistence is disabled. Set DATABASE_ENABLED=true."
        )

    validated_source_id = validate_source_id(source_id)

    engine = create_database_engine(settings)
    session_factory = get_session_factory(engine)

    try:
        async with session_factory() as session:
            repository = AdminRepository(session)
            source = await repository.get_source(validated_source_id)

            if source is None:
                raise SourceNotFoundError(
                    f"Source {validated_source_id} was not found."
                )

            return source
    finally:
        await close_database(engine)


async def delete_source(
    settings: Settings,
    *,
    source_id: str,
    confirmed: bool,
) -> str:
    """Delete one persisted source with no remaining ingestion history."""
    if not settings.database_enabled:
        raise DatabaseNotEnabledError(
            "Database persistence is disabled. Set DATABASE_ENABLED=true."
        )

    validated_source_id = validate_source_id(source_id)

    if not confirmed:
        raise DestructiveOperationNotConfirmedError(
            "Source deletion requires explicit confirmation. Re-run with --confirm."
        )

    engine = create_database_engine(settings)
    session_factory = get_session_factory(engine)

    try:
        async with session_factory() as session:
            repository = AdminRepository(session)

            try:
                deleted = await repository.delete_source(validated_source_id)

                if not deleted:
                    raise SourceNotFoundError(
                        f"Source {validated_source_id} was not found."
                    )

                await session.commit()

                return validated_source_id
            except IntegrityError as exc:
                await session.rollback()

                if _has_sqlstate(exc, _FOREIGN_KEY_VIOLATION_SQLSTATE):
                    raise SourceDeletionRestrictedError(
                        f"Source {validated_source_id} cannot be deleted because "
                        "ingestion history still references it."
                    ) from exc

                raise
            except Exception:
                await session.rollback()
                raise
    finally:
        await close_database(engine)


async def list_ingestions(
    settings: Settings,
    *,
    limit: int,
) -> list[IngestionSummary]:
    """Return persisted ingestion records for administrative inspection."""
    if not settings.database_enabled:
        raise DatabaseNotEnabledError(
            "Database persistence is disabled. Set DATABASE_ENABLED=true."
        )

    validated_limit = validate_admin_limit(limit)

    engine = create_database_engine(settings)
    session_factory = get_session_factory(engine)

    try:
        async with session_factory() as session:
            repository = AdminRepository(session)
            return await repository.list_ingestions(limit=validated_limit)
    finally:
        await close_database(engine)


async def get_ingestion(
    settings: Settings,
    *,
    ingestion_id: str,
) -> IngestionDetail:
    """Return one persisted ingestion record for administrative inspection."""
    if not settings.database_enabled:
        raise DatabaseNotEnabledError(
            "Database persistence is disabled. Set DATABASE_ENABLED=true."
        )

    validated_ingestion_id = validate_ingestion_id(ingestion_id)

    engine = create_database_engine(settings)
    session_factory = get_session_factory(engine)

    try:
        async with session_factory() as session:
            repository = AdminRepository(session)
            ingestion = await repository.get_ingestion(validated_ingestion_id)

            if ingestion is None:
                raise IngestionNotFoundError(
                    f"Ingestion {validated_ingestion_id} was not found."
                )

            return ingestion
    finally:
        await close_database(engine)


async def delete_ingestion(
    settings: Settings,
    *,
    ingestion_id: str,
    confirmed: bool,
) -> str:
    """Delete one persisted ingestion record.

    The database cascades deletion to any linked parsed document.
    """
    if not settings.database_enabled:
        raise DatabaseNotEnabledError(
            "Database persistence is disabled. Set DATABASE_ENABLED=true."
        )

    validated_ingestion_id = validate_ingestion_id(ingestion_id)

    if not confirmed:
        raise DestructiveOperationNotConfirmedError(
            "Ingestion deletion requires explicit confirmation. Re-run with --confirm."
        )

    engine = create_database_engine(settings)
    session_factory = get_session_factory(engine)

    try:
        async with session_factory() as session:
            repository = AdminRepository(session)

            try:
                deleted = await repository.delete_ingestion(validated_ingestion_id)

                if not deleted:
                    raise IngestionNotFoundError(
                        f"Ingestion {validated_ingestion_id} was not found."
                    )

                await session.commit()

                return validated_ingestion_id
            except Exception:
                await session.rollback()
                raise
    finally:
        await close_database(engine)


async def list_documents(
    settings: Settings,
    *,
    limit: int,
) -> list[ParsedDocumentSummary]:
    """Return persisted parsed documents for administrative inspection."""
    if not settings.database_enabled:
        raise DatabaseNotEnabledError(
            "Database persistence is disabled. Set DATABASE_ENABLED=true."
        )

    validated_limit = validate_admin_limit(limit)

    engine = create_database_engine(settings)
    session_factory = get_session_factory(engine)

    try:
        async with session_factory() as session:
            repository = AdminRepository(session)
            return await repository.list_documents(limit=validated_limit)
    finally:
        await close_database(engine)


async def get_document(
    settings: Settings,
    *,
    document_id: str,
) -> ParsedDocumentDetail:
    """Return one persisted parsed document for administrative inspection."""
    if not settings.database_enabled:
        raise DatabaseNotEnabledError(
            "Database persistence is disabled. Set DATABASE_ENABLED=true."
        )

    validated_document_id = validate_document_id(document_id)

    engine = create_database_engine(settings)
    session_factory = get_session_factory(engine)

    try:
        async with session_factory() as session:
            repository = AdminRepository(session)
            document = await repository.get_document(validated_document_id)

            if document is None:
                raise DocumentNotFoundError(
                    f"Document {validated_document_id} was not found."
                )

            return document
    finally:
        await close_database(engine)
