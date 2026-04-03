from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.trace import Status, StatusCode
from opentelemetry import propagate
from typing import Optional, Dict
import os


SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "ghost-narrator-tts")


resource = Resource.create(
    {
        "service.name": SERVICE_NAME,
        "service.version": os.getenv("APP_VERSION", "dev"),
    }
)


provider = TracerProvider(resource=resource)

otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
if otlp_endpoint:
    exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))

trace.set_tracer_provider(provider)


tracer = trace.get_tracer(__name__)


def inject_trace_context(carrier: Dict):
    """Inject trace context into carrier (e.g., HTTP headers)."""
    propagate.inject(carrier)


def extract_trace_context(carrier: Dict) -> Optional[trace.SpanContext]:
    """Extract trace context from carrier."""
    context = propagate.extract(carrier)
    return trace.get_current_span(context).get_span_context()


def trace_async(span_name: str):
    """Decorator for tracing async functions."""

    def decorator(func):
        async def wrapper(*args, **kwargs):
            with tracer.start_as_current_span(span_name) as span:
                try:
                    result = await func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    return result
                except Exception as e:
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.record_exception(e)
                    raise

        return wrapper

    return decorator
