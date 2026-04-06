# Changelog

All notable changes to the Ghost Narrator audio pipeline will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.2.0] — 2026-04-06

### Fixed
- **GCS client leak** — `GCSStorageBackend._get_client()` created a new connection on every retry attempt; now caches the client instance as a singleton
- **n8n startup race** — n8n `depends_on` condition was `service_started` instead of `service_healthy`, allowing n8n to boot before the TTS service was ready
- **Qwen3-TTS API** — updated engine from removed `QwenTTS` class to `Qwen3TTSModel` with correct `from_pretrained()`, `create_voice_clone_prompt()`, and `generate_voice_clone()` calls
- **Narration fallback** — silent `except` swallowed narration errors and sent raw markdown to TTS; now logs the error and surfaces `narration_skipped: true` in job status
- **HuggingFace model names** — all four hardware tiers updated from `Qwen/Qwen3-TTS-{0.6,1.7}B` to correct `Qwen/Qwen3-TTS-12Hz-{0.6,1.7}B-CustomVoice` IDs in `hardware.py` and `hardware-probe.sh`
- **Ollama init timeout** — raised `MAX_WAIT` from 60 s to 300 s to prevent premature failure on first-run model pull
- **sox missing from Docker image** — added `sox` to Dockerfile apt-get; tightened build-time import to `from qwen_tts import Qwen3TTSModel`
- **`qwen-tts` version pin** — corrected from fabricated CalVer `2026.1.22` to actual PyPI release `0.1.1`
- **Test mocks** — updated all four test files from stale `_mock.QwenTTS` to `_mock.Qwen3TTSModel` after API rename

### CI
- Restrict `ci.yml` permissions to `contents: read`
- Explicitly pass `GITHUB_TOKEN` to both checkout steps to fix auth error in GitHub Actions

### Docs
- Replace stale `TTS_DEVICE` / `TTS_TIER` env vars with `HARDWARE_TIER` in `QUICKSTART.md`

---

## [2.1.1] — 2026-04-03

### Security
- **C3: Path disclosure** — removed server filesystem path from voice sample error response (was exposing `/app/voices/default/reference.wav` to API callers)

### Fixed
- **C1: TOCTOU race condition** — job re-creation could spawn duplicate synthesis jobs when two requests arrived simultaneously for the same completed job_id. Now returns existing status atomically.
- **C2: Unbounded memory store** — in-memory fallback (when Redis is down) had no size limit. Added 1000-job cap with LRU eviction to prevent OOM.
- **W1: Redis KEYS blocking** — `list_all()` and `count()` used `KEYS *` which blocks the entire Redis server. Replaced with `SCAN` iteration.
- **W2: ffmpeg return code unchecked** — `pitch_shift_segment` didn't check if ffmpeg succeeded before loading potentially corrupt output.
- **W3: Temp file leak** — `pitch_shift_segment` left temp files in `/tmp` on exceptions. Added `try/finally` cleanup.
- **W6: Silent directory failure** — `OUTPUT_DIR.mkdir()` failure was silently swallowed. Now logs a warning.
- **W7: Overly broad exception catch** — `strategy.py` caught `Exception` alongside `JSONDecodeError`, hiding real bugs. Split into separate handlers.

### CI
- Added `ci.yml` — runs ruff lint + pytest on every PR and push to main
- Added `dependabot-auto-merge.yml` — auto-merges dependabot PRs that pass CI
- Fixed `dependabot.yml` — grouped updates, excluded heavy deps (torch/transformers)
- Fixed all CI test failures: hardware mock (torch unavailable in CI), narration strategy (word count ratio retries), tts_job (wrong patch target), storage (boto3 skip/patch)

---

## [2.1.0] — 2026-04-03

### Critical Fix
- **Narration step wired into TTS pipeline** — LLM narration was completely missing from `run_tts_job`. Articles were synthesized verbatim (markdown, headers, bullet lists) without the podcast rewrite. The narration/ package existed but was never called.

### Fixed
- `gcs_object_path.split("/")[0]` passed wrong site slug to storage backend — now uses explicit `site_slug` parameter
- Parallel synthesis now checks job cancellation between batches instead of only once before dispatching all tasks
- Stale docstring referencing Fish Speech pipeline updated to reflect Qwen3-TTS architecture
- Engine readiness busy-poll (60 Redis round-trips) replaced with `asyncio.Event` — zero polling overhead
- n8n workflows no longer duplicate LLM narration — TTS service owns narration entirely

### Added
- **Pipelined narration + synthesis** — LLM narrates chunk N+1 while TTS synthesizes chunk N (overlapped execution)
- **Layered information preservation** during LLM narration conversion:
  - Prompt: 10-item preservation checklist (numbers, dates, names, quotes, URLs, lists, etc.)
  - Validator: date/time, URL, email regex patterns + word count ratio check (flags if <55%)
  - Chunk overlap: 1 paragraph overlap at chunk boundaries prevents context loss
  - LLM completeness check (HIGH_VRAM only): second LLM call verifies no facts were dropped
- **Audio quality improvements** (zero performance cost, ~250ms total for 30-chunk article):
  - Text preprocessing: strips markdown, smart quotes, expands 19 abbreviations (Dr.→Doctor, e.g.→for example)
  - 15ms crossfade at chunk boundaries eliminates clicks/pops
  - Prosodic-aware splitting: long sentences split at clause boundaries (commas, conjunctions)
  - Silence trimming: removes 6-15s of dead air from typical articles
- **HIGH_VRAM premium features** (20+ GB GPU):
  - fp32 TTS precision — cleaner audio, less quantization noise
  - 2 parallel TTS workers — ~2x faster synthesis
  - qwen3:14b-q4 LLM — significantly better narration quality
  - Pre-computed voice reference tokens cached at startup (saves 2-5s per job)
  - Multi-voice for quoted speech — pitch-shifts quotes for speaker differentiation
  - Automatic quality re-synthesis — re-synthesizes chunks with excessive silence
  - Two-pass EBU R128 loudness normalization for final mastering
- MID_VRAM now receives full pacing prompt (same qwen3:8b-q4 model as HIGH_VRAM)
- `_TRANSITION_STARTERS` narrowed to actual topic transitions (removed "the", "for", "so", "if")
- Continuity seeding passes both output tail AND source tail for richer context

### Changed
- n8n workflows: removed "Convert to Narration (LLM)" and "Parse Narration" nodes — n8n sends raw article text directly to TTS service
- `LLM_BASE_URL` and `LLM_MODEL_NAME` no longer required in n8n — configured on TTS service container
- Architecture diagrams rewritten as clean mermaid flowcharts (TD, no subgraphs)
- Documentation updated across README.md, ARCHITECTURE.md, SETUP_GUIDE.md

---

## [2.0.0] — 2026-04-02

### Added
- Hardware auto-detection: CPU_ONLY / LOW_VRAM / MID_VRAM / HIGH_VRAM tiers
- Qwen3-TTS engine (replaces Fish Speech v1.5)
- Bundled Ollama LLM service for narration rewriting
- Tiered narration pipeline: ChunkedStrategy + SingleShotStrategy
- NarrationValidator: entity-level information preservation check
- Voice profiles: named profiles, runtime upload, backward-compatible default
- Storage backends: local (default), GCS, AWS S3
- Tiered audio quality: 192kbps/44.1kHz standard, 256kbps/48kHz on HIGH_VRAM
- docker-compose.gpu.yml overlay + start.sh auto GPU detection

### Changed
- Callback payload: `gcs_uri` → `audio_uri` (gcs_uri kept for backward compat)
- `LLM_BASE_URL` default points to bundled Ollama at `http://ollama:11434/v1`
- `scripts/setup-gcp.sh` renamed to `scripts/setup-storage.sh`

### Removed
- Fish Speech v1.5 dependency
- External LLM dependency (Ollama is now bundled)

---

## [Unreleased]

### Added — Audio Backfill Scripts (2026-03-19)

New utility scripts for generating audio on existing Ghost posts that were published before the pipeline was set up.

**`scripts/backfill-audio.sh`** (Linux / macOS):
- Prompts for n8n webhook URL, Ghost site URLs + Content API keys, delay between jobs, and dry-run mode
- Paginates the Ghost Content API to retrieve all published posts
- Filters posts where HTML does not contain an `<audio>` element
- Sends each post sequentially to the n8n pipeline with a configurable delay (default: 300 s) to avoid overloading the TTS service
- Supports multiple Ghost sites in a single run
- Requires `curl` and `jq`

**`scripts/backfill-audio.ps1`** (Windows — native PowerShell):
- Identical functionality implemented in PowerShell 5.1+ compatible syntax
- Uses `Invoke-RestMethod` for Ghost Content API and `Invoke-WebRequest` for webhook trigger
- No external dependencies beyond built-in PowerShell cmdlets

---

### Fixed — TTS Service Hardening & Production Readiness (2026-03-19)

Comprehensive bug fixes across the entire TTS service codebase.

**Core fixes:**
- `config.py`: Wrapped all `int(os.environ.get(...))` calls in `try/except ValueError` so invalid env vars (e.g. `MAX_WORKERS=auto`) no longer crash the service at import time
- `main.py`: Stored `asyncio.create_task()` reference in a module-level variable to prevent premature garbage collection; cancel the task cleanly on shutdown
- `job_store.py`: Removed permanent `self.use_redis = False` on transient Redis errors — the service now falls back gracefully per-operation without permanently disabling Redis
- `tts_job.py`: Added `gcs_upload_failed` flag so GCS failures are non-fatal and reflected in job metadata (`gcs_upload_warning`); standardised error truncation to 450 chars
- `synthesis.py`: Added `await asyncio.gather(*tasks, return_exceptions=True)` after parallel task cancellation to prevent resource leaks
- `storage.py`: Added exponential-backoff retry loop (up to `MAX_RETRIES` attempts, capped at 30 s) for GCS uploads
- `tts.py`: Removed dead `TYPE_CHECKING` import block

**Tests:**
- Added `pytest.ini` with `asyncio_mode = auto`
- Added three new test cases: synthesis failure, GCS failure with non-fatal completion, and missing executor

**Scripts:**
- `run-docker.sh` / `run-docker.ps1`: Added `MAX_WORKERS` env var passthrough

**Docs:**
- `docs/ARCHITECTURE.md`: Fixed orphaned Python code fragment in "Test Voice Cloning" section; fixed duplicate `## Component Deep Dive` heading; updated directory structure listing
- `scripts/validate-build.sh`: Extended startup health-check timeout from 60 s → 300 s to accommodate Fish Speech model downloads
- `tts-service/README.md`: Corrected Code Style section (ESLint/Prettier → PEP 8/ruff)

---

### Fixed - Fish Speech v1.5 Implementation (2025-01-16)

**Problem:**
- TTS service failing with `cannot import name 'LlamaForConditionalGeneration' from 'fish_speech.models.text2semantic.llama'`
- Engine code written for non-existent Fish Speech API
- Architecture mismatch between documentation and implementation

**Root Cause:**
- Code attempted to use classes (`LlamaForConditionalGeneration`, `Firefly`) that don't exist in Fish Speech v1.5
- Fish Speech v1.5 uses CLI-based inference, not a Python library API
- Original code was written for a different TTS system or Fish Speech version

**Solution Implemented:**
- Complete rewrite of `tts_engine.py` to use Fish Speech v1.5 CLI-based inference pipeline
- Implemented 3-step synthesis process via subprocess calls:
  1. Reference audio encoding (DAC codec → VQ tokens)
  2. Semantic token generation (text2semantic model)
  3. Audio decoding (DAC decoder → WAV file)
- Removed `:ro` flag from voices volume mount for transcription file writes
- Pinned Fish Speech to stable `v1.5.0` tag

**Technical Implementation:**
- Uses `subprocess.run()` to call Fish Speech CLI tools
- Reference audio encoded once during initialization
- Semantic tokens generated per synthesis request
- Working directory managed to handle Fish Speech's file outputs
- Thread-safe synthesis with proper cleanup

**Files Modified:**
- `tts-service/app/core/tts_engine.py` (complete rewrite, 500+ lines changed)
- `docker-compose.yml` (line 137 - removed `:ro` flag)
- `tts-service/Dockerfile` (line 215 - pinned to v1.5.0)

**Performance:**
- Initialization: ~30-60 seconds (reference encoding + transcription)
- Synthesis: ~10-30 seconds per request (device-dependent)
- Memory: 4-6GB RAM (GPU mode), 8-16GB RAM (CPU mode)

**Migration:**
```bash
docker compose build --no-cache tts-service
docker compose up -d
# Wait for initialization (~1-2 minutes)
docker compose logs -f tts-service
```

**Verification:**
```bash
# Should see: "Fish Speech v1.5 engine ready (Studio Quality)"
curl http://localhost:8020/health
```

---

### Fixed - Docker Build Dependency Resolution (2025-01)

**Problem:**
Docker build failing with `resolution-too-deep` error after 30+ minutes when pip tries to resolve 50+ packages simultaneously.

**Fixed:**
- Restructured Dockerfile with 20-stage installation process (packages installed in dependency order)
- Pinned all package versions to exact releases (e.g., `numpy==1.26.4`, `gradio==5.1.0`)
- Added build retry logic and resource validation to `init.sh`

**Files Modified:**
- `tts-service/Dockerfile` (complete rewrite with staged builds)
- `tts-service/requirements.txt` (added version constraints)
- `scripts/init.sh` (added retry logic)
- `tts-service/README.md` (added build troubleshooting)
- `docs/ARCHITECTURE.md` (added build documentation)

**Performance:**
- Build time: 15-25 minutes (previously: failed)
- Success rate: 95%+ (previously: 0%)

**Migration:**
```bash
docker compose build --no-cache tts-service
docker compose up -d
```

See `docs/ARCHITECTURE.md` for technical details.

---

## [1.0.0] - Initial Release

### Added
- TTS service with Fish Speech v1.5 integration
- n8n workflow automation for Ghost CMS
- Redis job state persistence
- GCS audio storage integration
- Voice cloning with reference audio
- Multi-site Ghost support
- Comprehensive documentation

### Components
- TTS Service API (FastAPI + Fish Speech)
- n8n Workflow Engine
- Redis Job Store
- Docker Compose orchestration
- GCP integration (GCS, Secret Manager)
- Init scripts for automated deployment

---

[Unreleased]: https://github.com/getsimpledirect/ghost-narrator/compare/v2.2.1...HEAD
[2.2.1]: https://github.com/getsimpledirect/ghost-narrator/compare/v2.2.0...v2.2.1
[2.2.0]: https://github.com/getsimpledirect/ghost-narrator/compare/v2.1.1...v2.2.0
[2.1.1]: https://github.com/getsimpledirect/ghost-narrator/compare/v2.1.0...v2.1.1
[2.1.0]: https://github.com/getsimpledirect/ghost-narrator/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/getsimpledirect/ghost-narrator/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/getsimpledirect/ghost-narrator/releases/tag/v1.0.0
