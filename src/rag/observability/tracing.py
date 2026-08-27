"""OpenTelemetry tracing setup for the RAG pipeline."""

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

_initialized = False


def setup_tracing(service_name: str = "rag-api") -> None:
    global _initialized
    if _initialized:
        return

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    # provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    _initialized = True


def get_tracer(name: str):
    return trace.get_tracer(name)
