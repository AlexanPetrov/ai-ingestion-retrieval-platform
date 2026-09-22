"""Add parsed-document content identity."""

from __future__ import annotations

from collections.abc import Sequence
from hashlib import sha256

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "e13f6c2d9a71"
down_revision: str | Sequence[str] | None = "4eb7669e862c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _calculate_content_sha256(text: str) -> str:
    """Return the SHA-256 digest for the exact UTF-8 encoded text."""
    return sha256(text.encode("utf-8")).hexdigest()


def upgrade() -> None:
    """Add and backfill parsed-content SHA-256 identity."""

    op.add_column(
        "parsed_document",
        sa.Column(
            "content_sha256",
            sa.String(length=64),
            nullable=True,
        ),
    )

    parsed_document = sa.table(
        "parsed_document",
        sa.column("id", sa.UUID()),
        sa.column("text_content", sa.Text()),
        sa.column("content_sha256", sa.String(length=64)),
    )

    connection = op.get_bind()

    existing_documents = connection.execute(
        sa.select(
            parsed_document.c.id,
            parsed_document.c.text_content,
        ).order_by(parsed_document.c.id)
    )

    for row in existing_documents:
        content_sha256 = _calculate_content_sha256(row._mapping["text_content"])

        connection.execute(
            parsed_document.update()
            .where(
                parsed_document.c.id == row._mapping["id"],
            )
            .values(
                content_sha256=content_sha256,
            )
        )

    remaining_nulls = connection.scalar(
        sa.select(sa.func.count())
        .select_from(parsed_document)
        .where(parsed_document.c.content_sha256.is_(None))
    )

    if remaining_nulls:
        raise RuntimeError(
            "parsed_document content_sha256 backfill left "
            f"{remaining_nulls} rows without a digest"
        )

    op.alter_column(
        "parsed_document",
        "content_sha256",
        existing_type=sa.String(length=64),
        nullable=False,
    )

    op.create_check_constraint(
        "ck_parsed_document_content_sha256",
        "parsed_document",
        "content_sha256 ~ '^[0-9a-f]{64}$'",
    )


def downgrade() -> None:
    """Remove parsed-content SHA-256 identity."""

    op.drop_constraint(
        "ck_parsed_document_content_sha256",
        "parsed_document",
        type_="check",
    )

    op.drop_column(
        "parsed_document",
        "content_sha256",
    )
