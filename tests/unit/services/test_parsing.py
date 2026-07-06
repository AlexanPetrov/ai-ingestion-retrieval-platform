"""Unit tests for local document parser boundary."""

import asyncio

import pytest
from fastapi import HTTPException
from tests.fixtures.pdf_bytes import build_text_pdf

from ai_ingestion_retrieval_platform.core.config import Settings
from ai_ingestion_retrieval_platform.schemas.parsing import ParseRequest
from ai_ingestion_retrieval_platform.services import parsing as parsing_service


@pytest.mark.asyncio
async def test_parse_document_parses_plain_text() -> None:
    result = await parsing_service.parse_document(
        ParseRequest(
            content=b"hello parser",
            content_type="text/plain",
            source_url="https://example.com/file.txt",
        ),
        settings=Settings(),
    )

    assert result.text == "hello parser"
    assert result.content_type == "text/plain"
    assert result.source_url == "https://example.com/file.txt"
    assert result.byte_length == 12
    assert result.char_length == 12


@pytest.mark.asyncio
async def test_parse_document_normalizes_content_type_with_charset() -> None:
    result = await parsing_service.parse_document(
        ParseRequest(
            content=b"hello",
            content_type="text/plain; charset=utf-8",
        ),
        settings=Settings(),
    )

    assert result.content_type == "text/plain"
    assert result.text == "hello"


@pytest.mark.asyncio
async def test_parse_document_truncates_parsed_text() -> None:
    result = await parsing_service.parse_document(
        ParseRequest(
            content=b"abcdef",
            content_type="text/plain",
        ),
        settings=Settings(max_parsed_text_chars=3),
    )

    assert result.text == "abc"
    assert result.byte_length == 6
    assert result.char_length == 3


@pytest.mark.asyncio
async def test_parse_document_extracts_readable_html_text() -> None:
    result = await parsing_service.parse_document(
        ParseRequest(
            content=(
                b"<html><head><style>.hidden{display:none}</style>"
                b"<script>alert('no')</script></head>"
                b"<body><h1>Hello</h1><p>Readable text</p></body></html>"
            ),
            content_type="text/html; charset=utf-8",
            source_url="https://example.com/page",
        ),
        settings=Settings(),
    )

    assert result.content_type == "text/html"
    assert result.source_url == "https://example.com/page"
    assert result.text == "Hello\nReadable text"
    assert "alert" not in result.text
    assert "display:none" not in result.text


@pytest.mark.asyncio
async def test_parse_document_truncates_html_text() -> None:
    result = await parsing_service.parse_document(
        ParseRequest(
            content=b"<html><body><p>abcdef</p></body></html>",
            content_type="text/html",
        ),
        settings=Settings(max_parsed_text_chars=3),
    )

    assert result.text == "abc"
    assert result.char_length == 3


@pytest.mark.asyncio
async def test_parse_document_parses_pdf_text() -> None:
    pdf_bytes = build_text_pdf(["hello pdf parser"])

    result = await parsing_service.parse_document(
        ParseRequest(
            content=pdf_bytes,
            content_type="application/pdf",
            source_url="https://example.com/file.pdf",
        ),
        settings=Settings(),
    )

    assert "hello pdf parser" in result.text
    assert result.content_type == "application/pdf"
    assert result.source_url == "https://example.com/file.pdf"
    assert result.byte_length == len(pdf_bytes)
    assert result.char_length == len(result.text)


@pytest.mark.asyncio
async def test_parse_document_rejects_pdf_over_page_limit() -> None:
    pdf_bytes = build_text_pdf(["page one", "page two"])

    with pytest.raises(HTTPException) as exc_info:
        await parsing_service.parse_document(
            ParseRequest(
                content=pdf_bytes,
                content_type="application/pdf",
            ),
            settings=Settings(max_parse_pages=1),
        )

    assert exc_info.value.status_code == 413
    assert exc_info.value.detail == parsing_service.ERROR_PARSE_PDF_TOO_MANY_PAGES


@pytest.mark.asyncio
async def test_parse_document_rejects_malformed_pdf() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await parsing_service.parse_document(
            ParseRequest(
                content=b"not a real pdf",
                content_type="application/pdf",
            ),
            settings=Settings(),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == parsing_service.ERROR_PARSE_PDF_MALFORMED


@pytest.mark.asyncio
async def test_parse_document_truncates_pdf_text() -> None:
    pdf_bytes = build_text_pdf(["hello pdf parser"])

    result = await parsing_service.parse_document(
        ParseRequest(
            content=pdf_bytes,
            content_type="application/pdf",
        ),
        settings=Settings(max_parsed_text_chars=5),
    )

    assert result.text == "hello"
    assert result.char_length == 5


@pytest.mark.asyncio
async def test_parse_document_rejects_unsupported_content_type() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await parsing_service.parse_document(
            ParseRequest(
                content=b'{"ok": true}',
                content_type="application/json",
            ),
            settings=Settings(),
        )

    assert exc_info.value.status_code == 415
    assert exc_info.value.detail == parsing_service.ERROR_PARSE_CONTENT_TYPE_UNSUPPORTED


@pytest.mark.asyncio
async def test_parse_document_rejects_oversized_content() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await parsing_service.parse_document(
            ParseRequest(
                content=b"abcd",
                content_type="text/plain",
            ),
            settings=Settings(max_parse_bytes=3),
        )

    assert exc_info.value.status_code == 413
    assert exc_info.value.detail == parsing_service.ERROR_PARSE_CONTENT_TOO_LARGE


@pytest.mark.asyncio
async def test_parse_document_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def slow_parse(
        _request: ParseRequest,
        _settings: Settings,
    ) -> object:
        import time

        time.sleep(0.05)
        return None

    monkeypatch.setattr(parsing_service, "_parse_document_sync", slow_parse)

    with pytest.raises(HTTPException) as exc_info:
        await parsing_service.parse_document(
            ParseRequest(
                content=b"hello",
                content_type="text/plain",
            ),
            settings=Settings(parse_timeout_seconds=0.001),
        )

    assert exc_info.value.status_code == 504
    assert exc_info.value.detail == parsing_service.ERROR_PARSE_TIMEOUT


@pytest.mark.asyncio
async def test_parse_document_uses_thread_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_to_thread(
        func: object,
        *args: object,
    ) -> object:
        captured["func"] = func
        captured["args"] = args
        return parsing_service.ParsedDocument(
            text="ok",
            content_type="text/plain",
            source_url=None,
            byte_length=2,
            char_length=2,
        )

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    result = await parsing_service.parse_document(
        ParseRequest(
            content=b"ok",
            content_type="text/plain",
        ),
        settings=Settings(),
    )

    assert result.text == "ok"
    assert captured["func"] is parsing_service._parse_document_sync
