from fastapi import APIRouter
from fastapi.responses import Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

router = APIRouter(tags=["monitoring"])

# Job metrics
tts_jobs_total = Counter(
    "tts_jobs_total",
    "Total number of TTS jobs",
    ["status"],
)

tts_jobs_processing_time = Histogram(
    "tts_jobs_processing_time_seconds",
    "Time spent processing TTS jobs",
    buckets=[1, 5, 10, 30, 60, 120, 300],
)

# Synthesis metrics
tts_synthesis_duration_seconds = Histogram(
    "tts_synthesis_duration_seconds",
    "Time spent on audio synthesis",
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60],
)

tts_chunks_total = Counter(
    "tts_chunks_total",
    "Total number of audio chunks processed",
)

# Storage metrics
tts_storage_upload_duration_seconds = Histogram(
    "tts_storage_upload_duration_seconds",
    "Time spent uploading audio to storage",
    buckets=[0.5, 1, 2, 5, 10, 30],
)

# LLM metrics
tts_narration_duration_seconds = Histogram(
    "tts_narration_duration_seconds",
    "Time spent on LLM narration",
    buckets=[1, 3, 5, 10, 30, 60],
)


@router.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
