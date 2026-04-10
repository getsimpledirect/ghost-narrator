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

from fastapi import APIRouter
from fastapi.responses import Response

try:
    from prometheus_client import (
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
        CONTENT_TYPE_LATEST,
    )

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    CollectorRegistry = Counter = Gauge = Histogram = generate_latest = CONTENT_TYPE_LATEST = None

router = APIRouter(tags=['Monitoring'])

registry = None
if PROMETHEUS_AVAILABLE:
    registry = CollectorRegistry()

    # Job metrics
    tts_jobs_total = Counter(
        'tts_jobs_total',
        'Total number of TTS jobs',
        ['status'],
        registry=registry,
    )

    tts_jobs_processing_time = Histogram(
        'tts_jobs_processing_time_seconds',
        'Time spent processing TTS jobs',
        buckets=[1, 5, 10, 30, 60, 120, 300],
        registry=registry,
    )

    # Synthesis metrics
    tts_synthesis_duration_seconds = Histogram(
        'tts_synthesis_duration_seconds',
        'Time spent on audio synthesis',
        buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60],
        registry=registry,
    )

    tts_chunks_total = Counter(
        'tts_chunks_total',
        'Total number of audio chunks processed',
        registry=registry,
    )

    # Storage metrics
    tts_storage_upload_duration_seconds = Histogram(
        'tts_storage_upload_duration_seconds',
        'Time spent uploading audio to storage',
        buckets=[0.5, 1, 2, 5, 10, 30],
        registry=registry,
    )

    # LLM metrics
    tts_narration_duration_seconds = Histogram(
        'tts_narration_duration_seconds',
        'Time spent on LLM narration',
        buckets=[1, 3, 5, 10, 30, 60],
        registry=registry,
    )

    # Business metrics - Job counts by status
    jobs_created_total = Counter(
        'tts_job_creations_total',
        'Total number of TTS jobs created',
        registry=registry,
    )

    jobs_completed_total = Counter(
        'tts_job_completions_total',
        'Total number of TTS jobs completed successfully',
        registry=registry,
    )

    jobs_failed_total = Counter(
        'tts_job_failures_total',
        'Total number of TTS jobs failed',
        registry=registry,
    )

    jobs_cancelled_total = Counter(
        'tts_job_cancellations_total',
        'Total number of TTS jobs cancelled',
        registry=registry,
    )

    # Performance metrics - Histograms for durations
    job_duration_seconds = Histogram(
        'tts_job_duration_seconds',
        'Time spent processing entire TTS job',
        buckets=[1, 5, 10, 30, 60, 120, 300, 600],
        registry=registry,
    )

    # Resource metrics - Gauges
    active_jobs_count = Gauge(
        'tts_active_jobs_count',
        'Number of currently active TTS jobs',
        registry=registry,
    )

    gpu_memory_usage_bytes = Gauge(
        'tts_gpu_memory_usage_bytes',
        'GPU memory usage in bytes',
        registry=registry,
    )

    gpu_utilization_percent = Gauge(
        'tts_gpu_utilization_percent',
        'GPU utilization percentage',
        registry=registry,
    )

    # Cache metrics
    cache_hits_total = Counter(
        'tts_cache_hits_total',
        'Total number of cache hits',
        registry=registry,
    )

    cache_misses_total = Counter(
        'tts_cache_misses_total',
        'Total number of cache misses',
        registry=registry,
    )


def record_job_created():
    """Record a new job creation."""
    if PROMETHEUS_AVAILABLE:
        jobs_created_total.inc()


def record_job_completed(duration: float):
    """Record a job completion."""
    if PROMETHEUS_AVAILABLE:
        jobs_completed_total.inc()
        job_duration_seconds.observe(duration)
        active_jobs_count.dec()


def record_job_failed():
    """Record a job failure."""
    if PROMETHEUS_AVAILABLE:
        jobs_failed_total.inc()
        active_jobs_count.dec()


def record_cache_hit():
    """Record a cache hit."""
    if PROMETHEUS_AVAILABLE:
        cache_hits_total.inc()


def record_cache_miss():
    """Record a cache miss."""
    if PROMETHEUS_AVAILABLE:
        cache_misses_total.inc()


@router.get(
    '/metrics',
    summary='Prometheus metrics',
    description=(
        'Exposes job, synthesis, storage, LLM, and cache metrics in Prometheus text format. '
        'Scrape this endpoint with your Prometheus collector. '
        'Returns a plain-text `# Prometheus client not installed` message if '
        '`prometheus-client` is not available.'
    ),
    responses={
        200: {'description': 'Prometheus metrics in text exposition format'},
    },
)
async def metrics():
    """Prometheus metrics endpoint."""
    if not PROMETHEUS_AVAILABLE or registry is None:
        return Response(content='# Prometheus client not installed', media_type='text/plain')
    return Response(content=generate_latest(registry=registry), media_type=CONTENT_TYPE_LATEST)
