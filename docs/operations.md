# Operations

## Purpose

This document describes how to configure, run, verify, inspect, and safely operate the AI Ingestion & Retrieval Platform through Stage 3.5.

It covers:

- local runtime setup
- PostgreSQL and Alembic
- Redis
- authentication
- metrics
- health/readiness
- administrative CLI
- destructive operations
- dedicated test-database safety
- troubleshooting
- release verification

Stage 4 retrieval infrastructure is not included yet.

---

## Runtime Requirements

Current external/runtime dependencies:

- Python 3.14
- PostgreSQL
- Redis when inbound rate limiting is enabled

Primary development/runtime tooling:

- `uv`
- FastAPI / Uvicorn
- SQLAlchemy asyncio
- asyncpg
- Alembic
- httpx
- Tenacity
- prometheus-client
- Ruff
- Pyright
- pytest

---

## Install

Clone the repository:

```bash
git clone <repository-url>
cd ai-ingestion-retrieval-platform
```

Install Python/dependencies:

```bash
uv python install 3.14
uv sync
```

Create local configuration:

```bash
cp .env.example .env
```

Do not commit:

- real tokens
- database passwords
- `.env`
- `.envrc`
- local secret files

---

## PostgreSQL Setup

The configured PostgreSQL database must already exist.

Example:

```dotenv
DATABASE_ENABLED=true
DATABASE_URL=postgresql+asyncpg://app_user:change-me@127.0.0.1:5432/ai_ingestion_retrieval_platform
```

Create the database with local PostgreSQL tooling:

```bash
createdb ai_ingestion_retrieval_platform
```

If credentials contain URL-reserved characters, percent-encode them in `DATABASE_URL`.

### Important persistence settings

```dotenv
DATABASE_ENABLED=true
DATABASE_URL=postgresql+asyncpg://...
DATABASE_POOL_SIZE=10
DATABASE_POOL_TIMEOUT_SECONDS=5
DATABASE_CONNECT_TIMEOUT_SECONDS=10
DATABASE_READINESS_TIMEOUT_SECONDS=2
DATABASE_ECHO_SQL=false
```

When enabled, the URL must use:

```text
postgresql+asyncpg://
```

`DATABASE_ECHO_SQL=true` is useful for local debugging but should be used carefully because SQL logging can be noisy and expose application details.

---

## Alembic

Alembic owns schema creation/upgrades.

Apply all migrations:

```bash
uv run alembic upgrade head
```

Inspect current revision:

```bash
uv run alembic current
```

Check model/schema alignment:

```bash
uv run alembic check
```

Expected clean output:

```text
No new upgrade operations detected.
```

Application startup does not create tables automatically.

Current persistence migrations:

```text
4eb7669e862c_create_ingestion_persistence_schema.py
e13f6c2d9a71_add_parsed_document_content_sha256.py
```

---

## Redis

Redis is required when rate limiting is enabled.

Homebrew example:

```bash
brew services start redis
redis-cli ping
```

Expected:

```text
PONG
```

Inspect local state:

```bash
redis-cli DBSIZE
redis-cli --scan
```

Clear the selected local Redis database when appropriate:

```bash
redis-cli FLUSHDB
```

Stop Redis:

```bash
brew services stop redis
```

Do not run destructive Redis commands against environments containing data you intend to preserve.

---

## Run the API

```bash
uv run uvicorn \
  ai_ingestion_retrieval_platform.main:create_app \
  --factory \
  --reload
```

Swagger UI:

```text
http://127.0.0.1:8000/docs
```

---

## Ingestion Authentication

Bearer authentication is optional.

When enabled:

```dotenv
INGESTION_AUTH_ENABLED=true
INGESTION_AUTH_TOKEN=<strong-secret>
```

Requests must include:

```http
Authorization: Bearer <token>
```

The ingestion token and metrics token are separate credentials.

Rotate credentials if exposed in:

- logs
- screenshots
- shell output
- chat transcripts
- source control

---

## Metrics Endpoint

Metrics are disabled by default.

Enable them:

```dotenv
METRICS_ENABLED=true
METRICS_TOKEN=<strong-secret>
```

Query:

```bash
curl \
  -H "Authorization: Bearer <strong-secret>" \
  http://127.0.0.1:8000/metrics
```

### Metric families

HTTP:

```text
http_requests_total
http_request_duration_seconds
```

Ingestion/fetching:

```text
ingestion_url_preview_total
ingestion_url_retry_total
ingestion_url_timeout_total
ingestion_batch_preview_total
ingestion_batch_duration_seconds
ingestion_outbound_limiter_wait_seconds
ingestion_batch_limiter_wait_seconds
ingestion_host_limiter_wait_seconds
ingestion_outbound_in_flight
ingestion_batch_in_flight
```

Rate limiting:

```text
inbound_rate_limit_total
inbound_rate_limit_storage_error_total
```

Parsing:

```text
parser_requests_total
parser_duration_seconds
parser_input_bytes
parser_extracted_chars
```

Persistence:

```text
persistence_operations_total{operation,result}
persistence_errors_total{operation,error_type}
persistence_transaction_duration_seconds{operation}
```

Bounded persistence operation labels:

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

Persistence error types:

```text
sqlalchemy
unexpected
```

Do not add URLs, IDs, IPs, request IDs, exception messages, or other unbounded values as Prometheus labels.

---

## Health Checks

### Liveness

```bash
curl http://127.0.0.1:8000/health/live
```

Checks whether the process is alive.

It does not require PostgreSQL or Redis to be healthy.

### Readiness

```bash
curl http://127.0.0.1:8000/health/ready
```

Checks required runtime dependencies.

When persistence is enabled, readiness performs a bounded lightweight PostgreSQL query.

Expected dependency-outage behavior:

```text
process alive + PostgreSQL unavailable

/health/live  -> 200
/health/ready -> 503
```

A load balancer/orchestrator should stop routing traffic to an unready instance without treating the process as dead.

---

## Administrative CLI

Run:

```bash
uv run ai-irp-admin
```

Current command surface:

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

Administrative database operations require persistence to be enabled.

### Database statistics

```bash
uv run ai-irp-admin database stats
```

Use this before/after destructive maintenance to verify expected row-count changes.

### List/detail inspection

```bash
uv run ai-irp-admin sources list
uv run ai-irp-admin ingestions list
uv run ai-irp-admin documents list
```

```bash
uv run ai-irp-admin sources show <source-uuid>
uv run ai-irp-admin ingestions show <ingestion-uuid>
uv run ai-irp-admin documents show <document-uuid>
```

The default list limit is 50.

Valid limits are 1 through 500.

Parsed-document detail output may include the full persisted bounded text. Treat it as potentially sensitive application data.

---

## Delete an Ingestion Record

```bash
uv run ai-irp-admin ingestions delete <ingestion-uuid> --confirm
```

Behavior:

- deletes exactly the target ingestion
- deletes its parsed document through DB-level cascade when present
- preserves the source
- commits once on success
- rolls back on failure

Without `--confirm`, the operation is refused.

---

## Delete a Source

```bash
uv run ai-irp-admin sources delete <source-uuid> --confirm
```

Source deletion is restrictive.

If ingestion history still references the source, PostgreSQL rejects the delete and the administrative service rolls back.

Do not remove ingestion history merely to satisfy a source delete unless deleting that history is itself intentional.

---

## Purge Application Persistence Data

```bash
uv run ai-irp-admin database purge --confirm
```

This removes application persistence rows while preserving:

- the database
- schema
- Alembic migration state

The purge workflow:

1. acquires application-table locks
2. captures deterministic row counts
3. deletes ingestion records
4. relies on ingestion-to-document cascade
5. deletes sources
6. commits once
7. reports deleted counts

It deliberately avoids:

```text
TRUNCATE ... CASCADE
```

Future Stage 4 persistence dependencies should be added explicitly to lifecycle tooling.

---

## Content Identity Operations

Every successful parsed document stores:

```text
content_sha256 =
SHA-256(exact persisted parsed text encoded as UTF-8)
```

No normalization occurs.

Operational implications:

- equal hashes mean exact persisted UTF-8 text equality
- different hashes mean persisted parsed text differs
- equal hashes are allowed across sources/ingestions
- the hash is not a global deduplication key

The content-hash migration backfills existing rows using the same rule.

If hashes differ unexpectedly, compare:

- exact persisted text
- whitespace
- line endings
- Unicode representation
- parser provenance/version

---

## Parser Provenance Operations

Current identities:

```text
text/plain
  python-utf8-replace

text/html
  beautifulsoup4-html.parser

application/pdf
  pypdf
```

Version strings include application adapter versioning and relevant runtime/package versions.

Known parser failures preserve provenance when parser selection occurred before the failure.

Failures before parser selection do not invent provenance.

---

## Dedicated PostgreSQL Test Database

Real database tests are destructive to application rows in the configured test database.

They run only when `TEST_DATABASE_URL` is explicitly configured.

Example:

```bash
export TEST_DATABASE_URL='postgresql+asyncpg://test_user:change-me@127.0.0.1:5432/ai_ingestion_retrieval_platform_test'
```

The target database must already exist:

```bash
createdb ai_ingestion_retrieval_platform_test
```

The harness validates that the database name contains `test` as a distinct component before allowing destructive cleanup.

Never point `TEST_DATABASE_URL` at:

- a development DB containing data you care about
- staging
- production
- shared non-disposable databases

The integration fixture cleans application persistence rows around tests but preserves:

- the database
- schema
- Alembic migration state

---

## Focused Verification

Use the narrowest relevant tests first.

Examples:

```bash
uv run pytest --no-cov tests/unit/services/test_persistence_service.py
```

```bash
uv run pytest --no-cov tests/integration/persistence/test_postgres_persistence.py
```

Focused tests normally use `--no-cov` because project-wide coverage reporting is not meaningful for a narrow slice.

---

## Full Verification Gate

With `TEST_DATABASE_URL` configured:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
uv run alembic check
```

Current verified baseline:

```text
79 files already formatted
Ruff: clean
Pyright 1.1.414: 0 errors, 0 warnings, 0 informations
412 tests passed
96.53% total coverage
Alembic: No new upgrade operations detected.
```

Coverage requirement:

```text
>= 90%
```

Coverage is a gate, not a substitute for behavioral integration tests.

---

## Schema Change Workflow

When persistence models intentionally change:

1. update the SQLAlchemy model
2. generate a migration

```bash
uv run alembic revision --autogenerate -m "describe change"
```

3. review the migration manually
4. apply it to a disposable/development database

```bash
uv run alembic upgrade head
```

5. test real PostgreSQL behavior
6. run:

```bash
uv run alembic check
```

Do not treat autogenerated migration output as automatically correct.

---

## Troubleshooting PostgreSQL Readiness

If:

```text
/health/live  = 200
/health/ready = 503
```

and persistence is enabled:

1. confirm PostgreSQL is running
2. confirm `DATABASE_URL`
3. confirm credentials
4. confirm the DB exists
5. confirm network access
6. confirm migrations are applied
7. inspect logs
8. run:

```bash
uv run alembic current
uv run alembic check
```

Do not fix readiness by adding automatic schema creation to application startup.

---

## Troubleshooting Persistence 503

Persisted endpoints may return:

```text
503 Persistence unavailable
```

Possible causes:

- DB unavailable
- pool exhaustion/timeout
- transaction failure
- constraint failure surfaced through persistence
- required failure-audit persistence failure

Check:

- PostgreSQL availability
- `/health/ready`
- structured logs
- persistence metrics
- DB constraints
- recent migrations

Useful metrics:

```text
persistence_operations_total
persistence_errors_total
persistence_transaction_duration_seconds
```

A rise in:

```text
persistence_errors_total{error_type="sqlalchemy"}
```

indicates DB-layer transaction failures and should be correlated with application/database logs.

---

## Troubleshooting Parser Failures

For parsed-ingestion failures:

1. inspect the API error
2. inspect the persisted ingestion record
3. check `parser_name`
4. check `parser_version`
5. check parse timing/error metadata
6. verify declared content type
7. verify sniffed bytes match the declared type
8. verify byte/page/text limits

Known parser failures should retain provenance when a parser had been selected.

---

## Secrets and Logs

Be careful when pasting:

- settings representations
- exception traces
- environment dumps
- database URLs
- shell history

These may expose credentials even when source files are clean.

Rotate credentials immediately if exposed outside their intended secret store.

---

## Backup / Restore

Automated backup/restore is not implemented in Stage 3.5.

Before production deployment, define:

- PostgreSQL backup schedule
- retention policy
- restore procedure
- restore verification
- migration/restore compatibility procedure

Administrative purge tooling is not a backup/restore mechanism.

---

## Deferred Operational Work

Intentionally deferred until deployment scale justifies it:

- dashboards/alerting
- centralized log aggregation
- OpenTelemetry
- distributed tracing
- production deployment manifests
- managed-secret integration
- automated backup/restore
- migration deployment automation
- horizontal worker/queue architecture

---

## Pre-Stage-4 Checklist

Before Stage 4:

- full verification gate is green
- Alembic drift check is clean
- real PostgreSQL integration tests pass
- persistence observability is present
- architecture documentation is current
- operations documentation is current
- README links to both durable docs
- repository diff is understood
- Stage 3.5 checkpoint is committed/pushed
- exposed credentials have been rotated
