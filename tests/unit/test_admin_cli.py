"""Tests for the administrative CLI."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import ANY, AsyncMock

import pytest

from ai_ingestion_retrieval_platform import admin_cli
from ai_ingestion_retrieval_platform.persistence.admin_repository import (
    DatabasePurgeResult,
    DatabaseStats,
    IngestionDetail,
    IngestionSummary,
    ParsedDocumentDetail,
    ParsedDocumentSummary,
    SourceSummary,
)
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


def test_main_database_stats_prints_counts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        admin_cli,
        "get_database_stats",
        AsyncMock(
            return_value=DatabaseStats(
                sources=2,
                ingestion_records=6,
                parsed_documents=3,
            )
        ),
    )

    result = admin_cli.main(["database", "stats"])

    captured = capsys.readouterr()

    assert result == 0
    assert captured.out == (
        "Database statistics\n"
        "Sources:           2\n"
        "Ingestion records: 6\n"
        "Parsed documents:  3\n"
    )
    assert captured.err == ""


def test_main_database_stats_reports_disabled_database(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        admin_cli,
        "get_database_stats",
        AsyncMock(
            side_effect=DatabaseNotEnabledError(
                "Database persistence is disabled. Set DATABASE_ENABLED=true."
            )
        ),
    )

    result = admin_cli.main(["database", "stats"])

    captured = capsys.readouterr()

    assert result == 2
    assert captured.out == ""
    assert captured.err == (
        "ai-irp-admin: Database persistence is disabled. Set DATABASE_ENABLED=true.\n"
    )


def test_main_database_purge_prints_deleted_counts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    purge_database = AsyncMock(
        return_value=DatabasePurgeResult(
            sources_deleted=2,
            ingestion_records_deleted=6,
            parsed_documents_deleted=3,
        )
    )

    monkeypatch.setattr(
        admin_cli,
        "purge_database",
        purge_database,
    )

    result = admin_cli.main(
        [
            "database",
            "purge",
            "--confirm",
        ]
    )

    captured = capsys.readouterr()

    assert result == 0
    assert captured.out == (
        "Database purge complete\n"
        "Sources deleted:           2\n"
        "Ingestion records deleted: 6\n"
        "Parsed documents deleted:  3\n"
    )
    assert captured.err == ""

    purge_database.assert_awaited_once_with(
        ANY,
        confirmed=True,
    )


def test_main_database_purge_reports_missing_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    purge_database = AsyncMock(
        side_effect=DestructiveOperationNotConfirmedError(
            "Database purge requires explicit confirmation. Re-run with --confirm."
        )
    )

    monkeypatch.setattr(
        admin_cli,
        "purge_database",
        purge_database,
    )

    result = admin_cli.main(
        [
            "database",
            "purge",
        ]
    )

    captured = capsys.readouterr()

    assert result == 2
    assert captured.out == ""
    assert captured.err == (
        "ai-irp-admin: Database purge requires explicit confirmation. "
        "Re-run with --confirm.\n"
    )

    purge_database.assert_awaited_once_with(
        ANY,
        confirmed=False,
    )


def test_main_database_purge_reports_disabled_database(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        admin_cli,
        "purge_database",
        AsyncMock(
            side_effect=DatabaseNotEnabledError(
                "Database persistence is disabled. Set DATABASE_ENABLED=true."
            )
        ),
    )

    result = admin_cli.main(
        [
            "database",
            "purge",
            "--confirm",
        ]
    )

    captured = capsys.readouterr()

    assert result == 2
    assert captured.out == ""
    assert captured.err == (
        "ai-irp-admin: Database persistence is disabled. Set DATABASE_ENABLED=true.\n"
    )


def test_main_sources_list_prints_sources(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    created_at = datetime(2026, 9, 9, 8, 0, tzinfo=UTC)
    last_seen_at = datetime(2026, 9, 9, 9, 0, tzinfo=UTC)

    list_sources = AsyncMock(
        return_value=[
            SourceSummary(
                id="source-123",
                url="https://example.com/",
                created_at=created_at,
                last_seen_at=last_seen_at,
            )
        ]
    )

    monkeypatch.setattr(admin_cli, "list_sources", list_sources)

    result = admin_cli.main(
        [
            "sources",
            "list",
            "--limit",
            "10",
        ]
    )

    captured = capsys.readouterr()

    assert result == 0
    assert captured.out == (
        "Sources (1)\n"
        "ID:        source-123\n"
        "URL:       https://example.com/\n"
        "Created:   2026-09-09T08:00:00+00:00\n"
        "Last seen: 2026-09-09T09:00:00+00:00\n"
    )
    assert captured.err == ""

    list_sources.assert_awaited_once_with(
        ANY,
        limit=10,
    )


def test_main_sources_list_uses_default_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_sources = AsyncMock(return_value=[])

    monkeypatch.setattr(admin_cli, "list_sources", list_sources)

    result = admin_cli.main(["sources", "list"])

    assert result == 0
    list_sources.assert_awaited_once_with(ANY, limit=50)


def test_main_sources_list_reports_empty_database(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        admin_cli,
        "list_sources",
        AsyncMock(return_value=[]),
    )

    result = admin_cli.main(["sources", "list"])

    captured = capsys.readouterr()

    assert result == 0
    assert captured.out == "No sources found.\n"
    assert captured.err == ""


def test_main_sources_list_reports_invalid_limit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        admin_cli,
        "list_sources",
        AsyncMock(
            side_effect=InvalidAdminLimitError("Limit must be between 1 and 500.")
        ),
    )

    result = admin_cli.main(
        [
            "sources",
            "list",
            "--limit",
            "501",
        ]
    )

    captured = capsys.readouterr()

    assert result == 2
    assert captured.out == ""
    assert captured.err == "ai-irp-admin: Limit must be between 1 and 500.\n"


def test_main_sources_show_prints_source(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_id = "123e4567-e89b-12d3-a456-426614174000"

    get_source = AsyncMock(
        return_value=SourceSummary(
            id=source_id,
            url="https://example.com/",
            created_at=datetime(2026, 9, 9, 8, 0, tzinfo=UTC),
            last_seen_at=datetime(2026, 9, 9, 9, 0, tzinfo=UTC),
        )
    )

    monkeypatch.setattr(admin_cli, "get_source", get_source)

    result = admin_cli.main(["sources", "show", source_id])

    captured = capsys.readouterr()

    assert result == 0
    assert captured.out == (
        "Source\n"
        f"ID:        {source_id}\n"
        "URL:       https://example.com/\n"
        "Created:   2026-09-09T08:00:00+00:00\n"
        "Last seen: 2026-09-09T09:00:00+00:00\n"
    )
    assert captured.err == ""

    get_source.assert_awaited_once_with(
        ANY,
        source_id=source_id,
    )


def test_main_sources_show_reports_invalid_source_id(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        admin_cli,
        "get_source",
        AsyncMock(
            side_effect=InvalidSourceIdError(
                "Invalid source ID 'not-a-uuid'; expected a UUID."
            )
        ),
    )

    result = admin_cli.main(["sources", "show", "not-a-uuid"])

    captured = capsys.readouterr()

    assert result == 2
    assert captured.out == ""
    assert captured.err == (
        "ai-irp-admin: Invalid source ID 'not-a-uuid'; expected a UUID.\n"
    )


def test_main_sources_show_reports_source_not_found(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_id = "123e4567-e89b-12d3-a456-426614174000"

    monkeypatch.setattr(
        admin_cli,
        "get_source",
        AsyncMock(
            side_effect=SourceNotFoundError(f"Source {source_id} was not found.")
        ),
    )

    result = admin_cli.main(["sources", "show", source_id])

    captured = capsys.readouterr()

    assert result == 2
    assert captured.out == ""
    assert captured.err == (f"ai-irp-admin: Source {source_id} was not found.\n")


def test_main_sources_delete_prints_deleted_source(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_id = "123e4567-e89b-12d3-a456-426614174000"

    delete_source = AsyncMock(return_value=source_id)
    monkeypatch.setattr(
        admin_cli,
        "delete_source",
        delete_source,
    )

    result = admin_cli.main(
        [
            "sources",
            "delete",
            source_id,
            "--confirm",
        ]
    )

    captured = capsys.readouterr()

    assert result == 0
    assert captured.out == f"Deleted source {source_id}.\n"
    assert captured.err == ""

    delete_source.assert_awaited_once_with(
        ANY,
        source_id=source_id,
        confirmed=True,
    )


def test_main_sources_delete_reports_missing_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_id = "123e4567-e89b-12d3-a456-426614174000"

    delete_source = AsyncMock(
        side_effect=DestructiveOperationNotConfirmedError(
            "Source deletion requires explicit confirmation. Re-run with --confirm."
        )
    )
    monkeypatch.setattr(
        admin_cli,
        "delete_source",
        delete_source,
    )

    result = admin_cli.main(
        [
            "sources",
            "delete",
            source_id,
        ]
    )

    captured = capsys.readouterr()

    assert result == 2
    assert captured.out == ""
    assert captured.err == (
        "ai-irp-admin: Source deletion requires explicit confirmation. "
        "Re-run with --confirm.\n"
    )

    delete_source.assert_awaited_once_with(
        ANY,
        source_id=source_id,
        confirmed=False,
    )


def test_main_sources_delete_reports_invalid_source_id(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        admin_cli,
        "delete_source",
        AsyncMock(
            side_effect=InvalidSourceIdError(
                "Invalid source ID 'not-a-uuid'; expected a UUID."
            )
        ),
    )

    result = admin_cli.main(
        [
            "sources",
            "delete",
            "not-a-uuid",
            "--confirm",
        ]
    )

    captured = capsys.readouterr()

    assert result == 2
    assert captured.out == ""
    assert captured.err == (
        "ai-irp-admin: Invalid source ID 'not-a-uuid'; expected a UUID.\n"
    )


def test_main_sources_delete_reports_source_not_found(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_id = "123e4567-e89b-12d3-a456-426614174000"

    monkeypatch.setattr(
        admin_cli,
        "delete_source",
        AsyncMock(
            side_effect=SourceNotFoundError(f"Source {source_id} was not found.")
        ),
    )

    result = admin_cli.main(
        [
            "sources",
            "delete",
            source_id,
            "--confirm",
        ]
    )

    captured = capsys.readouterr()

    assert result == 2
    assert captured.out == ""
    assert captured.err == (f"ai-irp-admin: Source {source_id} was not found.\n")


def test_main_sources_delete_reports_restricted_source(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_id = "123e4567-e89b-12d3-a456-426614174000"

    monkeypatch.setattr(
        admin_cli,
        "delete_source",
        AsyncMock(
            side_effect=SourceDeletionRestrictedError(
                f"Source {source_id} cannot be deleted because "
                "ingestion history still references it."
            )
        ),
    )

    result = admin_cli.main(
        [
            "sources",
            "delete",
            source_id,
            "--confirm",
        ]
    )

    captured = capsys.readouterr()

    assert result == 2
    assert captured.out == ""
    assert captured.err == (
        f"ai-irp-admin: Source {source_id} cannot be deleted because "
        "ingestion history still references it.\n"
    )


def test_main_ingestions_list_prints_ingestions(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    list_ingestions = AsyncMock(
        return_value=[
            IngestionSummary(
                id="ingestion-123",
                source_id="source-123",
                ingestion_mode="parsed",
                batch_id="batch-123",
                batch_position=0,
                ingested_at=datetime(2026, 9, 9, 10, 0, tzinfo=UTC),
            )
        ]
    )

    monkeypatch.setattr(admin_cli, "list_ingestions", list_ingestions)

    result = admin_cli.main(
        [
            "ingestions",
            "list",
            "--limit",
            "10",
        ]
    )

    captured = capsys.readouterr()

    assert result == 0
    assert captured.out == (
        "Ingestion records (1)\n"
        "ID:             ingestion-123\n"
        "Source ID:      source-123\n"
        "Mode:           parsed\n"
        "Batch ID:       batch-123\n"
        "Batch position: 0\n"
        "Ingested:       2026-09-09T10:00:00+00:00\n"
    )
    assert captured.err == ""

    list_ingestions.assert_awaited_once_with(ANY, limit=10)


def test_main_ingestions_list_prints_non_batch_ingestion(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        admin_cli,
        "list_ingestions",
        AsyncMock(
            return_value=[
                IngestionSummary(
                    id="ingestion-123",
                    source_id="source-123",
                    ingestion_mode="raw",
                    batch_id=None,
                    batch_position=None,
                    ingested_at=datetime(
                        2026,
                        9,
                        9,
                        10,
                        0,
                        tzinfo=UTC,
                    ),
                )
            ]
        ),
    )

    result = admin_cli.main(["ingestions", "list"])

    captured = capsys.readouterr()

    assert result == 0
    assert captured.out == (
        "Ingestion records (1)\n"
        "ID:             ingestion-123\n"
        "Source ID:      source-123\n"
        "Mode:           raw\n"
        "Batch ID:       -\n"
        "Batch position: -\n"
        "Ingested:       2026-09-09T10:00:00+00:00\n"
    )
    assert captured.err == ""


def test_main_ingestions_list_uses_default_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_ingestions = AsyncMock(return_value=[])

    monkeypatch.setattr(admin_cli, "list_ingestions", list_ingestions)

    result = admin_cli.main(["ingestions", "list"])

    assert result == 0
    list_ingestions.assert_awaited_once_with(ANY, limit=50)


def test_main_ingestions_list_reports_empty_database(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        admin_cli,
        "list_ingestions",
        AsyncMock(return_value=[]),
    )

    result = admin_cli.main(["ingestions", "list"])

    captured = capsys.readouterr()

    assert result == 0
    assert captured.out == "No ingestion records found.\n"
    assert captured.err == ""


def test_main_ingestions_list_reports_invalid_limit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        admin_cli,
        "list_ingestions",
        AsyncMock(
            side_effect=InvalidAdminLimitError("Limit must be between 1 and 500.")
        ),
    )

    result = admin_cli.main(
        [
            "ingestions",
            "list",
            "--limit",
            "501",
        ]
    )

    captured = capsys.readouterr()

    assert result == 2
    assert captured.out == ""
    assert captured.err == "ai-irp-admin: Limit must be between 1 and 500.\n"


def test_main_ingestions_show_prints_ingestion(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ingestion_id = "123e4567-e89b-12d3-a456-426614174001"
    source_id = "123e4567-e89b-12d3-a456-426614174000"
    document_id = "123e4567-e89b-12d3-a456-426614174002"
    batch_id = "123e4567-e89b-12d3-a456-426614174003"

    get_ingestion = AsyncMock(
        return_value=IngestionDetail(
            id=ingestion_id,
            source_id=source_id,
            parsed_document_id=document_id,
            ingestion_mode="parsed",
            batch_id=batch_id,
            batch_position=2,
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
    )

    monkeypatch.setattr(admin_cli, "get_ingestion", get_ingestion)

    result = admin_cli.main(["ingestions", "show", ingestion_id])

    captured = capsys.readouterr()

    assert result == 0
    assert captured.out == (
        "Ingestion record\n"
        f"ID:                      {ingestion_id}\n"
        f"Source ID:               {source_id}\n"
        f"Parsed document ID:      {document_id}\n"
        "Mode:                    parsed\n"
        f"Batch ID:                {batch_id}\n"
        "Batch position:          2\n"
        "Request ID:              request-123\n"
        "Client IP:               203.0.113.10\n"
        "HTTP status:             200\n"
        "HTTP status reason:      OK\n"
        "Final URL:               -\n"
        "Response content type:   text/html\n"
        "Response content length: 1024\n"
        "Fetch elapsed ms:        125\n"
        "Fetch error code:        -\n"
        "Fetch error message:     -\n"
        "Retry attempts:          0\n"
        "Fetched:                 2026-09-09T09:59:00+00:00\n"
        "Parser name:             -\n"
        "Parser version:          -\n"
        "Parse elapsed ms:        25\n"
        "Parse error code:        -\n"
        "Parse error message:     -\n"
        "Ingested:                2026-09-09T10:00:00+00:00\n"
    )
    assert captured.err == ""

    get_ingestion.assert_awaited_once_with(
        ANY,
        ingestion_id=ingestion_id,
    )


def test_main_ingestions_show_reports_invalid_ingestion_id(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        admin_cli,
        "get_ingestion",
        AsyncMock(
            side_effect=InvalidIngestionIdError(
                "Invalid ingestion ID 'not-a-uuid'; expected a UUID."
            )
        ),
    )

    result = admin_cli.main(["ingestions", "show", "not-a-uuid"])

    captured = capsys.readouterr()

    assert result == 2
    assert captured.out == ""
    assert captured.err == (
        "ai-irp-admin: Invalid ingestion ID 'not-a-uuid'; expected a UUID.\n"
    )


def test_main_ingestions_show_reports_ingestion_not_found(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ingestion_id = "123e4567-e89b-12d3-a456-426614174001"

    monkeypatch.setattr(
        admin_cli,
        "get_ingestion",
        AsyncMock(
            side_effect=IngestionNotFoundError(
                f"Ingestion {ingestion_id} was not found."
            )
        ),
    )

    result = admin_cli.main(["ingestions", "show", ingestion_id])

    captured = capsys.readouterr()

    assert result == 2
    assert captured.out == ""
    assert captured.err == (f"ai-irp-admin: Ingestion {ingestion_id} was not found.\n")


def test_main_ingestions_delete_prints_deleted_ingestion(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ingestion_id = "123e4567-e89b-12d3-a456-426614174001"

    delete_ingestion = AsyncMock(return_value=ingestion_id)
    monkeypatch.setattr(
        admin_cli,
        "delete_ingestion",
        delete_ingestion,
    )

    result = admin_cli.main(
        [
            "ingestions",
            "delete",
            ingestion_id,
            "--confirm",
        ]
    )

    captured = capsys.readouterr()

    assert result == 0
    assert captured.out == f"Deleted ingestion {ingestion_id}.\n"
    assert captured.err == ""

    delete_ingestion.assert_awaited_once_with(
        ANY,
        ingestion_id=ingestion_id,
        confirmed=True,
    )


def test_main_ingestions_delete_reports_missing_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ingestion_id = "123e4567-e89b-12d3-a456-426614174001"

    delete_ingestion = AsyncMock(
        side_effect=DestructiveOperationNotConfirmedError(
            "Ingestion deletion requires explicit confirmation. Re-run with --confirm."
        )
    )
    monkeypatch.setattr(
        admin_cli,
        "delete_ingestion",
        delete_ingestion,
    )

    result = admin_cli.main(
        [
            "ingestions",
            "delete",
            ingestion_id,
        ]
    )

    captured = capsys.readouterr()

    assert result == 2
    assert captured.out == ""
    assert captured.err == (
        "ai-irp-admin: Ingestion deletion requires explicit confirmation. "
        "Re-run with --confirm.\n"
    )

    delete_ingestion.assert_awaited_once_with(
        ANY,
        ingestion_id=ingestion_id,
        confirmed=False,
    )


def test_main_ingestions_delete_reports_invalid_ingestion_id(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        admin_cli,
        "delete_ingestion",
        AsyncMock(
            side_effect=InvalidIngestionIdError(
                "Invalid ingestion ID 'not-a-uuid'; expected a UUID."
            )
        ),
    )

    result = admin_cli.main(
        [
            "ingestions",
            "delete",
            "not-a-uuid",
            "--confirm",
        ]
    )

    captured = capsys.readouterr()

    assert result == 2
    assert captured.out == ""
    assert captured.err == (
        "ai-irp-admin: Invalid ingestion ID 'not-a-uuid'; expected a UUID.\n"
    )


def test_main_ingestions_delete_reports_ingestion_not_found(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ingestion_id = "123e4567-e89b-12d3-a456-426614174001"

    monkeypatch.setattr(
        admin_cli,
        "delete_ingestion",
        AsyncMock(
            side_effect=IngestionNotFoundError(
                f"Ingestion {ingestion_id} was not found."
            )
        ),
    )

    result = admin_cli.main(
        [
            "ingestions",
            "delete",
            ingestion_id,
            "--confirm",
        ]
    )

    captured = capsys.readouterr()

    assert result == 2
    assert captured.out == ""
    assert captured.err == (f"ai-irp-admin: Ingestion {ingestion_id} was not found.\n")


def test_main_documents_list_prints_documents(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    list_documents = AsyncMock(
        return_value=[
            ParsedDocumentSummary(
                id="document-123",
                ingestion_record_id="ingestion-123",
                content_type="text/html",
                char_length=1200,
                created_at=datetime(2026, 9, 9, 10, 0, tzinfo=UTC),
            )
        ]
    )

    monkeypatch.setattr(admin_cli, "list_documents", list_documents)

    result = admin_cli.main(
        [
            "documents",
            "list",
            "--limit",
            "10",
        ]
    )

    captured = capsys.readouterr()

    assert result == 0
    assert captured.out == (
        "Parsed documents (1)\n"
        "ID:                  document-123\n"
        "Ingestion record ID: ingestion-123\n"
        "Content type:        text/html\n"
        "Character length:    1200\n"
        "Created:             2026-09-09T10:00:00+00:00\n"
    )
    assert captured.err == ""

    list_documents.assert_awaited_once_with(ANY, limit=10)


def test_main_documents_list_uses_default_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_documents = AsyncMock(return_value=[])

    monkeypatch.setattr(admin_cli, "list_documents", list_documents)

    result = admin_cli.main(["documents", "list"])

    assert result == 0
    list_documents.assert_awaited_once_with(ANY, limit=50)


def test_main_documents_list_reports_empty_database(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        admin_cli,
        "list_documents",
        AsyncMock(return_value=[]),
    )

    result = admin_cli.main(["documents", "list"])

    captured = capsys.readouterr()

    assert result == 0
    assert captured.out == "No parsed documents found.\n"
    assert captured.err == ""


def test_main_documents_list_reports_invalid_limit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        admin_cli,
        "list_documents",
        AsyncMock(
            side_effect=InvalidAdminLimitError("Limit must be between 1 and 500.")
        ),
    )

    result = admin_cli.main(
        [
            "documents",
            "list",
            "--limit",
            "501",
        ]
    )

    captured = capsys.readouterr()

    assert result == 2
    assert captured.out == ""
    assert captured.err == "ai-irp-admin: Limit must be between 1 and 500.\n"


def test_main_documents_show_prints_document(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document_id = "123e4567-e89b-12d3-a456-426614174002"
    ingestion_id = "123e4567-e89b-12d3-a456-426614174001"

    get_document = AsyncMock(
        return_value=ParsedDocumentDetail(
            id=document_id,
            ingestion_record_id=ingestion_id,
            content_type="text/plain",
            char_length=24,
            text_content="First line.\nSecond line.",
            created_at=datetime(2026, 9, 9, 10, 0, tzinfo=UTC),
        )
    )

    monkeypatch.setattr(admin_cli, "get_document", get_document)

    result = admin_cli.main(["documents", "show", document_id])

    captured = capsys.readouterr()

    assert result == 0
    assert captured.out == (
        "Parsed document\n"
        f"ID:                  {document_id}\n"
        f"Ingestion record ID: {ingestion_id}\n"
        "Content type:        text/plain\n"
        "Character length:    24\n"
        "Created:             2026-09-09T10:00:00+00:00\n"
        "\n"
        "Text content:\n"
        "First line.\n"
        "Second line.\n"
    )
    assert captured.err == ""

    get_document.assert_awaited_once_with(
        ANY,
        document_id=document_id,
    )


def test_main_documents_show_reports_invalid_document_id(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        admin_cli,
        "get_document",
        AsyncMock(
            side_effect=InvalidDocumentIdError(
                "Invalid document ID 'not-a-uuid'; expected a UUID."
            )
        ),
    )

    result = admin_cli.main(["documents", "show", "not-a-uuid"])

    captured = capsys.readouterr()

    assert result == 2
    assert captured.out == ""
    assert captured.err == (
        "ai-irp-admin: Invalid document ID 'not-a-uuid'; expected a UUID.\n"
    )


def test_main_documents_show_reports_document_not_found(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document_id = "123e4567-e89b-12d3-a456-426614174002"

    monkeypatch.setattr(
        admin_cli,
        "get_document",
        AsyncMock(
            side_effect=DocumentNotFoundError(f"Document {document_id} was not found.")
        ),
    )

    result = admin_cli.main(["documents", "show", document_id])

    captured = capsys.readouterr()

    assert result == 2
    assert captured.out == ""
    assert captured.err == (f"ai-irp-admin: Document {document_id} was not found.\n")


def test_database_requires_subcommand() -> None:
    with pytest.raises(SystemExit) as exc_info:
        admin_cli.main(["database"])

    assert exc_info.value.code == 2


def test_sources_requires_subcommand() -> None:
    with pytest.raises(SystemExit) as exc_info:
        admin_cli.main(["sources"])

    assert exc_info.value.code == 2


def test_sources_show_requires_source_id() -> None:
    with pytest.raises(SystemExit) as exc_info:
        admin_cli.main(["sources", "show"])

    assert exc_info.value.code == 2


def test_sources_delete_requires_source_id() -> None:
    with pytest.raises(SystemExit) as exc_info:
        admin_cli.main(["sources", "delete"])

    assert exc_info.value.code == 2


def test_ingestions_requires_subcommand() -> None:
    with pytest.raises(SystemExit) as exc_info:
        admin_cli.main(["ingestions"])

    assert exc_info.value.code == 2


def test_ingestions_show_requires_ingestion_id() -> None:
    with pytest.raises(SystemExit) as exc_info:
        admin_cli.main(["ingestions", "show"])

    assert exc_info.value.code == 2


def test_ingestions_delete_requires_ingestion_id() -> None:
    with pytest.raises(SystemExit) as exc_info:
        admin_cli.main(["ingestions", "delete"])

    assert exc_info.value.code == 2


def test_documents_requires_subcommand() -> None:
    with pytest.raises(SystemExit) as exc_info:
        admin_cli.main(["documents"])

    assert exc_info.value.code == 2


def test_documents_show_requires_document_id() -> None:
    with pytest.raises(SystemExit) as exc_info:
        admin_cli.main(["documents", "show"])

    assert exc_info.value.code == 2


def test_build_parser_includes_top_level_commands() -> None:
    parser = admin_cli.build_parser()

    help_text = parser.format_help()

    assert "sources" in help_text
    assert "ingestions" in help_text
    assert "documents" in help_text
    assert "database" in help_text
