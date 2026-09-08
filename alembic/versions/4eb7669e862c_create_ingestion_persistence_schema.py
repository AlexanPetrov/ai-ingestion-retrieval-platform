"""Create the initial ingestion persistence schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "4eb7669e862c"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the initial persistence tables, constraints, and indexes."""
    op.create_table(
        "source",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "url",
            name="uq_source_url",
        ),
    )

    op.create_table(
        "ingestion_record",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "ingestion_mode",
            sa.String(length=16),
            nullable=False,
        ),
        sa.Column("batch_id", sa.UUID(), nullable=True),
        sa.Column("batch_position", sa.Integer(), nullable=True),
        sa.Column(
            "request_id",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "client_ip",
            sa.String(length=45),
            nullable=True,
        ),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column(
            "http_status_reason",
            sa.String(length=256),
            nullable=True,
        ),
        sa.Column(
            "final_url",
            sa.String(length=2048),
            nullable=True,
        ),
        sa.Column(
            "response_content_type",
            sa.String(length=256),
            nullable=True,
        ),
        sa.Column(
            "response_content_length",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "fetch_elapsed_ms",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "fetch_error_code",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "fetch_error_message",
            sa.String(length=512),
            nullable=True,
        ),
        sa.Column(
            "retry_attempts",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "parser_name",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "parser_version",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "parse_elapsed_ms",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "parse_error_code",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "parse_error_message",
            sa.String(length=512),
            nullable=True,
        ),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "ingestion_mode IN ('raw', 'parsed')",
            name="ck_ingestion_record_mode",
        ),
        sa.CheckConstraint(
            "(batch_id IS NULL AND batch_position IS NULL) OR "
            "(batch_id IS NOT NULL AND batch_position IS NOT NULL)",
            name="ck_ingestion_record_batch_fields",
        ),
        sa.CheckConstraint(
            "batch_position IS NULL OR batch_position >= 0",
            name="ck_ingestion_record_batch_position",
        ),
        sa.CheckConstraint(
            "response_content_length IS NULL OR response_content_length >= 0",
            name="ck_ingestion_record_content_length",
        ),
        sa.CheckConstraint(
            "fetch_elapsed_ms IS NULL OR fetch_elapsed_ms >= 0",
            name="ck_ingestion_record_fetch_elapsed_ms",
        ),
        sa.CheckConstraint(
            "http_status IS NULL OR (http_status >= 100 AND http_status <= 599)",
            name="ck_ingestion_record_http_status",
        ),
        sa.CheckConstraint(
            "parse_elapsed_ms IS NULL OR parse_elapsed_ms >= 0",
            name="ck_ingestion_record_parse_elapsed_ms",
        ),
        sa.CheckConstraint(
            "retry_attempts >= 0",
            name="ck_ingestion_record_retry_attempts",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "batch_id",
            "batch_position",
            name="uq_ingestion_record_batch_position",
        ),
    )

    op.create_index(
        "ix_ingestion_record_ingested_at",
        "ingestion_record",
        [sa.literal_column("ingested_at DESC")],
        unique=False,
    )

    op.create_index(
        "ix_ingestion_record_request_id",
        "ingestion_record",
        ["request_id"],
        unique=False,
    )

    op.create_index(
        "ix_ingestion_record_source_ingested_at",
        "ingestion_record",
        [
            "source_id",
            sa.literal_column("ingested_at DESC"),
        ],
        unique=False,
    )

    op.create_table(
        "parsed_document",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "ingestion_record_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "content_type",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "char_length",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "text_content",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length >= 0",
            name="ck_parsed_document_char_length",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_record_id"],
            ["ingestion_record.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ingestion_record_id",
            name="uq_parsed_document_ingestion_record_id",
        ),
    )


def downgrade() -> None:
    """Remove the initial persistence schema."""
    op.drop_table("parsed_document")

    op.drop_index(
        "ix_ingestion_record_source_ingested_at",
        table_name="ingestion_record",
    )

    op.drop_index(
        "ix_ingestion_record_request_id",
        table_name="ingestion_record",
    )

    op.drop_index(
        "ix_ingestion_record_ingested_at",
        table_name="ingestion_record",
    )

    op.drop_table("ingestion_record")
    op.drop_table("source")
