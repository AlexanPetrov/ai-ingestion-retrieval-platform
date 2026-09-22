"""SQLAlchemy ORM models for persisted ingestion state and audit history."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all persistence models."""


class Source(Base):
    """Stable identity for an external URL known to the application.

    A Source represents the external resource itself, not an individual fetch
    attempt. Repeated ingestion attempts for the same normalized URL reuse the
    same Source row and create separate IngestionRecord rows.
    """

    __tablename__ = "source"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    url: Mapped[str] = mapped_column(
        String(2048),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    ingestion_records: Mapped[list[IngestionRecord]] = relationship(
        back_populates="source",
        lazy="selectin",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "url",
            name="uq_source_url",
        ),
    )


class IngestionRecord(Base):
    """Immutable audit record for one persisted ingestion attempt."""

    __tablename__ = "ingestion_record"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "source.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    ingestion_mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )

    batch_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )

    batch_position: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    request_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    client_ip: Mapped[str | None] = mapped_column(
        String(45),
        nullable=True,
    )

    http_status: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    http_status_reason: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
    )

    final_url: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )

    response_content_type: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
    )

    response_content_length: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    fetch_elapsed_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    fetch_error_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    fetch_error_message: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )

    retry_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    parser_name: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    parser_version: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    parse_elapsed_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    parse_error_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    parse_error_message: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )

    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    source: Mapped[Source] = relationship(
        back_populates="ingestion_records",
    )

    parsed_document: Mapped[ParsedDocument | None] = relationship(
        back_populates="ingestion_record",
        cascade="all, delete-orphan",
        single_parent=True,
        lazy="selectin",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "ingestion_mode IN ('raw', 'parsed')",
            name="ck_ingestion_record_mode",
        ),
        CheckConstraint(
            "http_status IS NULL OR (http_status >= 100 AND http_status <= 599)",
            name="ck_ingestion_record_http_status",
        ),
        CheckConstraint(
            "response_content_length IS NULL OR response_content_length >= 0",
            name="ck_ingestion_record_content_length",
        ),
        CheckConstraint(
            "fetch_elapsed_ms IS NULL OR fetch_elapsed_ms >= 0",
            name="ck_ingestion_record_fetch_elapsed_ms",
        ),
        CheckConstraint(
            "retry_attempts >= 0",
            name="ck_ingestion_record_retry_attempts",
        ),
        CheckConstraint(
            "parse_elapsed_ms IS NULL OR parse_elapsed_ms >= 0",
            name="ck_ingestion_record_parse_elapsed_ms",
        ),
        CheckConstraint(
            "batch_position IS NULL OR batch_position >= 0",
            name="ck_ingestion_record_batch_position",
        ),
        CheckConstraint(
            "(batch_id IS NULL AND batch_position IS NULL) OR "
            "(batch_id IS NOT NULL AND batch_position IS NOT NULL)",
            name="ck_ingestion_record_batch_fields",
        ),
        UniqueConstraint(
            "batch_id",
            "batch_position",
            name="uq_ingestion_record_batch_position",
        ),
        Index(
            "ix_ingestion_record_source_ingested_at",
            "source_id",
            ingested_at.desc(),
        ),
        Index(
            "ix_ingestion_record_ingested_at",
            ingested_at.desc(),
        ),
        Index(
            "ix_ingestion_record_request_id",
            "request_id",
        ),
    )


class ParsedDocument(Base):
    """Successfully parsed document content produced by one ingestion attempt."""

    __tablename__ = "parsed_document"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    ingestion_record_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "ingestion_record.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    content_type: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    char_length: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    text_content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    content_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    ingestion_record: Mapped[IngestionRecord] = relationship(
        back_populates="parsed_document",
    )

    __table_args__ = (
        CheckConstraint(
            "char_length >= 0",
            name="ck_parsed_document_char_length",
        ),
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_parsed_document_content_sha256",
        ),
        UniqueConstraint(
            "ingestion_record_id",
            name="uq_parsed_document_ingestion_record_id",
        ),
    )
