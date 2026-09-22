# AI Ingestion & Retrieval Platform

Production-grade asynchronous ingestion platform built with FastAPI, secure outbound I/O, bounded parser execution, PostgreSQL persistence, Alembic migrations, authentication, rate limiting, operational observability, and shell-based administrative tooling.

**Current status: Stage 3.5 in progress — Production Hardening / Operationalization**

Stages 1–3 are complete. The platform supports both preview-only ingestion and durable PostgreSQL-backed ingestion for single URLs and batches. Secure fetching, bounded parsing, deterministic parsed-content identity, parser provenance, transaction handling, persistence, schema migration, readiness behavior, real PostgreSQL integration testing, and shell-only administrative read/write tooling are implemented.

The administrative CLI supports database statistics, source/ingestion/document inspection, ingestion deletion, restricted source deletion, and full application-data purge with explicit destructive-operation confirmation.

**Next Stage 3.5 work: persistence-specific observability, final architecture/operations documentation, and the final hardening verification checkpoint before Stage 4.**

**Stage 4 — Indexing and Retrieval** remains planned but is **not implemented yet**.

---

## Table of Contents

- [Implemented Scope](#implemented-scope)
- [Architecture](#architecture)
- [API Surface](#api-surface)
- [Administrative CLI](#administrative-cli)
- [Persistence Model](#persistence-model)
- [Runtime Behavior](#runtime-behavior)
- [Technology Stack](#technology-stack)
- [Local Setup](#local-setup)
- [PostgreSQL and Alembic](#postgresql-and-alembic)
- [Configuration](#configuration)
- [Authentication](#authentication)
- [Rate Limiting](#rate-limiting)
- [Metrics](#metrics)
- [Health Checks](#health-checks)
- [Testing](#testing)
- [Project Structure](#project-structure)
- [Development Workflow](#development-workflow)
- [Roadmap](#roadmap)
- [Deferred Operational Work](#deferred-operational-work)

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
- Rejection of credentials embedded in URLs
- Declared `Content-Length` admission checks
- Bounded streaming response bodies
- Parsed `Content-Type` admission checks
- Byte-level content sniffing
- Text, HTML, and PDF parsing
- Per-URL timeout enforcement
- Retry/backoff with `429` / `503` `Retry-After` support
- Shared `httpx.AsyncClient` lifecycle through FastAPI lifespan
- Global, per-host, and per-batch concurrency controls
- Ordered batch results with per-URL partial failure handling

### Persistence

- PostgreSQL-backed durable ingestion
- Async SQLAlchemy engine and session lifecycle
- `asyncpg` PostgreSQL driver
- Alembic-owned schema migrations
- Repository/service separation
- Explicit transaction ownership in the persistence service
- Stable source identity by URL
- Immutable ingestion-attempt history
- Successful parsed-document storage
- Deterministic SHA-256 identity for exact persisted parsed text
- Migration-backed hash backfill for pre-existing parsed documents
- Authoritative parser name/version propagation for successful parses
- Parser provenance retention on expected parser failures after parser selection
- Request and batch correlation metadata
- Batch ordering persisted through `batch_position`
- Database-aware readiness checks
- Explicit `503` behavior when persistence is disabled or unavailable
- Transaction rollback semantics
- Database-level constraints and referential integrity

### Administrative operations

- Internal shell-only `ai-irp-admin` CLI
- Database entity counts
- Source listing
- Source detail lookup by UUID
- Ingestion-record listing
- Ingestion-record detail lookup by UUID
- Parsed-document listing
- Parsed-document detail lookup by UUID
- Full persisted parsed text available through document detail inspection
- Shared administrative list-limit validation
- UUID validation and normalization
- Explicit not-found handling
- Database-disabled handling
- Ingestion deletion with explicit `--confirm`
- Database-level parsed-document cascade when deleting an ingestion
- Source deletion with explicit `--confirm`
- Source-delete restriction while ingestion history exists
- Full application-data purge with explicit `--confirm`
- Transaction ownership and rollback for administrative writes
- Repository/service/CLI separation for administrative operations

An independent parsed-document delete command is intentionally not exposed. Parsed-document lifecycle belongs to the owning ingestion record.

### Security and operations

- Optional Bearer authentication for ingestion routes
- Redis-backed inbound API rate limiting
- Weighted rate-limit costing
- Structured JSON logging
- Request correlation IDs
- Prometheus metrics
- Liveness and readiness probes
- Cross-setting configuration validation

### Verification

- Ruff formatting and lint checks
- Pyright static type checking
- Unit tests
- API integration tests
- Application lifespan integration tests
- Real PostgreSQL integration tests
- Administrative repository/service/CLI tests
- Parsed-content identity and migration-backfill tests
- Parser-provenance unit and real PostgreSQL/API integration tests
- Coverage enforcement
- Alembic model/schema drift detection
- Performance baseline tests

---

## Architecture

The application separates inbound API concerns, secure outbound fetching, parser execution, persistence, administrative operations, and infrastructure lifecycle.

```text
Client
  |
  v
FastAPI
  |
  +--> request logging / correlation ID
  +--> authentication
  +--> rate limiting
  +--> request validation
  |
  v
Ingestion orchestration
  |
  +--> secure fetch boundary
  |      |
  |      +--> URL validation
  |      +--> DNS resolution
  |      +--> resolved-IP validation
  |      +--> pinned outbound connection
  |      +--> redirect revalidation
  |      +--> response admission
  |      +--> bounded streaming
  |
  +--> parser boundary
  |      |
  |      +--> parsed Content-Type admission
  |      +--> byte-level sniffing
  |      +--> parser selection + provenance
  |      +--> parser timeout
  |      +--> byte/page/text limits
  |
  +--> persistence service
         |
         +--> transaction boundary
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
SQLAlchemy asyncio / asyncpg
  |
  v
PostgreSQL
```

The administrative CLI is intentionally not exposed as an HTTP administration API and does not appear in Swagger.

Preview routes stop after shaping the bounded response.

Persisted routes continue through the persistence layer and commit durable ingestion state when PostgreSQL is enabled and available.

---

## API Surface

### Preview endpoints

Preview endpoints perform secure fetch/parse work without creating persistence records.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/ingestion/url/preview` | Fetch one URL and return a bounded raw preview |
| `POST` | `/ingestion/url/parse-preview` | Fetch and parse one URL and return a bounded parsed preview |
| `POST` | `/ingestion/urls/preview` | Fetch multiple URLs and return ordered raw preview results |
| `POST` | `/ingestion/urls/parse-preview` | Fetch and parse multiple URLs and return ordered parsed preview results |

### Persisted ingestion endpoints

Persisted endpoints execute the secure ingestion pipeline and record the ingestion attempt in PostgreSQL.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/ingestion/url/ingest` | Fetch one URL, return a raw preview, and persist the ingestion attempt |
| `POST` | `/ingestion/url/parse-ingest` | Fetch and parse one URL, persist the attempt and parsed document |
| `POST` | `/ingestion/urls/ingest` | Persist a batch of raw ingestion attempts |
| `POST` | `/ingestion/urls/parse-ingest` | Persist a batch of parsed ingestion attempts |

Persisted success responses include durable UUID identifiers such as:

- `source_id`
- `ingestion_record_id`
- `parsed_document_id` for successful parsed ingestion
- `batch_id` for batch ingestion

Batch responses preserve request order and support partial failure on a per-URL basis.

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

There is currently **no HTTP administration API**. Administrative operations are shell-only through `ai-irp-admin`.

---

## Administrative CLI

The project installs an internal administrative command:

```bash
ai-irp-admin
```

The command is registered through:

```toml
[project.scripts]
ai-irp-admin = "ai_ingestion_retrieval_platform.admin_cli:main"
```

The current command surface is:

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

The CLI is intentionally shell-only and is not exposed through the HTTP API or Swagger.

### Database statistics

```bash
uv run ai-irp-admin database stats
```

Example output shape:

```text
Database statistics
Sources:           10
Ingestion records: 25
Parsed documents:  18
```

### List sources

```bash
uv run ai-irp-admin sources list
uv run ai-irp-admin sources list --limit 10
```

The default list limit is `50`. Valid administrative limits are `1..500`.

### Show a source

```bash
uv run ai-irp-admin sources show <source-uuid>
```

The command displays:

- source ID
- URL
- creation timestamp
- last-seen timestamp

### Delete a source

```bash
uv run ai-irp-admin sources delete <source-uuid> --confirm
```

Source deletion is intentionally restrictive.

A source that is still referenced by one or more ingestion records cannot be deleted. PostgreSQL referential integrity remains authoritative; the administrative service rolls the failed transaction back and reports a usage-style error instead of deleting ingestion history automatically.

Example:

```text
ai-irp-admin: Source <uuid> cannot be deleted because ingestion history still references it.
```

Once all ingestion records referencing the source have been removed, the source may be deleted explicitly.

### List ingestion records

```bash
uv run ai-irp-admin ingestions list
uv run ai-irp-admin ingestions list --limit 10
```

The list view displays:

- ingestion-record ID
- source ID
- ingestion mode
- batch ID
- batch position
- ingestion timestamp

### Show an ingestion record

```bash
uv run ai-irp-admin ingestions show <ingestion-uuid>
```

The detail view exposes the persisted audit fields available for the ingestion, including:

- ingestion-record ID
- source ID
- linked parsed-document ID when present
- ingestion mode
- batch correlation
- request ID
- client IP
- HTTP status and reason
- final URL field
- response content metadata
- fetch timing and error metadata
- retry-attempt field
- fetched timestamp
- parser name/version fields
- parse timing and error metadata
- ingestion timestamp

The CLI reports actual persisted values. It does not fabricate values for metadata that upstream contracts do not yet supply authoritatively.

### Delete an ingestion record

```bash
uv run ai-irp-admin ingestions delete <ingestion-uuid> --confirm
```

Deleting an ingestion record:

- requires explicit `--confirm`
- deletes exactly the requested ingestion record
- deletes its linked `ParsedDocument`, when present, through the existing database-level `ON DELETE CASCADE`
- preserves the owning `Source`
- commits on success
- rolls back on failure

The source remains available because source identity and ingestion history have separate lifecycles.

### List parsed documents

```bash
uv run ai-irp-admin documents list
uv run ai-irp-admin documents list --limit 10
```

The list view deliberately returns metadata only:

- parsed-document ID
- owning ingestion-record ID
- content type
- character length
- creation timestamp

Full stored text is intentionally omitted from list output.

### Show a parsed document

```bash
uv run ai-irp-admin documents show <document-uuid>
```

The detail view displays:

- parsed-document ID
- owning ingestion-record ID
- content type
- character length
- creation timestamp
- full persisted bounded `text_content`

The administrative repository returns stored text unchanged. Presentation-level truncation, paging, or control-character sanitization is not currently implemented.

There is no independent parsed-document delete command. Parsed-document deletion is owned by ingestion deletion.

### Purge application data

```bash
uv run ai-irp-admin database purge --confirm
```

The purge command deletes all persisted application rows while preserving the database, schema, and Alembic migration state.

The purge implementation:

- requires explicit `--confirm`
- acquires PostgreSQL table locks for `source`, `ingestion_record`, and `parsed_document`
- counts the rows to be removed while those locks are held
- deletes ingestion records first
- relies on the existing ingestion-to-document database cascade for parsed documents
- deletes sources after ingestion history is removed
- commits the operation as one transaction
- rolls back on failure
- reports the source, ingestion-record, and parsed-document counts removed

The implementation deliberately avoids `TRUNCATE ... CASCADE`. Future persistence dependencies introduced by Stage 4 should be added to the purge lifecycle explicitly rather than being deleted implicitly.

Example output shape:

```text
Database purge complete
Sources deleted:           10
Ingestion records deleted: 25
Parsed documents deleted:  18
```

### Destructive-operation confirmation

Destructive commands require explicit confirmation:

```text
sources delete <uuid> --confirm
ingestions delete <uuid> --confirm
database purge --confirm
```

Without `--confirm`, the service rejects the operation before creating the database engine.

Example:

```text
ai-irp-admin: Database purge requires explicit confirmation. Re-run with --confirm.
```

### Administrative error behavior

Expected administrative input and domain errors return exit code `2`.

Invalid UUID input:

```text
ai-irp-admin: Invalid document ID 'not-a-uuid'; expected a UUID.
```

Valid but missing UUID:

```text
ai-irp-admin: Document 123e4567-e89b-12d3-a456-426614174002 was not found.
```

Invalid list limit:

```text
ai-irp-admin: Limit must be between 1 and 500.
```

Restricted source deletion:

```text
ai-irp-admin: Source <uuid> cannot be deleted because ingestion history still references it.
```

Missing destructive confirmation:

```text
ai-irp-admin: Ingestion deletion requires explicit confirmation. Re-run with --confirm.
```

Administrative database operations require:

```dotenv
DATABASE_ENABLED=true
```

Unexpected database/runtime failures are not currently normalized into a separate friendly CLI error class and may still surface as unexpected failures.

---

## Persistence Model

Persistence is modeled as:

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

Represents stable external URL identity.

Key properties:

- UUID primary key
- unique URL
- creation timestamp
- last-seen timestamp

Repeated ingestion of the same URL reuses the same `Source` identity while preserving separate ingestion records.

### `IngestionRecord`

Represents one durable ingestion attempt.

It stores audit and execution metadata including:

- source reference
- ingestion mode (`raw` or `parsed`)
- request ID
- client IP
- batch ID
- batch position
- HTTP status and reason
- response content type
- response content length
- fetch elapsed time
- fetch error code/message
- retry-attempt field
- fetched timestamp
- parser name/version provenance
- parse elapsed time
- parse error code/message
- ingestion timestamp

An ingestion record is created for successful persisted ingestion and for expected fetch/parse failures when the failure can be durably audited.

### `ParsedDocument`

Represents successful parser output for one ingestion.

It stores:

- ingestion-record reference
- parsed content type
- parsed character length
- full bounded parsed text
- `content_sha256` for exact persisted text identity
- creation timestamp

At most one `ParsedDocument` may exist for an `IngestionRecord`.

`content_sha256` is defined as SHA-256 of the exact persisted `text_content` encoded as UTF-8. No whitespace, Unicode, newline, case, or other normalization is applied before hashing. The hash is an identity signal, not a uniqueness constraint: the same hash may legitimately appear on multiple ingestion records or sources, and ingestion history is never deduplicated by content hash.

The persistence repository can retrieve the latest successful parsed-content identity for a source while ignoring raw and failed ingestion attempts. The content-identity helper classifies a current hash relative to that successful baseline as `new`, `unchanged`, or `changed`; the classification does not remove or collapse ingestion history.

The API returns a configured preview, while persistence stores the parser's full bounded text output up to the configured parsing limit.

### Database-enforced invariants

PostgreSQL constraints enforce important persistence semantics, including:

- unique source URLs
- allowed ingestion modes
- valid batch ID / batch position pairing
- unique `(batch_id, batch_position)` combinations
- non-negative bounded metadata where applicable
- at most one parsed document per ingestion
- non-null lowercase 64-character SHA-256 identity on parsed documents
- restricted source deletion while ingestion history exists
- parsed-document cascade when its ingestion record is deleted

Administrative delete commands preserve these schema-enforced semantics rather than bypassing them.

---

## Runtime Behavior

### Outbound Fetch Safety

Outbound fetching is treated as a security boundary.

The fetch layer:

- accepts only allowed URL schemes
- rejects embedded URL credentials
- restricts outbound fetch ports
- resolves DNS before connecting
- validates resolved target addresses
- blocks private, loopback, link-local, multicast, and otherwise disallowed addresses
- revalidates every redirect target
- connects to a validated resolved IP while preserving the original `Host` header and TLS SNI
- rejects oversized declared responses before reading the body
- caps streamed response bodies
- applies global and per-host concurrency limits

### Response Admission

Before parser execution, parsed ingestion performs response admission checks.

It:

- validates declared `Content-Length`
- restricts parsed ingestion to configured content types
- enforces a streaming byte cap
- validates body bytes against the declared parsed type

Current byte-level checks include:

- `application/pdf` must resemble PDF bytes
- `text/html` must resemble HTML
- `text/plain` must decode as text and not resemble binary content

### Parsing Boundary

Supported parsed content types:

- `text/plain`
- `text/html`
- `application/pdf`

Parser work is bounded by configurable:

- maximum input bytes
- maximum extracted text characters
- PDF page limit
- parser timeout

Successful parser output now carries required provenance:

| Content type | Parser identity | Version semantics |
|---|---|---|
| `text/plain` | `python-utf8-replace` | adapter revision plus Python runtime version |
| `text/html` | `beautifulsoup4-html.parser` | adapter revision plus Beautiful Soup and Python runtime versions |
| `application/pdf` | `pypdf` | adapter revision plus pypdf version |

The explicit adapter revision versions the project's own extraction behavior independently of dependency releases. Successful persisted parsed ingestion stores this provenance on `IngestionRecord`. Expected parser failures also retain the selected parser name/version when parser selection occurred before the failure. If no parser was selected, such as for an unsupported content type, parser provenance remains unset rather than being fabricated.

OCR, office-document parsing, image extraction, and media transcription are not currently implemented.

### Transaction Semantics

The persistence service owns commit/rollback boundaries. Repository methods flush database changes but do not commit the transaction.

For a successful single parsed ingestion:

```text
secure fetch
    |
    v
bounded parse
    |
    v
database transaction
    |
    +--> Source
    +--> IngestionRecord
    +--> ParsedDocument
    |
    v
commit
```

The fetch and parser work occur before the short persistence transaction.

For batch persisted ingestion, each URL is processed with its own database session/transaction. This allows partial success: one URL failing does not roll back successful URLs from the same batch request.

Administrative read operations use short-lived async SQLAlchemy resources and close their database engine after the operation.

Administrative write operations also use explicit service-owned transaction boundaries. Successful delete/purge operations commit once; not-found, referential-integrity, repository, and commit failures roll back before the database engine is closed.

Source deletion does not pre-delete ingestion history. PostgreSQL's restrictive foreign key is the authoritative concurrency-safe guard.

Database purge locks the application persistence tables, captures counts, deletes ingestion records so parsed documents cascade, then deletes sources in the same transaction.

### Failure Semantics

The persistence layer deliberately distinguishes ingestion failures from persistence failures.

```text
fetch success + parse success
    -> Source + IngestionRecord + ParsedDocument

fetch success + expected parse failure
    -> Source + IngestionRecord
    -> selected parser provenance persisted when known
    -> no ParsedDocument
    -> original parse HTTP error returned

expected fetch failure
    -> Source + IngestionRecord
    -> original fetch HTTP error returned

database failure while persistence is required
    -> HTTP 503 "Persistence unavailable"

unexpected fetch failure
    -> HTTP 502 "URL fetch failed"

unexpected parser failure
    -> HTTP 502 "Document parsing failed"
```

If an expected ingestion failure occurs but its required audit record cannot be persisted, the persistence failure takes precedence and the API returns `503`.

### Intentional Metadata Gaps

Persistence does not fabricate metadata that upstream contracts do not currently expose reliably.

The following fields are intentionally not populated with invented values:

- final canonical URL
- authoritative retry-attempt count

Parser name/version are no longer general metadata gaps. They are populated from the parser boundary for successful parses and for expected parse failures after a parser has been selected. They remain unset only when no parser identity is truthfully available.

Until the remaining upstream contracts are extended, the persistence layer keeps unavailable values unset/defaulted rather than presenting guessed metadata as factual audit data.

The administrative CLI follows the same rule and displays the actual persisted value, including unset/default values where appropriate.

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

### 1. Clone the repository

```bash
git clone https://github.com/apfb11/ai-ingestion-retrieval-platform.git
cd ai-ingestion-retrieval-platform
```

### 2. Install Python and dependencies

```bash
uv python install 3.14
uv sync
```

### 3. Create local configuration

```bash
cp .env.example .env
```

Edit `.env` for the local environment.

Do not commit real credentials, tokens, database passwords, or local shell environment files containing secrets.

### 4. Start Redis when rate limiting is enabled

```bash
brew services start redis
redis-cli ping
```

Expected result:

```text
PONG
```

### 5. Configure PostgreSQL when persistence is enabled

The application expects the target PostgreSQL database to already exist.

Example development configuration:

```dotenv
DATABASE_ENABLED=true
DATABASE_URL=postgresql+asyncpg://app_user:change-me@127.0.0.1:5432/ai_ingestion_retrieval_platform
```

If credentials contain URL-reserved characters, percent-encode them in the connection URL.

Create the database using the PostgreSQL tooling appropriate for your local environment, for example:

```bash
createdb ai_ingestion_retrieval_platform
```

Then apply migrations:

```bash
uv run alembic upgrade head
```

The application does **not** create tables automatically on startup.

### 6. Run the API

```bash
uv run uvicorn   ai_ingestion_retrieval_platform.main:create_app   --factory   --reload
```

Open Swagger UI:

```text
http://127.0.0.1:8000/docs
```

### 7. Use the administrative CLI

With persistence enabled and the database available:

```bash
uv run ai-irp-admin database stats
uv run ai-irp-admin sources list
uv run ai-irp-admin ingestions list
uv run ai-irp-admin documents list
```

Inspect individual records with:

```bash
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

A source cannot be deleted while ingestion history still references it. Delete the relevant ingestion records first only when that history is intentionally being removed.

`database purge --confirm` deletes all application persistence rows. Use it only against a database whose application data is intentionally disposable.

### 8. Check health

```bash
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
```

---

## PostgreSQL and Alembic

### Schema ownership

Alembic is the authoritative schema-management mechanism.

Application startup does **not** call:

```python
Base.metadata.create_all()
```

This is intentional:

- schema changes remain explicit
- deployments can review migration operations
- application startup does not silently mutate database structure
- model/schema drift can be checked independently
- migration execution can be controlled as a deployment step

### Apply migrations

```bash
uv run alembic upgrade head
```

### Inspect the current revision

```bash
uv run alembic current
```

### Verify model/schema alignment

```bash
uv run alembic check
```

A clean schema/model state reports:

```text
No new upgrade operations detected.
```

### Create a future migration

After intentionally changing SQLAlchemy persistence models:

```bash
uv run alembic revision --autogenerate -m "describe schema change"
```

Always review generated migrations before applying them.

Autogenerate is a migration authoring aid, not a substitute for migration review.

Current persistence migrations include the initial ingestion schema plus `e13f6c2d9a71_add_parsed_document_content_sha256.py`, which backfills SHA-256 identity for existing parsed documents before enforcing the non-null hash constraint.

### Deployment expectation

For an environment using persistence, migrations should be applied as an explicit release/deployment step **before** serving persisted ingestion traffic.

The application should not rely on runtime DDL.

---

## Configuration

Settings are loaded with `pydantic-settings` from defaults, `.env`, and process environment variables.

### Application and security

| Setting | Purpose |
|---|---|
| `APP_NAME` | Application name |
| `LOG_LEVEL` | Application log level |
| `INGESTION_AUTH_ENABLED` | Enables Bearer authentication for ingestion routes |
| `INGESTION_AUTH_TOKEN` | Bearer token for ingestion routes |
| `METRICS_ENABLED` | Enables the `/metrics` endpoint |
| `METRICS_TOKEN` | Bearer token for `/metrics` |

### Persistence

| Setting | Purpose |
|---|---|
| `DATABASE_ENABLED` | Enables PostgreSQL persistence and DB readiness checks |
| `DATABASE_URL` | SQLAlchemy async PostgreSQL URL; must use `postgresql+asyncpg://` |
| `DATABASE_POOL_SIZE` | Async SQLAlchemy connection-pool size |
| `DATABASE_POOL_TIMEOUT_SECONDS` | Maximum wait for a pooled DB connection |
| `DATABASE_CONNECT_TIMEOUT_SECONDS` | PostgreSQL connection timeout |
| `DATABASE_READINESS_TIMEOUT_SECONDS` | Timeout for readiness DB probe |
| `DATABASE_ECHO_SQL` | Enables SQLAlchemy SQL echoing for local diagnostics |

When `DATABASE_ENABLED=true`, startup configuration validation requires a non-empty asyncpg PostgreSQL URL.

### HTTP client and ingestion

| Setting | Purpose |
|---|---|
| `HTTP_TIMEOUT_CONNECT_SECONDS` | HTTP connection timeout |
| `HTTP_TIMEOUT_READ_SECONDS` | HTTP read timeout |
| `HTTP_TIMEOUT_WRITE_SECONDS` | HTTP write timeout |
| `HTTP_TIMEOUT_POOL_SECONDS` | HTTP connection-pool wait timeout |
| `HTTP_MAX_CONNECTIONS` | Maximum shared HTTP connections |
| `HTTP_MAX_KEEPALIVE_CONNECTIONS` | Maximum idle keep-alive connections |
| `HTTP_KEEPALIVE_EXPIRY_SECONDS` | Keep-alive expiry |
| `URL_TIMEOUT_SECONDS` | Overall per-URL ingestion timeout |
| `MAX_REDIRECTS` | Maximum followed redirects |
| `MAX_PREVIEW_BYTES` | Raw preview fetch byte cap |
| `MAX_PREVIEW_TEXT_CHARS` | Raw preview text cap |
| `MAX_BATCH_URLS` | Maximum URLs accepted per batch request |
| `ALLOWED_FETCH_PORTS` | Allowed outbound destination ports |

### Parser boundary

| Setting | Purpose |
|---|---|
| `MAX_PARSE_BYTES` | Parsed-ingestion body byte cap |
| `MAX_PARSED_TEXT_CHARS` | Maximum bounded parser output |
| `MAX_PARSE_PAGES` | Maximum PDF pages parsed |
| `PARSE_TIMEOUT_SECONDS` | Parser execution timeout |
| `ALLOWED_PARSE_CONTENT_TYPES` | Accepted parsed content types |

### Retry and concurrency

| Setting | Purpose |
|---|---|
| `RETRY_ATTEMPTS` | Configured retry policy attempts |
| `RETRY_TOTAL_TIMEOUT_SECONDS` | Total retry budget |
| `RETRY_BACKOFF_INITIAL_SECONDS` | Initial retry backoff |
| `RETRY_BACKOFF_MAX_SECONDS` | Maximum retry backoff |
| `DEFAULT_MAX_CONCURRENCY` | Default per-batch concurrency |
| `MAX_ALLOWED_CONCURRENCY` | Maximum accepted batch concurrency |
| `GLOBAL_MAX_OUTBOUND_FETCHES` | Global outbound fetch concurrency cap |
| `HOST_MAX_CONCURRENCY` | Per-host outbound concurrency cap |
| `HOST_LIMITER_CACHE_SIZE` | Per-host limiter cache size |

### Rate limiting

| Setting | Purpose |
|---|---|
| `RATE_LIMIT_ENABLED` | Enables inbound rate limiting |
| `RATE_LIMIT_REDIS_URL` | Redis storage URL |
| `RATE_LIMIT_KEY_PREFIX` | Redis key namespace |
| `RATE_LIMIT_FAIL_OPEN` | Controls behavior when rate-limit storage fails |
| `RATE_LIMIT_URL_PREVIEW_REQUESTS` | Single-URL request quota |
| `RATE_LIMIT_URL_PREVIEW_WINDOW_SECONDS` | Single-URL quota window |
| `RATE_LIMIT_BATCH_PREVIEW_REQUESTS` | Batch request quota |
| `RATE_LIMIT_BATCH_PREVIEW_WINDOW_SECONDS` | Batch quota window |
| `RATE_LIMIT_URL_PREVIEW_COST` | Raw single-URL cost |
| `RATE_LIMIT_URL_PARSE_PREVIEW_COST` | Parsed single-URL cost |
| `RATE_LIMIT_BATCH_PREVIEW_URL_COST` | Raw batch per-URL cost |
| `RATE_LIMIT_BATCH_PARSE_PREVIEW_URL_COST` | Parsed batch per-URL cost |

Cross-setting validation rejects contradictory limits and incomplete security configuration during startup.

---

## Authentication

Ingestion-route authentication is optional and disabled by default.

When enabled:

```dotenv
INGESTION_AUTH_ENABLED=true
INGESTION_AUTH_TOKEN=<strong-secret>
```

Ingestion requests must include:

```http
Authorization: Bearer <token>
```

The ingestion token and metrics token are separate credentials.

Do not store production secrets in source control.

---

## Rate Limiting

Redis-backed inbound ingestion rate limiting is work-weighted.

Default cost model:

| Work type | Default cost |
|---|---:|
| Raw single-URL ingestion | `1` |
| Parsed single-URL ingestion | `2` |
| Raw batch ingestion | `1` per URL |
| Parsed batch ingestion | `2` per URL |

Redis is required when:

```dotenv
RATE_LIMIT_ENABLED=true
```

Check local Redis:

```bash
redis-cli ping
```

Inspect local state:

```bash
redis-cli DBSIZE
redis-cli --scan
```

Clear the currently selected local Redis database:

```bash
redis-cli FLUSHDB
```

Stop Homebrew Redis:

```bash
brew services stop redis
```

---

## Metrics

Prometheus metrics are exposed at:

```text
http://127.0.0.1:8000/metrics
```

The endpoint is disabled by default.

Enable it with:

```dotenv
METRICS_ENABLED=true
METRICS_TOKEN=<strong-secret>
```

Query it with:

```bash
curl   -H "Authorization: Bearer <strong-secret>"   http://127.0.0.1:8000/metrics
```

Metrics include:

- HTTP request count
- HTTP request latency
- request error count
- ingestion retry count
- ingestion timeout count
- global outbound limiter wait time
- per-host limiter wait time
- active outbound fetch count
- batch in-flight work
- rate-limit allowed/blocked decisions
- rate-limit storage errors
- parser attempts
- parser duration
- parser input bytes
- extracted character counts

Request metric paths are normalized to avoid high-cardinality labels.

Persistence-specific operation, error, and transaction-duration metrics are not yet implemented.

---

## Health Checks

### Liveness

```text
GET /health/live
```

Liveness verifies that the application process is running.

It does not require external dependencies to be healthy.

### Readiness

```text
GET /health/ready
```

Readiness verifies required runtime dependencies.

Current checks include:

- shared `httpx.AsyncClient`
- Redis rate-limit storage when rate limiting is enabled
- PostgreSQL when persistence is enabled

The database readiness probe executes a lightweight `SELECT 1` under a configured timeout.

Expected operational behavior:

```text
application process alive + database unavailable
    -> /health/live  = 200
    -> /health/ready = 503
```

This separation allows an orchestrator or load balancer to stop routing traffic without treating a dependency outage as a dead process.

---

## Testing

The repository uses layered verification rather than relying on coverage alone.

### Unit and application-level tests

The normal suite covers:

- configuration validation
- authentication
- rate limiting
- URL safety
- response admission
- content sniffing
- fetching
- parsing
- ingestion orchestration
- request logging
- persistence engine configuration
- repositories
- administrative repository behavior
- persistence schemas
- persistence service behavior
- administrative service behavior
- administrative CLI behavior
- API routes
- health routes
- application lifespan
- performance baselines

### Administrative CLI verification

Administrative tooling is tested at each layer:

```text
CLI
  |
  v
administrative service
  |
  v
administrative repository
```

Current focused test counts:

```text
Admin repository: 21 passed
Admin service:    61 passed
Admin CLI:        46 passed
```

The focused tests verify:

- list behavior
- default and explicit limits
- empty-database behavior
- UUID normalization
- invalid UUID handling
- not-found handling
- database-disabled handling
- engine cleanup
- repository failure propagation
- source detail output
- ingestion audit detail output
- parsed-document metadata output
- full parsed-document text output
- ingestion deletion
- source deletion
- restrictive source-delete behavior
- destructive-operation confirmation
- commit/rollback behavior
- database purge counts
- empty-database purge behavior

### Real PostgreSQL integration tests

Real database semantics are tested in:

```text
tests/integration/persistence/
├── conftest.py
├── test_content_sha256_migration.py
├── test_parser_provenance.py
└── test_postgres_persistence.py
```

The PostgreSQL integration layer verifies behavior that mocks cannot establish reliably, including:

- concurrent source upsert identity
- repeated ingestion history
- batch ordering
- one parsed document per ingestion
- unique batch positions
- ingestion-mode check constraints
- batch-field consistency constraints
- source delete restriction
- parsed-document cascade behavior
- transaction rollback
- parsed-content SHA-256 migration backfill and constraint enforcement
- latest successful parsed-content identity semantics
- parser provenance on successful parsed ingestion
- parser provenance retention on expected parser failure with no document row

Administrative destructive operations have also been manually smoke-tested against PostgreSQL:

```text
ingestions delete <uuid> --confirm
    -> ingestion deleted
    -> linked parsed document cascades
    -> source preserved

sources delete <uuid> --confirm
    -> referenced source refused and rolled back
    -> unreferenced source deleted

database purge
    -> refused without --confirm and database unchanged

database purge --confirm
    -> reported counts match pre-purge counts
    -> source, ingestion_record, and parsed_document rows removed
```

Both raw-only and parsed-document purge paths were verified.

### Dedicated test database safety

PostgreSQL integration tests run only when `TEST_DATABASE_URL` is explicitly configured.

Example:

```bash
export TEST_DATABASE_URL='postgresql+asyncpg://test_user:change-me@127.0.0.1:5432/ai_ingestion_retrieval_platform_test'
```

The target database must already exist.

For example:

```bash
createdb ai_ingestion_retrieval_platform_test
```

The test harness applies:

```bash
alembic upgrade head
```

to the dedicated test database before running database integration tests.

The harness also validates that the database name clearly contains `test` as a distinct name component before allowing destructive test cleanup.

**Never point `TEST_DATABASE_URL` at a development, staging, or production database containing data you care about.**

The integration fixture truncates the application persistence tables around tests:

```text
source
ingestion_record
parsed_document
```

The database itself and its Alembic schema remain in place; test rows do not accumulate across normal successful runs.

`alembic_version` is not treated as disposable application test data.

### Running tests without PostgreSQL integration

If `TEST_DATABASE_URL` is not set, the dedicated PostgreSQL integration tests are skipped.

Run the rest of the suite normally:

```bash
uv run pytest
```

### Running the PostgreSQL integration layer explicitly

```bash
uv run pytest tests/integration/persistence/ --no-cov -v
```

### Full verification gate

For the fully verified baseline, configure the dedicated test DB first, then run:

```bash
uv run ruff format .
uv run ruff check .
uv run pyright
uv run pytest
uv run alembic check
```

Current tested baseline after content identity and parser-provenance hardening:

```text
409 passed
96.49% total test coverage
Ruff lint: clean
Pyright 1.1.414: 0 errors, 0 warnings, 0 informations
Administrative repository coverage: 100%
Administrative service coverage: 99%
Alembic check: No new upgrade operations detected.
```


The coverage requirement is currently:

```text
>= 90%
```

Coverage is treated as a gate, not as a substitute for behavioral integration tests.

---

## Project Structure

Generated `__pycache__` directories, compiled Python files, and personal/local artifacts are omitted.

```text
.
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 4eb7669e862c_create_ingestion_persistence_schema.py
│       └── e13f6c2d9a71_add_parsed_document_content_sha256.py
├── alembic.ini
├── generate_token.py
├── pyproject.toml
├── README.md
├── src/
│   └── ai_ingestion_retrieval_platform/
│       ├── __init__.py
│       ├── admin_cli.py
│       ├── main.py
│       ├── api/
│       │   ├── __init__.py
│       │   ├── dependencies/
│       │   │   ├── __init__.py
│       │   │   ├── auth.py
│       │   │   ├── database.py
│       │   │   ├── http_client.py
│       │   │   ├── rate_limit.py
│       │   │   └── settings.py
│       │   └── routes/
│       │       ├── __init__.py
│       │       ├── health.py
│       │       ├── ingestion.py
│       │       └── metrics.py
│       ├── core/
│       │   ├── __init__.py
│       │   ├── config.py
│       │   ├── content_identity.py
│       │   ├── content_sniffing.py
│       │   ├── limits.py
│       │   ├── logging.py
│       │   ├── metrics.py
│       │   ├── response_admission.py
│       │   └── url_safety.py
│       ├── middleware/
│       │   ├── __init__.py
│       │   └── request_logging.py
│       ├── persistence/
│       │   ├── __init__.py
│       │   ├── admin_repository.py
│       │   ├── engine.py
│       │   ├── models.py
│       │   └── repositories.py
│       ├── schemas/
│       │   ├── __init__.py
│       │   ├── ingestion.py
│       │   ├── parsing.py
│       │   └── persistence.py
│       └── services/
│           ├── __init__.py
│           ├── admin.py
│           ├── fetching.py
│           ├── ingestion.py
│           ├── parsing.py
│           └── persistence.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── fixtures/
│   │   ├── __init__.py
│   │   └── pdf_bytes.py
│   ├── integration/
│   │   ├── api/
│   │   │   ├── test_health_routes.py
│   │   │   ├── test_ingestion_routes.py
│   │   │   ├── test_metrics_route.py
│   │   │   └── test_persistence_ingestion_routes.py
│   │   ├── app/
│   │   │   └── test_lifespan.py
│   │   └── persistence/
│   │       ├── conftest.py
│   │       ├── test_content_sha256_migration.py
│   │       ├── test_parser_provenance.py
│   │       └── test_postgres_persistence.py
│   ├── performance/
│   │   └── test_ingestion_latency.py
│   └── unit/
│       ├── api/
│       │   └── dependencies/
│       │       ├── test_auth.py
│       │       ├── test_database.py
│       │       ├── test_http_client_dependency.py
│       │       └── test_rate_limit.py
│       ├── core/
│       │   ├── test_config.py
│       │   ├── test_content_identity.py
│       │   ├── test_content_sniffing.py
│       │   ├── test_response_admission.py
│       │   └── test_url_safety.py
│       ├── middleware/
│       │   └── test_request_logging.py
│       ├── persistence/
│       │   ├── test_admin_repository.py
│       │   ├── test_engine.py
│       │   └── test_repositories.py
│       ├── schemas/
│       │   └── test_persistence_schemas.py
│       ├── services/
│       │   ├── test_admin.py
│       │   ├── test_ingestion_batch.py
│       │   ├── test_ingestion_errors.py
│       │   ├── test_ingestion_fetch.py
│       │   ├── test_parsing.py
│       │   └── test_persistence_service.py
│       └── test_admin_cli.py
└── uv.lock
```

### Code ownership by layer

- `api/` — HTTP transport, dependencies, and route contracts
- `core/` — configuration, limits, URL safety, content identity, and observability primitives
- `middleware/` — request lifecycle logging and request ID propagation
- `persistence/` — SQLAlchemy engine, models, ingestion repository, and administrative read/write repository
- `schemas/` — request/response and persistence schema validation
- `services/fetching.py` — secure outbound fetch boundary
- `services/parsing.py` — bounded parser boundary
- `services/ingestion.py` — preview ingestion orchestration
- `services/persistence.py` — durable ingestion orchestration and transaction ownership
- `services/admin.py` — administrative validation, read orchestration, and write transaction ownership
- `admin_cli.py` — shell-only administrative read/write command surface
- `alembic/` — schema migration environment and revisions
- `tests/integration/persistence/` — real PostgreSQL behavioral verification

---

## Development Workflow

### Format

```bash
uv run ruff format .
```

### Lint

```bash
uv run ruff check .
```

### Static type checking

```bash
uv run pyright
```

### Tests

```bash
uv run pytest
```

For focused unit work where global coverage reporting is unnecessary:

```bash
uv run pytest --no-cov <test-path>
```

### Migration drift check

```bash
uv run alembic check
```

### Recommended pre-commit / pre-push verification

With a dedicated `TEST_DATABASE_URL` configured:

```bash
uv run ruff format .
uv run ruff check .
uv run pyright
uv run pytest
uv run alembic check
```

A change is not considered complete solely because unit tests pass. Persistence and administrative changes should preserve:

- schema/model alignment
- transaction semantics
- real PostgreSQL behavior
- API failure contracts
- readiness behavior
- administrative behavior
- type safety
- lint/format cleanliness

---

## Roadmap

### Stage 1 — Secure Ingestion Preview Foundation

**Complete**

Implemented:

- secure raw and parsed preview ingestion
- single and batch routes
- SSRF/DNS protections
- redirect revalidation
- bounded response streaming
- response admission
- byte-level content sniffing
- text/HTML/PDF parser boundary
- concurrency controls
- retry/backoff
- authentication
- Redis rate limiting
- metrics
- structured logging
- liveness/readiness checks

### Stage 2 — Persistence Design

**Complete**

Implemented:

- source identity model
- ingestion-history model
- parsed-document model
- audit/debug metadata placement
- explicit persistence boundaries
- transaction ownership model
- batch identity/order semantics
- deliberate handling of unavailable metadata

### Stage 3 — Persistence Implementation

**Complete**

Implemented:

- PostgreSQL
- async SQLAlchemy / asyncpg
- application DB lifecycle
- repository layer
- persistence service
- persisted single and batch routes
- Alembic migrations
- DB-aware readiness
- unit and route integration coverage
- real PostgreSQL constraint/transaction integration tests
- Alembic schema drift verification

### Stage 3.5 — Production Hardening / Operationalization

**In progress**

Implemented:

- internal `ai-irp-admin` command
- database statistics
- source list/detail inspection
- ingestion list/detail inspection
- parsed-document list/detail inspection
- full persisted parsed-text inspection
- administrative UUID validation
- administrative not-found behavior
- administrative database-disabled behavior
- ingestion deletion with explicit confirmation
- parsed-document cascade verification through ingestion deletion
- source deletion with explicit confirmation
- restrictive source deletion while ingestion history exists
- full application-data purge with explicit confirmation
- purge table locking and deterministic deletion counts
- administrative write commit/rollback ownership
- focused repository/service/CLI coverage
- real PostgreSQL smoke verification for destructive operations
- deterministic parsed-content SHA-256 identity over exact persisted UTF-8 text
- migration backfill and database constraint for `ParsedDocument.content_sha256`
- latest successful parsed-content identity lookup and `new` / `unchanged` / `changed` classification semantics
- authoritative parser identity/version propagation from parser boundary through persistence
- parser provenance retention on expected parser failures after parser selection
- real PostgreSQL/API verification of successful and failed parser provenance persistence
- Pyright 1.1.414 verification
- tested baseline of 409 passing tests and 96.49% coverage

Planned remaining work:

- persistence operation/error counters and transaction-duration metrics
- additional architecture and operations documentation
- final hardening verification before Stage 4

Administrative destructive operations preserve the existing persistence invariants and remain shell-only.

### Stage 4 — Indexing and Retrieval

**Planned — not implemented**

Planned work:

- document chunking
- chunk persistence model
- embeddings integration
- pgvector extension/storage
- vector similarity search
- retrieval API
- retrieval filters and result contracts
- relevance evaluation
- retrieval latency evaluation
- load testing after retrieval MVP

Persistence should remain authoritative source/ingestion/document storage; Stage 4 should extend it rather than collapsing ingestion history into retrieval-specific tables.

---

## Deferred Operational Work

The following are intentionally deferred until deployment scale or additional service boundaries justify them:

- dashboards and alerting
- centralized log aggregation
- OpenTelemetry instrumentation
- distributed tracing across API, PostgreSQL, Redis, workers, and future queue systems
- log sampling for high-volume traffic
- production deployment manifests
- managed-secret integration
- backup/restore automation
- database migration deployment automation
- horizontal worker/queue architecture

These are deployment and scale concerns, not substitutes for the correctness and safety boundaries already implemented in the ingestion, persistence, and administrative layers.
