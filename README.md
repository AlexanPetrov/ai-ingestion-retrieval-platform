# AI Ingestion & Retrieval Platform

Production-grade asynchronous ingestion platform built with FastAPI, secure outbound I/O, bounded parser execution, PostgreSQL persistence, Alembic migrations, authentication, rate limiting, operational observability, and shell-based administrative tooling.

**Current status: Stage 3.5 in progress — Production Hardening / Operationalization**

Stages 1–3 are complete. Stage 3.5 now includes destructive administrative lifecycle tooling, deterministic parsed-content identity, parser provenance, persistence-specific Prometheus metrics, and durable architecture/operations documentation.

**Remaining before Stage 4:** final Stage 3.5 repository review, verification checkpoint, and commit/push.

**Stage 4 — Indexing and Retrieval** is planned but is **not implemented yet**.

---

## Documentation

- [Architecture](docs/architecture.md) — system boundaries, persistence model, transaction semantics, content identity, parser provenance, observability, and Stage 4 extension boundary.
- [Operations](docs/operations.md) — setup, PostgreSQL/Alembic, Redis, metrics, health checks, administrative CLI, troubleshooting, testing, and release verification.

This README is the project landing page. Detailed design and operational material live under `docs/`.

---

## Implemented Scope

### Secure ingestion

- Raw and parsed URL ingestion
- Preview-only and persisted ingestion modes
- Single-URL and batch ingestion routes
- SSRF-resistant outbound URL validation
- DNS resolution and resolved-IP validation
- Redirect revalidation
- Restricted outbound fetch ports
- Embedded URL credential rejection
- Declared `Content-Length` admission checks
- Bounded streaming response bodies
- Parsed `Content-Type` admission checks
- Byte-level content sniffing
- Text, HTML, and PDF parsing
- Per-URL timeout enforcement
- Retry/backoff with `429` / `503` `Retry-After` support
- Shared `httpx.AsyncClient` lifecycle
- Global, per-host, and per-batch concurrency controls
- Ordered batch results with per-URL partial failure handling

### Persistence

- PostgreSQL-backed durable ingestion
- Async SQLAlchemy / `asyncpg`
- Alembic-owned schema migrations
- Repository/service separation
- Explicit service-owned transaction boundaries
- Stable source identity by URL
- Immutable ingestion-attempt history
- Successful parsed-document storage
- Deterministic SHA-256 identity for exact persisted parsed text
- Migration-backed content-hash backfill
- Authoritative parser name/version propagation
- Parser provenance retention on expected parser failures after parser selection
- Request and batch correlation metadata
- Batch ordering through `batch_position`
- Database-aware readiness
- Explicit persistence-unavailable behavior
- Database constraints and referential integrity

### Administrative operations

- Internal shell-only `ai-irp-admin` CLI
- Database statistics
- Source list/detail inspection
- Ingestion list/detail inspection
- Parsed-document list/detail inspection
- Full persisted parsed-text inspection
- UUID validation and not-found handling
- Ingestion deletion with explicit confirmation
- Parsed-document cascade through ingestion deletion
- Restrictive source deletion while ingestion history exists
- Full application-data purge with explicit confirmation
- Transaction ownership and rollback for administrative writes

There is intentionally no independent parsed-document delete command. Parsed-document lifecycle belongs to the owning ingestion record.

### Security and observability

- Optional Bearer authentication for ingestion routes
- Redis-backed weighted inbound rate limiting
- Structured JSON logging
- Request correlation IDs
- Prometheus metrics
- Persistence operation/error/transaction-duration metrics
- Liveness and dependency-aware readiness probes
- Cross-setting configuration validation

---

## Architecture Overview

```text
Client
  |
  v
FastAPI
  |
  +--> request correlation / logging
  +--> optional Bearer authentication
  +--> Redis-backed rate limiting
  +--> request validation
  |
  v
Ingestion orchestration
  |
  +--> secure fetch boundary
  |
  +--> bounded parser boundary
  |
  +--> persistence service
         |
         +--> service-owned transaction
         +--> repository layer
         +--> SQLAlchemy asyncio
         +--> asyncpg
         +--> PostgreSQL
```

Administrative operations use a separate shell-only path:

```text
Operator
  |
  v
ai-irp-admin
  |
  v
administrative service
  |
  v
administrative repository
  |
  v
PostgreSQL
```

See [docs/architecture.md](docs/architecture.md) for the full design.

---

## API Surface

### Preview endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/ingestion/url/preview` | Fetch one URL and return a bounded raw preview |
| `POST` | `/ingestion/url/parse-preview` | Fetch and parse one URL and return a bounded parsed preview |
| `POST` | `/ingestion/urls/preview` | Fetch multiple URLs and return ordered raw preview results |
| `POST` | `/ingestion/urls/parse-preview` | Fetch and parse multiple URLs and return ordered parsed preview results |

### Persisted ingestion endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/ingestion/url/ingest` | Fetch one URL, return a raw preview, and persist the attempt |
| `POST` | `/ingestion/url/parse-ingest` | Fetch and parse one URL, persist the attempt and parsed document |
| `POST` | `/ingestion/urls/ingest` | Persist a batch of raw ingestion attempts |
| `POST` | `/ingestion/urls/parse-ingest` | Persist a batch of parsed ingestion attempts |

Persisted success responses include durable identifiers such as:

- `source_id`
- `ingestion_record_id`
- `parsed_document_id` for successful parsed ingestion
- `batch_id` for batch ingestion

Persisted endpoints require:

```dotenv
DATABASE_ENABLED=true
```

If persistence is disabled, persisted endpoints return:

```text
503 Persistence is not enabled
```

### Operational endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health/live` | Process liveness probe |
| `GET` | `/health/ready` | Dependency-aware readiness probe |
| `GET` | `/metrics` | Protected Prometheus metrics endpoint |

Swagger UI is available locally at:

```text
http://127.0.0.1:8000/docs
```

There is no HTTP administration API.

---

## Persistence Model

```text
Source
  |
  | 1:N
  v
IngestionRecord
  |
  | 1:0..1
  v
ParsedDocument
```

### `Source`

Stable external URL identity.

- UUID primary key
- unique URL
- creation timestamp
- last-seen timestamp

### `IngestionRecord`

One durable ingestion attempt.

It stores:

- source reference
- ingestion mode
- request/batch correlation
- HTTP response metadata
- fetch timing/failure metadata
- parser name/version when known
- parse timing/failure metadata
- ingestion timestamp

### `ParsedDocument`

Successful bounded parser output for one ingestion.

It stores:

- ingestion-record reference
- content type
- character length
- full bounded parsed text
- `content_sha256`
- creation timestamp

`content_sha256` is:

```text
SHA-256(exact persisted text_content encoded as UTF-8)
```

No normalization is performed before hashing. The hash is an identity signal, not a uniqueness constraint.

See [docs/architecture.md](docs/architecture.md) for full persistence semantics.

---

## Parser Provenance

Current parser identities:

| Content type | Parser identity | Version semantics |
|---|---|---|
| `text/plain` | `python-utf8-replace` | adapter revision + Python runtime |
| `text/html` | `beautifulsoup4-html.parser` | adapter revision + Beautiful Soup + Python runtime |
| `application/pdf` | `pypdf` | adapter revision + pypdf version |

Parser provenance is stored for successful parsed ingestion and for expected parser failures when parser selection occurred before the failure.

Unsupported/selection failures do not fabricate provenance.

---

## Persistence Observability

Prometheus now includes:

```text
persistence_operations_total{operation,result}
persistence_errors_total{operation,error_type}
persistence_transaction_duration_seconds{operation}
```

Current bounded operation labels:

```text
fetch_failure_audit
raw_ingestion
parse_failure_audit
parsed_ingestion
```

The transaction-duration histogram measures only service-owned persistence transactions, including commit/rollback work. Fetch and parser execution are excluded.

No URL, UUID, request ID, batch ID, client IP, or exception message is used as a persistence metric label.

---

## Administrative CLI

The command surface is:

```text
ai-irp-admin
├── sources
│   ├── list [--limit N]
│   ├── show <uuid>
│   └── delete <uuid> --confirm
├── ingestions
│   ├── list [--limit N]
│   ├── show <uuid>
│   └── delete <uuid> --confirm
├── documents
│   ├── list [--limit N]
│   └── show <uuid>
└── database
    ├── stats
    └── purge --confirm
```

Examples:

```bash
uv run ai-irp-admin database stats

uv run ai-irp-admin sources list
uv run ai-irp-admin ingestions list
uv run ai-irp-admin documents list

uv run ai-irp-admin sources show <source-uuid>
uv run ai-irp-admin ingestions show <ingestion-uuid>
uv run ai-irp-admin documents show <document-uuid>
```

Destructive operations require explicit confirmation:

```bash
uv run ai-irp-admin ingestions delete <ingestion-uuid> --confirm
uv run ai-irp-admin sources delete <source-uuid> --confirm
uv run ai-irp-admin database purge --confirm
```

See [docs/operations.md](docs/operations.md) for destructive-operation semantics and operational guidance.

---

## Technology Stack

### Runtime

- Python 3.14
- FastAPI
- Uvicorn
- Pydantic
- pydantic-settings
- httpx
- asyncio
- SQLAlchemy asyncio
- asyncpg
- PostgreSQL
- Alembic
- Redis
- limits
- structlog
- prometheus-client
- tenacity
- pypdf
- beautifulsoup4

### Development and testing

- uv
- Ruff
- Pyright
- pytest
- pytest-asyncio
- pytest-cov
- pytest-mock
- respx

---

## Local Setup

### 1. Install dependencies

```bash
uv python install 3.14
uv sync
```

### 2. Create local configuration

```bash
cp .env.example .env
```

Do not commit real credentials, tokens, database passwords, `.env`, or local shell environment files.

### 3. Start Redis when rate limiting is enabled

```bash
brew services start redis
redis-cli ping
```

Expected:

```text
PONG
```

### 4. Configure PostgreSQL when persistence is enabled

Example:

```dotenv
DATABASE_ENABLED=true
DATABASE_URL=postgresql+asyncpg://app_user:change-me@127.0.0.1:5432/ai_ingestion_retrieval_platform
```

Create the database, then apply migrations:

```bash
createdb ai_ingestion_retrieval_platform
uv run alembic upgrade head
```

The application does not create tables automatically at startup.

### 5. Run the API

```bash
uv run uvicorn   ai_ingestion_retrieval_platform.main:create_app   --factory   --reload
```

### 6. Check health

```bash
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
```

For the full operational setup, see [docs/operations.md](docs/operations.md).

---

## PostgreSQL and Alembic

Alembic is the authoritative schema-management mechanism.

Apply migrations:

```bash
uv run alembic upgrade head
```

Inspect the current revision:

```bash
uv run alembic current
```

Check model/schema alignment:

```bash
uv run alembic check
```

Expected clean state:

```text
No new upgrade operations detected.
```

Current persistence migrations include:

```text
4eb7669e862c_create_ingestion_persistence_schema.py
e13f6c2d9a71_add_parsed_document_content_sha256.py
```

The content-hash migration backfills existing parsed documents before enforcing the non-null SHA-256 constraint.

---

## Configuration

Settings are loaded with `pydantic-settings`.

Important groups include:

### Application/security

- `APP_NAME`
- `LOG_LEVEL`
- `INGESTION_AUTH_ENABLED`
- `INGESTION_AUTH_TOKEN`
- `METRICS_ENABLED`
- `METRICS_TOKEN`

### Persistence

- `DATABASE_ENABLED`
- `DATABASE_URL`
- `DATABASE_POOL_SIZE`
- `DATABASE_POOL_TIMEOUT_SECONDS`
- `DATABASE_CONNECT_TIMEOUT_SECONDS`
- `DATABASE_READINESS_TIMEOUT_SECONDS`
- `DATABASE_ECHO_SQL`

### Fetching/parsing

- HTTP timeout/pool settings
- URL timeout
- redirect limit
- response-size limits
- parser byte/page/text limits
- parser timeout
- allowed content types

### Retry/concurrency

- retry attempts and total timeout
- retry backoff
- batch concurrency
- global outbound fetch limit
- per-host concurrency

### Rate limiting

- Redis URL
- fail-open/fail-closed behavior
- request quotas/windows
- weighted route costs

See [docs/operations.md](docs/operations.md) for operational configuration details.

---

## Metrics

Metrics are exposed at:

```text
http://127.0.0.1:8000/metrics
```

Enable them with:

```dotenv
METRICS_ENABLED=true
METRICS_TOKEN=<strong-secret>
```

Current metric coverage includes:

- HTTP request counts and latency
- ingestion retries and timeouts
- batch duration/in-flight work
- global/per-host/per-batch limiter wait time
- inbound rate-limit decisions/storage failures
- parser attempts/duration/input bytes/extracted characters
- persistence operation results
- persistence error categories
- persistence transaction duration

Request and persistence metric labels are intentionally bounded to avoid high-cardinality series.

---

## Health Checks

### Liveness

```text
GET /health/live
```

Checks whether the process is alive.

### Readiness

```text
GET /health/ready
```

Checks required runtime dependencies.

Current checks include:

- shared `httpx.AsyncClient`
- Redis storage when rate limiting is enabled
- PostgreSQL when persistence is enabled

Expected dependency-outage behavior:

```text
process alive + PostgreSQL unavailable
    -> /health/live  = 200
    -> /health/ready = 503
```

---

## Testing

The project uses layered verification:

- unit tests
- API integration tests
- application lifespan tests
- real PostgreSQL integration tests
- administrative repository/service/CLI tests
- content-identity migration tests
- parser-provenance integration tests
- performance baselines
- coverage enforcement
- Alembic model/schema drift checks

Real PostgreSQL tests live under:

```text
tests/integration/persistence/
├── conftest.py
├── test_content_sha256_migration.py
├── test_parser_provenance.py
└── test_postgres_persistence.py
```

### Current verified baseline

```text
79 files already formatted
Ruff checks passed
Pyright 1.1.414: 0 errors, 0 warnings, 0 informations
412 tests passed
96.53% total coverage
Alembic check: No new upgrade operations detected.
```

Configured coverage threshold:

```text
>= 90%
```

### Full verification gate

With a dedicated `TEST_DATABASE_URL` configured:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
uv run alembic check
```

---

## Project Structure

Generated caches and personal/local artifacts are omitted.

```text
.
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 4eb7669e862c_create_ingestion_persistence_schema.py
│       └── e13f6c2d9a71_add_parsed_document_content_sha256.py
├── alembic.ini
├── docs/
│   ├── architecture.md
│   └── operations.md
├── generate_token.py
├── pyproject.toml
├── README.md
├── src/
│   └── ai_ingestion_retrieval_platform/
│       ├── admin_cli.py
│       ├── main.py
│       ├── api/
│       ├── core/
│       │   ├── content_identity.py
│       │   ├── metrics.py
│       │   └── ...
│       ├── middleware/
│       ├── persistence/
│       ├── schemas/
│       └── services/
├── tests/
│   ├── integration/
│   │   ├── api/
│   │   ├── app/
│   │   └── persistence/
│   ├── performance/
│   └── unit/
└── uv.lock
```

---

## Development Workflow

Format:

```bash
uv run ruff format .
```

Lint:

```bash
uv run ruff check .
```

Type-check:

```bash
uv run pyright
```

Tests:

```bash
uv run pytest
```

Focused tests without global coverage:

```bash
uv run pytest --no-cov <test-path>
```

Migration drift:

```bash
uv run alembic check
```

---

## Roadmap

### Stage 1 — Secure Ingestion Preview Foundation

**Complete**

Implemented secure preview ingestion, SSRF/DNS protections, bounded streaming/parsing, retries, concurrency controls, authentication, Redis rate limiting, metrics, structured logging, and health checks.

### Stage 2 — Persistence Design

**Complete**

Defined source identity, ingestion history, parsed-document semantics, transaction ownership, batch identity/order, and metadata placement.

### Stage 3 — Persistence Implementation

**Complete**

Implemented PostgreSQL, SQLAlchemy/asyncpg, persistence repositories/services/routes, Alembic migrations, DB-aware readiness, and real PostgreSQL verification.

### Stage 3.5 — Production Hardening / Operationalization

**In progress**

Implemented:

- shell-only administrative CLI
- read/detail administrative inspection
- destructive ingestion/source/purge lifecycle tooling
- explicit destructive confirmation
- commit/rollback ownership
- real PostgreSQL destructive-operation verification
- deterministic parsed-content SHA-256 identity
- migration-backed content-hash backfill/constraint
- latest-successful-content identity semantics
- parser name/version propagation
- expected-failure parser provenance persistence
- real PostgreSQL parser-provenance verification
- persistence operation/error counters
- persistence transaction-duration histogram
- architecture documentation
- operations documentation
- Pyright 1.1.414 verification
- current baseline: **412 passed / 96.53% coverage**

Remaining:

- final Stage 3.5 repository/diff review
- final verification checkpoint
- commit/push before Stage 4

### Stage 4 — Indexing and Retrieval

**Planned — not implemented**

Planned work:

- deterministic document chunking
- chunk persistence model
- embeddings integration
- pgvector storage
- vector similarity search
- retrieval API
- retrieval filters/result contracts
- relevance evaluation
- retrieval latency evaluation
- load testing after retrieval MVP

Stage 4 should extend the existing ingestion/persistence model rather than replace it.

---

## Deferred Operational Work

Deferred until deployment scale or additional service boundaries justify them:

- dashboards and alerting
- centralized log aggregation
- OpenTelemetry
- distributed tracing
- log sampling
- production deployment manifests
- managed-secret integration
- backup/restore automation
- migration deployment automation
- horizontal worker/queue architecture
