"""Async parser boundary for local document parsing."""

import asyncio
from io import BytesIO

from bs4 import BeautifulSoup
from fastapi import HTTPException
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from ai_ingestion_retrieval_platform.core.config import Settings
from ai_ingestion_retrieval_platform.schemas.parsing import ParsedDocument, ParseRequest

ERROR_PARSE_CONTENT_TOO_LARGE = "Document is too large to parse"
ERROR_PARSE_CONTENT_TYPE_UNSUPPORTED = "Content type is not supported for parsing"
ERROR_PARSE_TIMEOUT = "Document parsing timed out"
ERROR_PARSE_PDF_MALFORMED = "PDF could not be parsed"
ERROR_PARSE_PDF_TOO_MANY_PAGES = "PDF has too many pages to parse"


def _normalize_content_type(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


def _truncate_text(text: str, settings: Settings) -> str:
    return text[: settings.max_parsed_text_chars]


def _build_parsed_document(
    request: ParseRequest,
    settings: Settings,
    text: str,
) -> ParsedDocument:
    text = _truncate_text(text, settings)

    return ParsedDocument(
        text=text,
        content_type=_normalize_content_type(request.content_type),
        source_url=request.source_url,
        byte_length=len(request.content),
        char_length=len(text),
    )


def _parse_text_content(request: ParseRequest, settings: Settings) -> ParsedDocument:
    text = request.content.decode("utf-8", errors="replace")
    return _build_parsed_document(request, settings, text)


def _parse_html_content(request: ParseRequest, settings: Settings) -> ParsedDocument:
    html = request.content.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")

    for element in soup(["script", "style", "noscript"]):
        element.decompose()

    text = soup.get_text(separator="\n", strip=True)
    return _build_parsed_document(request, settings, text)


def _parse_pdf_content(request: ParseRequest, settings: Settings) -> ParsedDocument:
    try:
        reader = PdfReader(BytesIO(request.content))
    except PdfReadError as exc:
        raise HTTPException(
            status_code=400,
            detail=ERROR_PARSE_PDF_MALFORMED,
        ) from exc

    page_count = len(reader.pages)

    if page_count > settings.max_parse_pages:
        raise HTTPException(
            status_code=413,
            detail=ERROR_PARSE_PDF_TOO_MANY_PAGES,
        )

    try:
        page_text = [
            page.extract_text() or ""
            for page in reader.pages[: settings.max_parse_pages]
        ]
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=ERROR_PARSE_PDF_MALFORMED,
        ) from exc

    return _build_parsed_document(request, settings, "\n".join(page_text))


def _parse_document_sync(
    request: ParseRequest,
    settings: Settings,
) -> ParsedDocument:
    normalized_content_type = _normalize_content_type(request.content_type)

    if normalized_content_type not in settings.allowed_parse_content_types:
        raise HTTPException(
            status_code=415,
            detail=ERROR_PARSE_CONTENT_TYPE_UNSUPPORTED,
        )

    if len(request.content) > settings.max_parse_bytes:
        raise HTTPException(
            status_code=413,
            detail=ERROR_PARSE_CONTENT_TOO_LARGE,
        )

    if normalized_content_type == "text/plain":
        return _parse_text_content(request, settings)

    if normalized_content_type == "text/html":
        return _parse_html_content(request, settings)

    if normalized_content_type == "application/pdf":
        return _parse_pdf_content(request, settings)

    raise HTTPException(
        status_code=415,
        detail=ERROR_PARSE_CONTENT_TYPE_UNSUPPORTED,
    )


async def parse_document(
    request: ParseRequest,
    settings: Settings | None = None,
) -> ParsedDocument:
    runtime_settings = settings if settings is not None else Settings()

    try:
        async with asyncio.timeout(runtime_settings.parse_timeout_seconds):
            return await asyncio.to_thread(
                _parse_document_sync,
                request,
                runtime_settings,
            )

    except TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail=ERROR_PARSE_TIMEOUT,
        ) from exc
