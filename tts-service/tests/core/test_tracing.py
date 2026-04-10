import pytest


class TestTracing:
    def test_tracer_initialization(self):
        from app.core.tracing import tracer, OPENTELEMETRY_AVAILABLE

        if OPENTELEMETRY_AVAILABLE:
            assert tracer is not None
        else:
            assert tracer is None

    def test_trace_context_propagation(self):
        from app.core.tracing import (
            inject_trace_context,
            extract_trace_context,
            tracer,
            OPENTELEMETRY_AVAILABLE,
        )

        if not OPENTELEMETRY_AVAILABLE:
            pytest.skip('OpenTelemetry not available')

        # Test extraction from carrier with traceparent
        test_trace_id = '0af7651916cd43dd8448eb211c80319c'
        test_span_id = 'b7ad6b7169203331'
        carrier = {'traceparent': f'00-{test_trace_id}-{test_span_id}-01'}

        context = extract_trace_context(carrier)
        assert context is not None

        # Test inject with active span - creates new traceparent
        carrier = {}
        with tracer.start_as_current_span('test-span') as span:
            inject_trace_context(carrier)
            assert 'traceparent' in carrier
            # Verify it has proper format
            assert carrier['traceparent'].startswith('00-')
