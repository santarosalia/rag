from prometheus_client import Counter, Gauge, Histogram

RETRIEVAL_LATENCY = Histogram(
    "rag_retrieval_latency_seconds",
    "Retrieval pipeline latency",
    ["stage"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

LLM_LATENCY = Histogram(
    "rag_llm_latency_seconds",
    "LLM generation latency",
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
)

INGEST_COUNTER = Counter(
    "rag_ingest_total",
    "Total document ingestions",
    ["status"],
)

QUERY_COUNTER = Counter(
    "rag_query_total",
    "Total queries",
    ["endpoint", "status"],
)

SEARCH_ERRORS = Counter(
    "rag_search_errors_total",
    "Search/index errors",
    ["operation"],
)

INGEST_QUEUE_DEPTH = Gauge(
    "rag_ingest_queue_depth",
    "Current ingest queue depth",
)
