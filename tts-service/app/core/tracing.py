# MIT License
#
# Copyright (c) 2026 Ayush Naik
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import os
from typing import Optional, Dict

try:
    from opentelemetry import trace, propagate
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.trace import Status, StatusCode

    OPENTELEMETRY_AVAILABLE = True
except ImportError:
    OPENTELEMETRY_AVAILABLE = False
    trace = propagate = None
    TracerProvider = BatchSpanProcessor = Resource = OTLPSpanExporter = Status = StatusCode = None

TELEMETRY_AVAILABLE = OPENTELEMETRY_AVAILABLE

if OPENTELEMETRY_AVAILABLE:
    try:
        SERVICE_NAME = os.getenv('OTEL_SERVICE_NAME', 'ghost-narrator-tts')

        resource = Resource.create(
            {
                'service.name': SERVICE_NAME,
                'service.version': os.getenv('APP_VERSION', 'dev'),
            }
        )

        provider = TracerProvider(resource=resource)

        otlp_endpoint = os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT')
        if otlp_endpoint:
            exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))

        trace.set_tracer_provider(provider)

        tracer = trace.get_tracer(__name__)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning(
            f'OpenTelemetry setup failed, using no-op tracer: {exc}'
        )
        tracer = None
else:
    tracer = None


def inject_trace_context(carrier: Dict):
    """Inject trace context into carrier (e.g., HTTP headers)."""
    if OPENTELEMETRY_AVAILABLE:
        propagate.inject(carrier)


def extract_trace_context(carrier: Dict) -> Optional[trace.SpanContext]:
    """Extract trace context from carrier."""
    if not OPENTELEMETRY_AVAILABLE:
        return None
    context = propagate.extract(carrier)
    return trace.get_current_span(context).get_span_context()


def trace_async(span_name: str):
    """Decorator for tracing async functions."""
    if not OPENTELEMETRY_AVAILABLE:
        return lambda func: func

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
