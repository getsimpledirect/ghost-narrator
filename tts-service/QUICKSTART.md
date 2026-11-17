# TTS Service Quick Start Guide

## Studio-Quality Narration

This service uses **Qwen3-TTS** for professional, studio-quality narration of your Ghost articles.

**Feature**: High-fidelity zero-shot voice cloning with natural prosody and breathing.

The maintained container path is Linux with NVIDIA/CUDA. The application has a CPU tier, but the current Dockerfile is not a turnkey macOS/Apple-Silicon build. Build a compatible image and benchmark it before planning around CPU performance. A clean CUDA worker should have a 100GB disk.

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
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

For a source-preserving private preview, only the hardware probe, Redis and TTS service are required. Do not start n8n or an LLM unless the workflow being tested actually needs them.

---

### Step 3: Verify Services are Running

Check that both TTS service and Redis are running:

```bash
docker ps

# You should see containers:
# - tts-service
# - redis
# - hardware-probe (completed after writing the tier config)
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

**Note:** `job_store` should show `"redis"` (persistent storage). If it shows `"memory"`, check Redis container status.

**View API documentation:**

Open in your browser: http://localhost:8020/docs

---

## Usage Example

### Generate Audio from Text

```bash
curl -X POST "http://localhost:8020/tts/generate" \
  -H "Authorization: Bearer $TTS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "This is a test of the voice cloning system.",
    "job_id": "test-001",
    "preserve_source_wording": true
  }'
```

`preserve_source_wording` bypasses the narration LLM. Supply already-reviewed, narration-ready plain text; table conversion and pronunciation changes must be shown to the reviewer before synthesis.

### Check Job Status

```bash
curl -H "Authorization: Bearer $TTS_API_KEY" \
  "http://localhost:8020/tts/status/test-001"
```

### Download Generated Audio

```bash
curl -H "Authorization: Bearer $TTS_API_KEY" \
  "http://localhost:8020/tts/download/test-001" -o output.mp3
```

---

## Configuration

### Environment Variables (Optional)

Set these before running if you want to customize:

```bash
export TTS_LANGUAGE="en"           # Language code (en, es, fr, de, etc.)
export SINGLE_SHOT_SEGMENT_WORDS="60"    # Override tier's studio segment size (clamped to 30-300)
export SINGLE_SHOT_OVERLAP_MS="500"     # Overlap crossfade between segments
export HARDWARE_TIER="cpu_only"    # Override auto-detection: cpu_only, low_vram, mid_vram, high_vram
export MAX_WORKERS="4"             # Thread pool size for parallel synthesis
```

### Hardware Tiers

The service auto-detects hardware and selects the appropriate Qwen3-TTS model:

| Tier | VRAM | TTS Model | Output Quality |
|---|---|---|---|
| CPU only | None | Qwen3-TTS-12Hz-0.6B-Base | 192kbps, 48kHz |
| Low (<12 GB) | <12 GB | Qwen3-TTS-12Hz-0.6B-Base | 192kbps, 48kHz |
| Mid (12–18 GB) | 12–18 GB | Qwen3-TTS-12Hz-1.7B-Base | 256kbps, 48kHz |
| High (18+ GB) | 18+ GB | Qwen3-TTS-12Hz-1.7B-Base (bf16) | 320kbps, 48kHz, −14 LUFS |

Override with `HARDWARE_TIER=cpu_only|low_vram|mid_vram|high_vram` in `.env`.

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

Long-form quality mode intentionally synthesizes multiple candidates and may re-run segments after acoustic and transcript checks. Measure end-to-end time on the exact host, model, voice and article; do not estimate it from raw model inference benchmarks. The November 2026 Founder Reality trial took about 2 hours 10 minutes for a 2,717-word job on one L4; its full disposable-VM lifetime was about 2 hours 57 minutes.

### First run model load

Startup loads the selected model and caches the voice prompt. Time varies with the model cache, disk and network; check readiness and logs instead of assuming a fixed 30–60 second calibration.

### Jobs lost after restart

Check Redis is running: `docker ps | grep redis`
Verify health endpoint shows `"job_store": "redis"`

### View detailed logs

```bash
docker compose logs -f tts-service
# Or directly:
docker logs -f tts-service
```

---

## Performance

No universal words-per-minute figure is documented. Runtime depends on hardware tier, model size, best-of-N count, segment count, transcript checks, retries and mastering. Record the article word count, model, GPU, build/startup time, synthesis time and total worker lifetime for every bounded trial.

---

## Next Steps

1. **Test with your voice**: Generate a short test audio
2. **Verify output**: Decode the full MP3 and review it against the exact script
3. **Keep it private**: Do not expose port 8020 or publish the preview
4. **Review security**: Complete the gates in `../SECURITY.md` before n8n or callbacks
5. **Publish separately**: Upload only an explicitly approved MP3, then verify playback and seeking

For detailed documentation, see [README.md](./README.md)
