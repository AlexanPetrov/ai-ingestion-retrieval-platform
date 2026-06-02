# AI Ingestion & Retrieval Platform

Production-oriented async ingestion and retrieval platform built with FastAPI and modern Python backend patterns.

## Focus Areas

- Async systems
- Concurrent ingestion pipelines
- Resilient external I/O
- Structured observability
- Production backend architecture
- Retrieval infrastructure foundations

## Current Features

- Async URL ingestion
- SSRF-safe URL validation
- Private/internal IP blocking
- Redirect validation
- Response size limits
- Bounded concurrency
- Global outbound fetch limiting
- Shared async HTTP client lifecycle
- Connection pooling
- Retry/backoff handling
- Timeout protection
- Partial batch failure handling
- Structured JSON logging
- Request correlation IDs
- Prometheus metrics
- Failure-path request metrics
- Typed ingestion errors
- ASGI request middleware
- Config-driven runtime settings

## Stack

- FastAPI
- httpx
- asyncio
- structlog
- Prometheus client
- pydantic-settings
- tenacity
- Ruff

## Setup

```bash
git clone https://github.com/apfb11/ai-ingestion-retrieval-platform.git
cd ai-ingestion-retrieval-platform
uv sync
PYTHONPATH=src uv run uvicorn ai_ingestion_retrieval_platform.main:app --reload
```

## Project Structure

```text
src/
└── ai_ingestion_retrieval_platform/
    ├── api/
    │   └── routes/
    ├── core/
    ├── middleware/
    ├── schemas/
    ├── services/
    └── main.py
```

## API Docs

http://127.0.0.1:8000/docs

## Metrics

http://127.0.0.1:8000/metrics

## Development

```bash
uv run ruff format .
uv run ruff check . --fix
```

## Status

Current focus:

- async backend systems
- concurrency patterns
- observability
- backend optimization
- production architecture

Next phase:

- testing
- PostgreSQL
- pgvector
- retrieval pipeline architecture
- dependency injection cleanup
- phase-specific timeout tuning
- metrics endpoint hardening
