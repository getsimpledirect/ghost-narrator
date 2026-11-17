<p align="center">
  <img src="assets/ghost-narrator-banner.png" alt="Ghost Narrator — Open Source AI Narration for Your Blog" width="100%">
</p>

# Ghost Narrator

Self-hosted AI narration for your blog, using Qwen3-TTS voice cloning and an optional narration LLM.

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://github.com/getsimpledirect/ghost-narrator/stargazers"><img src="https://img.shields.io/github/stars/getsimpledirect/ghost-narrator?style=flat" alt="GitHub Stars"></a>
  <a href="https://github.com/getsimpledirect/ghost-narrator/issues"><img src="https://img.shields.io/github/issues/getsimpledirect/ghost-narrator" alt="GitHub Issues"></a>
  <a href="https://github.com/getsimpledirect/ghost-narrator/commits/main"><img src="https://img.shields.io/github/last-commit/getsimpledirect/ghost-narrator" alt="Last Commit"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white" alt="Python 3.12"></a>
  <a href="https://docs.docker.com/compose/"><img src="https://img.shields.io/badge/docker-compose%20v2-2496ED?logo=docker&logoColor=white" alt="Docker"></a>
</p>

---

## Current operational status

This repository is source code, not evidence that a narrator host is currently deployed. Verify the VM, containers, volumes, model cache, storage objects and recent logs before relying on an old installation. The supported Docker image is CUDA/Linux based. CPU execution exists in the application and tier configuration, but the current Dockerfile is not a turnkey macOS/Apple-Silicon image and CPU speed must be measured on the intended machine.

For a reviewed one-article preview, call `/tts/generate` with `preserve_source_wording: true`. This skips the LLM rewrite and synthesizes the exact plain-text script supplied by the caller. Convert Markdown tables and links before submission, review the script and MP3, and publish separately. Source-preserving jobs require Whisper transcript checks. If a retry is acoustically acceptable but still exceeds the WER threshold, recovery continues through the remaining response-ladder strategies; missing ASR or exhaustion without a transcript-safe candidate fails the job. Loudness-consistency replacements use the same transcript gate. A private voice reference belongs at `tts-service/voices/default/reference.wav`; it is ignored by Git and must not be baked into an image.

Quality-gated generation is not a real-time path. A November 2026 L4 trial showed that best-of-three candidates and WER recovery can take minutes for one names-and-numbers segment. It also exposed two fixed edge cases: a short-tail merge could recombine a 78-word paragraph after splitting it, and Whisper needs long-form timestamps for audio beyond 30 seconds. Estimate from measured jobs on the intended image; do not use the old sub-minute examples as a budget.

Automatic Ghost/n8n publication is not trial-safe merely because the workflows import successfully. Keep it disabled until inbound webhooks and callbacks are authenticated, retries are idempotent, jobs are tied to an article revision, stale callbacks are rejected, exclusions are enforced, and `completed` requires a playable output. See [SECURITY.md](SECURITY.md).

---

## What It Does

Ghost Narrator has two modes:

**Auto-narration (Ghost CMS):** The included n8n workflows can turn a publish webhook into narration and a Ghost embed after the production-safety gates above are implemented and verified.

```
Ghost CMS (publish) → n8n (trigger) → TTS Service (narrate + synthesize) → Storage (MP3) → Ghost (embed player)
```

**Static / arbitrary text:** Send any plain text to the TTS service directly via its REST API or the bundled `static-content-audio-pipeline.json` n8n workflow — no Ghost required. Use for books, series content, landing pages, or any text you want narrated.

No cloud TTS API or per-character billing is required. Self-hosted compute, storage and networking can still incur hourly or monthly charges.

> **Read the full story:** [You Cannot Buy What Can Only Be Built](https://founderreality.com/blog/you-cannot-buy-what-can-only-be-built) — why we built this and how it works.

---

## Cost Comparison

| | ElevenLabs Scale | Ghost Narrator |
|---|---|---|
| Monthly cost | ~$330 | Hardware/electricity or hourly cloud compute |
| Per-character billing | Yes | No |
| Voice cloning | Yes | Yes (5-120s voice sample) |
| Data privacy | Cloud | Controlled by your selected host and storage |
| Latency | Fast | Measure on the selected host; the 2,717-word November 2026 L4 trial took about 2h10m for the job |
| Quality | Excellent | Good to excellent (depends on tier) |
| Effort to set up | Sign up | ~1 hour |

---

## What You Need

Ghost Narrator is a standalone project. It needs:

1. **A [Ghost](https://ghost.org/) blog** — the open-source publishing platform ([GitHub](https://github.com/TryGhost/Ghost))
2. **Docker** — with Docker Compose V2
3. **A voice sample** — 5-120 seconds WAV recording of your voice

The bundled LLM can handle narration rewriting — Ollama (CPU/low-VRAM) or vLLM (GPU). Qwen3-TTS handles voice synthesis. Source-preserving requests do not need the narration LLM.

---

## Hardware Tiers

Ghost Narrator auto-detects your hardware and selects the right models:

| Tier | VRAM | TTS Model | LLM Model | Output Quality | Key Features |
|---|---|---|---|---|---|
| CPU only | None | Qwen3-TTS-0.6B | qwen3.5:2b (Ollama) | 192kbps, 48kHz | Application tier exists; build and benchmark a compatible image first |
| Low | <12 GB | Qwen3-TTS-0.6B (fp32) | qwen3.5:4b (Ollama) | 192kbps, 48kHz | Compatible with all CUDA GPUs incl. older hardware |
| Mid | 12–18 GB | Qwen3-TTS-1.7B (fp16) | Qwen3.5-4B (vLLM fp8, 8K ctx) | 256kbps, 48kHz | Studio-segment pipeline (70w), best-of-3 per segment, neural enhancement |
| **High** | **18+ GB** | **Qwen3-TTS-1.7B (bf16)** | **Qwen3.5-9B (vLLM fp8, 64K ctx)** | **320kbps, 48kHz** | **Studio-segment pipeline (60w), best-of-3 per segment, DeepFilterNet enhancement, response ladder, voice caching, LLM completeness** |

Override with `HARDWARE_TIER=cpu_only` in `.env` if auto-detection fails.

---

## Architecture

```mermaid
flowchart TD
    G["📝 Ghost CMS"] -->|"webhook"| N["⚡ n8n\nTrigger & Embed"]
    N -->|"raw article text"| T["🎙️ TTS Service\nNarrate + Synthesize"]
    T -->|"LLM narration"| O["🧠 Ollama\ncpu / low VRAM"]
    T -->|"LLM narration"| V["⚡ vLLM\nmid / high VRAM"]
    O -->|"narration script"| T
    V -->|"narration script"| T
    T -->|"MP3"| S["💾 Storage\nlocal / GCS / S3"]
    T -->|"callback"| N
    N -->|"embed player"| G
    H["🔍 Hardware Probe"] -.->|"tier.env"| T
    H -.->|"tier.env"| O
    H -.->|"tier.env"| V
```

---

## Prerequisites

**Hardware:**
- NVIDIA/CUDA Linux is the current turnkey Docker path; an L4 falls in the high-VRAM tier
- CPU mode exists but requires a compatible image/runtime and a measured speed check
- 8GB+ RAM
- 100GB SSD recommended for a clean CUDA build, model layers and temporary audio (the November 2026 L4 trial used about 61GB after its first build)

**Software:**
- Docker with Docker Compose V2
- Git

**You also need:**
- A [Ghost](https://ghost.org/) blog ([open source](https://github.com/TryGhost/Ghost))
- A 5-120 second WAV recording of your voice (45+ seconds recommended)

---

## Quick Start

```bash
git clone https://github.com/getsimpledirect/ghost-narrator.git
cd ghost-narrator

# Interactive setup — configures .env, storage, voice sample, and starts services
./install.sh
```

**GPU users:** `install.sh` auto-detects your GPU and uses `docker-compose.gpu.yml`. To start manually with GPU: `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d`

After startup, import the n8n workflows:
1. Open `http://YOUR_VM_IP:5678` → log in
2. **Workflows → Import from File** → upload `n8n/workflows/ghost-audio-pipeline.json`
3. Repeat for `n8n/workflows/ghost-audio-callback.json`

Then configure your Ghost site to send webhooks to:
```
http://YOUR_VM_IP:5678/webhook/ghost-published
```

Verify everything is running:
```bash
curl http://localhost:8020/health/ready   # TTS engine ready
curl http://localhost:5678/healthz        # n8n healthy
```

Do not publish a first test automatically. Submit a private preview, verify the output file and review the full audio before enabling any Ghost write-back.

### Source-preserving preview

The caller must supply narration-ready plain text. The flag bypasses summarization and paraphrasing; it does not convert tables into spoken prose.

```json
{
  "text": "The exact approved spoken script.",
  "job_id": "article-slug-body-checksum",
  "site_slug": "founder-reality",
  "preserve_source_wording": true
}
```

### Bounded cloud trial

For a paid preview, keep the blast radius smaller than the article:

1. Pin the repository commit and verify the current CUDA image, voice file, model cache and free disk before submitting a job.
2. Use a Spot worker with a hard runtime limit, no service account/scopes, a localhost-only API and only Redis/TTS running. Keep n8n, callbacks, publication and backfill off.
3. Use `STOP` on preemption and a persistent disk while the trial is active. Save each accepted exact-text part outside the container volume, then verify it with `ffprobe` and a full decode before reuse.
4. Keep the high-tier 60-word segmentation policy. Oversized paragraphs may split at existing sentence boundaries, but a very short sentence should remain grouped when the combined unit is still safe.
5. A status is not success. Require the final non-empty MP3, a clean full decode, a recorded checksum and human review before publication.
6. Copy the evidence off the worker and delete the VM, disk and temporary snapshots. `STOP` is for preemption recovery, not recurring storage.

Never upload a private voice sample to a public audio bucket. If direct recovery is slow, mount the stopped disk read-only on a short-lived CPU rescue VM instead of restarting the GPU.

### Storage Options

**Local (default):** Audio files saved to Docker volume. No cloud account needed.

**Google Cloud Storage:** For production, select `gcs` during `./install.sh` or set `STORAGE_BACKEND=gcs` in `.env`.

**AWS S3:** Select `s3` during `./install.sh` or set `STORAGE_BACKEND=s3` in `.env`.

---

## Configuration

### Required

| Variable | Description |
|----------|-------------|
| `GHOST_SITE1_URL` | Your Ghost site URL |
| `GHOST_SITE1_ADMIN_API_KEY` | Ghost Admin API key (Settings → Integrations) |
| `GHOST_KEY_SITE1` | Ghost Content API key |
| `SERVER_EXTERNAL_IP` | VM's external IP for webhooks |
| `N8N_USER` / `N8N_PASSWORD` | n8n owner credentials — `N8N_USER` must be a valid email (e.g. `admin@localhost`) |
| `N8N_ENCRYPTION_KEY` | Run `openssl rand -hex 32` |

### Optional

| Variable | Description | Default |
|----------|-------------|---------|
| `HARDWARE_TIER` | Override auto-detection | *(auto)* |
| `VOICE_SAMPLE_REF_TEXT` | Transcription of your reference audio for higher-quality ICL cloning; leave blank for x-vector-only mode | *(empty)* |
| `STORAGE_BACKEND` | `local`, `gcs`, or `s3` | `local` |
| `GCS_BUCKET_NAME` | GCS bucket for audio | *(local if unset)* |
| `S3_BUCKET_NAME` | S3 bucket for audio | *(local if unset)* |
| `MAX_WORKERS` | Parallel workers (CPU mode) | `4` |
| `SINGLE_SHOT_SEGMENT_WORDS` | Words per studio segment — overrides the tier default (CPU 100 / LOW 80 / MID 70 / HIGH 60); clamped to 30-300 | *(tier default)* |
| `SINGLE_SHOT_OVERLAP_MS` | Overlap crossfade between segments (ms) | `500` |
| `GHOST_SITE2_URL` | Second Ghost site | *(single site)* |

See [`.env.example`](.env.example) for the full list.

### Using an External LLM Provider

By default Ghost Narrator uses a bundled LLM for narration — Ollama (cpu/low VRAM tiers) or vLLM (mid/high VRAM tiers). To use an external OpenAI-compatible API instead:

```env
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-your-api-key
LLM_MODEL_NAME=gpt-4o-mini
```

Set these in `.env` before running `docker compose up`.

### Auto-Generated Secrets

`install.sh` automatically generates the following credentials on first run — you do not need to set them manually:

| Variable | Purpose |
|----------|---------|
| `REDIS_PASSWORD` | Redis auth (port not exposed to host) |
| `N8N_ENCRYPTION_KEY` | n8n credential encryption |
| `N8N_GHOST_WEBHOOK_SECRET` | HMAC-SHA256 signature verification for Ghost webhooks |
| `TTS_API_KEY` | Bearer token required by the TTS service API |

Set the same `N8N_GHOST_WEBHOOK_SECRET` value in Ghost Admin → Settings → Integrations → Webhooks. All other secrets are internal and never need to leave your server.

### Redis Authentication (v2+)

Redis is password-protected by default and the port is no longer exposed to the host. The `install.sh` script automatically generates `REDIS_PASSWORD` in `.env`.

**Upgrading from a previous version:**
```bash
docker compose down
# Add REDIS_PASSWORD to .env (or re-run install.sh)
docker compose up -d
```

### Multi-Voice Profiles

The `/voices/upload` endpoint accepts a WAV file to register a named voice profile. Profiles are stored under `voices/<profile-name>/reference.wav`.

To use a non-default profile, set `voice_profile` in your TTS request:
```json
{ "text": "Hello", "voice_profile": "my-custom-voice" }
```

The default profile (`voices/default/`) is set up during `install.sh`.

### Disk Management (Local Storage)

When `STORAGE_BACKEND=local`, generated MP3 files are written to the `tts_output` Docker volume and are **not automatically deleted** when job metadata expires (24h Redis TTL).

To clean up files older than 7 days:
```bash
docker compose exec tts-service find /app/output -name "*.mp3" -mtime +7 -delete
```

GCS and S3 backends are not affected — audio lives in your bucket with its own lifecycle policy.

### LLM Override

Ghost Narrator bundles its own LLM for narration rewriting — no external API needed. The backend is selected by `install.sh` based on your hardware. To use an external OpenAI-compatible API instead, set `LLM_BASE_URL` in `.env`:

| Provider | `LLM_BASE_URL` | `LLM_MODEL_NAME` |
|----------|------------------|--------------------|
| Bundled Ollama (cpu / low VRAM) | `http://ollama:11434/v1` | *(auto from tier)* |
| Bundled vLLM (mid / high VRAM) | `http://vllm:8000/v1` | *(auto from tier)* |
| OpenAI API | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Any OpenAI-compatible API | `http://host.docker.internal:PORT/v1` | model name |

---

## Multi-Site Support

Ghost Narrator supports multiple Ghost sites. The workflow automatically detects which site a post belongs to by matching the webhook URL hostname against your configured `GHOST_SITE1_URL` and `GHOST_SITE2_URL`.

See the [n8n Setup Guide](n8n/SETUP_GUIDE.md) for adding more sites.

### Adding a Third Ghost Site

To add a third Ghost site beyond the default two:

1. Add env vars to `.env`:
   ```env
   GHOST_SITE3_URL=https://your-third-site.com
   GHOST_SITE3_ADMIN_API_KEY=your-admin-key
   ```

2. In `n8n/workflows/ghost-audio-pipeline.json`, find the site detection Code node and add a third branch.

3. In `n8n/workflows/ghost-audio-callback.json`, add the third case in `Extract API Keys`.

4. Re-import both updated workflow JSON files in the n8n UI.

The `siteSlug` convention: use `'site1'`, `'site2'`, `'site3'` to match the env var suffix.

### Production Deployment

For production deployment beyond local development:

1. **Firewall**: Restrict access to Docker network only — don't expose Redis (port 6379), Ollama (port 11434), or vLLM (port 8000) to host
2. **Reverse Proxy**: Use Traefik or nginx to expose only the TTS service (port 8020) and n8n (port 5678)
3. **SSL**: Terminate TLS at the reverse proxy, not in containers
4. **Monitoring**: The service exposes Prometheus metrics at `/metrics` — integrate with Grafana
5. **Backup**: Regularly backup the `n8n_data` and `tts_output` volumes

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| TTS health check times out | First run downloads models. Wait up to 5 min. |
| Webhooks don't trigger | Check `SERVER_EXTERNAL_IP` and firewall on port 5678. |
| Audio not embedded in Ghost | Verify Admin API key. Check: `docker compose logs n8n` |
| LLM errors (cpu/low VRAM) | Check: `docker compose logs ollama` |
| LLM errors (mid/high VRAM) | Check: `docker compose logs vllm` |
| GPU not detected | Run `nvidia-smi`. Set `HARDWARE_TIER=mid_vram` to override. |

```bash
# Health checks
curl http://localhost:8020/health       # TTS Service
curl http://localhost:5678/healthz      # n8n
curl http://localhost:11434/api/tags    # Ollama (cpu/low VRAM)
curl http://localhost:8000/health       # vLLM (mid/high VRAM)
```

---

## Licensing

Ghost Narrator's code is MIT licensed — do whatever you want with it.

**Qwen3-TTS (default TTS model)**
- Licensed under [Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0)
- Fully permissive — commercial use allowed
- Repo: [Qwen/Qwen3-TTS on Hugging Face](https://huggingface.co/Qwen/Qwen3-TTS)

**Qwen3.5 LLM (default narration model)**
- Licensed under [Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0)
- Fully permissive — commercial use allowed

**Target state:** MIT code + Apache 2.0 models = fully permissive end-to-end. No licensing asterisks.

You are responsible for complying with the licenses of the underlying models you choose to use.

---

## Documentation

- [Architecture Guide](docs/ARCHITECTURE.md) — full pipeline walkthrough including resilience & observability features
- [TTS Service Docs](tts-service/README.md) — API reference & standalone usage
- [TTS Quick Start](tts-service/QUICKSTART.md) — get TTS running in 5 minutes
- [n8n Setup Guide](n8n/SETUP_GUIDE.md) — workflow configuration
- [Contributing](CONTRIBUTING.md)
- [Security Policy](SECURITY.md)

---

## License

MIT License (code). See [Licensing](#licensing) for model license details.

---

## Support

- [GitHub Issues](https://github.com/getsimpledirect/ghost-narrator/issues)
- [GitHub Discussions](https://github.com/getsimpledirect/ghost-narrator/discussions)

---

Built by [SimpleDirect](https://getsimpledirect.com)
