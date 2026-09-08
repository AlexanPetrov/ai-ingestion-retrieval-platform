"""PostgreSQL integration tests for ingestion persistence semantics."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import (
    delete,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
)

from ai_ingestion_retrieval_platform.persistence.engine import (
    get_session_factory,
)
from ai_ingestion_retrieval_platform.persistence.models import (
    IngestionRecord,
    ParsedDocument,
    Source,
)
from ai_ingestion_retrieval_platform.persistence.repositories import (
    IngestionRepository,
)


async def _create_ingestion_record(
    repository: IngestionRepository,
    *,
    source_id: UUID,
    ingestion_mode: str = "raw",
    batch_id: UUID | None = None,
    batch_position: int | None = None,
) -> UUID:
    """Create one valid ingestion record and return its ID."""
    result = await repository.create_ingestion_record(
        source_id=source_id,
        ingestion_mode=ingestion_mode,
        batch_id=batch_id,
        batch_position=batch_position,
        request_id="postgres-integration-test",
        client_ip="127.0.0.1",
        http_status=200,
        http_status_reason="OK",
        final_url=None,
        response_content_type="text/plain",
        response_content_length=5,
        fetch_elapsed_ms=1,
        fetch_error_code=None,
        fetch_error_message=None,
        retry_attempts=0,
        fetched_at=datetime.now(UTC),
        parser_name=None,
        parser_version=None,
        parse_elapsed_ms=None,
        parse_error_code=None,
        parse_error_message=None,
    )

    return result.ingestion_record_id


@pytest.mark.asyncio
async def test_source_upsert_reuses_same_database_identity(
    postgres_engine: AsyncEngine,
) -> None:
    """Concurrent upserts for one URL must produce one Source row."""
    session_factory = get_session_factory(postgres_engine)

    url = "https://example.com/concurrent-source"

    async def create_source() -> UUID:
        async with session_factory() as session:
            repository = IngestionRepository(session)

            async with session.begin():
                result = await repository.get_or_create_source(
                    url=url,
                )

            return result.source_id

    first_id, second_id = await asyncio.gather(
        create_source(),
        create_source(),
    )

    assert first_id == second_id

    async with session_factory() as session:
        source_count = await session.scalar(
            select(func.count()).select_from(Source).where(Source.url == url)
        )

    assert source_count == 1


@pytest.mark.asyncio
async def test_repeated_ingestions_preserve_history_for_same_source(
    db_session: AsyncSession,
) -> None:
    """One stable Source may own many immutable ingestion records."""
    repository = IngestionRepository(db_session)

    async with db_session.begin():
        source = await repository.get_or_create_source(
            url="https://example.com/history",
        )

        first_record_id = await _create_ingestion_record(
            repository,
            source_id=source.source_id,
        )

        second_record_id = await _create_ingestion_record(
            repository,
            source_id=source.source_id,
        )

    assert first_record_id != second_record_id

    statement = (
        select(IngestionRecord)
        .where(IngestionRecord.source_id == source.source_id)
        .order_by(IngestionRecord.ingested_at.asc())
    )

    result = await db_session.execute(statement)

    records = list(result.scalars().all())

    assert len(records) == 2

    assert {record.id for record in records} == {
        first_record_id,
        second_record_id,
    }

    assert all(record.source_id == source.source_id for record in records)


@pytest.mark.asyncio
async def test_batch_records_are_returned_in_batch_position_order(
    db_session: AsyncSession,
) -> None:
    """Batch audit reads should preserve original request order."""
    repository = IngestionRepository(db_session)

    batch_id = uuid4()

    async with db_session.begin():
        source = await repository.get_or_create_source(
            url="https://example.com/batch-order",
        )

        await _create_ingestion_record(
            repository,
            source_id=source.source_id,
            batch_id=batch_id,
            batch_position=1,
        )

        await _create_ingestion_record(
            repository,
            source_id=source.source_id,
            batch_id=batch_id,
            batch_position=0,
        )

    records = await repository.get_ingestion_records_by_batch_id(
        batch_id=batch_id,
    )

    assert [record.batch_position for record in records] == [
        0,
        1,
    ]


@pytest.mark.asyncio
async def test_only_one_parsed_document_is_allowed_per_ingestion(
    db_session: AsyncSession,
) -> None:
    """The one-to-one ParsedDocument constraint must be enforced by PostgreSQL."""
    repository = IngestionRepository(db_session)

    async with db_session.begin():
        source = await repository.get_or_create_source(
            url="https://example.com/one-document",
        )

        ingestion_record_id = await _create_ingestion_record(
            repository,
            source_id=source.source_id,
            ingestion_mode="parsed",
        )

        await repository.create_parsed_document(
            ingestion_record_id=ingestion_record_id,
            content_type="text/plain",
            char_length=5,
            text_content="hello",
        )

    with pytest.raises(IntegrityError):
        async with db_session.begin():
            await repository.create_parsed_document(
                ingestion_record_id=ingestion_record_id,
                content_type="text/plain",
                char_length=5,
                text_content="again",
            )


@pytest.mark.asyncio
async def test_batch_id_and_position_combination_is_unique(
    db_session: AsyncSession,
) -> None:
    """Two ingestion rows cannot occupy the same position in one batch."""
    repository = IngestionRepository(db_session)

    batch_id = uuid4()

    async with db_session.begin():
        source = await repository.get_or_create_source(
            url="https://example.com/batch-unique",
        )

        await _create_ingestion_record(
            repository,
            source_id=source.source_id,
            batch_id=batch_id,
            batch_position=0,
        )

    with pytest.raises(IntegrityError):
        async with db_session.begin():
            await _create_ingestion_record(
                repository,
                source_id=source.source_id,
                batch_id=batch_id,
                batch_position=0,
            )


@pytest.mark.asyncio
async def test_invalid_ingestion_mode_is_rejected_by_database(
    db_session: AsyncSession,
) -> None:
    """PostgreSQL must enforce the ingestion-mode CHECK constraint."""
    repository = IngestionRepository(db_session)

    async with db_session.begin():
        source = await repository.get_or_create_source(
            url="https://example.com/invalid-mode",
        )

    with pytest.raises(IntegrityError):
        async with db_session.begin():
            db_session.add(
                IngestionRecord(
                    source_id=source.source_id,
                    ingestion_mode="invalid",
                    retry_attempts=0,
                )
            )

            await db_session.flush()


@pytest.mark.asyncio
async def test_batch_fields_must_be_both_null_or_both_present(
    db_session: AsyncSession,
) -> None:
    """PostgreSQL must enforce batch_id/batch_position consistency."""
    repository = IngestionRepository(db_session)

    async with db_session.begin():
        source = await repository.get_or_create_source(
            url="https://example.com/batch-fields",
        )

    with pytest.raises(IntegrityError):
        async with db_session.begin():
            db_session.add(
                IngestionRecord(
                    source_id=source.source_id,
                    ingestion_mode="raw",
                    batch_id=uuid4(),
                    batch_position=None,
                    retry_attempts=0,
                )
            )

            await db_session.flush()


@pytest.mark.asyncio
async def test_source_delete_is_restricted_when_ingestion_history_exists(
    postgres_engine: AsyncEngine,
) -> None:
    """Historical ingestion records must prevent deletion of their Source."""
    session_factory = get_session_factory(postgres_engine)

    async with session_factory() as session:
        repository = IngestionRepository(session)

        async with session.begin():
            source = await repository.get_or_create_source(
                url="https://example.com/restrict-source",
            )

            await _create_ingestion_record(
                repository,
                source_id=source.source_id,
            )

        source_id = source.source_id

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                await session.execute(delete(Source).where(Source.id == source_id))


@pytest.mark.asyncio
async def test_deleting_ingestion_record_cascades_to_parsed_document(
    postgres_engine: AsyncEngine,
) -> None:
    """The database FK must cascade ParsedDocument deletion."""
    session_factory = get_session_factory(postgres_engine)

    async with session_factory() as session:
        repository = IngestionRepository(session)

        async with session.begin():
            source = await repository.get_or_create_source(
                url="https://example.com/cascade-document",
            )

            ingestion_record_id = await _create_ingestion_record(
                repository,
                source_id=source.source_id,
                ingestion_mode="parsed",
            )

            document = await repository.create_parsed_document(
                ingestion_record_id=ingestion_record_id,
                content_type="text/plain",
                char_length=5,
                text_content="hello",
            )

        parsed_document_id = document.parsed_document_id

    # SQL DELETE deliberately bypasses ORM relationship cascades so this
    # proves PostgreSQL's ON DELETE CASCADE behavior.
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                delete(IngestionRecord).where(IngestionRecord.id == ingestion_record_id)
            )

    async with session_factory() as session:
        persisted_document = await session.scalar(
            select(ParsedDocument).where(ParsedDocument.id == parsed_document_id)
        )

    assert persisted_document is None


@pytest.mark.asyncio
async def test_transaction_rolls_back_source_and_ingestion_together(
    postgres_engine: AsyncEngine,
) -> None:
    """A failed transaction must not leave partial persistence behind."""
    session_factory = get_session_factory(postgres_engine)

    url = "https://example.com/rollback"

    with pytest.raises(
        RuntimeError,
        match="force rollback",
    ):
        async with session_factory() as session:
            repository = IngestionRepository(session)

            async with session.begin():
                source = await repository.get_or_create_source(
                    url=url,
                )

                await _create_ingestion_record(
                    repository,
                    source_id=source.source_id,
                )

                raise RuntimeError("force rollback")

    async with session_factory() as session:
        source_count = await session.scalar(
            select(func.count()).select_from(Source).where(Source.url == url)
        )

        ingestion_count = await session.scalar(
            select(func.count()).select_from(IngestionRecord)
        )

    assert source_count == 0
    assert ingestion_count == 0
