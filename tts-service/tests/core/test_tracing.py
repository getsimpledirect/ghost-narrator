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
        with tracer.start_as_current_span('test-span'):
            inject_trace_context(carrier)
            assert 'traceparent' in carrier
            # Verify it has proper format
            assert carrier['traceparent'].startswith('00-')
