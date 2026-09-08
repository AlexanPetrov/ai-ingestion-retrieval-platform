"""Async PostgreSQL persistence layer with SQLAlchemy 2.0."""

from ai_ingestion_retrieval_platform.persistence.engine import (
    close_database,
    create_database_engine,
    get_session_factory,
)
from ai_ingestion_retrieval_platform.persistence.models import (
    Base,
    IngestionRecord,
    ParsedDocument,
    Source,
)
from ai_ingestion_retrieval_platform.persistence.repositories import (
    IngestionRecordResult,
    IngestionRepository,
    ParsedDocumentResult,
    SourceResult,
)

__all__ = [
    "Base",
    "Source",
    "IngestionRecord",
    "ParsedDocument",
    "IngestionRepository",
    "SourceResult",
    "IngestionRecordResult",
    "ParsedDocumentResult",
    "create_database_engine",
    "get_session_factory",
    "close_database",
]
