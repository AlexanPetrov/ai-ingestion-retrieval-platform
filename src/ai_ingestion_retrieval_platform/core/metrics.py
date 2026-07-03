from prometheus_client import Counter, Gauge, Histogram

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

INGESTION_URL_TIMEOUT_TOTAL = Counter(
    "ingestion_url_timeout_total",
    "Total URL preview timeout failures by timeout type.",
    ["reason"],
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

INGESTION_OUTBOUND_LIMITER_WAIT_SECONDS = Histogram(
    "ingestion_outbound_limiter_wait_seconds",
    "Wait time in seconds to acquire global outbound limiter.",
)

INGESTION_BATCH_LIMITER_WAIT_SECONDS = Histogram(
    "ingestion_batch_limiter_wait_seconds",
    "Wait time in seconds to acquire per-batch limiter.",
)

INGESTION_HOST_LIMITER_WAIT_SECONDS = Histogram(
    "ingestion_host_limiter_wait_seconds",
    "Wait time in seconds to acquire per-host limiter.",
)

INGESTION_OUTBOUND_IN_FLIGHT = Gauge(
    "ingestion_outbound_in_flight",
    "Current number of active outbound fetch operations.",
)

INGESTION_BATCH_IN_FLIGHT = Gauge(
    "ingestion_batch_in_flight",
    "Current number of active URL preview operations inside a batch.",
)

INBOUND_RATE_LIMIT_TOTAL = Counter(
    "inbound_rate_limit_total",
    "Total inbound API rate-limit decisions.",
    ["policy", "result"],
)

INBOUND_RATE_LIMIT_STORAGE_ERROR_TOTAL = Counter(
    "inbound_rate_limit_storage_error_total",
    "Total inbound API rate-limit storage failures.",
    ["policy"],
)
