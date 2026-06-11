# AI Ingestion & Retrieval Platform

Production-grade async ingestion and retrieval platform built with FastAPI and modern Python backend patterns.

## Focus Areas

- Async FastAPI backend reliability
- Safe and resilient external URL ingestion
- Concurrency control and bounded outbound I/O
- Production observability and operational security

## Current Features

- Async URL preview ingestion pipeline
- SSRF and DNS safety checks for outbound fetches
- Redirect validation and response body size capping
- Bounded concurrency with global outbound limiting
- Shared async HTTP client via FastAPI lifespan and dependency injection
- Connection pooling and phase-specific HTTP timeouts
- Retry and backoff with 429 Retry-After support
- Partial batch failure handling with typed error mapping
- Structured JSON logs with request correlation IDs
- Protected Prometheus metrics endpoint disabled by default
- ASGI request logging middleware with latency and error metrics
- Config-driven runtime settings and validated request bounds

## Stack

- uv
- FastAPI
- httpx
- asyncio
- structlog
- prometheus-client
- pydantic-settings
- tenacity
- Ruff
- pytest
- pytest-asyncio
- pytest-cov
- pytest-mock
- respx

## Setup

```bash
git clone https://github.com/apfb11/ai-ingestion-retrieval-platform.git
cd ai-ingestion-retrieval-platform
uv sync
cp .env.example .env
PYTHONPATH=src uv run uvicorn ai_ingestion_retrieval_platform.main:app --reload
```

## Project Structure

```text
src/
└── ai_ingestion_retrieval_platform/
    ├── api/
    │   ├── dependencies/
    │   └── routes/
    ├── core/
    ├── middleware/
    ├── schemas/
    ├── services/
    └── main.py

tests/
├── conftest.py
├── fixtures/
├── integration/
├── performance/
└── unit/
```

## API Docs

http://127.0.0.1:8000/docs

## Metrics

http://127.0.0.1:8000/metrics

The metrics endpoint is disabled by default. To enable it, set:

- `METRICS_ENABLED=true`
- `METRICS_TOKEN=<your-token>`

Then query it with a bearer token:

```bash
curl -H "Authorization: Bearer <your-token>" http://127.0.0.1:8000/metrics
```

## Development

```bash
uv run ruff format .
uv run ruff check . --fix
```

## Testing

```bash
uv run pytest
```

## Status

Current implementation scope: ingestability verification and preview output, not full persistence/indexing/retrieval yet.

Current focus:

- Stage 1 FastAPI reliability hardening (complete)
- Secure and resilient URL preview ingestion
- Observability and test baseline
- Transition to persistence/indexing/retrieval work

Next phase:

- PostgreSQL
- pgvector
- embeddings integration
- persistence/indexing/retrieval pipeline
- retrieval API with relevance and latency evaluation
- performance/load testing (after retrieval MVP baseline)

Observability follow-ups:

- metric path normalization when parameterized routes appear
- dashboards and alerts
- centralized log aggregation at deploy stage
- OpenTelemetry once service boundaries increase
- distributed tracing when workers, DB, Redis, or Kafka are added
- log sampling when traffic volume is high
