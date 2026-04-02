# TTS Service Quick Start Guide

## Studio-Quality Narration

This service uses **Qwen3-TTS** for professional, studio-quality narration of your Ghost articles.

**Feature**: High-fidelity zero-shot voice cloning with natural prosody and breathing.

---

## Quick Start (3 Steps)

### Step 1: Add Your Voice Sample

Place a reference voice WAV file in the `voices/default` directory:

```bash
# Create voices/default directory if needed
mkdir -p voices/default

# Add your voice file (rename it to reference.wav)
# Requirements: WAV format, 22.05 kHz, mono, 5-60s
```

**Convert any audio to the correct format:**

```bash
ffmpeg -i your-voice.mp3 -ar 22050 -ac 1 -c:a pcm_s16le voices/default/reference.wav
```

---

### Step 2: Start Services

```bash
# From the ghost-narrator directory
./start.sh up -d
```

---

### Step 3: Verify Services are Running

Check that both TTS service and Redis are running:

```bash
docker ps

# You should see containers:
# - tts-service
# - redis
# - ollama
# - n8n
```

Once running, the service is available at: **http://localhost:8020**

**Test the health endpoint:**

```bash
curl http://localhost:8020/health
```

**Expected response:**

```json
{
  "status": "healthy",
  "device": "cpu",
  "model": "Qwen/Qwen3-TTS-0.6B",
  "voice_sample": true,
  "model_loaded": true,
  "reference_audio_present": true,
  "reference_tokens_present": true,
  "tts_engine_ready": true,
  "job_store": "redis",
  "jobs_count": 0,
  "max_workers": 4,
  "executor_active": true,
  "gcs_client_active": true,
  "hardware_tier": "cpu_only",
  "tts_model": "Qwen/Qwen3-TTS-0.6B",
  "llm_model": "qwen3:1.7b"
}
```

**Note:** `job_store` should show `"redis"` (persistent storage). If it shows `"memory"`, check Redis container status.

**View API documentation:**

Open in your browser: http://localhost:8020/docs

---

## Usage Example

### Generate Audio from Text

```bash
curl -X POST "http://localhost:8020/tts/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "This is a test of the voice cloning system.",
    "job_id": "test-001"
  }'
# Note: First run triggers one-time reference voice calibration (~30-60 seconds).
# Subsequent requests use the calibrated voice immediately.
```

### Check Job Status

```bash
curl "http://localhost:8020/tts/status/test-001"
```

### Download Generated Audio

```bash
curl "http://localhost:8020/tts/download/test-001" -o output.mp3
```

---

## Configuration

### Environment Variables (Optional)

Set these before running if you want to customize:

```bash
export TTS_LANGUAGE="en"           # Language code (en, es, fr, de, etc.)
export MAX_CHUNK_WORDS="200"       # Max words per synthesis chunk
export TTS_DEVICE="cpu"            # Use "cuda" for GPU acceleration
export MAX_WORKERS="4"             # Thread pool size for parallel synthesis
```

### Hardware Tiers

The service auto-detects hardware and selects the appropriate Qwen3-TTS model:

| Tier | VRAM | TTS Model | Output Quality |
|---|---|---|---|
| CPU only | None | Qwen3-TTS-0.6B | 192kbps, 44.1kHz |
| Low (4–8 GB) | 4–8 GB | Qwen3-TTS-0.6B | 192kbps, 44.1kHz |
| Mid (10–16 GB) | 10–16 GB | Qwen3-TTS-1.7B | 192kbps, 44.1kHz |
| High (20+ GB) | 20+ GB | Qwen3-TTS-1.7B | 256kbps, 48kHz, −14 LUFS |

Override with `TTS_TIER=cpu|low|mid|high` in `.env`.

### Performance Configuration

**Parallel Processing for CPU Mode:**

```bash
# Quad-core CPU (recommended)
export MAX_WORKERS="4"

# Octa-core CPU
export MAX_WORKERS="8"
```

### Storage Backend

```bash
# Local (default) — no cloud setup needed
export STORAGE_BACKEND="local"

# Google Cloud Storage
export STORAGE_BACKEND="gcs"
export GCS_BUCKET_NAME="your-bucket-name"

# AWS S3
export STORAGE_BACKEND="s3"
export S3_BUCKET_NAME="your-bucket-name"
```

### Redis Configuration (Optional)

Redis is included by default for persistent job storage:

```bash
export REDIS_URL="redis://localhost:6379/0"
export REDIS_JOB_TTL="86400"  # seconds (24 hours)
```

---

## Troubleshooting

### "Reference voice file not found"

```bash
ls voices/default/reference.wav
# Should exist
```

### "Docker is not running"

Start Docker Desktop application first, then try again.

### "Port 8020 already in use"

Another service is using port 8020. Stop it or change the port in `docker-compose.yml`.

### Slow generation

This is normal for CPU mode with default settings. For faster generation:

1. **Enable parallel processing** (recommended):
   ```bash
   export MAX_WORKERS="4"
   ```
   With 4 workers: ~50-60 seconds per 2000 words (vs 3-5 minutes sequential)

2. Use GPU mode (requires NVIDIA GPU with 4GB+ VRAM):
   ```bash
   export TTS_DEVICE="cuda"
   ```

### First run calibration

The first synthesis request triggers a one-time reference voice calibration (~30-60 seconds). This happens only once at startup. Subsequent requests use the calibrated voice immediately.

### Jobs lost after restart

Check Redis is running: `docker ps | grep redis`
Verify health endpoint shows `"job_store": "redis"`

### View detailed logs

```bash
./start.sh logs tts-service
# Or directly:
docker logs -f tts-service
```

---

## Performance

| Mode | Device | Speed | Memory | Notes |
|------|--------|-------|--------|-------|
| CPU (Sequential) | Any | ~3-5 min/2000 words | 800MB RAM | 1 worker |
| CPU (Parallel 4x) | Quad-core+ | ~50-60 sec/2000 words | 1GB RAM | **Recommended default** |
| CPU (Parallel 8x) | Octa-core+ | ~30-40 sec/2000 words | 1.2GB RAM | High performance |
| GPU | NVIDIA L4/T4 | ~20-30 sec/2000 words | 3GB VRAM + 6GB RAM | Requires GPU config |

---

## Next Steps

1. **Test with your voice**: Generate a short test audio
2. **Optimize performance**: Set `MAX_WORKERS` to match your CPU cores
3. **Integrate with n8n**: Set up the callback webhook
4. **Configure storage**: Enable GCS or S3 if needed
5. **Production deployment**: Review security and scaling

For detailed documentation, see [README.md](./README.md)
