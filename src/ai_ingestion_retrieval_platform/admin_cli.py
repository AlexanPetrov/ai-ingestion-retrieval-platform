"""Administrative CLI for AI Ingestion & Retrieval Platform."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

from ai_ingestion_retrieval_platform.core.config import Settings
from ai_ingestion_retrieval_platform.persistence.admin_repository import (
    IngestionDetail,
    IngestionSummary,
    ParsedDocumentDetail,
    ParsedDocumentSummary,
    SourceSummary,
)
from ai_ingestion_retrieval_platform.services.admin import (
    DatabaseNotEnabledError,
    DocumentNotFoundError,
    IngestionNotFoundError,
    InvalidAdminLimitError,
    InvalidDocumentIdError,
    InvalidIngestionIdError,
    InvalidSourceIdError,
    SourceNotFoundError,
    get_database_stats,
    get_document,
    get_ingestion,
    get_source,
    list_documents,
    list_ingestions,
    list_sources,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the administrative CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="ai-irp-admin",
        description="Administrative tools for AI Ingestion & Retrieval Platform.",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    sources_parser = subparsers.add_parser(
        "sources",
        help="Inspect persisted sources.",
    )

    sources_subparsers = sources_parser.add_subparsers(
        dest="sources_command",
        required=True,
    )

    sources_list_parser = sources_subparsers.add_parser(
        "list",
        help="List persisted sources.",
    )
    sources_list_parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of sources to return (default: 50, maximum: 500).",
    )

    sources_show_parser = sources_subparsers.add_parser(
        "show",
        help="Show one persisted source.",
    )
    sources_show_parser.add_argument(
        "source_id",
        help="UUID of the source to show.",
    )

    ingestions_parser = subparsers.add_parser(
        "ingestions",
        help="Inspect ingestion records.",
    )

    ingestions_subparsers = ingestions_parser.add_subparsers(
        dest="ingestions_command",
        required=True,
    )

    ingestions_list_parser = ingestions_subparsers.add_parser(
        "list",
        help="List persisted ingestion records.",
    )
    ingestions_list_parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help=(
            "Maximum number of ingestion records to return (default: 50, maximum: 500)."
        ),
    )

    ingestions_show_parser = ingestions_subparsers.add_parser(
        "show",
        help="Show one persisted ingestion record.",
    )
    ingestions_show_parser.add_argument(
        "ingestion_id",
        help="UUID of the ingestion record to show.",
    )

    documents_parser = subparsers.add_parser(
        "documents",
        help="Inspect parsed documents.",
    )

    documents_subparsers = documents_parser.add_subparsers(
        dest="documents_command",
        required=True,
    )

    documents_list_parser = documents_subparsers.add_parser(
        "list",
        help="List persisted parsed documents.",
    )
    documents_list_parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help=(
            "Maximum number of parsed documents to return (default: 50, maximum: 500)."
        ),
    )

    documents_show_parser = documents_subparsers.add_parser(
        "show",
        help="Show one persisted parsed document.",
    )
    documents_show_parser.add_argument(
        "document_id",
        help="UUID of the parsed document to show.",
    )

    database_parser = subparsers.add_parser(
        "database",
        help="Database administration.",
    )

    database_subparsers = database_parser.add_subparsers(
        dest="database_command",
        required=True,
    )

    database_subparsers.add_parser(
        "stats",
        help="Show persisted entity counts.",
    )

    return parser


async def _show_database_stats() -> int:
    """Print database statistics."""
    settings = Settings()
    stats = await get_database_stats(settings)

    print("Database statistics")
    print(f"Sources:           {stats.sources}")
    print(f"Ingestion records: {stats.ingestion_records}")
    print(f"Parsed documents:  {stats.parsed_documents}")

    return 0


def _print_source(source: SourceSummary) -> None:
    """Print one source summary."""
    print(f"ID:        {source.id}")
    print(f"URL:       {source.url}")
    print(f"Created:   {source.created_at.isoformat()}")
    print(f"Last seen: {source.last_seen_at.isoformat()}")


async def _show_sources(*, limit: int) -> int:
    """Print persisted sources."""
    settings = Settings()
    sources = await list_sources(
        settings,
        limit=limit,
    )

    if not sources:
        print("No sources found.")
        return 0

    print(f"Sources ({len(sources)})")

    for index, source in enumerate(sources):
        if index:
            print()

        _print_source(source)

    return 0


async def _show_source(*, source_id: str) -> int:
    """Print one persisted source."""
    settings = Settings()
    source = await get_source(
        settings,
        source_id=source_id,
    )

    print("Source")
    _print_source(source)

    return 0


def _display_optional(value: object | None) -> str:
    """Return a display-safe value for optional administrative fields."""
    if value is None:
        return "-"

    return str(value)


def _print_ingestion(ingestion: IngestionSummary) -> None:
    """Print one ingestion summary."""
    print(f"ID:             {ingestion.id}")
    print(f"Source ID:      {ingestion.source_id}")
    print(f"Mode:           {ingestion.ingestion_mode}")
    print(f"Batch ID:       {_display_optional(ingestion.batch_id)}")
    print(f"Batch position: {_display_optional(ingestion.batch_position)}")
    print(f"Ingested:       {ingestion.ingested_at.isoformat()}")


async def _show_ingestions(*, limit: int) -> int:
    """Print persisted ingestion records."""
    settings = Settings()
    ingestions = await list_ingestions(
        settings,
        limit=limit,
    )

    if not ingestions:
        print("No ingestion records found.")
        return 0

    print(f"Ingestion records ({len(ingestions)})")

    for index, ingestion in enumerate(ingestions):
        if index:
            print()

        _print_ingestion(ingestion)

    return 0


def _print_ingestion_detail(ingestion: IngestionDetail) -> None:
    """Print one detailed ingestion record."""
    print(f"ID:                      {ingestion.id}")
    print(f"Source ID:               {ingestion.source_id}")
    print(f"Parsed document ID:      {_display_optional(ingestion.parsed_document_id)}")
    print(f"Mode:                    {ingestion.ingestion_mode}")
    print(f"Batch ID:                {_display_optional(ingestion.batch_id)}")
    print(f"Batch position:          {_display_optional(ingestion.batch_position)}")
    print(f"Request ID:              {_display_optional(ingestion.request_id)}")
    print(f"Client IP:               {_display_optional(ingestion.client_ip)}")
    print(f"HTTP status:             {_display_optional(ingestion.http_status)}")
    print(f"HTTP status reason:      {_display_optional(ingestion.http_status_reason)}")
    print(f"Final URL:               {_display_optional(ingestion.final_url)}")
    print(
        f"Response content type:   {_display_optional(ingestion.response_content_type)}"
    )
    print(
        "Response content length: "
        f"{_display_optional(ingestion.response_content_length)}"
    )
    print(f"Fetch elapsed ms:        {_display_optional(ingestion.fetch_elapsed_ms)}")
    print(f"Fetch error code:        {_display_optional(ingestion.fetch_error_code)}")
    print(
        f"Fetch error message:     {_display_optional(ingestion.fetch_error_message)}"
    )
    print(f"Retry attempts:          {ingestion.retry_attempts}")
    print(f"Fetched:                 {ingestion.fetched_at.isoformat()}")
    print(f"Parser name:             {_display_optional(ingestion.parser_name)}")
    print(f"Parser version:          {_display_optional(ingestion.parser_version)}")
    print(f"Parse elapsed ms:        {_display_optional(ingestion.parse_elapsed_ms)}")
    print(f"Parse error code:        {_display_optional(ingestion.parse_error_code)}")
    print(
        f"Parse error message:     {_display_optional(ingestion.parse_error_message)}"
    )
    print(f"Ingested:                {ingestion.ingested_at.isoformat()}")


async def _show_ingestion(*, ingestion_id: str) -> int:
    """Print one persisted ingestion record."""
    settings = Settings()
    ingestion = await get_ingestion(
        settings,
        ingestion_id=ingestion_id,
    )

    print("Ingestion record")
    _print_ingestion_detail(ingestion)

    return 0


def _print_document(document: ParsedDocumentSummary) -> None:
    """Print one parsed-document summary."""
    print(f"ID:                  {document.id}")
    print(f"Ingestion record ID: {document.ingestion_record_id}")
    print(f"Content type:        {document.content_type}")
    print(f"Character length:    {document.char_length}")
    print(f"Created:             {document.created_at.isoformat()}")


async def _show_documents(*, limit: int) -> int:
    """Print persisted parsed documents."""
    settings = Settings()
    documents = await list_documents(
        settings,
        limit=limit,
    )

    if not documents:
        print("No parsed documents found.")
        return 0

    print(f"Parsed documents ({len(documents)})")

    for index, document in enumerate(documents):
        if index:
            print()

        _print_document(document)

    return 0


def _print_document_detail(document: ParsedDocumentDetail) -> None:
    """Print one detailed parsed document."""
    print(f"ID:                  {document.id}")
    print(f"Ingestion record ID: {document.ingestion_record_id}")
    print(f"Content type:        {document.content_type}")
    print(f"Character length:    {document.char_length}")
    print(f"Created:             {document.created_at.isoformat()}")
    print()
    print("Text content:")
    print(document.text_content)


async def _show_document(*, document_id: str) -> int:
    """Print one persisted parsed document."""
    settings = Settings()
    document = await get_document(
        settings,
        document_id=document_id,
    )

    print("Parsed document")
    _print_document_detail(document)

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the administrative CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "database" and args.database_command == "stats":
            return asyncio.run(_show_database_stats())

        if args.command == "sources":
            if args.sources_command == "list":
                return asyncio.run(
                    _show_sources(
                        limit=args.limit,
                    )
                )

            if args.sources_command == "show":
                return asyncio.run(
                    _show_source(
                        source_id=args.source_id,
                    )
                )

        if args.command == "ingestions":
            if args.ingestions_command == "list":
                return asyncio.run(
                    _show_ingestions(
                        limit=args.limit,
                    )
                )

            if args.ingestions_command == "show":
                return asyncio.run(
                    _show_ingestion(
                        ingestion_id=args.ingestion_id,
                    )
                )

        if args.command == "documents":
            if args.documents_command == "list":
                return asyncio.run(
                    _show_documents(
                        limit=args.limit,
                    )
                )

            if args.documents_command == "show":
                return asyncio.run(
                    _show_document(
                        document_id=args.document_id,
                    )
                )

        parser.error(f"Command {args.command!r} is not implemented yet.")

    except (
        DatabaseNotEnabledError,
        DocumentNotFoundError,
        IngestionNotFoundError,
        InvalidAdminLimitError,
        InvalidDocumentIdError,
        InvalidIngestionIdError,
        InvalidSourceIdError,
        SourceNotFoundError,
    ) as exc:
        print(f"ai-irp-admin: {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
