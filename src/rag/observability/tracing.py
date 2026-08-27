"""OpenTelemetry tracing setup for the RAG pipeline."""

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

_initialized = False


def setup_tracing(service_name: str = "rag-api") -> None:
    global _initialized
    if _initialized:
        return

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    trace.set_tracer_provider(provider)
    _initialized = True


def get_tracer(name: str):
    return trace.get_tracer(name)
