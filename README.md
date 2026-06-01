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
- Bounded concurrency
- Shared async HTTP client lifecycle
- Connection pooling
- Retry/backoff handling
- Timeout protection
- Partial batch failure handling
- Structured JSON logging
- Request correlation IDs
- Prometheus metrics
- Typed ingestion errors
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

git clone https://github.com/<YOUR_USERNAME>/ai-ingestion-retrieval-platform.git
cd ai-ingestion-retrieval-platform
uv sync
PYTHONPATH=src uv run uvicorn ai_ingestion_retrieval_platform.main:app --reload

## API Docs

http://127.0.0.1:8000/docs 

## Metrics

http://127.0.0.1:8000/metrics 

## Project Structure

src/ 
└── ai_ingestion_retrieval_platform     
    ├── api     
    │   └── routes     
    ├── core     
    ├── middleware     
    ├── schemas     
    ├── services     
    └── main.py 

## Development

uv run ruff format . uv run ruff check . --fix 

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