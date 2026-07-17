"""Async parser boundary for local document parsing."""

import asyncio
from io import BytesIO
from time import perf_counter

from bs4 import BeautifulSoup
from fastapi import HTTPException
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from ai_ingestion_retrieval_platform.core.config import Settings
from ai_ingestion_retrieval_platform.core.metrics import (
    PARSER_DURATION_SECONDS,
    PARSER_EXTRACTED_CHARS,
    PARSER_INPUT_BYTES,
    PARSER_REQUESTS_TOTAL,
)
from ai_ingestion_retrieval_platform.core.response_admission import (
    normalize_content_type,
)
from ai_ingestion_retrieval_platform.schemas.parsing import ParsedDocument, ParseRequest

ERROR_PARSE_CONTENT_TOO_LARGE = "Document is too large to parse"
ERROR_PARSE_CONTENT_TYPE_UNSUPPORTED = "Content type is not supported for parsing"
ERROR_PARSE_TIMEOUT = "Document parsing timed out"
ERROR_PARSE_PDF_MALFORMED = "PDF could not be parsed"
ERROR_PARSE_PDF_TOO_MANY_PAGES = "PDF has too many pages to parse"

_PARSER_RESULT_BY_HTTP_DETAIL = {
    ERROR_PARSE_CONTENT_TOO_LARGE: "too_large",
    ERROR_PARSE_CONTENT_TYPE_UNSUPPORTED: "unsupported_content_type",
    ERROR_PARSE_PDF_MALFORMED: "pdf_malformed",
    ERROR_PARSE_PDF_TOO_MANY_PAGES: "pdf_too_many_pages",
}


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
        content_type=normalize_content_type(request.content_type) or "",
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
    normalized_content_type = normalize_content_type(request.content_type) or ""

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


def _get_parser_metric_content_type(
    request: ParseRequest,
    settings: Settings,
) -> str:
    normalized_content_type = normalize_content_type(request.content_type)

    if normalized_content_type is None:
        return "missing"

    if normalized_content_type in settings.allowed_parse_content_types:
        return normalized_content_type

    return "unsupported"


def _get_parser_result(exc: HTTPException) -> str:
    detail = exc.detail

    if isinstance(detail, str):
        return _PARSER_RESULT_BY_HTTP_DETAIL.get(detail, "http_error")

    return "http_error"


def _record_parser_attempt(
    *,
    content_type: str,
    result: str,
    input_bytes: int,
    elapsed_seconds: float,
    extracted_chars: int | None = None,
) -> None:
    PARSER_REQUESTS_TOTAL.labels(
        content_type=content_type,
        result=result,
    ).inc()
    PARSER_DURATION_SECONDS.labels(content_type=content_type).observe(elapsed_seconds)
    PARSER_INPUT_BYTES.labels(content_type=content_type).observe(input_bytes)

    if extracted_chars is not None:
        PARSER_EXTRACTED_CHARS.labels(content_type=content_type).observe(
            extracted_chars
        )


async def parse_document(
    request: ParseRequest,
    settings: Settings | None = None,
) -> ParsedDocument:
    runtime_settings = settings if settings is not None else Settings()
    metric_content_type = _get_parser_metric_content_type(request, runtime_settings)
    input_bytes = len(request.content)
    started_at = perf_counter()

    try:
        async with asyncio.timeout(runtime_settings.parse_timeout_seconds):
            parsed_document = await asyncio.to_thread(
                _parse_document_sync,
                request,
                runtime_settings,
            )

    except TimeoutError as exc:
        _record_parser_attempt(
            content_type=metric_content_type,
            result="timeout",
            input_bytes=input_bytes,
            elapsed_seconds=perf_counter() - started_at,
        )
        raise HTTPException(
            status_code=504,
            detail=ERROR_PARSE_TIMEOUT,
        ) from exc

    except HTTPException as exc:
        _record_parser_attempt(
            content_type=metric_content_type,
            result=_get_parser_result(exc),
            input_bytes=input_bytes,
            elapsed_seconds=perf_counter() - started_at,
        )
        raise

    except Exception:
        _record_parser_attempt(
            content_type=metric_content_type,
            result="error",
            input_bytes=input_bytes,
            elapsed_seconds=perf_counter() - started_at,
        )
        raise

    _record_parser_attempt(
        content_type=metric_content_type,
        result="success",
        input_bytes=input_bytes,
        elapsed_seconds=perf_counter() - started_at,
        extracted_chars=parsed_document.char_length,
    )

    return parsed_document
