"""Tests for administrative service operations."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError

from ai_ingestion_retrieval_platform.core.config import Settings
from ai_ingestion_retrieval_platform.persistence.admin_repository import (
    DatabasePurgeResult,
    DatabaseStats,
    IngestionDetail,
    IngestionSummary,
    ParsedDocumentDetail,
    ParsedDocumentSummary,
    SourceSummary,
)
from ai_ingestion_retrieval_platform.services import admin as admin_service
from ai_ingestion_retrieval_platform.services.admin import (
    DatabaseNotEnabledError,
    DestructiveOperationNotConfirmedError,
    DocumentNotFoundError,
    IngestionNotFoundError,
    InvalidAdminLimitError,
    InvalidDocumentIdError,
    InvalidIngestionIdError,
    InvalidSourceIdError,
    SourceDeletionRestrictedError,
    SourceNotFoundError,
)


class FakePostgresIntegrityError(Exception):
    """Minimal PostgreSQL-like exception carrying a SQLSTATE."""

    def __init__(self, message: str, *, sqlstate: str) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


@pytest.mark.parametrize("limit", [1, 50, 500])
def test_validate_admin_limit_accepts_valid_limits(limit: int) -> None:
    assert admin_service.validate_admin_limit(limit) == limit


@pytest.mark.parametrize("limit", [0, 501])
def test_validate_admin_limit_rejects_out_of_range_limits(limit: int) -> None:
    with pytest.raises(
        InvalidAdminLimitError,
        match="Limit must be between 1 and 500",
    ):
        admin_service.validate_admin_limit(limit)


def test_validate_source_id_returns_normalized_uuid() -> None:
    source_id = "550E8400-E29B-41D4-A716-446655440000"

    result = admin_service.validate_source_id(source_id)

    assert result == "550e8400-e29b-41d4-a716-446655440000"


def test_validate_source_id_rejects_invalid_uuid() -> None:
    with pytest.raises(
        InvalidSourceIdError,
        match="Invalid source ID 'not-a-uuid'; expected a UUID",
    ):
        admin_service.validate_source_id("not-a-uuid")


def test_validate_ingestion_id_returns_normalized_uuid() -> None:
    ingestion_id = "550E8400-E29B-41D4-A716-446655440001"

    result = admin_service.validate_ingestion_id(ingestion_id)

    assert result == "550e8400-e29b-41d4-a716-446655440001"


def test_validate_ingestion_id_rejects_invalid_uuid() -> None:
    with pytest.raises(
        InvalidIngestionIdError,
        match="Invalid ingestion ID 'not-a-uuid'; expected a UUID",
    ):
        admin_service.validate_ingestion_id("not-a-uuid")


def test_validate_document_id_returns_normalized_uuid() -> None:
    document_id = "550E8400-E29B-41D4-A716-446655440002"

    result = admin_service.validate_document_id(document_id)

    assert result == "550e8400-e29b-41d4-a716-446655440002"


def test_validate_document_id_rejects_invalid_uuid() -> None:
    with pytest.raises(
        InvalidDocumentIdError,
        match="Invalid document ID 'not-a-uuid'; expected a UUID",
    ):
        admin_service.validate_document_id("not-a-uuid")


@pytest.mark.asyncio
async def test_get_database_stats_rejects_disabled_database() -> None:
    settings = Settings.model_construct(database_enabled=False)

    with pytest.raises(
        DatabaseNotEnabledError,
        match="Database persistence is disabled",
    ):
        await admin_service.get_database_stats(settings)


@pytest.mark.asyncio
async def test_get_database_stats_returns_repository_stats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    expected_stats = DatabaseStats(
        sources=2,
        ingestion_records=6,
        parsed_documents=3,
    )

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.get_database_stats = AsyncMock(return_value=expected_stats)

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    result = await admin_service.get_database_stats(settings)

    assert result == expected_stats
    repository.get_database_stats.assert_awaited_once_with()
    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_get_database_stats_closes_engine_when_repository_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.get_database_stats = AsyncMock(
        side_effect=RuntimeError("database query failed")
    )

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    with pytest.raises(RuntimeError, match="database query failed"):
        await admin_service.get_database_stats(settings)

    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_purge_database_rejects_disabled_database() -> None:
    settings = Settings.model_construct(database_enabled=False)

    with pytest.raises(
        DatabaseNotEnabledError,
        match="Database persistence is disabled",
    ):
        await admin_service.purge_database(
            settings,
            confirmed=True,
        )


@pytest.mark.asyncio
async def test_purge_database_rejects_missing_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    create_database_engine = Mock()
    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        create_database_engine,
    )

    with pytest.raises(
        DestructiveOperationNotConfirmedError,
        match=("Database purge requires explicit confirmation. Re-run with --confirm."),
    ):
        await admin_service.purge_database(
            settings,
            confirmed=False,
        )

    create_database_engine.assert_not_called()


@pytest.mark.asyncio
async def test_purge_database_commits_successful_purge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    expected_result = DatabasePurgeResult(
        sources_deleted=2,
        ingestion_records_deleted=6,
        parsed_documents_deleted=3,
    )

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.purge_database = AsyncMock(return_value=expected_result)

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    result = await admin_service.purge_database(
        settings,
        confirmed=True,
    )

    assert result == expected_result
    repository.purge_database.assert_awaited_once_with()
    session.commit.assert_awaited_once_with()
    session.rollback.assert_not_awaited()
    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_purge_database_rolls_back_when_repository_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.purge_database = AsyncMock(
        side_effect=RuntimeError("database purge failed")
    )

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    with pytest.raises(RuntimeError, match="database purge failed"):
        await admin_service.purge_database(
            settings,
            confirmed=True,
        )

    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once_with()
    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_purge_database_rolls_back_when_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    expected_result = DatabasePurgeResult(
        sources_deleted=2,
        ingestion_records_deleted=6,
        parsed_documents_deleted=3,
    )

    engine = object()
    session = AsyncMock()
    session.commit.side_effect = RuntimeError("database commit failed")

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.purge_database = AsyncMock(return_value=expected_result)

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    with pytest.raises(RuntimeError, match="database commit failed"):
        await admin_service.purge_database(
            settings,
            confirmed=True,
        )

    repository.purge_database.assert_awaited_once_with()
    session.commit.assert_awaited_once_with()
    session.rollback.assert_awaited_once_with()
    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_list_sources_rejects_disabled_database() -> None:
    settings = Settings.model_construct(database_enabled=False)

    with pytest.raises(
        DatabaseNotEnabledError,
        match="Database persistence is disabled",
    ):
        await admin_service.list_sources(
            settings,
            limit=50,
        )


@pytest.mark.asyncio
async def test_list_sources_rejects_invalid_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    create_database_engine = Mock()
    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        create_database_engine,
    )

    with pytest.raises(
        InvalidAdminLimitError,
        match="Limit must be between 1 and 500",
    ):
        await admin_service.list_sources(
            settings,
            limit=501,
        )

    create_database_engine.assert_not_called()


@pytest.mark.asyncio
async def test_list_sources_returns_repository_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    expected_sources = [
        SourceSummary(
            id="550e8400-e29b-41d4-a716-446655440000",
            url="https://example.com/",
            created_at=datetime(2026, 9, 9, 8, 0, tzinfo=UTC),
            last_seen_at=datetime(2026, 9, 9, 9, 0, tzinfo=UTC),
        )
    ]

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.list_sources = AsyncMock(return_value=expected_sources)

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    result = await admin_service.list_sources(
        settings,
        limit=50,
    )

    assert result == expected_sources
    repository.list_sources.assert_awaited_once_with(limit=50)
    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_list_sources_closes_engine_when_repository_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.list_sources = AsyncMock(
        side_effect=RuntimeError("database query failed")
    )

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    with pytest.raises(RuntimeError, match="database query failed"):
        await admin_service.list_sources(
            settings,
            limit=50,
        )

    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_get_source_rejects_disabled_database() -> None:
    settings = Settings.model_construct(database_enabled=False)

    with pytest.raises(
        DatabaseNotEnabledError,
        match="Database persistence is disabled",
    ):
        await admin_service.get_source(
            settings,
            source_id="550e8400-e29b-41d4-a716-446655440000",
        )


@pytest.mark.asyncio
async def test_get_source_rejects_invalid_source_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    create_database_engine = Mock()
    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        create_database_engine,
    )

    with pytest.raises(
        InvalidSourceIdError,
        match="Invalid source ID 'not-a-uuid'; expected a UUID",
    ):
        await admin_service.get_source(
            settings,
            source_id="not-a-uuid",
        )

    create_database_engine.assert_not_called()


@pytest.mark.asyncio
async def test_get_source_returns_repository_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    source_id = "550e8400-e29b-41d4-a716-446655440000"

    expected_source = SourceSummary(
        id=source_id,
        url="https://example.com/",
        created_at=datetime(2026, 9, 9, 8, 0, tzinfo=UTC),
        last_seen_at=datetime(2026, 9, 9, 9, 0, tzinfo=UTC),
    )

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.get_source = AsyncMock(return_value=expected_source)

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    result = await admin_service.get_source(
        settings,
        source_id=source_id,
    )

    assert result == expected_source
    repository.get_source.assert_awaited_once_with(source_id)
    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_get_source_raises_when_source_does_not_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    source_id = "550e8400-e29b-41d4-a716-446655440000"

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.get_source = AsyncMock(return_value=None)

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    with pytest.raises(
        SourceNotFoundError,
        match=f"Source {source_id} was not found",
    ):
        await admin_service.get_source(
            settings,
            source_id=source_id,
        )

    repository.get_source.assert_awaited_once_with(source_id)
    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_get_source_normalizes_uuid_before_repository_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    source_id = "550E8400-E29B-41D4-A716-446655440000"
    normalized_source_id = str(UUID(source_id))

    expected_source = SourceSummary(
        id=normalized_source_id,
        url="https://example.com/",
        created_at=datetime(2026, 9, 9, 8, 0, tzinfo=UTC),
        last_seen_at=datetime(2026, 9, 9, 9, 0, tzinfo=UTC),
    )

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.get_source = AsyncMock(return_value=expected_source)

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    result = await admin_service.get_source(
        settings,
        source_id=source_id,
    )

    assert result == expected_source
    repository.get_source.assert_awaited_once_with(normalized_source_id)
    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_delete_source_rejects_disabled_database() -> None:
    settings = Settings.model_construct(database_enabled=False)

    with pytest.raises(
        DatabaseNotEnabledError,
        match="Database persistence is disabled",
    ):
        await admin_service.delete_source(
            settings,
            source_id="550e8400-e29b-41d4-a716-446655440000",
            confirmed=True,
        )


@pytest.mark.asyncio
async def test_delete_source_rejects_invalid_source_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    create_database_engine = Mock()
    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        create_database_engine,
    )

    with pytest.raises(
        InvalidSourceIdError,
        match="Invalid source ID 'not-a-uuid'; expected a UUID",
    ):
        await admin_service.delete_source(
            settings,
            source_id="not-a-uuid",
            confirmed=True,
        )

    create_database_engine.assert_not_called()


@pytest.mark.asyncio
async def test_delete_source_rejects_missing_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    source_id = "550e8400-e29b-41d4-a716-446655440000"

    create_database_engine = Mock()
    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        create_database_engine,
    )

    with pytest.raises(
        DestructiveOperationNotConfirmedError,
        match=(
            "Source deletion requires explicit confirmation. Re-run with --confirm."
        ),
    ):
        await admin_service.delete_source(
            settings,
            source_id=source_id,
            confirmed=False,
        )

    create_database_engine.assert_not_called()


@pytest.mark.asyncio
async def test_delete_source_commits_successful_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    source_id = "550E8400-E29B-41D4-A716-446655440000"
    normalized_source_id = str(UUID(source_id))

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.delete_source = AsyncMock(return_value=True)

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    result = await admin_service.delete_source(
        settings,
        source_id=source_id,
        confirmed=True,
    )

    assert result == normalized_source_id
    repository.delete_source.assert_awaited_once_with(normalized_source_id)
    session.commit.assert_awaited_once_with()
    session.rollback.assert_not_awaited()
    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_delete_source_rolls_back_when_source_does_not_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    source_id = "550e8400-e29b-41d4-a716-446655440000"

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.delete_source = AsyncMock(return_value=False)

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    with pytest.raises(
        SourceNotFoundError,
        match=f"Source {source_id} was not found",
    ):
        await admin_service.delete_source(
            settings,
            source_id=source_id,
            confirmed=True,
        )

    repository.delete_source.assert_awaited_once_with(source_id)
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once_with()
    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_delete_source_translates_foreign_key_integrity_error_and_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    source_id = "550e8400-e29b-41d4-a716-446655440000"

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.delete_source = AsyncMock(
        side_effect=IntegrityError(
            "DELETE FROM source",
            {"id": source_id},
            FakePostgresIntegrityError(
                "foreign key violation",
                sqlstate="23503",
            ),
        )
    )

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    with pytest.raises(
        SourceDeletionRestrictedError,
        match=(
            f"Source {source_id} cannot be deleted because "
            "ingestion history still references it"
        ),
    ):
        await admin_service.delete_source(
            settings,
            source_id=source_id,
            confirmed=True,
        )

    repository.delete_source.assert_awaited_once_with(source_id)
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once_with()
    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_delete_source_reraises_non_foreign_key_integrity_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    source_id = "550e8400-e29b-41d4-a716-446655440000"

    integrity_error = IntegrityError(
        "DELETE FROM source",
        {"id": source_id},
        FakePostgresIntegrityError(
            "unique violation",
            sqlstate="23505",
        ),
    )

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.delete_source = AsyncMock(side_effect=integrity_error)

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    with pytest.raises(IntegrityError) as exc_info:
        await admin_service.delete_source(
            settings,
            source_id=source_id,
            confirmed=True,
        )

    assert exc_info.value is integrity_error
    repository.delete_source.assert_awaited_once_with(source_id)
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once_with()
    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_delete_source_rolls_back_when_repository_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    source_id = "550e8400-e29b-41d4-a716-446655440000"

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.delete_source = AsyncMock(
        side_effect=RuntimeError("database delete failed")
    )

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    with pytest.raises(RuntimeError, match="database delete failed"):
        await admin_service.delete_source(
            settings,
            source_id=source_id,
            confirmed=True,
        )

    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once_with()
    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_delete_source_rolls_back_when_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    source_id = "550e8400-e29b-41d4-a716-446655440000"

    engine = object()
    session = AsyncMock()
    session.commit.side_effect = RuntimeError("database commit failed")

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.delete_source = AsyncMock(return_value=True)

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    with pytest.raises(RuntimeError, match="database commit failed"):
        await admin_service.delete_source(
            settings,
            source_id=source_id,
            confirmed=True,
        )

    repository.delete_source.assert_awaited_once_with(source_id)
    session.commit.assert_awaited_once_with()
    session.rollback.assert_awaited_once_with()
    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_list_ingestions_rejects_disabled_database() -> None:
    settings = Settings.model_construct(database_enabled=False)

    with pytest.raises(
        DatabaseNotEnabledError,
        match="Database persistence is disabled",
    ):
        await admin_service.list_ingestions(
            settings,
            limit=50,
        )


@pytest.mark.asyncio
async def test_list_ingestions_returns_repository_ingestions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    expected_ingestions = [
        IngestionSummary(
            id="550e8400-e29b-41d4-a716-446655440001",
            source_id="550e8400-e29b-41d4-a716-446655440000",
            ingestion_mode="parsed",
            batch_id="550e8400-e29b-41d4-a716-446655440002",
            batch_position=0,
            ingested_at=datetime(2026, 9, 9, 10, 0, tzinfo=UTC),
        )
    ]

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.list_ingestions = AsyncMock(return_value=expected_ingestions)

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    result = await admin_service.list_ingestions(
        settings,
        limit=50,
    )

    assert result == expected_ingestions
    repository.list_ingestions.assert_awaited_once_with(limit=50)
    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_list_ingestions_closes_engine_when_repository_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.list_ingestions = AsyncMock(
        side_effect=RuntimeError("database query failed")
    )

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    with pytest.raises(RuntimeError, match="database query failed"):
        await admin_service.list_ingestions(
            settings,
            limit=50,
        )

    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_get_ingestion_rejects_disabled_database() -> None:
    settings = Settings.model_construct(database_enabled=False)

    with pytest.raises(
        DatabaseNotEnabledError,
        match="Database persistence is disabled",
    ):
        await admin_service.get_ingestion(
            settings,
            ingestion_id="550e8400-e29b-41d4-a716-446655440001",
        )


@pytest.mark.asyncio
async def test_get_ingestion_rejects_invalid_ingestion_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    create_database_engine = Mock()
    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        create_database_engine,
    )

    with pytest.raises(
        InvalidIngestionIdError,
        match="Invalid ingestion ID 'not-a-uuid'; expected a UUID",
    ):
        await admin_service.get_ingestion(
            settings,
            ingestion_id="not-a-uuid",
        )

    create_database_engine.assert_not_called()


@pytest.mark.asyncio
async def test_get_ingestion_returns_repository_ingestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    ingestion_id = "550E8400-E29B-41D4-A716-446655440001"
    normalized_ingestion_id = str(UUID(ingestion_id))

    expected_ingestion = IngestionDetail(
        id=normalized_ingestion_id,
        source_id="550e8400-e29b-41d4-a716-446655440000",
        parsed_document_id="550e8400-e29b-41d4-a716-446655440002",
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
        fetched_at=datetime(2026, 9, 9, 9, 59, tzinfo=UTC),
        parser_name=None,
        parser_version=None,
        parse_elapsed_ms=25,
        parse_error_code=None,
        parse_error_message=None,
        ingested_at=datetime(2026, 9, 9, 10, 0, tzinfo=UTC),
    )

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.get_ingestion = AsyncMock(return_value=expected_ingestion)

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    result = await admin_service.get_ingestion(
        settings,
        ingestion_id=ingestion_id,
    )

    assert result == expected_ingestion
    repository.get_ingestion.assert_awaited_once_with(normalized_ingestion_id)
    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_get_ingestion_raises_when_ingestion_does_not_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    ingestion_id = "550e8400-e29b-41d4-a716-446655440001"

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.get_ingestion = AsyncMock(return_value=None)

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    with pytest.raises(
        IngestionNotFoundError,
        match=f"Ingestion {ingestion_id} was not found",
    ):
        await admin_service.get_ingestion(
            settings,
            ingestion_id=ingestion_id,
        )

    repository.get_ingestion.assert_awaited_once_with(ingestion_id)
    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_get_ingestion_closes_engine_when_repository_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    ingestion_id = "550e8400-e29b-41d4-a716-446655440001"

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.get_ingestion = AsyncMock(
        side_effect=RuntimeError("database query failed")
    )

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    with pytest.raises(RuntimeError, match="database query failed"):
        await admin_service.get_ingestion(
            settings,
            ingestion_id=ingestion_id,
        )

    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_delete_ingestion_rejects_disabled_database() -> None:
    settings = Settings.model_construct(database_enabled=False)

    with pytest.raises(
        DatabaseNotEnabledError,
        match="Database persistence is disabled",
    ):
        await admin_service.delete_ingestion(
            settings,
            ingestion_id="550e8400-e29b-41d4-a716-446655440001",
            confirmed=True,
        )


@pytest.mark.asyncio
async def test_delete_ingestion_rejects_invalid_ingestion_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    create_database_engine = Mock()
    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        create_database_engine,
    )

    with pytest.raises(
        InvalidIngestionIdError,
        match="Invalid ingestion ID 'not-a-uuid'; expected a UUID",
    ):
        await admin_service.delete_ingestion(
            settings,
            ingestion_id="not-a-uuid",
            confirmed=True,
        )

    create_database_engine.assert_not_called()


@pytest.mark.asyncio
async def test_delete_ingestion_rejects_missing_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    ingestion_id = "550e8400-e29b-41d4-a716-446655440001"

    create_database_engine = Mock()
    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        create_database_engine,
    )

    with pytest.raises(
        DestructiveOperationNotConfirmedError,
        match=(
            "Ingestion deletion requires explicit confirmation. Re-run with --confirm."
        ),
    ):
        await admin_service.delete_ingestion(
            settings,
            ingestion_id=ingestion_id,
            confirmed=False,
        )

    create_database_engine.assert_not_called()


@pytest.mark.asyncio
async def test_delete_ingestion_commits_successful_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    ingestion_id = "550E8400-E29B-41D4-A716-446655440001"
    normalized_ingestion_id = str(UUID(ingestion_id))

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.delete_ingestion = AsyncMock(return_value=True)

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    result = await admin_service.delete_ingestion(
        settings,
        ingestion_id=ingestion_id,
        confirmed=True,
    )

    assert result == normalized_ingestion_id
    repository.delete_ingestion.assert_awaited_once_with(normalized_ingestion_id)
    session.commit.assert_awaited_once_with()
    session.rollback.assert_not_awaited()
    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_delete_ingestion_rolls_back_when_ingestion_does_not_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    ingestion_id = "550e8400-e29b-41d4-a716-446655440001"

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.delete_ingestion = AsyncMock(return_value=False)

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    with pytest.raises(
        IngestionNotFoundError,
        match=f"Ingestion {ingestion_id} was not found",
    ):
        await admin_service.delete_ingestion(
            settings,
            ingestion_id=ingestion_id,
            confirmed=True,
        )

    repository.delete_ingestion.assert_awaited_once_with(ingestion_id)
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once_with()
    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_delete_ingestion_rolls_back_when_repository_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    ingestion_id = "550e8400-e29b-41d4-a716-446655440001"

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.delete_ingestion = AsyncMock(
        side_effect=RuntimeError("database delete failed")
    )

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    with pytest.raises(RuntimeError, match="database delete failed"):
        await admin_service.delete_ingestion(
            settings,
            ingestion_id=ingestion_id,
            confirmed=True,
        )

    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once_with()
    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_delete_ingestion_rolls_back_when_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    ingestion_id = "550e8400-e29b-41d4-a716-446655440001"

    engine = object()
    session = AsyncMock()
    session.commit.side_effect = RuntimeError("database commit failed")

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.delete_ingestion = AsyncMock(return_value=True)

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    with pytest.raises(RuntimeError, match="database commit failed"):
        await admin_service.delete_ingestion(
            settings,
            ingestion_id=ingestion_id,
            confirmed=True,
        )

    repository.delete_ingestion.assert_awaited_once_with(ingestion_id)
    session.commit.assert_awaited_once_with()
    session.rollback.assert_awaited_once_with()
    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_list_documents_rejects_disabled_database() -> None:
    settings = Settings.model_construct(database_enabled=False)

    with pytest.raises(
        DatabaseNotEnabledError,
        match="Database persistence is disabled",
    ):
        await admin_service.list_documents(
            settings,
            limit=50,
        )


@pytest.mark.asyncio
async def test_list_documents_rejects_invalid_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    create_database_engine = Mock()
    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        create_database_engine,
    )

    with pytest.raises(
        InvalidAdminLimitError,
        match="Limit must be between 1 and 500",
    ):
        await admin_service.list_documents(
            settings,
            limit=501,
        )

    create_database_engine.assert_not_called()


@pytest.mark.asyncio
async def test_list_documents_returns_repository_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    expected_documents = [
        ParsedDocumentSummary(
            id="550e8400-e29b-41d4-a716-446655440002",
            ingestion_record_id="550e8400-e29b-41d4-a716-446655440001",
            content_type="text/html",
            char_length=1200,
            created_at=datetime(2026, 9, 9, 10, 0, tzinfo=UTC),
        )
    ]

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.list_documents = AsyncMock(return_value=expected_documents)

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    result = await admin_service.list_documents(
        settings,
        limit=50,
    )

    assert result == expected_documents
    repository.list_documents.assert_awaited_once_with(limit=50)
    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_list_documents_closes_engine_when_repository_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.list_documents = AsyncMock(
        side_effect=RuntimeError("database query failed")
    )

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    with pytest.raises(RuntimeError, match="database query failed"):
        await admin_service.list_documents(
            settings,
            limit=50,
        )

    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_get_document_rejects_disabled_database() -> None:
    settings = Settings.model_construct(database_enabled=False)

    with pytest.raises(
        DatabaseNotEnabledError,
        match="Database persistence is disabled",
    ):
        await admin_service.get_document(
            settings,
            document_id="550e8400-e29b-41d4-a716-446655440002",
        )


@pytest.mark.asyncio
async def test_get_document_rejects_invalid_document_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    create_database_engine = Mock()
    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        create_database_engine,
    )

    with pytest.raises(
        InvalidDocumentIdError,
        match="Invalid document ID 'not-a-uuid'; expected a UUID",
    ):
        await admin_service.get_document(
            settings,
            document_id="not-a-uuid",
        )

    create_database_engine.assert_not_called()


@pytest.mark.asyncio
async def test_get_document_returns_repository_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    document_id = "550E8400-E29B-41D4-A716-446655440002"
    normalized_document_id = str(UUID(document_id))

    expected_document = ParsedDocumentDetail(
        id=normalized_document_id,
        ingestion_record_id="550e8400-e29b-41d4-a716-446655440001",
        content_type="text/html",
        char_length=25,
        text_content="Persisted parsed content.",
        created_at=datetime(2026, 9, 9, 10, 0, tzinfo=UTC),
    )

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.get_document = AsyncMock(return_value=expected_document)

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    result = await admin_service.get_document(
        settings,
        document_id=document_id,
    )

    assert result == expected_document
    repository.get_document.assert_awaited_once_with(normalized_document_id)
    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_get_document_raises_when_document_does_not_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    document_id = "550e8400-e29b-41d4-a716-446655440002"

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.get_document = AsyncMock(return_value=None)

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    with pytest.raises(
        DocumentNotFoundError,
        match=f"Document {document_id} was not found",
    ):
        await admin_service.get_document(
            settings,
            document_id=document_id,
        )

    repository.get_document.assert_awaited_once_with(document_id)
    close_database.assert_awaited_once_with(engine)


@pytest.mark.asyncio
async def test_get_document_closes_engine_when_repository_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.model_construct(database_enabled=True)

    document_id = "550e8400-e29b-41d4-a716-446655440002"

    engine = object()
    session = AsyncMock()

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)

    session_factory = Mock(return_value=session_context)

    repository = Mock()
    repository.get_document = AsyncMock(
        side_effect=RuntimeError("database query failed")
    )

    monkeypatch.setattr(
        admin_service,
        "create_database_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        admin_service,
        "get_session_factory",
        Mock(return_value=session_factory),
    )
    monkeypatch.setattr(
        admin_service,
        "AdminRepository",
        Mock(return_value=repository),
    )

    close_database = AsyncMock()
    monkeypatch.setattr(
        admin_service,
        "close_database",
        close_database,
    )

    with pytest.raises(RuntimeError, match="database query failed"):
        await admin_service.get_document(
            settings,
            document_id=document_id,
        )

    close_database.assert_awaited_once_with(engine)
