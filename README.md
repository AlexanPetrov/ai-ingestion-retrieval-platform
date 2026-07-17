# AI Ingestion & Retrieval Platform

Production-grade async ingestion platform built with FastAPI, bounded outbound I/O, SSRF protections, parser isolation, authentication, rate limiting, and operational observability.

Current stage: **Stage 1 — Secure Ingestion Preview Foundation**

The current implementation supports secure raw and parsed URL preview flows. Persistence, indexing, embeddings, pgvector search, and retrieval APIs are planned but not implemented yet.

## Implemented Scope

- Raw and parsed URL preview ingestion
- Single-URL and batch ingestion routes
- Safe outbound URL fetching with SSRF/DNS protections
- Redirect validation and response-size caps
- Response admission checks for declared `Content-Length` and allowed parsed `Content-Type`
- Byte-level content sniffing for parsed ingestion responses
- Text, HTML, and PDF parsing boundary
- Global, per-host, and per-batch concurrency controls
- Shared `httpx.AsyncClient` lifecycle through FastAPI lifespan
- Retry/backoff with `429` / `503` `Retry-After` support
- Per-URL timeout enforcement
- Optional Bearer authentication for ingestion routes
- Redis-backed inbound API rate limiting
- Weighted rate-limit costing for parsed requests and batch URL counts
- Partial batch failure handling with typed error mapping
- Structured JSON logging with request correlation IDs
- Prometheus metrics for requests, retries, timeouts, rate limits, parser behavior, and limiter saturation
- Liveness and readiness health checks
- Cross-setting configuration validation at application startup
- Ruff, Pyright, pytest, coverage, and performance baseline checks

## API Surface

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/ingestion/url/preview` | Fetch one URL and return raw preview text |
| `POST` | `/ingestion/url/parse-preview` | Fetch one URL, parse supported content, and return parsed preview text |
| `POST` | `/ingestion/urls/preview` | Fetch multiple URLs and return raw preview results |
| `POST` | `/ingestion/urls/parse-preview` | Fetch multiple URLs, parse supported content, and return parsed preview results |
| `GET` | `/health/live` | Liveness probe |
| `GET` | `/health/ready` | Readiness probe |
| `GET` | `/metrics` | Protected Prometheus metrics endpoint |

Swagger UI is available locally at:

```text
http://127.0.0.1:8000/docs
```

## Runtime Behavior

### Outbound Fetch Safety

- Rejects unsafe URL schemes
- Rejects credentials embedded in URLs
- Restricts outbound fetch ports
- Resolves and validates DNS targets
- Blocks unsafe private, loopback, link-local, multicast, and otherwise disallowed IP ranges
- Revalidates every redirect target
- Preserves original Host header and SNI while connecting to the pinned resolved IP
- Applies global and per-host concurrency limits

### Response Admission

- Rejects oversized declared `Content-Length` before reading the body
- Restricts parsed ingestion to configured supported content types
- Caps response bodies while streaming
- Applies byte-level sniffing for parsed ingestion:
  - `application/pdf` must look like PDF bytes
  - `text/html` must look like HTML bytes
  - `text/plain` must decode as text and not look binary

### Parsing Boundary

Supported parsed content types:

- `text/plain`
- `text/html`
- `application/pdf`

Parsing runs behind a local parser boundary with configurable byte, page, text-length, and timeout limits.

### Rate Limiting

Inbound ingestion rate limits are work-weighted:

| Route type | Default cost |
|---|---:|
| Raw single-URL preview | `1` |
| Parsed single-URL preview | `2` |
| Raw batch preview | `1` per URL |
| Parsed batch preview | `2` per URL |

Redis is required when `RATE_LIMIT_ENABLED=true`.

### Authentication

Ingestion-route authentication is optional and disabled by default.

When enabled, ingestion routes require:

```http
Authorization: Bearer <token>
```

Metrics use a separate metrics token.

## Stack

Runtime:

- Python 3.14
- uv
- FastAPI
- Uvicorn
- Pydantic
- pydantic-settings
- httpx
- asyncio
- structlog
- prometheus-client
- tenacity
- Redis
- limits
- pypdf
- beautifulsoup4

Development and testing:

- Ruff
- Pyright
- pytest
- pytest-asyncio
- pytest-cov
- pytest-mock
- respx

## Setup

Clone the repository:

```bash
git clone https://github.com/apfb11/ai-ingestion-retrieval-platform.git
cd ai-ingestion-retrieval-platform
```

Install Python and project dependencies:

```bash
uv python install 3.14
uv sync
```

Create a local environment file:

```bash
cp .env.example .env
```

Edit `.env` as needed.

Start Redis when `RATE_LIMIT_ENABLED=true`:

```bash
brew services start redis
redis-cli ping
```

Expected Redis check:

```text
PONG
```

Run the API locally:

```bash
uv run uvicorn ai_ingestion_retrieval_platform.main:create_app --factory --reload
```

Open Swagger UI:

```text
http://127.0.0.1:8000/docs
```

Check health:

```bash
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
```

## Configuration

Key environment settings:

| Setting | Purpose |
|---|---|
| `LOG_LEVEL` | Application log level |
| `METRICS_ENABLED` | Enables or disables `/metrics` |
| `METRICS_TOKEN` | Bearer token for `/metrics` |
| `INGESTION_AUTH_ENABLED` | Enables Bearer auth for ingestion routes |
| `INGESTION_AUTH_TOKEN` | Bearer token for ingestion routes |
| `RATE_LIMIT_ENABLED` | Enables Redis-backed inbound rate limiting |
| `RATE_LIMIT_REDIS_URL` | Redis URL used by the rate limiter |
| `MAX_BATCH_URLS` | Maximum URLs accepted in a batch request |
| `MAX_PREVIEW_BYTES` | Raw preview fetch byte cap |
| `MAX_PARSE_BYTES` | Parsed ingestion fetch byte cap |
| `MAX_PARSED_TEXT_CHARS` | Parsed preview text cap |
| `MAX_PARSE_PAGES` | PDF page cap |
| `PARSE_TIMEOUT_SECONDS` | Parser timeout |
| `ALLOWED_PARSE_CONTENT_TYPES` | Content types accepted for parsed ingestion |
| `GLOBAL_MAX_OUTBOUND_FETCHES` | Global outbound fetch concurrency limit |
| `HOST_MAX_CONCURRENCY` | Per-host outbound fetch concurrency limit |

Cross-setting validation rejects contradictory limits and incomplete security configuration during startup.

## Metrics

Prometheus metrics are available at:

```text
http://127.0.0.1:8000/metrics
```

The metrics endpoint is disabled by default. To enable it, set:

```dotenv
METRICS_ENABLED=true
METRICS_TOKEN=<your-token>
```

Query metrics with a bearer token:

```bash
curl -H "Authorization: Bearer <your-token>" http://127.0.0.1:8000/metrics
```

Metrics include:

- HTTP request count and latency
- Request error count
- Ingestion retry count
- Ingestion timeout count
- Global outbound limiter wait time
- Per-host limiter wait time
- Outbound in-flight fetch count
- Rate-limit allowed, blocked, and storage-error decisions
- Parser attempts, duration, input bytes, and extracted characters

## Health Checks

Liveness and readiness endpoints are available at:

```text
http://127.0.0.1:8000/health/live
http://127.0.0.1:8000/health/ready
```

Readiness verifies required shared runtime resources, including the shared HTTP client and Redis rate-limit storage when rate limiting is enabled.

## Project Structure

```text
.
├── pyproject.toml
├── README.md
├── uv.lock
├── src/
│   └── ai_ingestion_retrieval_platform/
│       ├── api/
│       │   ├── dependencies/
│       │   │   ├── auth.py
│       │   │   ├── http_client.py
│       │   │   ├── rate_limit.py
│       │   │   └── settings.py
│       │   └── routes/
│       │       ├── health.py
│       │       ├── ingestion.py
│       │       └── metrics.py
│       ├── core/
│       │   ├── config.py
│       │   ├── content_sniffing.py
│       │   ├── limits.py
│       │   ├── logging.py
│       │   ├── metrics.py
│       │   ├── response_admission.py
│       │   └── url_safety.py
│       ├── middleware/
│       │   └── request_logging.py
│       ├── schemas/
│       │   ├── ingestion.py
│       │   └── parsing.py
│       ├── services/
│       │   ├── fetching.py
│       │   ├── ingestion.py
│       │   └── parsing.py
│       └── main.py
└── tests/
    ├── conftest.py
    ├── fixtures/
    │   └── pdf_bytes.py
    ├── integration/
    │   ├── api/
    │   └── app/
    ├── performance/
    │   └── test_ingestion_latency.py
    └── unit/
        ├── api/
        ├── core/
        ├── middleware/
        └── services/
```

## Development

Format source code:

```bash
uv run ruff format .
```

Run lint checks:

```bash
uv run ruff check .
```

Run static type checks:

```bash
uv run pyright
```

Run tests:

```bash
uv run pytest
```

Run the full verification suite:

```bash
uv run ruff format .
uv run ruff check .
uv run pyright
uv run pytest
```

Current verified baseline:

```text
196 passed
94.32% test coverage
Ruff clean
Pyright clean
```

## Local Redis

Start Redis:

```bash
brew services start redis
```

Check connectivity:

```bash
redis-cli ping
```

Inspect local Redis state:

```bash
redis-cli DBSIZE
redis-cli --scan
```

Clear local Redis state:

```bash
redis-cli FLUSHDB
```

Stop Redis:

```bash
brew services stop redis
```

## Roadmap

### Stage 2 — Persistence Design

Define the persistence model before adding database code:

- persisted source metadata
- parsed document storage
- source-to-document relationships
- parser and fetch metadata required for audit/debugging
- boundaries between preview-only behavior and persisted ingestion

### Stage 3 — Persistence Implementation

Planned implementation work:

- PostgreSQL
- async database access layer
- Alembic migrations
- persisted ingestion writes
- repository/service boundaries
- persistence tests

### Stage 4 — Indexing and Retrieval

Planned retrieval work:

- document chunking
- embeddings integration
- pgvector storage
- vector similarity search
- retrieval API
- relevance evaluation
- retrieval latency evaluation
- load testing after retrieval MVP

## Deferred Operational Work

Deferred until deployment or additional service boundaries require it:

- dashboards and alerts
- centralized log aggregation
- OpenTelemetry instrumentation
- distributed tracing across API, workers, database, Redis, and future queue systems
- log sampling for high-volume traffic