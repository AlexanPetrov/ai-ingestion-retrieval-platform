# Architecture

## Purpose

This document describes the production architecture of the AI Ingestion & Retrieval Platform through Stage 3.5.

It is the authoritative design-level companion to the project README.

Current responsibilities include:

- secure URL ingestion
- bounded text/HTML/PDF parsing
- preview-only ingestion
- PostgreSQL-backed durable ingestion
- immutable ingestion history
- parsed-content identity
- parser provenance
- administrative lifecycle tooling
- health/readiness behavior
- Prometheus observability

Stage 4 retrieval/indexing capabilities are intentionally not implemented yet.

---

## System Overview

```text
Client
  |
  v
FastAPI
  |
  +--> request correlation / structured logging
  +--> optional Bearer authentication
  +--> Redis-backed rate limiting
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
  |      +--> retry/backoff
  |
  +--> parser boundary
  |      |
  |      +--> parsed Content-Type admission
  |      +--> byte-level sniffing
  |      +--> parser selection
  |      +--> parser provenance
  |      +--> parser timeout
  |      +--> byte/page/text limits
  |
  +--> persistence service
         |
         +--> service-owned transaction
         +--> ingestion repository
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

The administrative CLI is intentionally not exposed as an HTTP administration API.

---

## Architectural Boundaries

### API boundary

`src/ai_ingestion_retrieval_platform/api/` owns transport-level concerns:

- route definitions
- request/response contracts
- authentication dependencies
- rate-limit dependencies
- settings dependencies
- HTTP-client dependency wiring
- database-session dependency wiring
- operational endpoints

Business rules are kept in service layers rather than route handlers where practical.

### Secure fetch boundary

`services/fetching.py` is the outbound I/O security boundary.

It owns:

- URL scheme validation
- embedded-credential rejection
- outbound port restrictions
- DNS resolution
- resolved-IP classification
- blocking of private/loopback/link-local/multicast/disallowed addresses
- pinned-IP outbound connections
- original `Host` preservation
- TLS SNI preservation
- redirect revalidation
- response-size admission
- retry/backoff behavior
- global/per-host concurrency controls

Outbound network work completes before persistence transactions begin.

### Parser boundary

`services/parsing.py` owns parser selection and bounded parser execution.

Supported content types:

```text
text/plain
text/html
application/pdf
```

Parser execution is bounded by:

- maximum input bytes
- maximum extracted characters
- PDF page limit
- parser timeout

Parser selection also establishes provenance when a supported parser is known.

### Persistence boundary

`services/persistence.py` owns durable-ingestion workflows and database transaction boundaries.

Repository methods:

- perform database reads/writes
- flush changes
- do not independently commit ingestion workflows

The service layer owns the transaction scope so that:

- fetch/parser work stays outside DB transactions
- commit/rollback behavior is explicit
- persistence failures are separated from ingestion failures
- transaction metrics measure only persistence work

### Administrative boundary

`services/admin.py` owns administrative validation and write transaction behavior.

`persistence/admin_repository.py` owns administrative database access.

`admin_cli.py` owns the shell interface.

Administrative operations intentionally remain separate from HTTP ingestion routes.

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

Represents stable URL identity.

Properties include:

- UUID primary key
- unique URL
- `created_at`
- `last_seen_at`

Repeated ingestion of one URL reuses one source identity while preserving multiple ingestion records.

### `IngestionRecord`

Represents one durable ingestion attempt.

It records:

- source reference
- ingestion mode (`raw` or `parsed`)
- request ID
- client IP
- batch ID/position
- HTTP status/reason
- response content metadata
- fetch elapsed time
- fetch failure metadata
- retry-attempt field
- fetched timestamp
- parser name/version when known
- parse elapsed time
- parse failure metadata
- ingestion timestamp

Expected fetch/parse failures may still produce durable ingestion records when their audit transaction succeeds.

### `ParsedDocument`

Represents successful parser output for exactly one ingestion.

It stores:

- ingestion-record reference
- content type
- character length
- full bounded parsed text
- `content_sha256`
- creation timestamp

At most one parsed document may exist per ingestion record.

---

## Content Identity

Content identity is defined as:

```text
content_sha256 =
SHA-256(exact persisted ParsedDocument.text_content encoded as UTF-8)
```

No normalization is performed before hashing.

Therefore the following may intentionally change the hash:

- whitespace
- line endings
- case
- Unicode representation
- any other textual change that affects UTF-8 bytes

The hash is **not** a uniqueness constraint.

Two sources or ingestion attempts may legitimately persist the same hash.

### Latest successful baseline

The persistence repository can retrieve the most recent successful parsed-content identity for a source.

Raw attempts and failed parsed attempts do not replace that successful baseline.

The content-identity helper can classify current content relative to that baseline as:

```text
new
unchanged
changed
```

This classification does not delete, merge, or deduplicate ingestion history.

It exists to support future downstream decisions such as avoiding unnecessary Stage 4 reprocessing.

---

## Parser Provenance

Successful parsed output carries explicit parser identity and version metadata.

Current contracts:

```text
text/plain
  parser_name    = python-utf8-replace
  parser_version = adapter=1;python=<runtime version>

text/html
  parser_name    = beautifulsoup4-html.parser
  parser_version = adapter=1;beautifulsoup4=<installed version>;python=<runtime version>

application/pdf
  parser_name    = pypdf
  parser_version = adapter=1;pypdf=<installed version>
```

`adapter=1` versions the application's extraction behavior independently from third-party package versions.

Provenance is persisted for:

- successful parsed ingestion
- expected parser failure after parser selection
- parser timeout after parser selection

When no parser can truthfully be selected, provenance remains unset.

The system does not fabricate parser identity.

---

## Database Invariants

PostgreSQL constraints enforce persistence semantics including:

- unique source URLs
- allowed ingestion modes
- valid batch ID / batch-position pairing
- unique `(batch_id, batch_position)` combinations
- non-negative bounded metadata where applicable
- at most one parsed document per ingestion
- non-null lowercase 64-character SHA-256 identity on parsed documents
- restrictive source deletion while ingestion history exists
- parsed-document cascade when its ingestion record is deleted

Administrative operations preserve these database-level invariants rather than bypassing them.

---

## Transaction Semantics

### Raw success

```text
secure fetch
    |
    v
BEGIN TRANSACTION
    |
    +--> get/create Source
    +--> create IngestionRecord
    |
COMMIT
```

### Parsed success

```text
secure fetch
    |
    v
bounded parse
    |
    v
calculate content_sha256
    |
    v
BEGIN TRANSACTION
    |
    +--> get/create Source
    +--> create IngestionRecord
    +--> create ParsedDocument
    |
COMMIT
```

### Expected fetch failure

```text
secure fetch
    |
    +--> expected ingestion error
            |
            v
        BEGIN TRANSACTION
            |
            +--> get/create Source
            +--> create failed IngestionRecord
            |
        COMMIT
            |
            v
        original ingestion error returned
```

### Expected parse failure

```text
secure fetch
    |
    v
bounded parse
    |
    +--> expected parser error
            |
            v
        BEGIN TRANSACTION
            |
            +--> get/create Source
            +--> create failed IngestionRecord
            |
        COMMIT
            |
            v
        original parser error returned
```

If required audit persistence fails, the persistence failure takes precedence.

---

## Batch Semantics

Each URL in a persisted batch has its own processing lifecycle and database transaction.

This provides partial batch success:

- one failed URL does not roll back successful URLs
- each URL has independent persistence state
- `batch_id` identifies the batch
- `batch_position` preserves original ordering

---

## Failure Semantics

```text
fetch success + parse success
    -> Source + IngestionRecord + ParsedDocument

fetch success + expected parse failure
    -> Source + failed IngestionRecord
    -> selected parser provenance persisted when known
    -> no ParsedDocument
    -> original parser HTTP error returned

expected fetch failure
    -> Source + failed IngestionRecord
    -> original fetch HTTP error returned

database failure while persistence is required
    -> HTTP 503 "Persistence unavailable"

unexpected fetch failure
    -> HTTP 502 "URL fetch failed"

unexpected parser failure
    -> HTTP 502 "Document parsing failed"
```

The application does not claim an audit record exists unless it committed successfully.

---

## Intentional Metadata Gaps

Persistence deliberately avoids inventing unavailable metadata.

Current intentional gaps include:

- final canonical URL independent of pinned-IP transport behavior
- authoritative retry-attempt count

Parser identity/version is no longer a general metadata gap.

When parser selection is authoritative, provenance is persisted.

---

## Persistence Observability

Persistence transaction instrumentation is separate from fetch/parser instrumentation.

Metric families:

```text
persistence_operations_total{operation,result}
persistence_errors_total{operation,error_type}
persistence_transaction_duration_seconds{operation}
```

Bounded operation labels:

```text
fetch_failure_audit
raw_ingestion
parse_failure_audit
parsed_ingestion
```

Result labels:

```text
success
failure
```

Error-type labels:

```text
sqlalchemy
unexpected
```

### Timing boundary

The persistence timer begins immediately before the service enters its database transaction and stops after the transaction exits.

Therefore it includes:

- database statements
- flushes
- commit
- rollback

It excludes:

- DNS
- outbound HTTP
- retries
- response streaming
- parser execution

### Cardinality policy

Persistence metrics must not use high-cardinality labels such as:

- URL
- source ID
- ingestion ID
- parsed-document ID
- request ID
- batch ID
- client IP
- exception message

---

## Application Lifecycle

FastAPI lifespan owns long-lived application resources.

Current lifecycle responsibilities include:

- shared `httpx.AsyncClient`
- rate-limit storage lifecycle
- optional database engine/session factory lifecycle

When persistence is enabled, startup configures the async SQLAlchemy engine/session factory.

Startup does **not** create tables.

---

## Alembic and Schema Ownership

Alembic is the authoritative schema-management mechanism.

Runtime startup does not call:

```python
Base.metadata.create_all()
```

This keeps schema changes:

- explicit
- reviewable
- deployable independently
- verifiable through drift checks

Current persistence revisions include:

```text
4eb7669e862c_create_ingestion_persistence_schema.py
e13f6c2d9a71_add_parsed_document_content_sha256.py
```

The content-hash migration performs an exact UTF-8 Python backfill before enforcing the non-null SHA-256 constraint.

---

## Health Model

### Liveness

`GET /health/live`

Checks that the process is alive.

Dependency outages do not make liveness fail.

### Readiness

`GET /health/ready`

Checks required runtime dependencies:

- shared HTTP client
- Redis when rate limiting is enabled
- PostgreSQL when persistence is enabled

The database readiness probe uses a bounded lightweight query.

Expected behavior:

```text
process alive + PostgreSQL unavailable
    -> liveness  200
    -> readiness 503
```

---

## Security Boundaries

Major boundaries include:

- URL validation before outbound I/O
- DNS/IP validation
- pinned-IP transport
- redirect revalidation
- response-size admission
- parser input/output limits
- parser timeout
- optional Bearer authentication
- protected metrics endpoint
- Redis-backed inbound rate limiting
- explicit destructive CLI confirmation
- dedicated test-database safety checks

Secrets are configuration, not source code.

---

## Administrative Lifecycle

```text
ai-irp-admin
├── sources
│   ├── list
│   ├── show
│   └── delete --confirm
├── ingestions
│   ├── list
│   ├── show
│   └── delete --confirm
├── documents
│   ├── list
│   └── show
└── database
    ├── stats
    └── purge --confirm
```

No independent parsed-document delete command exists.

Parsed-document deletion belongs to ingestion deletion.

Source deletion remains restrictive while ingestion history references the source.

The purge flow explicitly deletes application persistence data rather than using broad `TRUNCATE ... CASCADE` behavior.

---

## Verification Architecture

### Static verification

- Ruff formatting
- Ruff linting
- Pyright

### Behavioral verification

- unit tests
- API integration tests
- application lifespan tests
- administrative repository/service/CLI tests
- performance baselines

### Real PostgreSQL verification

The PostgreSQL integration layer verifies behavior that mocks cannot establish reliably:

- source upsert identity
- repeated ingestion history
- constraints
- batch ordering
- transaction rollback
- cascade/restrict behavior
- content-hash migration/backfill
- latest successful parsed-content identity
- successful parser provenance persistence
- expected parser-failure provenance persistence

### Schema drift verification

`alembic check` is part of the full project gate.

Current verified baseline:

```text
412 tests passed
96.53% total coverage
Ruff clean
Pyright 1.1.414 clean
Alembic drift check clean
```

---

## Stage 4 Extension Boundary

Stage 4 should extend, not replace, the current ingestion model.

Expected direction:

```text
ParsedDocument
    |
    +--> Chunk
            |
            +--> Embedding / vector representation
```

Likely Stage 4 responsibilities:

- deterministic chunking
- chunk persistence
- content/version linkage
- embedding generation
- pgvector storage
- similarity search
- retrieval filters
- retrieval API contracts
- retrieval relevance evaluation
- retrieval latency evaluation

`Source`, `IngestionRecord`, and `ParsedDocument` should remain authoritative ingestion/audit entities.

`content_sha256` and parser provenance provide the basis for deciding when downstream retrieval artifacts need regeneration.
