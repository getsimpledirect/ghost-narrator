# TTS Service — Studio-Quality Narration API

A FastAPI service wrapping **Qwen3-TTS** for high-fidelity voice cloning and professional narration.

## Python Version

This service requires **Python 3.12**. Use Docker (recommended) which handles the correct Python version automatically.

## Build Information

**First build time**: 2-5 minutes (downloads ~3GB of models)
**Cached rebuild**: 1-3 minutes
**Docker resources required**: 8GB RAM, 20GB disk space

**Runtime Resources:**
- **CPU Mode (Default)**: ~1GB RAM, configurable parallel workers
- **GPU Mode**: ~3GB VRAM + ~6GB RAM

The Dockerfile uses **uv** (by Astral) for blazingly fast and deterministic dependency resolution, completely replacing legacy pip installations.

## Quick Start

```bash
# From the ghost-narrator directory
docker compose up -d
```

The service will be available at `http://localhost:8020`

See [QUICKSTART.md](./QUICKSTART.md) for detailed setup instructions.

## Build Troubleshooting

### Common Build Errors

#### 1. Out of Memory During Build

**Symptom:**
```
Killed
The command '/bin/sh -c ...' returned a non-zero code: 137
```

**Solution:**
1. Increase Docker Desktop memory allocation: Settings → Resources → Memory → 8GB+
2. Close other applications during build

#### 2. Disk Space Error

**Symptom:**
```
no space left on device
```

**Solution:**
```bash
docker system prune -a --volumes
# Ensure at least 20GB free disk space
```

#### 3. Network Timeout

**Solution:**
1. Check internet connection
2. Retry the build (timeout settings are already configured in Dockerfile)

### Manual Build (Detailed Output)

```bash
cd tts-service
docker build --progress=plain --no-cache -t ghost-tts-service:latest .
```

### Build Architecture

The Dockerfile uses **uv** to provide a fast and deterministic build process:

1. **System Dependencies**: Installs ffmpeg and build essentials.
2. **uv Package Manager**: Installs uv for blazingly fast dependency resolution.
3. **Requirement Resolution**: Resolves and installs all PyTorch and ML packages from `requirements.txt`.
4. **Model Pre-download**: Downloads Qwen3-TTS and Whisper weights during build (optional).
5. **Validation**: Verifies critical imports (torch, transformers, fastapi) work correctly.

## Local Development

```bash
# Create virtual environment with Python 3.12
python3.12 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies using uv
uv pip install -r requirements.txt

# Run the service
uvicorn app.main:app --host 0.0.0.0 --port 8020 --reload
```

### Environment Variables (Local Development)

Create a `.env` file:

```env
VOICE_SAMPLE_PATH=./voices/default/reference.wav
TTS_LANGUAGE=en
MAX_CHUNK_WORDS=200
SINGLE_SHOT_MAX_WORDS=400
SINGLE_SHOT_OVERLAP_MS=500
DEVICE=cpu
STORAGE_BACKEND=local
N8N_CALLBACK_URL=http://localhost:5678/webhook/tts-callback
```

## Architecture

### How It Works

1. **POST /tts/generate** - Submit text for TTS generation
2. Background processing:
   - Automatically transcribes reference audio if needed (Whisper tiny)
   - Generates semantic tokens using Qwen3-TTS model
   - Decodes high-fidelity audio
   - Concatenates chunks into single MP3 file
   - Uploads to configured storage backend
   - Notifies n8n via callback webhook
3. **GET /tts/status/{job_id}** - Poll job status
4. **GET /tts/download/{job_id}** - Download generated audio

### Key Features

- **Studio-quality voice cloning**: Zero-shot cloning with expressive prosody
- **Expressive Narration**: Captures natural breathing and human-like emphasis
- **Automatic chunking**: Handles long texts by splitting at sentence boundaries
- **GPU acceleration**: Optional CUDA support for faster generation
- **Flexible storage**: Local, GCS, or S3 backends
- **Async processing**: Non-blocking background jobs with status polling

## API Endpoints

### Generate Audio

```bash
POST /tts/generate
Content-Type: application/json

{
  "text": "Your long article text here...",
  "job_id": "optional-custom-id",
  "article_slug": "my-article",
  "callback_url": "https://your-webhook.com/callback"
}
```

### Check Status

```bash
GET /tts/status/{job_id}

Response:
{
  "job_id": "abc123",
  "status": "processing|completed|failed",
  "storage_uri": "audio/articles/abc123.mp3",
  "error": null
}
```

### Download Audio

```bash
GET /tts/download/{job_id}

Returns: MP3 file (audio/mpeg)
```

### Health Check

```bash
GET /health

Response:
{
  "status": "healthy",
  "device": "cpu",
  "model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
  "voice_sample": true,
  "model_loaded": true,
  "reference_audio_present": true,
  "reference_text_present": true,
  "tts_engine_ready": true,
  "job_store": "redis",
  "jobs_count": 0,
  "max_workers": 4,
  "executor_active": true,
  "gcs_client_active": true,
  "hardware_tier": "cpu_only",
  "tts_model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
  "llm_model": "qwen3.5:2b"
}
```

### Additional Health Endpoints

```bash
GET /health/ready    # Kubernetes readiness probe — returns {"ready": true} when engine is fully initialized
GET /health/live     # Kubernetes liveness probe — returns {"alive": true} if service is responsive
GET /health/detailed # Component-level breakdown for debugging
```

### Job Management

```bash
POST /tts/pause/{job_id}    # Pause an active job
POST /tts/resume/{job_id}   # Resume a paused job
DELETE /tts/{job_id}        # Delete a job and clean up its files
GET /tts/jobs               # List all jobs
```

## Voice Sample Requirements

Place your reference voice WAV file in `./voices/default/reference.wav`:

- **Duration**: 5-60 seconds (optimal 45+)
- **Format**: WAV, 22.05 kHz, mono, 16-bit PCM
- **Quality**: Clear speech, no background noise
- **Content**: Natural speaking, varied intonation
- **Language**: Must match `TTS_LANGUAGE` setting

### Creating a Good Voice Sample

```bash
# Convert any audio to proper format with ffmpeg
ffmpeg -i input.mp3 -ar 22050 -ac 1 -c:a pcm_s16le voices/default/reference.wav

# Trim to 45 seconds starting at 10 seconds
ffmpeg -i input.wav -ss 10 -t 45 -ar 22050 -ac 1 -c:a pcm_s16le voices/default/reference.wav

# Verify format
ffprobe -v quiet -show_entries stream=codec_name,sample_rate,channels \
  -of default=noprint_wrappers=1 voices/default/reference.wav
# Expected: codec_name=pcm_s16le, sample_rate=22050, channels=1
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VOICE_SAMPLE_PATH` | `/app/voices/default/reference.wav` | Path to reference voice WAV |
| `VOICE_SAMPLE_REF_TEXT` | *(empty)* | Transcription of the reference audio. When set, uses ICL mode (higher-quality cloning). When empty, uses x-vector-only mode (no transcription needed — default). |
| `TTS_LANGUAGE` | `en` | BCP-47 language code |
| `MAX_CHUNK_WORDS` | `200` | Max words per synthesis chunk |
| `SINGLE_SHOT_MAX_WORDS` | `400` | Max words for single-pass synthesis (fallback if VRAM probe unavailable) |
| `SINGLE_SHOT_SEGMENT_WORDS` | *(auto)* | Words per segment — auto-probed from free VRAM at startup; override to force a fixed size |
| `SINGLE_SHOT_OVERLAP_MS` | `500` | Overlap crossfade in milliseconds |
| `DEVICE` | `cpu` | PyTorch device: `cpu` or `cuda` |
| `MAX_WORKERS` | `4` | Thread pool size for parallel synthesis (CPU mode) |
| `HARDWARE_TIER` | `auto` | Hardware tier: auto/cpu/low/mid/high |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL for job persistence |
| `REDIS_JOB_TTL` | `86400` | Job retention time in seconds (24 hours) |
| `STORAGE_BACKEND` | `local` | Storage backend: local/gcs/s3 |
| `GCS_BUCKET_NAME` | - | Google Cloud Storage bucket name (if using GCS) |
| `S3_BUCKET_NAME` | - | AWS S3 bucket name (if using S3) |
| `GCS_AUDIO_PREFIX` | `audio/articles` | Storage path prefix for uploads |
| `N8N_CALLBACK_URL` | - | Webhook URL for job completion |
| `MAX_JOB_DURATION_SECONDS` | `28800` | Hard wall-clock limit per job (min 300s). If a job exceeds this inside the GPU slot, the semaphore is released and the job fails with a timeout error rather than blocking the queue indefinitely. |
| `DRY_RUN_GATE` | `false` | Acoustic quality gate mode. `false` = enforce (reject segments that fail quality checks). `true` = shadow/calibration mode (log failures but pass all segments through). |

### Hardware Tiers

| Tier | VRAM | TTS Model | LLM Model | Output Quality |
|---|---|---|---|---|
| CPU only | None | Qwen3-TTS-12Hz-0.6B-Base | qwen3.5:2b | 192kbps, 48kHz |
| Low (<12 GB) | <12 GB | Qwen3-TTS-12Hz-0.6B-Base | qwen3.5:4b (Ollama) | 192kbps, 48kHz |
| Mid (12–18 GB) | 12–18 GB | Qwen3-TTS-12Hz-1.7B-Base | Qwen/Qwen3.5-4B (vLLM fp8) | 256kbps, 48kHz |
| High (18+ GB) | 18+ GB | Qwen3-TTS-12Hz-1.7B-Base (bf16) | Qwen/Qwen3.5-9B (vLLM fp8, 64K ctx) | 320kbps, 48kHz, −14 LUFS |

### Performance Tuning

#### CPU Mode (Default)
- Safe for all systems
- **Parallel Processing**: Synthesizes multiple chunks simultaneously
- Generation time:
  - Sequential (1 worker): ~3-5 minutes per 2000-word article
  - Parallel (4 workers): ~50-60 seconds per 2000-word article
  - Parallel (8 workers): ~30-40 seconds per 2000-word article
- Memory: ~800 MB - 1.2 GB RAM (optimized with streaming concatenation)
- Recommended for: Most deployments, shared GPU systems

**Optimize CPU Performance:**
```bash
# Quad-core CPU
MAX_WORKERS=4

# Octa-core CPU
MAX_WORKERS=8
```

#### GPU Mode (CUDA)
- Requires NVIDIA GPU with 4+ GB VRAM
- Generation time: ~20-40 seconds per 2000-word article
- Memory: ~3 GB VRAM + 6 GB RAM

## Redis Job Persistence

**Jobs are persisted to Redis by default!**

### Why Redis?

- **No data loss**: Jobs survive container restarts
- **Persistent state**: Running jobs can be recovered after crashes
- **Automatic fallback**: If Redis is unavailable, falls back to in-memory storage

### How It Works

1. All job state (queued, processing, completed, failed) is stored in Redis
2. Jobs are kept for 24 hours by default (configurable with `REDIS_JOB_TTL`)
3. If Redis connection fails, service automatically uses in-memory storage
4. Redis uses AOF (Append-Only File) persistence with `fsync` every second

### Monitoring

The `/health` endpoint shows storage status:

```json
{
  "status": "healthy",
  "device": "cpu",
  "model": "qwen3-tts-0.6b",
  "voice_sample": true,
  "model_loaded": true,
  "reference_audio_present": true,
  "reference_text_present": true,
  "tts_engine_ready": true,
  "job_store": "redis",
  "jobs_count": 5,
  "max_workers": 4,
  "executor_active": true,
  "storage_client_active": true
}
```

- `job_store`: `"redis"` (persistent) or `"memory"` (ephemeral)
- `jobs_count`: Total jobs in storage

## Performance Optimizations

### 1. Parallel Chunk Synthesis (CPU Mode)
- Multiple chunks processed simultaneously using ThreadPoolExecutor
- Up to **4x faster** on CPU with default 4 workers
- Configure with `MAX_WORKERS` environment variable

### 2. Resource Reuse
- **Storage Client**: Single reusable instance
- **HTTP Client**: Connection pooling with keepalive
- Initialized at startup, shared across all requests

### 3. Streaming Concatenation
- Automatic for large files (>10 chunks)
- **Up to 80% memory reduction** for long articles
- Prevents OOM errors on 5000+ word articles

### 4. Smart Processing Strategy
- CPU mode + multiple chunks → Parallel synthesis
- GPU mode → Sequential processing (optimal for CUDA)
- Large files → Streaming concatenation
- Small files → Standard concatenation (faster)

### Performance Benchmarks

**Typical 2000-word Article:**

| Configuration | Time | Improvement |
|--------------|------|-------------|
| CPU (1 worker) | 180s | Baseline |
| CPU (4 workers) | 50s | **72% faster** |
| CPU (8 workers) | 30s | **83% faster** |
| CUDA | 23s | 87% faster |

**Memory Usage:**

| Scenario | Memory | Notes |
|----------|--------|-------|
| 2000 words | 800 MB | Standard |
| 5000 words | 1.1 GB | Streaming enabled |
| 10000 words | 1.8 GB | Previously OOM |

## Troubleshooting

### Model download fails

First run downloads Qwen3-TTS model weights. If it fails:

```bash
# Pre-download inside container
docker exec -it tts-service python -c "import torch; print('OK')"
```

### Out of memory errors

If the service crashes with OOM:
- Reduce `MAX_CHUNK_WORDS` to 150 to shrink per-chunk memory
- Set `SINGLE_SHOT_SEGMENT_WORDS=200` to force smaller synthesis segments
- Increase system swap space
- Use GPU mode if available

### Poor audio quality

- Ensure reference WAV is high quality (no noise, 22 kHz, 15–30s ideal)
- Set `VOICE_SAMPLE_REF_TEXT` to the transcription of your reference audio — enables ICL mode (significantly better voice cloning than x-vector-only)
- Use `HARDWARE_TIER=high_vram` if your GPU supports it — bf16 precision, larger LLM, quality re-synthesis
- Ensure language matches reference voice
- Use `HARDWARE_TIER=mid_vram` or higher — larger TTS model, best-of-3 segment selection, and DeepFilterNet enhancement all improve coherence

### Jobs lost after restart

Check Redis is running: `docker ps | grep redis`
Check health endpoint for `job_store` value (should be `"redis"`)

### Storage upload fails

Check authentication credentials for your configured `STORAGE_BACKEND`.

## Development

### Project Structure

```
tts-service/
├── app/                        # Application package
│   ├── __init__.py            # Package initialization
│   ├── main.py                # FastAPI application entry point
│   ├── config.py              # Configuration and environment variables
│   ├── dependencies.py        # FastAPI dependency injection
│   │
│   ├── api/                   # API layer
│   │   ├── __init__.py
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── tts.py         # TTS endpoints (generate, status, download)
│   │       ├── voices.py      # Voice profile endpoints (upload, list, delete)
│   │       └── health.py      # Health check endpoints
│   │
│   ├── core/                  # Core functionality
│   │   ├── __init__.py
│   │   ├── exceptions.py      # Custom exception classes
│   │   ├── hardware.py        # Hardware tier detection + EngineConfig
│   │   └── tts_engine.py      # Qwen3-TTS engine wrapper
│   │
│   ├── models/                # Pydantic schemas
│   │   ├── __init__.py
│   │   └── schemas.py         # Request/response models
│   │
│   ├── domains/               # Domain-driven business logic
│   │   ├── __init__.py
│   │   ├── job/               # Job management domain
│   │   │   ├── __init__.py
│   │   │   ├── state.py       # JobState enum and JobStatus dataclass
│   │   │   ├── store.py       # Redis/in-memory job storage
│   │   │   ├── notification.py # Webhook notifications (n8n)
│   │   │   ├── runner.py      # Background job runner entry point
│   │   │   └── tts_job.py     # Complete TTS pipeline orchestration
│   │   ├── narration/         # LLM narration script generation
│   │   │   ├── __init__.py
│   │   │   ├── factory.py     # Strategy factory (selects by hardware tier)
│   │   │   ├── strategy.py    # ChunkedStrategy + SingleShotStrategy
│   │   │   ├── prompt.py      # Tier-specific system prompts
│   │   │   └── validator.py   # NarrationValidator (entity preservation)
│   │   ├── storage/           # Pluggable storage backends
│   │   │   ├── __init__.py    # Factory: get_storage_backend()
│   │   │   ├── local.py       # LocalStorageBackend (local:// URIs)
│   │   │   ├── gcs.py         # GCSStorageBackend (gs:// URIs)
│   │   │   └── s3.py          # S3StorageBackend (s3:// URIs)
│   │   ├── synthesis/         # TTS synthesis orchestration
│   │   │   ├── __init__.py
│   │   │   ├── chunker.py     # Text chunking for synthesis
│   │   │   ├── concatenate.py # Audio concatenation utilities
│   │   │   ├── normalize.py   # Audio normalization
│   │   │   ├── mastering.py   # Audio mastering with fallback
│   │   │   ├── quality.py     # Audio quality validation and mastering wrapper
│   │   │   ├── quality_check.py # Per-chunk quality check and resynthesis
│   │   │   └── service.py     # Synthesis orchestration (sequential/parallel)
│   │   └── voices/            # Voice profile management
│   │       ├── __init__.py
│   │       ├── registry.py    # VoiceRegistry (resolve, list, delete)
│   │       └── upload.py      # Voice sample validation and save
│   │
│   └── utils/                 # Utility functions
│       ├── __init__.py
│       └── text.py            # Text chunking utilities
│
├── voices/                    # Voice samples directory (Docker volume)
│   └── default/
│       └── reference.wav      # Your voice sample (not in git)
│
├── Dockerfile                 # Container image definition
├── requirements.txt           # Python dependencies
├── QUICKSTART.md              # Quick start guide
└── README.md                  # This file
```

### Module Responsibilities

| Module | Description |
|--------|-------------|
| `app/main.py` | FastAPI app initialization, lifecycle management |
| `app/config.py` | Centralized configuration from environment variables |
| `app/core/hardware.py` | Hardware tier detection and EngineConfig singleton |
| `app/core/tts_engine.py` | Thread-safe Qwen3-TTS wrapper with singleton pattern |
| `app/core/exceptions.py` | Domain-specific exception hierarchy |
| `app/domains/job/store.py` | Job persistence with Redis + in-memory fallback |
| `app/domains/synthesis/service.py` | Parallel/sequential chunk synthesis |
| `app/domains/synthesis/concatenate.py` | WAV concatenation with streaming for large files |
| `app/domains/synthesis/normalize.py` | EBU R128 loudness normalization |
| `app/domains/synthesis/mastering.py` | Broadcast mastering chain: compress → two-pass EBU R128 loudnorm → true peak limit |
| `app/domains/narration/strategy.py` | ChunkedStrategy (CPU/LOW) and SingleShotStrategy (MID/HIGH) |
| `app/domains/narration/validator.py` | Entity-level information preservation check |
| `app/domains/storage/` | Pluggable storage: LocalStorageBackend, GCSStorageBackend, S3StorageBackend |
| `app/domains/voices/registry.py` | Voice profile resolution with backward-compat fallback |
| `app/domains/job/notification.py` | Webhook callbacks with retry logic |
| `app/domains/job/tts_job.py` | Complete TTS pipeline orchestration |
| `app/utils/text.py` | Sentence-boundary text chunking |

### Running the Service

```bash
# With Docker Compose (recommended)
docker compose up -d

# Or run directly (requires Python 3.12)
uvicorn app.main:app --host 0.0.0.0 --port 8020 --reload
```

### Running Tests

```bash
# Install dev dependencies
pip install pytest pytest-asyncio httpx

# Run tests
pytest tests/
```

### Code Style

This project follows PEP 8 conventions enforced by ruff:
- Max line length: 120 characters
- Use type hints for all function signatures
- Follow PEP 8 naming conventions
- Document all public functions with docstrings

## License

Part of the Ghost Narrator project. See main repository LICENSE.

## Support

For issues specific to:
- **TTS service**: Open issue in this repository
- **Qwen3-TTS model**: See [Qwen on Hugging Face](https://huggingface.co/Qwen)

## Credits

Built with:
- [Qwen3-TTS](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base) - Voice cloning model
- [FastAPI](https://fastapi.tiangolo.com/) - API framework
- [pydub](https://github.com/jiaaro/pydub) - Audio processing
- [Ollama](https://ollama.com/) - Bundled LLM inference (cpu/low VRAM tiers)
- [vLLM](https://github.com/vllm-project/vllm) - High-throughput LLM serving (mid/high VRAM tiers)
