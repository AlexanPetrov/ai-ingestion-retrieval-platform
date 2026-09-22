"""Integration tests for parsed-content identity migration behavior."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ai_ingestion_retrieval_platform.core.content_identity import (
    calculate_content_sha256,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BASE_PERSISTENCE_REVISION = "4eb7669e862c"


def _run_alembic(
    database_url: str,
    command: str,
    revision: str,
) -> None:
    """Run one Alembic command against the dedicated integration database."""

    environment = os.environ.copy()
    environment["DATABASE_ENABLED"] = "true"
    environment["DATABASE_URL"] = database_url

    subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            command,
            revision,
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
    )


@pytest.mark.asyncio
async def test_content_sha256_migration_backfills_existing_document(
    migrated_test_database: str,
    postgres_engine: AsyncEngine,
) -> None:
    """An existing ParsedDocument must receive its exact text-content digest."""

    source_id = uuid4()
    ingestion_record_id = uuid4()
    parsed_document_id = uuid4()

    text_content = "Existing café content.\nSecond line."
    expected_sha256 = calculate_content_sha256(text_content)

    _run_alembic(
        migrated_test_database,
        "downgrade",
        BASE_PERSISTENCE_REVISION,
    )

    upgraded = False

    try:
        async with postgres_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO source (
                        id,
                        url
                    )
                    VALUES (
                        :source_id,
                        :url
                    )
                    """
                ),
                {
                    "source_id": source_id,
                    "url": "https://example.com/preexisting-document",
                },
            )

            await connection.execute(
                text(
                    """
                    INSERT INTO ingestion_record (
                        id,
                        source_id,
                        ingestion_mode,
                        retry_attempts
                    )
                    VALUES (
                        :ingestion_record_id,
                        :source_id,
                        'parsed',
                        0
                    )
                    """
                ),
                {
                    "ingestion_record_id": ingestion_record_id,
                    "source_id": source_id,
                },
            )

            await connection.execute(
                text(
                    """
                    INSERT INTO parsed_document (
                        id,
                        ingestion_record_id,
                        content_type,
                        char_length,
                        text_content
                    )
                    VALUES (
                        :parsed_document_id,
                        :ingestion_record_id,
                        'text/plain',
                        :char_length,
                        :text_content
                    )
                    """
                ),
                {
                    "parsed_document_id": parsed_document_id,
                    "ingestion_record_id": ingestion_record_id,
                    "char_length": len(text_content),
                    "text_content": text_content,
                },
            )

        _run_alembic(
            migrated_test_database,
            "upgrade",
            "head",
        )
        upgraded = True

        async with postgres_engine.connect() as connection:
            persisted_sha256 = await connection.scalar(
                text(
                    """
                    SELECT content_sha256
                    FROM parsed_document
                    WHERE id = :parsed_document_id
                    """
                ),
                {
                    "parsed_document_id": parsed_document_id,
                },
            )

            is_nullable = await connection.scalar(
                text(
                    """
                    SELECT is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'parsed_document'
                      AND column_name = 'content_sha256'
                    """
                )
            )

            constraint_exists = await connection.scalar(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = 'ck_parsed_document_content_sha256'
                    )
                    """
                )
            )

        assert persisted_sha256 == expected_sha256
        assert is_nullable == "NO"
        assert constraint_exists is True

    finally:
        if not upgraded:
            _run_alembic(
                migrated_test_database,
                "upgrade",
                "head",
            )
