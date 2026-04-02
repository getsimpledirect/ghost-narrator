# Ghost Narrator — Standalone TTS Design Spec

**Date:** 2026-04-02
**Repo:** https://github.com/getsimpledirect/ghost-narrator
**Status:** Approved for implementation

---

## 1. Overview

Ghost Narrator is being repackaged as a **standalone, commercially-licensed, open-source audio narration pipeline**. It converts written content (Ghost CMS posts, static text, books, series) into studio-quality voice-narrated MP3 audio using voice cloning.

The repackaging adds four capabilities on top of the existing codebase:

1. **Hardware-tiered model selection** — auto-detects GPU/VRAM at startup, selects the appropriate Qwen3-TTS and Qwen3 LLM model for the machine
2. **Bundled narration LLM** — Ollama replaces the external vLLM dependency; overridable for users with their own vLLM stack
3. **Information-preserving narration pipeline** — NarrationStrategy with tier-calibrated chunking, strict conversion prompts, and NarrationValidator entity checks
4. **Flexible storage and voice profile support** — GCS, AWS S3, and local folder; named voice profiles and runtime voice upload

Everything else — n8n workflows, Ghost CMS integration, Redis job store, audio post-processing pipeline, GCS upload, callback webhook, static content support — is unchanged.

---

## 2. Architecture

```
Internet
   │
n8n:5678  ←── Ghost webhook (publish/update)
   │       ←── static-content webhook (manual)
   │
   ├──→ ollama:11434          Bundled Qwen3 LLM (tier-selected model)
   │         ↑
   │    reads tier.env from shared volume
   │
   └──→ tts-service:8020      Qwen3-TTS (tier-selected model)
              │  ↑
              │  reads tier.env (HardwareProbe writes at startup)
              │
              ├──→ redis:6379             Job state persistence
              ├──→ GCS / S3 / local       Audio storage (configurable)
              └──→ n8n:5678/webhook/tts-callback
```

### Startup sequence

```
hardware-probe (init container, exits)
   └── writes /shared/tier.env
          │
          ├── ollama (reads tier.env → pulls model → healthcheck passes)
          │
          └── tts-service (reads tier.env → EngineSelector → initializes engine)
                 │
                 └── n8n (depends on ollama healthy + tts-service started)
```

### Docker Compose files

```
docker-compose.yml          CPU-safe base (no GPU device declarations)
docker-compose.gpu.yml      GPU override (nvidia device reservations for ollama + tts-service)
start.sh                    Auto-detects nvidia-smi, runs correct compose command
```

---

## 3. Hardware Tiers

### Detection logic (`app/core/hardware.py`)

```
1. If HARDWARE_TIER env var is set → use it directly (skip probe)
2. If torch.cuda.is_available() is False → CPU_ONLY
3. Get VRAM: torch.cuda.get_device_properties(0).total_memory
4. VRAM < 9 GB  → LOW_VRAM
5. VRAM < 18 GB → MID_VRAM
6. VRAM >= 18 GB → HIGH_VRAM
```

`HardwareTier` enum values: `cpu_only`, `low_vram`, `mid_vram`, `high_vram`

### Tier matrix

| Tier | VRAM | TTS Model | TTS Precision | LLM Model | TTS Chunk | Synthesis Workers |
|---|---|---|---|---|---|---|
| CPU_ONLY | No GPU | Qwen3-TTS-0.6B | fp32 | qwen3:1.7b | 150w | 4 (CPU threads) |
| LOW_VRAM | 4–8 GB | Qwen3-TTS-0.6B | fp16 | qwen3:4b-q4 | 150w | 1 (GPU sequential) |
| MID_VRAM | 10–16 GB | Qwen3-TTS-1.7B | fp16 | qwen3:8b-q4 | 200w | 1 (GPU sequential) |
| HIGH_VRAM | 20+ GB | Qwen3-TTS-1.7B | fp16 (full) | qwen3:8b-q4 | 200w | 2 (concurrent inference on same loaded model) |

### Audio quality (all tiers produce high quality; HIGH_VRAM is broadcast-grade)

| Tier | Bitrate | Sample Rate | Final LUFS | Standard |
|---|---|---|---|---|
| CPU_ONLY | 192kbps | 44.1kHz | -16 LUFS | Streaming |
| LOW_VRAM | 192kbps | 44.1kHz | -16 LUFS | Streaming |
| MID_VRAM | 192kbps | 44.1kHz | -16 LUFS | Streaming |
| HIGH_VRAM | 256kbps | 48kHz | -14 LUFS | Broadcast/Podcast |

### Tier result sharing

`hardware-probe.sh` writes `/shared/tier.env` (Docker volume `tier_data`):

```bash
HARDWARE_TIER=mid_vram
SELECTED_TTS_MODEL=Qwen/Qwen3-TTS-1.7B
SELECTED_LLM_MODEL=qwen3:8b-q4
```

Both `tts-service` and `ollama` mount this volume read-only after the probe container exits.

### `EngineSelector` output

Given a `HardwareTier`, produces a config bundle consumed at startup:

```python
@dataclass
class EngineConfig:
    tier: HardwareTier
    tts_model: str           # HuggingFace model ID
    tts_device: str          # "cpu" or "cuda"
    tts_precision: str       # "fp32" or "fp16"
    llm_model: str           # Ollama model tag
    narration_strategy: str  # "chunked" or "single_shot"
    chunk_size_words: int    # LLM narration chunk size
    tts_chunk_words: int     # TTS synthesis chunk size
    synthesis_workers: int   # parallel synthesis workers
    mp3_bitrate: str         # "192k" or "256k"
    sample_rate: int         # 44100 or 48000
    target_lufs: float       # -16.0 or -14.0
```

---

## 4. Narration Pipeline

### Goal

Convert source content to a spoken-audio narration script **without losing any information**. This is a format conversion, not a summarization. Every fact, statistic, quote, and argument in the source must appear in the output.

### `NarrationStrategy` (new: `app/services/narration/`)

Two strategy implementations sharing a common interface:

```python
class NarrationStrategy(ABC):
    async def narrate(self, text: str, voice_hint: str = "") -> str:
        ...
```

**`ChunkedStrategy`** (CPU_ONLY, LOW_VRAM):
1. Split source at paragraph/heading boundaries into chunks of `chunk_size_words`
2. For each chunk (sequentially):
   - Build prompt: system prompt + last 3 sentences of previous output as continuity seed
   - Call Ollama `/v1/chat/completions`
   - Run `NarrationValidator` on result
   - On validation failure: retry once with failure context injected into prompt
3. Concatenate validated chunks → final narration script

**`SingleShotStrategy`** (MID_VRAM, HIGH_VRAM):
1. Send full source in one call if `len(words) <= 3000` (MID) or always (HIGH)
2. MID_VRAM fallback: if `len(words) > 3000`, switch to `ChunkedStrategy(chunk_size=2500)`
3. Run `NarrationValidator` on full output
4. On failure: retry once

### System prompt (all tiers — `app/services/narration/prompt.py`)

Base prompt used across all tiers:

```
You are converting written article content into spoken audio narration for a podcast.

RULES:
- This is a FORMAT CONVERSION, not a rewrite or summary
- DO NOT skip, condense, or omit any information
- Every fact, statistic, quote, and argument must appear in your output
- Convert markdown and HTML to natural spoken language
- Replace visual elements (bullet lists, headers) with spoken transitions
- Write in a clear, engaging podcast narrator voice
- Do not add information that is not in the source

OUTPUT: Return only the narration text. No preamble, no metadata.
```

HIGH_VRAM additionally appends pacing guidance:

```
- Add natural pacing: use sentence rhythm and paragraph breaks for breathing room
- Emphasize key terms and numbers with natural spoken stress patterns
- Use transitional phrases between sections for narrative flow
```

### `NarrationValidator` (`app/services/narration/validator.py`)

Lightweight post-generation check. Extracts from source:
- All numbers and percentages (regex)
- All quoted strings (regex)
- Proper nouns (capitalized words not at sentence start)

Verifies each extracted entity appears in the narration output (case-insensitive). Returns a `ValidationResult` with any missing entities. On failure, the strategy builds a targeted retry prompt listing exactly what was missing.

No LLM call needed — pure string matching. Runs in < 5ms regardless of content length.

---

## 5. Voice Profiles

Voice cloning is available on all tiers. Both Qwen3-TTS-0.6B and Qwen3-TTS-1.7B support reference-audio voice cloning via the same API.

### Directory structure

```
tts-service/voices/
├── default/
│   └── reference.wav          Backward compatible — existing deployments unchanged
└── profiles/
    ├── narrator-warm.wav
    ├── narrator-professional.wav
    └── <runtime-uploaded>.wav
```

### `VoiceRegistry` (`app/services/voices/registry.py`)

- `list_profiles()` — scans `voices/profiles/`, returns names
- `resolve(name: str) -> Path` — `"default"` → `voices/default/reference.wav`; else → `voices/profiles/<name>.wav`
- `validate(path: Path)` — checks: WAV format, duration 5–120s, sample rate ≥ 16kHz, mono or stereo

### API changes

`GenerateRequest` gains one new optional field:
```python
voice_profile: str = "default"
```

New routes registered in `app/api/routes/voices.py`:
```
POST   /voices/upload          Multipart WAV upload → saved as named profile
GET    /voices                 List available profiles with metadata
DELETE /voices/{name}          Remove a named profile (cannot delete "default")
```

### Volume

`voices_data` Docker volume persists uploaded profiles across container restarts.

---

## 6. Storage Backends

### Selection

`STORAGE_BACKEND` env var selects the active backend at startup via `get_storage_backend()` in `app/services/storage/__init__.py`. Default: `local`.

### Interface (`app/services/storage/base.py`)

```python
class StorageBackend(ABC):
    async def upload(self, local_path: Path, job_id: str, site_slug: str) -> str:
        """Upload audio file. Returns audio_uri string."""
    
    def make_public_url(self, audio_uri: str) -> str:
        """Convert storage URI to HTTP URL for embedding in Ghost player."""
```

### Implementations

**`LocalStorage`** (`local.py`):
- `audio_uri`: `local://<job_id>.mp3`
- `make_public_url`: `http://<SERVER_EXTERNAL_IP>:8020/tts/download/<job_id>`
- Files persist in `tts_output` Docker volume

**`GCSStorage`** (`gcs.py` — existing logic moved):
- `audio_uri`: `gs://<bucket>/<prefix>/<site_slug>/<job_id>.mp3`
- `make_public_url`: `https://storage.googleapis.com/<bucket>/<path>`
- Auth: ADC (GCE service account) or `GCS_SERVICE_ACCOUNT_KEY_PATH`

**`S3Storage`** (`s3.py` — new):
- `audio_uri`: `s3://<bucket>/<prefix>/<site_slug>/<job_id>.mp3`
- `make_public_url`: `https://<bucket>.s3.<region>.amazonaws.com/<path>`
- Auth: `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`

### Notification payload change

The TTS service callback payload renames `gcs_uri` → `audio_uri` to be storage-agnostic:

```json
{ "job_id": "...", "status": "completed", "audio_uri": "s3://...", "error": null }
```

The `ghost-audio-callback.json` n8n workflow is updated to parse all three URI schemes and produce the correct HTTP URL for the Ghost audio player embed.

### Environment variables

```env
# Storage
STORAGE_BACKEND=local         # local | gcs | s3

# Local (STORAGE_BACKEND=local)
OUTPUT_DIR=/app/output

# GCS (STORAGE_BACKEND=gcs)
GCS_BUCKET_NAME=
GCS_AUDIO_PREFIX=audio/articles
GCS_SERVICE_ACCOUNT_KEY_PATH=   # leave blank to use ADC on GCE

# S3 (STORAGE_BACKEND=s3)
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=us-east-1
S3_BUCKET_NAME=
S3_AUDIO_PREFIX=audio/articles
```

---

## 7. Bundled LLM (Ollama)

### Why Ollama over vLLM

vLLM requires CUDA — it cannot run on CPU. Ollama uses llama.cpp under the hood, supporting all tiers including CPU_ONLY. For single-user narration workloads (not high-throughput serving), Ollama's performance is adequate at all tiers.

Both expose an OpenAI-compatible `/v1/chat/completions` API, so n8n workflows require no changes to their HTTP request nodes.

### Compose service

```yaml
ollama:
  image: ollama/ollama:latest
  container_name: ollama
  volumes:
    - ollama_models:/root/.ollama   # persistent model cache
    - tier_data:/shared:ro          # reads tier.env
  entrypoint: ["/bin/sh", "/scripts/ollama-init.sh"]
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:11434/api/tags"]
    start_period: 600s              # first-run model pull can take time
```

`scripts/ollama-init.sh`:
1. Source `/shared/tier.env`
2. Start `ollama serve` in background
3. Wait for API ready
4. `ollama pull $SELECTED_LLM_MODEL`
5. Pre-warm: send one short test prompt to load model into memory
6. Exit 0 (service stays running via `ollama serve`)

### External vLLM override

Users with an existing vLLM stack set:
```env
LLM_BASE_URL=http://host.docker.internal:8001/v1
LLM_MODEL_NAME=Qwen/Qwen3-14B-AWQ
```

When `LLM_BASE_URL` is set to a non-Ollama URL, the `ollama` container is still started but n8n routes to the external endpoint. Future: add a `--profile no-ollama` to skip it entirely.

---

## 8. New & Modified Files

### New files (20)

```
docker-compose.gpu.yml
start.sh
scripts/hardware-probe.sh
scripts/ollama-init.sh
tts-service/app/core/hardware.py
tts-service/app/api/routes/voices.py
tts-service/app/services/narration/__init__.py
tts-service/app/services/narration/strategy.py
tts-service/app/services/narration/prompt.py
tts-service/app/services/narration/validator.py
tts-service/app/services/storage/__init__.py
tts-service/app/services/storage/base.py
tts-service/app/services/storage/local.py
tts-service/app/services/storage/gcs.py
tts-service/app/services/storage/s3.py
tts-service/app/services/voices/__init__.py
tts-service/app/services/voices/registry.py
tts-service/app/services/voices/upload.py
README.md
NOTICE
```

### Modified files (33)

```
docker-compose.yml                              Add ollama, hardware-probe, update defaults
.env.example                                    All new env vars documented
.gitignore                                      voices/profiles/*.wav, shared/tier.env
CHANGELOG.md                                    New version entry
CONTRIBUTING.md                                 Update repo URL to getsimpledirect/ghost-narrator
CODE_OF_CONDUCT.md                              Update repo references
SECURITY.md                                     Update repo references
docs/ARCHITECTURE.md                            Full rewrite — Qwen3-TTS, all new features
n8n/SETUP_GUIDE.md                              vLLM → Ollama, storage backend notes
n8n/workflows/ghost-audio-pipeline.json         Update VLLM_BASE_URL comment nodes
n8n/workflows/ghost-audio-callback.json         gcs_uri → audio_uri, multi-scheme URI parsing
n8n/workflows/static-content-audio-pipeline.json  Storage-backend awareness
scripts/init.sh                                 Fish Speech → Qwen3-TTS references
scripts/validate-build.sh                       Rewrite validation for Qwen3-TTS + new endpoints
scripts/setup-gcp.sh                            Rename → setup-storage.sh, add S3 section
scripts/backfill-audio.sh                       Update model name references
scripts/backfill-audio.ps1                      Update model name references
tts-service/Dockerfile                          Fish Speech → Qwen3-TTS (per migration plan)
tts-service/requirements.txt                    fish-speech → qwen-tts, add boto3
tts-service/README.md                           Full rewrite
tts-service/QUICKSTART.md                       Voice path, start.sh, hardware detection
tts-service/run-docker.sh                       Update model download references
tts-service/run-docker.ps1                      Update model download references
tts-service/app/__init__.py                     Docstring update
tts-service/app/main.py                         Register /voices routes, update description
tts-service/app/config.py                       HARDWARE_TIER, STORAGE_BACKEND, S3 vars, audio quality
tts-service/app/core/tts_engine.py              Full rewrite — Qwen3-TTS engine
tts-service/app/core/exceptions.py              GCSUploadError → StorageUploadError
tts-service/app/api/routes/health.py            Remove VQ token check, add tier + model status
tts-service/app/models/schemas.py               Add voice_profile to GenerateRequest
tts-service/app/services/synthesis.py           Parallel workers on HIGH_VRAM
tts-service/app/services/audio.py               Tiered audio quality (bitrate, sample rate, LUFS)
tts-service/app/services/tts_job.py             Wire narration strategy, voice profiles, storage
tts-service/app/utils/text.py                   Comment updates
tts-service/tests/test_tts_job.py               Update mocks, add narration/storage tests
tts-service/voices/.gitkeep                     Restructure voices/default/ and voices/profiles/
```

### Deleted files (2)

```
docs/plans/2026-04-01-qwen3-tts-migration.md    Superseded by this spec
tts-service/app/services/storage.py             Replaced by storage/ package
```

---

## 9. Key Invariants (Must Not Break)

1. Existing `voices/reference.wav` still works — `VoiceRegistry.resolve("default")` checks `voices/default/reference.wav` first, then silently falls back to `voices/reference.wav`. No migration step required for existing deployments.
2. `tts_job.py` external interface unchanged — `run_tts_job(job_id, text, site_slug)` signature stays the same
3. n8n workflow trigger paths unchanged — `/webhook/ghost-published`, `/webhook/tts-callback`, `/webhook/static-content-audio` stay identical
4. Redis job state schema backward-compatible — add `audio_uri` field alongside `gcs_uri` during transition, remove `gcs_uri` only after callback workflow is updated
5. Health endpoint at `/health` stays at same path with same response shape (add new fields, don't rename existing ones)

---

## 10. Out of Scope (v1)

- HTTPS / TLS termination — document reverse proxy setup instead
- Multi-GPU assignment (two separate GPUs for TTS vs LLM)
- WordPress or other CMS adapters
- Plugin architecture for TTS engines
- Rate limiting (n8n `N8N_CONCURRENCY_PRODUCTION_LIMIT` is the gatekeeper)
- API authentication on tts-service (internal Docker network only)
- vLLM `--profile` to skip Ollama when using external LLM

---

## 11. Open Questions / Future Considerations

- Qwen3-TTS 0.6B availability on HuggingFace needs verification before implementation starts
- Ollama GGUF model tags (`qwen3:4b-q4`, `qwen3:8b-q4`) need to be confirmed against Ollama's model library at implementation time
- S3 presigned URLs for private buckets — current design uses public bucket URLs; private bucket support via presigned URLs is a natural v2 addition
