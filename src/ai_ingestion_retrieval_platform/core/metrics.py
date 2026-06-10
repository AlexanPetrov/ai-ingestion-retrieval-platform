from prometheus_client import Counter, Histogram

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests.",
    ["method", "path", "status_code"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "path"],
)

INGESTION_URL_PREVIEW_TOTAL = Counter(
    "ingestion_url_preview_total",
    "Total URL ingestion preview attempts.",
    ["result"],
)

INGESTION_URL_RETRY_TOTAL = Counter(
    "ingestion_url_retry_total",
    "Total URL fetch retries scheduled.",
    ["error_type"],
)

INGESTION_BATCH_PREVIEW_TOTAL = Counter(
    "ingestion_batch_preview_total",
    "Total batch ingestion preview attempts.",
    ["result"],
)

INGESTION_BATCH_DURATION_SECONDS = Histogram(
    "ingestion_batch_duration_seconds",
    "Batch ingestion preview latency in seconds.",
)
