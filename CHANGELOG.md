# CHANGELOG


## v2.4.1 (2026-04-12)


## v2.4.0 (2026-04-12)

### Bug Fixes

- **ci**: Improve VERSION sync and release notes formatting
  ([`df4ff81`](https://github.com/getsimpledirect/ghost-narrator/commit/df4ff816b6467694a9044788fc3318b18e692f7d))

- **infra**: Raise LLM timeouts to 300/360s and tts-service memory to 12G
  ([`beab4a8`](https://github.com/getsimpledirect/ghost-narrator/commit/beab4a8879a2cc2e94a4b4f1028e80cda90156fc))

qwen3:8b narrates a 2500-word chunk in 30-60s; the previous 120s default left no margin when Ollama
  served multiple concurrent jobs. 300s gives 5x headroom. tts-service memory limit raised from 8G
  to 12G in the GPU compose: two concurrent jobs load WAV buffers and PyTorch CUDA contexts
  simultaneously, pushing usage well above 8G and risking silent OOM kills that restart the
  container mid-job. LLM_COMPLETENESS_TIMEOUT raised from 180s to 360s proportionally. Defaults in
  config.py updated to match so local dev without Docker inherits the safer values.

- **n8n**: Correct mojibake in Ghost Audio Pipeline workflow name (Ghost Article → Audio Pipeline)
  ([`2386de1`](https://github.com/getsimpledirect/ghost-narrator/commit/2386de1928092a0592c126f9e4c8358677529977))

- **narration**: Remove number/date entity checks from validator
  ([`f0959b2`](https://github.com/getsimpledirect/ghost-narrator/commit/f0959b2462243fbbd8b572e1dd66829f20c6d8e5))

The narration prompt instructs the LLM to convert numbers to spoken form ('$1.2B' -> 'one point two
  billion dollars', 'Q3 2024' -> 'the third quarter of twenty-twenty-four'). _NUMBER_RE and _DATE_RE
  then flagged these correctly-converted forms as missing, triggering a spurious retry LLM call on
  every narration chunk in any finance article. Removing these checks eliminates the false
  positives. Proper noun and direct quote checks are retained; MIN_WORD_RATIO=0.55 catches major
  content drops.

- **tts-service**: Bound GPU hold time and close retry coverage gaps
  ([`232dfcf`](https://github.com/getsimpledirect/ghost-narrator/commit/232dfcf0786c9797812c14a9c794b32565366cde))

Four reliability gaps identified in post-deploy code review:

- Job timeout: without a wall-clock limit on the GPU semaphore, a CUDA driver stall, OOM recovery,
  or model deadlock would block all subsequent jobs indefinitely with no recovery path short of a
  manual service restart. asyncio.timeout(MAX_JOB_DURATION_SECONDS, default 7200s) now wraps Steps
  1-5 so the semaphore is always released and the job marked failed cleanly.

- TimeoutError excluded from retry: retry_with_backoff(exceptions=(Exception,)) was silently
  retrying asyncio.TimeoutError, meaning a genuine Ollama overload burned 3 × 300s before surfacing
  the failure. A new exclude parameter prevents timeout errors from being retried uselessly.

- Single-shot narration lacked retry: the MID_VRAM single-shot path called _call_llm directly,
  unlike every other narration call site. A transient connection reset would fail the entire article
  with no recovery attempt.

- Misleading job status: status jumped to processing before the semaphore was acquired, making
  queued jobs indistinguishable from actively running ones in monitoring and n8n callbacks. Status
  now progresses queued → processing the moment the GPU slot is granted.

- **tts-service**: Serialize GPU pipeline with asyncio semaphore
  ([`21197f7`](https://github.com/getsimpledirect/ghost-narrator/commit/21197f74398df9bcb99d874c56a178822df9a79f))

Concurrent jobs were fighting _synthesis_lock at the chunk level, giving each job ~50% GPU
  throughput. Simultaneously their LLM narration requests queued in Ollama, pushing wait times past
  LLM_TIMEOUT and triggering cascading retry storms. Adding a process-wide Semaphore(1) serializes
  the narration+synthesis pipeline so jobs queue cleanly. Non-GPU steps (upload, cleanup, webhook)
  run outside the semaphore so the GPU slot is released the moment the MP3 is ready.

### Chores

- Bump VERSION to 2.3.15
  ([`5755e0b`](https://github.com/getsimpledirect/ghost-narrator/commit/5755e0b18163cd8a02c57cf389c0db65153d9ef4))

- **ghost-narrator**: Bump VERSION to 2.3.15 to reflect latest changes; include pending README tweak
  ([`b18ebf8`](https://github.com/getsimpledirect/ghost-narrator/commit/b18ebf8d6e98cbf258af0aab34be5a64f7aab4a4))

- **tts-service**: Add MIT license header to all Python source files
  ([#69](https://github.com/getsimpledirect/ghost-narrator/pull/69),
  [`30ca49d`](https://github.com/getsimpledirect/ghost-narrator/commit/30ca49d58397313237fe9dec0ff1a571288ff28f))

* chore(tts-service): add MIT license header to all Python source files

- 54 files in app/ and tests/ were missing the standard MIT license header that the rest of the
  codebase carries — adds it uniformly so every file is correctly attributed before open-sourcing

* chore(tts-service): add MIT headers to shell scripts and fix residual lint

- Add MIT license header to install.sh, hardware-probe.sh, ollama-init.sh - Add MIT license header
  to tests/conftest.py - Remove leftover inline qwen_tts mock blocks in test_narration_strategy,
  test_narration_validator, test_voices — conftest.py pytest_configure handles the stub
  session-wide, making per-file patching redundant - Drop unused variables (span, boto3, result)
  flagged by ruff F841/F401

### Documentation

- Document concurrent job serialization and dynamic Ollama config
  ([`aba9539`](https://github.com/getsimpledirect/ghost-narrator/commit/aba9539227a33f1ab0afc183b6d2d70261be65d5))

- Update HIGH_VRAM LLM reference from qwen3:14b to qwen3:8b
  ([`8179b50`](https://github.com/getsimpledirect/ghost-narrator/commit/8179b50b608795535f2a6fd03bf012c2e6cd78cb))

The hardware doc commit (2fdcb3a) updated the tier config and tests but left the README hardware
  table and ARCHITECTURE.md feature list still showing qwen3:14b. Both docs now reflect the actual
  deployed model.

- **CHANGELOG**: Add note clarifying current codebase state is v2.3.15
  ([`32b295c`](https://github.com/getsimpledirect/ghost-narrator/commit/32b295c9497614841dc6efc5ab3e2484ebab449d))

- **CHANGELOG**: Remove accidental v2.3.15 note added during audit; keep changelog clean
  ([`588a832`](https://github.com/getsimpledirect/ghost-narrator/commit/588a832fd8e10b30e8a86e5966b4382eecafd3b8))

### Features

- **hardware**: Compute OLLAMA_NUM_PARALLEL from actual free VRAM
  ([`2261dab`](https://github.com/getsimpledirect/ghost-narrator/commit/2261dabb7c10fe61f2b35477fecc9973b200ed9d))

Previously OLLAMA_NUM_PARALLEL was unset (defaulting to 1), so Ollama queued concurrent LLM
  narration requests serially. With two jobs each needing 3 narration chunks at 60-90s each, queued
  requests regularly exceeded LLM_TIMEOUT=120s, triggering 3-attempt retry storms per chunk.

Now hardware-probe.sh computes the value at startup: floor((vram - llm_size - tts_size - safety) /
  kv_per_slot), capped at 4

The cap of 4 reflects realistic concurrent job submission — Ollama pre-allocates all KV cache slots
  at startup so a higher value wastes VRAM permanently regardless of actual in-flight requests.

OLLAMA_FLASH_ATTENTION=1 is also set on GPU tiers; the L4 (Ampere) gains 20-40% lower per-token
  latency from flash attention.

high_vram LLM changed from qwen3:14b to qwen3:8b to match hardware.py.

- **tts-service**: Spoken-form validation for numeric/date entities
  ([`ddc77d3`](https://github.com/getsimpledirect/ghost-narrator/commit/ddc77d31ee0e87f8758e54d232118d27a2ddee69))

Restore number and date entity checking in NarrationValidator with spoken-form equivalents generated
  by num2words, replacing the naive literal-string match that caused false positives on every
  finance chunk.

_to_spoken_forms() maps source literals to all acceptable spoken forms: 47% → forty-seven percent
  \$2.3B → two point three billion dollars Q3 2024 → third quarter / the third quarter FY2024 →
  fiscal year twenty twenty-four 2024 → twenty twenty-four

validate() now checks any(form in narration for form in spoken_forms) so correctly-converted
  narration passes while completely dropped entities still trigger a retry.

Adds num2words>=0.5.13 as a runtime dependency (already satisfied in the existing Python env at
  0.5.14).

### Performance Improvements

- **hardware**: Downsize HIGH_VRAM LLM to qwen3:8b, cap max_new_tokens to 3000
  ([`2fdcb3a`](https://github.com/getsimpledirect/ghost-narrator/commit/2fdcb3a4e510885bf0837f468ec05f6e0631da17))

qwen3:14b consumed ~8.5 GB VRAM for a narration task that is pure format conversion — qwen3:8b
  delivers equivalent output at ~4.5 GB, freeing 4 GB headroom on the L4. tts_max_new_tokens reduced
  from 8000 to 3000 across HIGH and MID tiers: a 250-word TTS chunk produces ~1384 codec tokens at
  12 Hz, making 3000 a safe 2.2x ceiling that prevents runaway synthesis loops from running for 11+
  minutes before the quality check catches them.


## v2.3.15 (2026-04-10)

### Refactoring

- **tts-service**: Restructure tests/ to mirror app/ domain layout
  ([#68](https://github.com/getsimpledirect/ghost-narrator/pull/68),
  [`0659c1b`](https://github.com/getsimpledirect/ghost-narrator/commit/0659c1b6699f6757926d7e9ac2c57e6337be18a9))

- moved all 22 test files into subdirectories matching app/ structure: tests/api/, tests/core/,
  tests/domains/{job,narration,synthesis,storage,voices}/ - added __init__.py to every subdirectory
  so pytest treats them as packages, preventing import shadowing across subdirectories - added
  tests/conftest.py with pytest_configure() to stub out qwen_tts before any test module is imported
  — removes the duplicated 4-line mock block that was copy-pasted into every file needing app
  imports - removed now-redundant inline qwen_tts mock blocks from the 4 files that had them;
  cleaned up stale path comments and import ordering


## v2.3.14 (2026-04-10)

### Bug Fixes

- **tts-service**: Fix audio quality, pipelining deadlock, and docs
  ([`2673f00`](https://github.com/getsimpledirect/ghost-narrator/commit/2673f00a520d906423eb28b5dae27050eccc2e85))

- temperature 0.9→0.72, top_p 1.0→0.92 across all tiers: sharpens sampling distribution to eliminate
  robotic voice and prosodic instability (pitch/speed variation between synthesis calls) - chunk
  word limits increased per tier (175/175/225/250): fewer synthesis resets = smoother prosody
  continuity at audio joins - crossfade 15 ms→60 ms: audible fade-in masks prosodic resets at chunk
  boundaries instead of just suppressing clicks - HIGH_VRAM: fp32→bf16 for 1.5–2x faster synthesis
  on Tensor Core GPUs; quality difference is imperceptible at 1.7B params - HIGH_VRAM:
  synthesis_workers 2→1; _synthesis_lock serialises all TTS calls so the second worker was a no-op
  adding overhead - pipelining deadlock fix: consumer failure with full queue (maxsize=2) blocked
  producer's put(None) in finally; fix drains queue via get_nowait() to wake the putter, then yields
  with sleep(0) before awaiting the producer task - narration prompt: added DO NOT INCLUDE section
  for URLs, emails, image captions, markdown; rewrote emphasis instruction to use sentence-position
  guidance (bold/CAPS markup was appearing in output) - validator: removed URL/email entity checks —
  prompt now replaces them with spoken descriptions so their absence is correct - ARCHITECTURE.md:
  fp32→bf16, 2 workers→1, 15 ms→60 ms crossfade, VRAM budget table corrected


## v2.3.13 (2026-04-10)

### Bug Fixes

- **tts-service**: Guard cancel_job call to active jobs only
  ([`ce9ab65`](https://github.com/getsimpledirect/ghost-narrator/commit/ce9ab65c72db7f64123eeb86a8e340d033106c41))

- Moved the root cause fix to delete_job: only call cancel_job() when the job status is
  pending/processing; completed/failed jobs have already self-cleaned the signal via
  synthesize_to_file's finally block - Unconditionally calling cancel_job() on every delete left a
  stale signal in _cancelled_jobs, causing the first synthesis chunk of a reused job_id to be
  silently aborted (pipelined path fell back to sequential) - Removed clear_cancel() from TTSEngine
  and its call site in tts_job.py — defensive workaround is unnecessary once the call site is
  correct


## v2.3.12 (2026-04-10)

### Bug Fixes

- **tts-service**: Clear stale cancel signal before new synthesis run
  ([`352cae5`](https://github.com/getsimpledirect/ghost-narrator/commit/352cae5a82d52e56b568a203760461dee8ef8111))

- Added `clear_cancel(job_id)` to TTSEngine to discard any leftover entry in `_cancelled_jobs`
  before a new run starts - `cancel_job()` intentionally persists the signal so an in-flight
  synthesis can be aborted; the signal must be cleared at the start of the next run, not at deletion
  time - Without this fix, reusing a job_id after deletion caused the pipelined narration path to
  raise SynthesisError immediately, falling back silently to sequential synthesis - Called
  `engine.clear_cancel(job_id)` in `tts_job.py` immediately after engine readiness check, before
  synthesis begins


## v2.3.11 (2026-04-09)

### Bug Fixes

- **gcs**: Change key file permissions to 644
  ([`99f4907`](https://github.com/getsimpledirect/ghost-narrator/commit/99f49079b32b6d30a025a70598486c69042b884d))

- chmod 640 assumed container user is in the file's owning group, but appuser (UID 1000) and the
  host user (UID 1001, GID 1002) share no group membership. World-readable (644) is correct here
  since the file is protected by directory permissions and mounted read-only.


## v2.3.10 (2026-04-09)

### Bug Fixes

- **gcs,logs**: Fix GCS key permissions and suppress health check noise
  ([`fd7bdca`](https://github.com/getsimpledirect/ghost-narrator/commit/fd7bdcafa27226129fdd78dcbc97e3a4f6218cec))

- GCS upload failed with Permission denied because chmod 600 on the service account key blocks the
  container's appuser (UID 1000) from reading a file owned by the host user. Changed to chmod 640. -
  Docker healthcheck polls /health every 30s, flooding the uvicorn access log and burying real
  traffic. uvicorn.access is a separate child logger that needs its own filter — added one to drop
  /health.


## v2.3.9 (2026-04-09)

### Bug Fixes

- **n8n**: Add TTS auth header to static content workflow
  ([`0274a42`](https://github.com/getsimpledirect/ghost-narrator/commit/0274a42ccdab3d3df2d4d2fd7f890a1a694b74e8))

The static-content-audio-pipeline was missing the Authorization header on its Submit TTS Job node
  entirely. Applied the same fix as the main pipeline: read TTS_API_KEY in the Validate & Extract
  Input Code node and pass the assembled Bearer token via $json.ttsAuthHeader.


## v2.3.8 (2026-04-09)

### Bug Fixes

- **n8n**: Resolve Authorization header not sent to TTS service
  ([`245f62d`](https://github.com/getsimpledirect/ghost-narrator/commit/245f62d6e9f0b103782284ce00d6eaf902f73aee))

n8n HTTP Request v4.2 does not reliably evaluate $env references inside headerParameters values. The
  Authorization header was being sent empty, causing the TTS service to return 401.

Moved the API key read into the Prepare Article Text Code node, where $env access is guaranteed. The
  Submit TTS Job header now reads the pre-assembled Bearer token from $json.ttsAuthHeader instead.

### Chores

- **n8n**: Bump n8n from 1.93.0 to 1.123.30
  ([`c18f888`](https://github.com/getsimpledirect/ghost-narrator/commit/c18f88804766bfe84e0d413e24ee5c0bfe45f22a))

Critical security update flagged in the n8n UI. No breaking changes in this range affect the
  webhook, HTTP Request, or Code nodes used by the Ghost audio pipeline workflows.


## v2.3.7 (2026-04-09)

### Bug Fixes

- **install**: Auto-generate TTS_API_KEY and wire it end-to-end
  ([#64](https://github.com/getsimpledirect/ghost-narrator/pull/64),
  [`1f5395e`](https://github.com/getsimpledirect/ghost-narrator/commit/1f5395ee1fc5892416453dfdfd5c155667e747b8))

The container aborted at startup with "TTS_API_KEY must be set" because install.sh never generated
  the key and docker-compose.yml never passed it to n8n. The full auth chain was broken at every
  link.

Three fixes: - install.sh generates TTS_API_KEY on first run, same pattern as REDIS_PASSWORD and
  N8N_ENCRYPTION_KEY - docker-compose.yml passes TTS_API_KEY to the n8n container so workflows can
  read it via $env.TTS_API_KEY - Submit TTS Job node now sends Authorization: Bearer on every
  request

Also updates SECURITY.md to reflect reality (TTS service does have API key auth since PR #62) and
  adds an auto-generated secrets table to README.md so users know what install.sh handles for them.


## v2.3.6 (2026-04-09)

### Bug Fixes

- **release**: Trigger version bump for PRs #62 and #63
  ([`eb26d00`](https://github.com/getsimpledirect/ghost-narrator/commit/eb26d003e3cf9de1d046ecf1b552d41772650685))

PRs #62 (gap-remediation) and #63 (code-review-gaps) were squash-merged with non-conventional PR
  titles, so python-semantic-release found no releasable commits and skipped the version bump both
  times.


## v2.3.5 (2026-04-08)

### Bug Fixes

- **tts-engine**: Move cancellation check inside try so finally always clears cancelled_jobs
  ([#61](https://github.com/getsimpledirect/ghost-narrator/pull/61),
  [`e1547ea`](https://github.com/getsimpledirect/ghost-narrator/commit/e1547eab874f5cb45d9ce5019c3619ac371d52e0))

Cancellation check was before the try block, so when it raised SynthesisError the finally clause
  never ran and the job_id stayed in _cancelled_jobs forever. Resubmitting the same job_id after a
  DELETE would always fail on the next run.


## v2.3.4 (2026-04-08)

### Bug Fixes

- **install**: Chmod 644 GCS service account key after creation
  ([#60](https://github.com/getsimpledirect/ghost-narrator/pull/60),
  [`3c5105e`](https://github.com/getsimpledirect/ghost-narrator/commit/3c5105eabd0f2c4ea42d6c2ad92c3e4a727bf0dc))

gcloud creates the key with 600 (owner-only), which the container process cannot read through the
  :ro bind mount. Set 644 immediately after key creation so Docker can read it without manual
  intervention.


## v2.3.3 (2026-04-08)

### Bug Fixes

- **install**: Uncomment GCS/S3 vars correctly + add missing prefix prompts
  ([#59](https://github.com/getsimpledirect/ghost-narrator/pull/59),
  [`cf770fc`](https://github.com/getsimpledirect/ghost-narrator/commit/cf770fcf29b31296dbce44e176883ebf2cd2d8d2))

sed patterns without ^#? prefix silently fail on commented-out lines in .env.example, leaving
  GCS_BUCKET_NAME/S3_BUCKET_NAME still commented even after setup. Fixed all GCS and S3 sed calls to
  handle both commented and uncommented forms.

Added prompts for GCS_AUDIO_PREFIX and S3_AUDIO_PREFIX (default: audio/articles). Added prompts for
  AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY so S3 setup is fully self-contained without requiring
  manual .env edits.


## v2.3.2 (2026-04-08)

### Bug Fixes

- **installer**: Prompt for all env vars + fix run-docker.sh gaps
  ([#58](https://github.com/getsimpledirect/ghost-narrator/pull/58),
  [`b71fae7`](https://github.com/getsimpledirect/ghost-narrator/commit/b71fae7c7350a9a125ad3ee2043b949ff2e86e7c))

install.sh: added prompts for TIMEZONE, second Ghost site credentials, HARDWARE_TIER override, and
  VOICE_SAMPLE_REF_TEXT (uses awk to safely handle arbitrary text). Added VOICE_SAMPLE_REF_TEXT to
  .env.example.

run-docker.sh: fix TTS_LANGUAGE default en→auto, add HARDWARE_TIER and REDIS_URL to container env,
  warn when Redis is unreachable, update help text with missing vars and note about full-stack
  docker compose.


## v2.3.1 (2026-04-08)

### Bug Fixes

- **tts-service**: Fix spurious LUFS warnings and GCS bucket name guard
  ([#57](https://github.com/getsimpledirect/ghost-narrator/pull/57),
  [`050a99a`](https://github.com/getsimpledirect/ghost-narrator/commit/050a99a020f6a2bed53d67562d1fe127e18cca5c))

quality.py: ebur128 emits per-frame measurement lines during analysis, each showing transient
  loudness values like -70 LUFS. Only the final summary line is meaningful — collect last matched
  value and log once.

gcs.py: GCS_BUCKET_NAME='' caused cryptic IndexError inside the google-cloud-storage library. Added
  early guard with clear error message.


## v2.3.0 (2026-04-08)

### Features

- **tts-service**: Per-tier TTS generation params + Redis config API
  ([#56](https://github.com/getsimpledirect/ghost-narrator/pull/56),
  [`1a4a4d4`](https://github.com/getsimpledirect/ghost-narrator/commit/1a4a4d415edf982e8ee63437efa1cf25d8bb93f4))

Add runtime-configurable TTS generation parameters with hardware-tier defaults and a Redis-backed
  API for overrides.

Generation params (temperature, repetition_penalty, top_k, top_p, temperature_sub_talker,
  top_k_sub_talker, do_sample_sub_talker, max_new_tokens) added to EngineConfig with conservative
  defaults on CPU tiers and standard Qwen3-TTS defaults on GPU tiers.

New tts_config/store.py persists user overrides in Redis with no TTL so config survives container
  restarts. Falls back to tier defaults when Redis is unavailable.

New GET/PUT/DELETE /tts/config/generation endpoints let users read and update generation params at
  runtime without a restart. Overrides are merged on top of tier defaults per job.

generation_kwargs threaded through the full pipeline: tts_job -> synthesize_chunks_auto ->
  synthesize_chunk -> tts_engine.synthesize_to_file -> generate_voice_clone(**kwargs)

quality_check re-synthesis uses functools.partial to bind generation_kwargs as a keyword arg since
  run_in_executor only accepts positional arguments.

Also fixes VoiceClonePromptItem passed to wrong parameter: ref_audio=prompt ->
  voice_clone_prompt=prompt

Fixes cancelled job_id reuse: cancellation check moved inside try/finally so
  _cancelled_jobs.discard() always runs.

Test mocks updated for new synthesize_chunk signature.


## v2.2.8 (2026-04-08)

### Bug Fixes

- **tts-engine**: Move cancellation check inside try so finally always clears cancelled_jobs
  ([#55](https://github.com/getsimpledirect/ghost-narrator/pull/55),
  [`46e8efd`](https://github.com/getsimpledirect/ghost-narrator/commit/46e8efd43e1c848877c4ea00592070d4f39ad8d5))

Cancellation check was before the try block, so when it raised SynthesisError the finally clause
  never ran and the job_id stayed in _cancelled_jobs forever. Resubmitting the same job_id after a
  DELETE would always fail on the next run.


## v2.2.7 (2026-04-08)

### Bug Fixes

- **tts-service**: Correct TTS_LANGUAGE default and LLM_MODEL_NAME empty-string guard
  ([#53](https://github.com/getsimpledirect/ghost-narrator/pull/53),
  [`bb5019a`](https://github.com/getsimpledirect/ghost-narrator/commit/bb5019a74675bb4a865007f6a9874373c3c9f59e))

- TTS_LANGUAGE default was 'en' but Qwen3-TTS requires full names (english, chinese, etc.) or
  'auto'; changed default to 'auto' so language is detected from text, making the pipeline
  language-agnostic - LLM_MODEL_NAME read from env with os.environ.get() which returns '' when the
  key exists but is blank (as shipped in .env.example); added .strip() or guard so blank env var
  falls back to hardware-tier model, consistent with the same pattern in hardware.py


## v2.2.6 (2026-04-08)

### Refactoring

- Replace gcs_path with storage_path and remove hardcoded buckets
  ([#52](https://github.com/getsimpledirect/ghost-narrator/pull/52),
  [`1125ed2`](https://github.com/getsimpledirect/ghost-narrator/commit/1125ed230f1e9e127a43c5105c7e565f5be4f227))


## v2.2.5 (2026-04-08)

### Bug Fixes

- Tts engine voice clone crash + script bugs across install/backfill/run-docker
  ([#51](https://github.com/getsimpledirect/ghost-narrator/pull/51),
  [`5bdbfbb`](https://github.com/getsimpledirect/ghost-narrator/commit/5bdbfbba97306907a00b77f8ef993b2db9d8ceab))

TTS engine (critical): - tts_engine.py: create_voice_clone_prompt called with ref_text='' which
  crashes Qwen3-TTS ICL mode: 'ref_text is required when x_vector_only_mode=False' Fix: add
  VOICE_SAMPLE_REF_TEXT config — when set uses ICL mode (higher quality), when empty (default)
  automatically switches to x_vector_only_mode=True - config.py: expose VOICE_SAMPLE_REF_TEXT env
  var - docker-compose.yml: pass VOICE_SAMPLE_REF_TEXT to tts-service container

install.sh: - n8n owner prompt defaulted to 'admin' (not a valid email for n8n v1.x
  N8N_OWNER_EMAIL); changed to 'admin@localhost' and updated prompt label - document
  VOICE_SAMPLE_REF_TEXT in post-install info block

hardware-probe.sh: - guard against empty VRAM_MIB when nvidia-smi returns no output; arithmetic
  comparison would fail in sh — now falls back to cpu_only

backfill-audio.sh: - replace hardcoded /tmp/ghost-backfill-poll.tmp with mktemp per-run temp file;
  concurrent runs would clobber each other

run-docker.sh: - STORAGE_BACKEND never passed to container — GCS/S3 config was silently ignored even
  when GCS_BUCKET_NAME was set - pass VOICE_SAMPLE_REF_TEXT to container when set in environment

Docs: update tts-service/README.md, README.md, and ARCHITECTURE.md to document VOICE_SAMPLE_REF_TEXT
  and the two voice cloning modes.


## v2.2.4 (2026-04-07)

### Bug Fixes

- **ollama**: Use valid Ollama model tags for all hardware tiers
  ([#47](https://github.com/getsimpledirect/ghost-narrator/pull/47),
  [`cf466ea`](https://github.com/getsimpledirect/ghost-narrator/commit/cf466ea21a9a8e666e6f662f05bed806f57995da))

The qwen3:Xb-q4 tag format does not exist in the Ollama registry — "pull model manifest: file does
  not exist" caused the init script to exit, the container to restart-loop, and all dependent
  services to never start.

Ollama's default pull for qwen3:Xb already uses Q4_K_M quantization internally, so the bare tag
  (qwen3:4b, qwen3:8b, qwen3:14b) is both valid and appropriately quantized for each VRAM tier.

Fixes hardware-probe.sh (tier.env written for ollama-init.sh) and hardware.py (LLM_MODEL_NAME
  default for tts-service / n8n).

### Documentation

- Fix hardware tier tables — correct model tags and VRAM thresholds
  ([#48](https://github.com/getsimpledirect/ghost-narrator/pull/48),
  [`7caef06`](https://github.com/getsimpledirect/ghost-narrator/commit/7caef068a26c4af1d5e9ef70cf63f0927a5d5099))

Model tags qwen3:Xb-q4 never existed in the Ollama registry. Updated to the valid bare tags
  (qwen3:4b, qwen3:8b, qwen3:14b) which Ollama pulls with Q4_K_M quantization by default.

Also align VRAM thresholds with hardware-probe.sh (< 10 GiB = low, 10–18 GiB = mid, ≥ 18 GiB =
  high). README had <9/<9–18, ARCHITECTURE.md had 4–8/10–16/20+ — neither matched the actual code
  thresholds.


## v2.2.3 (2026-04-07)

### Bug Fixes

- **ollama**: Replace curl with ollama list in healthcheck
  ([#46](https://github.com/getsimpledirect/ghost-narrator/pull/46),
  [`681a598`](https://github.com/getsimpledirect/ghost-narrator/commit/681a598868629e6e071a914f3e61858fe37704b3))

curl is not present in the ollama/ollama image, so the Docker healthcheck was always failing
  immediately, causing dependent services (n8n, tts-service) to never start.

PR #40 fixed the same issue in ollama-init.sh but missed the compose healthcheck definition.


## v2.2.2 (2026-04-07)

### Bug Fixes

- **tts**: Add flash-attn via multi-stage Docker build
  ([#45](https://github.com/getsimpledirect/ghost-narrator/pull/45),
  [`bf79418`](https://github.com/getsimpledirect/ghost-narrator/commit/bf79418e1bc27bc7c53bdbefbc321d91765321b8))

flash-attn requires nvcc (CUDA compiler) which the runtime base image does not ship. Add a devel
  builder stage that compiles the wheel against the matching torch version (ABI-compatible via
  --no-build-isolation), then copy only the resulting .whl into the final runtime stage.

This eliminates the startup warning: "flash-attn is not installed. Will only run the manual PyTorch
  version."

- **tts**: Revert voices volume to bind mount
  ([#44](https://github.com/getsimpledirect/ghost-narrator/pull/44),
  [`de8773b`](https://github.com/getsimpledirect/ghost-narrator/commit/de8773be45f485c4fe74df313969890a276efd24))

Switching from named volume (voices_data) back to bind mount (./tts-service/voices:/app/voices) so
  that the reference.wav placed by install.sh is visible to the container at startup.

Named volume starts empty, which causes the engine to skip voice prompt pre-caching and log a
  warning on every restart. Bind mount directly exposes the host directory where install.sh deposits
  the voice sample.


## v2.2.1 (2026-04-07)

### Bug Fixes

- **hardware-probe**: Use nvidia/cuda base image for GPU tier detection
  ([#43](https://github.com/getsimpledirect/ghost-narrator/pull/43),
  [`7ba6bda`](https://github.com/getsimpledirect/ghost-narrator/commit/7ba6bdaa666b45cdb3d237ac2d4037dd0ec86440))

The GPU overlay was bind-mounting /usr/bin/nvidia-smi from the host into an alpine:3.19 container.
  While the binary was present, alpine lacks the NVIDIA driver userspace libraries (libnvidia-ml.so)
  that nvidia-smi needs to query GPU VRAM. Result: hardware-probe reported cpu_only on every GPU
  machine, cascading into wrong model selection for ollama and a crash-loop.

Switch to nvidia/cuda:12.4.0-base-ubuntu22.04, which ships the required driver libs and is properly
  recognised by the NVIDIA container runtime. Drop the nvidia-smi bind mount — no longer needed.


## v2.2.0 (2026-04-07)

### Bug Fixes

- Correct ollama timeout and stale HuggingFace model names
  ([`4da7191`](https://github.com/getsimpledirect/ghost-narrator/commit/4da719171b63c514b36db238b402bcd054b36162))

ollama-init.sh MAX_WAIT was 60s — too short under Rosetta emulation and on slow pull/startup paths.
  Raised to 300s to match the healthcheck start_period. Also updates all four tier configs to use
  the actual HF model IDs (Qwen3-TTS-12Hz-{0.6B,1.7B}-CustomVoice) which replaced the old
  Qwen3-TTS-{0.6B,1.7B} slugs that no longer resolve.

- Correct qwen-tts version pin to 0.1.1
  ([`ae510bd`](https://github.com/getsimpledirect/ghost-narrator/commit/ae510bdd9086358758340cf87f03e6cee13623fa))

- Make metrics and tracing optional - graceful degradation when dependencies not installed
  ([`d4df7bb`](https://github.com/getsimpledirect/ghost-narrator/commit/d4df7bb1d6881570de78dedf320038f45ab30f7b))

- Make python-multipart optional with lazy import for voices router
  ([`531378f`](https://github.com/getsimpledirect/ghost-narrator/commit/531378ff3b328b059f5b663c6bb132d06df6875f))

- Make soundfile optional with graceful degradation
  ([`3be6428`](https://github.com/getsimpledirect/ghost-narrator/commit/3be6428c9a5bb42ae8f2a818228b2b58c113022c))

- Add try/except import for soundfile in voices/upload.py - Use lazy import in voices.py to avoid
  import-time dependency - Returns helpful error when soundfile not installed

- Pin pydantic-core==2.41.5 to match pydantic 2.12.5
  ([`5086cae`](https://github.com/getsimpledirect/ghost-narrator/commit/5086cae946fdd04bfe6ee485a84a5a1f32987fb8))

- Properly check for python_multipart before importing voices router
  ([`8255469`](https://github.com/getsimpledirect/ghost-narrator/commit/8255469e763004fbeb7b566815b0fcb96b64ab67))

- Remove unused imports from lint errors
  ([`541f79a`](https://github.com/getsimpledirect/ghost-narrator/commit/541f79ad2d9c19642f934785d623cd1649c5f7e4))

- Resolve 6 script bugs — encryption key gen, GCS secrets path, hardware-probe thresholds, voice
  path, grep safety
  ([`07237e9`](https://github.com/getsimpledirect/ghost-narrator/commit/07237e95c6af97aa525637ce1b8daa7c8a51efd8))

- Resolve all 27 ruff lint errors
  ([`0601721`](https://github.com/getsimpledirect/ghost-narrator/commit/06017217d73a3d3dcbc99d4061d162544081c296))

- Remove 14 unused imports (auto-fixed by ruff) - Fix bare except in connection_pool.py -> except
  Exception - Fix synthesis/__init__.py re-exports with explicit 'as' aliases and __all__ - All 66
  tests pass, ruff check clean

- Resolve all test failures - mock executor, AudioSegment, narration validation
  ([`18b46ef`](https://github.com/getsimpledirect/ghost-narrator/commit/18b46efbc21a974483aadea9dbb197356ccc87e5))

- Add _make_mock_executor() returning real Future objects for run_in_executor - Mock _AudioSegment
  to avoid file I/O in tests - Fix test_chunked_strategy_uses_continuity_seed assertion - Fix
  test_single_shot_strategy_one_call with longer response text - Make metrics and tracing imports
  optional with graceful degradation

- Resolve critical bugs and race conditions
  ([`dbc205d`](https://github.com/getsimpledirect/ghost-narrator/commit/dbc205d2c98e57f0460bb3ad38e27beec7c8df37))

- Fix TTS engine singleton race condition (remove __new__, use only get_tts_engine) - Fix duplicate
  logging import in main.py, move setup_logging to lifespan - Fix S3 backend deferred import (lazy
  boto3 initialization) - Fix ConnectionPool._ensure_initialized race condition (guard with lock) -
  Fix notify_n8n catching bare Exception (catch specific exceptions) - All 49 tests pass

- Resolve test failures and deprecation warnings
  ([`d9506a2`](https://github.com/getsimpledirect/ghost-narrator/commit/d9506a26d265f6345df77788cce75b1007f5ebba))

- Fix GCS/S3 storage tests by clearing domain module cache - Fix backward compatibility layer in
  services/storage/gcs.py - Fix datetime.utcnow() deprecation in logging.py (use
  datetime.now(timezone.utc))

All 49 tests now pass.

- Sync model names and mocks after qwen-tts API update
  ([`6018cb5`](https://github.com/getsimpledirect/ghost-narrator/commit/6018cb52b1de8aaa35ea3c507b560900f26c1107))

- test_hardware.py: update 5 assertions from old short model names to
  Qwen3-TTS-12Hz-{0.6B,1.7B}-CustomVoice (CI blocker) - hardware-probe.sh: same update in tier.env
  emission; also fixes high_vram LLM model (was qwen3:8b-q4, should be qwen3:14b-q4) - 4 test files:
  replace QwenTTS mock attribute with Qwen3TTSModel so the try/except import guard resolves
  correctly in tests - QUICKSTART.md, README.md: update all stale model name strings in health
  response examples, tier tables, and built-with links

- Sync pyproject.toml version with app/__init__.py (2.1.0)
  ([`ff6dba2`](https://github.com/getsimpledirect/ghost-narrator/commit/ff6dba2d915eca84f42ab5d4e8d6e188d7984ca3))

- Sync version to 2.1.1 (latest release)
  ([`fbb1b2f`](https://github.com/getsimpledirect/ghost-narrator/commit/fbb1b2fcb64afd246ba305e6d28c8dfd2ca6b2d7))

- Update starlette pin to >=0.46.0 for fastapi 0.135.3 compatibility
  ([`f9c0036`](https://github.com/getsimpledirect/ghost-narrator/commit/f9c0036f49c911431e001ba9903187dc7772ccab))

- Update transformers to 4.57.3 for qwen-tts compatibility
  ([`44b2dd9`](https://github.com/getsimpledirect/ghost-narrator/commit/44b2dd9d047fc6f23179168e641152e1686f3390))

- **ci**: Fall back to git log for release notes when no CHANGELOG entry exists
  ([`9a3094d`](https://github.com/getsimpledirect/ghost-narrator/commit/9a3094dd504eff3753c8ad8deffd6775e4a7032a))

- **ci**: Find previous tag by version sort, not git ancestry (squash-merge safe)
  ([`e70fc5d`](https://github.com/getsimpledirect/ghost-narrator/commit/e70fc5d1d11821474441e0c402752ed895d98c34))

- **ci**: Read version from git tag and clear stale bump branch before push
  ([`64925fa`](https://github.com/getsimpledirect/ghost-narrator/commit/64925fa13d0116e66d4fee2fce01b3e487ba9cd9))

- **docker**: Add sox and tighten build-time import validation
  ([`489b318`](https://github.com/getsimpledirect/ghost-narrator/commit/489b3182edce643749415e5904ec16aed891ec6c))

pydub prints "SoX could not be found!" at startup when the sox binary is absent; adding it silences
  the warning. Also updates the build validation step to import Qwen3TTSModel by name so an API
  rename fails at image build time rather than silently at runtime.

- **docker**: Wait for tts-service health before starting n8n
  ([`467b6cf`](https://github.com/getsimpledirect/ghost-narrator/commit/467b6cfea18406afe68353cb86c4e2ac18f167f6))

service_started allowed n8n to accept webhooks while TTS was still loading models (up to 300s
  start_period), causing pipeline failures.

- **storage**: Cache GCS client instance to prevent connection leaks
  ([`58a1812`](https://github.com/getsimpledirect/ghost-narrator/commit/58a181224abac50536577000bdbf292680bd42f4))

_get_client() was creating a new storage.Client on every call, leaking HTTP transport connections
  across upload retries.

- **tests**: Clear HARDWARE_TIER env var in GPU hardware tests
  ([`7802442`](https://github.com/getsimpledirect/ghost-narrator/commit/78024420fd62f857c4e51c9ec04e98b9a0486f8c))

- **tts**: Convert precision string to torch.dtype for from_pretrained
  ([#33](https://github.com/getsimpledirect/ghost-narrator/pull/33),
  [`61ca22c`](https://github.com/getsimpledirect/ghost-narrator/commit/61ca22c2186fe4f1efb5375ae5770c8ea25daced))

- **tts**: Log and surface narration fallback failures
  ([`3e05457`](https://github.com/getsimpledirect/ghost-narrator/commit/3e0545720e3fd36f85c3ac0307b590af2c6a27b7))

Silent bare except swallowed the root cause when sequential narration also failed, and raw text was
  sent to TTS without any signal. Now logs the error and sets narration_skipped on the completed job
  record, matching the existing mastering_warning/upload_warning pattern.

- **tts**: Update qwen-tts API from QwenTTS to Qwen3TTSModel
  ([`822923c`](https://github.com/getsimpledirect/ghost-narrator/commit/822923c4bc994427c079e6586c293b79d72954d5))

QwenTTS no longer exists in qwen-tts>=2026.1.22. The package now exports Qwen3TTSModel with a
  from_pretrained constructor, create_voice_clone_prompt for cacheable reference prompts, and
  generate_voice_clone for synthesis. save_wav replaced with soundfile.write. Pin version to
  2026.1.22.

### Chores

- Migrate versioning to python-semantic-release
  ([#39](https://github.com/getsimpledirect/ghost-narrator/pull/39),
  [`e1f464c`](https://github.com/getsimpledirect/ghost-narrator/commit/e1f464c80251e6d4c808f194246812fe2c4815d1))

- Remove docs from commit
  ([`7dcc631`](https://github.com/getsimpledirect/ghost-narrator/commit/7dcc631ba5fc1c93e51b625b9c4bfdd8706c1628))

### Code Style

- Fix ruff formatting after conflict resolution
  ([`863fd57`](https://github.com/getsimpledirect/ghost-narrator/commit/863fd579415ef00b5f48cca19109ebaec0583f53))

- Fix type hints and minor code quality issues
  ([`08ab3c8`](https://github.com/getsimpledirect/ghost-narrator/commit/08ab3c8a669ec0d450f852b6b3adc080989f2a9e))

- Fix any -> Any in retry.py (proper typing import) - Fix Optional[dict] type hints in storage
  backends (local, gcs, s3) - Add module docstring and sort imports in logging.py - Fix dir()
  anti-pattern in metrics.py - Remove duplicate del sys.modules in test_storage.py - All 49 tests
  pass

- Format all files with ruff format
  ([`8cb53a4`](https://github.com/getsimpledirect/ghost-narrator/commit/8cb53a4d90f4ff3d30f2d19fe414117d4c998f20))

### Continuous Integration

- Auto-update CHANGELOG reference links on version bump
  ([`bf81c36`](https://github.com/getsimpledirect/ghost-narrator/commit/bf81c369dbcd6b7b9f6181f17780aa31dd3f8c5f))

- Explicitly pass GITHUB_TOKEN to checkout steps
  ([`30580ac`](https://github.com/getsimpledirect/ghost-narrator/commit/30580ac25f5341c7ea18ae1c20965120b9ef85c8))

- Fix GitHub Actions workflow errors and edge cases
  ([`706d3f8`](https://github.com/getsimpledirect/ghost-narrator/commit/706d3f899c47edb8b0c0e00026b9f5a129bb48e6))

- Replace uv with standard Python setup (project uses requirements.txt, not uv) - Fix ci.yml: use
  actions/setup-python@v5 instead of astral-sh/setup-uv@v4 - Fix ci.yml: use proper
  working-directory (tts-service) instead of redundant '.' - Fix versioning.yml: add fallback for
  VERSION file reading (git describe --tags) - Fix versioning.yml: handle missing VERSION file
  gracefully in both bump paths - Fix dependabot-auto-merge.yml: use 'gh pr merge --auto' instead of
  manual merge - All workflows now use correct paths and tooling for this project

- Restrict CI workflow permissions to contents: read
  ([`10a74fb`](https://github.com/getsimpledirect/ghost-narrator/commit/10a74fbcd10c58ed4b39f387dd179d1bafcb14e5))

- Use uv for faster dependency installation and install full requirements in tests
  ([`d81c396`](https://github.com/getsimpledirect/ghost-narrator/commit/d81c396bc097c735897d282d73a48cb2dcb86d8b))

- Replace pip with uv for faster installs - Install full requirements.txt instead of just subset -
  Fix working-directory paths

### Documentation

- Add production restructure design spec
  ([`cca42e3`](https://github.com/getsimpledirect/ghost-narrator/commit/cca42e3863c892ab7a9fef952d7080912968fb98))

- Add resilience and observability documentation
  ([`e39bd8f`](https://github.com/getsimpledirect/ghost-narrator/commit/e39bd8fa32cd4b0739e0fda9ff887b12ea6d3733))

- Add v2.2.0 changelog entry and fix release notes extraction
  ([`9e437d6`](https://github.com/getsimpledirect/ghost-narrator/commit/9e437d64c8e29ff61da8222cef15a763c258db10))

cz bump's --dry-run finds no unreleased commits after bump already committed them. Replace with awk
  extraction from CHANGELOG.md so future releases populate the GitHub release body correctly.

- Add v2.2.0 reference link and update Unreleased pointer
  ([`a64039a`](https://github.com/getsimpledirect/ghost-narrator/commit/a64039ab3a6b396c3fd104d7e92306e02771fca1))

- Fix stale directory trees — remove deleted audio/, base.py, callbacks.py; add quality.py,
  quality_check.py, factory.py
  ([`6595a0d`](https://github.com/getsimpledirect/ghost-narrator/commit/6595a0d317128c980fb52ad92689b89a0003a159))

- Fix v2.2.1 and v2.2.0 reference link base tags
  ([`002a2ac`](https://github.com/getsimpledirect/ghost-narrator/commit/002a2ac023f1af3be049932591e521137d3f2931))

- Replace all start.sh references with docker compose commands
  ([`70fb9b7`](https://github.com/getsimpledirect/ghost-narrator/commit/70fb9b7ad358f2dfdc0e47a57e05a9d24e5f45be))

- Replace TTS_DEVICE with HARDWARE_TIER in QUICKSTART.md
  ([`1b9a6c8`](https://github.com/getsimpledirect/ghost-narrator/commit/1b9a6c8aff1cc7e4260572a7277e4812ac480c23))

TTS_DEVICE is not read by any code. Device selection is handled automatically via HARDWARE_TIER.
  Also corrects TTS_TIER → HARDWARE_TIER and aligns tier values with actual config
  (cpu_only|low_vram|mid_vram|high_vram).

### Features

- Add API versioning middleware with header support
  ([`e3f3a77`](https://github.com/getsimpledirect/ghost-narrator/commit/e3f3a7772dc8c82bf50c81240056808a2230eda5))

- Add business and resource metrics for observability
  ([`098a59b`](https://github.com/getsimpledirect/ghost-narrator/commit/098a59b4210d33ef7e891b7a9f46ee6d25640d4a))

- Add circuit breaker implementation for resilience
  ([`c1377b6`](https://github.com/getsimpledirect/ghost-narrator/commit/c1377b658122fe58300466057db57d5063e5ba82))

- Add detailed health checks with dependency status
  ([`d88bd6a`](https://github.com/getsimpledirect/ghost-narrator/commit/d88bd6aa24f72c1cba28e6d8fa78465b336317aa))

- Add exponential backoff retry with circuit breaker integration
  ([`debfe27`](https://github.com/getsimpledirect/ghost-narrator/commit/debfe2705891d5e8245e592fdfdcd4c834801906))

- Add generic connection pool for Redis and HTTP clients
  ([`9fe3e9a`](https://github.com/getsimpledirect/ghost-narrator/commit/9fe3e9ab53a81d5bf958d0b53554469ad01efc78))

- Add OpenTelemetry distributed tracing support
  ([`162d7a1`](https://github.com/getsimpledirect/ghost-narrator/commit/162d7a1f10baac8f4fa3e125bd30bc25fad7eaa5))

- Add Prometheus metrics endpoint for observability
  ([`cf16115`](https://github.com/getsimpledirect/ghost-narrator/commit/cf16115c6b11d46ff5525e49f7241ac14c0434f6))

- Add pyproject.toml for uv-based project management
  ([`d55c6f6`](https://github.com/getsimpledirect/ghost-narrator/commit/d55c6f65e8c3da25913fc27b4a778ea0d2533b21))

- Create pyproject.toml with all dependencies - Update Dockerfile to copy pyproject.toml - CI
  already uses uv for testing

- Add rate limiting middleware for API protection
  ([`41b18f8`](https://github.com/getsimpledirect/ghost-narrator/commit/41b18f8583ad183a78c7a3cf5be37e7ba75a2129))

- Add Redis caching layer with graceful degradation
  ([`7bde77f`](https://github.com/getsimpledirect/ghost-narrator/commit/7bde77f670917e9fdd8033e04751834fbb51c14a))

- Add specific exception classes for each domain
  ([`7b69b3e`](https://github.com/getsimpledirect/ghost-narrator/commit/7b69b3ea291252b86e398572e9b1b73801a4aa23))

- Add structured logging with correlation IDs
  ([`d66cf68`](https://github.com/getsimpledirect/ghost-narrator/commit/d66cf68d02b7e820c4bee3d8bcb6f3b43562fe01))

- Create domain structure directories
  ([`4bcaafa`](https://github.com/getsimpledirect/ghost-narrator/commit/4bcaafa6279f43d9f7cf2b5ebb67a298ce0ace25))

- Enable API versioning in main application
  ([`5c0518f`](https://github.com/getsimpledirect/ghost-narrator/commit/5c0518f6efc652bf1fac3cab02a47462d8cb7277))

- Enable FastAPI tracing instrumentation
  ([`656c369`](https://github.com/getsimpledirect/ghost-narrator/commit/656c3690075bcc6ac44a0594d1f0896426929473))

- Enable rate limiting in main application
  ([`f6a6217`](https://github.com/getsimpledirect/ghost-narrator/commit/f6a6217a45dbcfdd9cbff94ec666cfca204a4ce4))

- Integrate circuit breaker for n8n callback protection
  ([`48f81f0`](https://github.com/getsimpledirect/ghost-narrator/commit/48f81f06625190491a943397a2b9d51d1cecbeb3))

- Make version dynamic - read from app/__version__ single source of truth
  ([`0e56e38`](https://github.com/getsimpledirect/ghost-narrator/commit/0e56e38b3795b852cf8017c96c5a788ec0e58fe2))

- Use dynamic version in pyproject.toml - Read version from app.__version__ attribute - Single
  source of truth in app/__init__.py

- Production hardening - add defensive code and error handling
  ([`74e9e40`](https://github.com/getsimpledirect/ghost-narrator/commit/74e9e4021e0360d8382e51e4deb89dfc509730b8))

- Reduce Redis polling from 1s to 2s interval - Add optional health_check callback to ConnectionPool
  - Add error handling to JobStore.update() Lua script - Add sync support to CircuitBreaker
  (call_sync method) - Wrap tracing.py module-level setup in try/except - Handle
  non-JSON-serializable results in cache decorator - Add TTL to memory store in JobStore with lazy
  cleanup - Document rate limiter distributed limitation - Document API versioning as placeholder -
  All 49 tests pass

### Refactoring

- Add backward compatibility exports to services package
  ([`05157b8`](https://github.com/getsimpledirect/ghost-narrator/commit/05157b8282c7b26b1a1fe8e3785ac748c1724933))

- Eliminate code duplication - remove dead/duplicate modules
  ([`9e9924b`](https://github.com/getsimpledirect/ghost-narrator/commit/9e9924b04011086b15ad3a3dddb046474fefeba4))

- Delete app/domains/audio/__init__.py (976 lines duplicate of synthesis/) - Move
  validate_audio_quality to app/domains/synthesis/quality.py - Delete app/domains/narration/base.py
  (dead ABC) - Delete app/domains/synthesis/base.py (dead ABC) - Delete app/domains/job/callbacks.py
  (stub functions) - Update imports in tts_job.py to use synthesis domain - All 49 tests pass

- Eliminate start.sh — GPU detection moved to install.sh via COMPOSE_FILE env var
  ([`22e3744`](https://github.com/getsimpledirect/ghost-narrator/commit/22e3744d16a07c7fdb7f3a9604a68d72cad4e5c5))

- Extract job domain to app/domains/job/
  ([`8f3d51c`](https://github.com/getsimpledirect/ghost-narrator/commit/8f3d51c663c88897878ebc633652ae2f5f8d2fac))

- Extract narration domain to app/domains/narration/
  ([`a2824ba`](https://github.com/getsimpledirect/ghost-narrator/commit/a2824ba38718e1509800ad19ee93d9a0895c9442))

- Extract storage domain to app/domains/storage/
  ([`6973423`](https://github.com/getsimpledirect/ghost-narrator/commit/69734230738bb7d0d20999f6a69451cf573620e8))

- Extract synthesis domain to app/domains/synthesis/
  ([`0d657dc`](https://github.com/getsimpledirect/ghost-narrator/commit/0d657dc9948bfdbd3129590c7c3af0debc7feae2))

- Improve domain boundaries and cross-domain dependencies
  ([`25fd580`](https://github.com/getsimpledirect/ghost-narrator/commit/25fd580193446d7589c4ea09746c7b5eec0f1207))

- Make config.py hardware values lazy (defer ENGINE_CONFIG import) - Move get_narration_strategy()
  to app/domains/narration/factory.py - Add path validation inside VoiceRegistry (not just routes) -
  Fix TOCTOU race in delete_voice (use missing_ok=True) - Use DEFAULT_TARGET_LUFS constant instead
  of hardcoded -23.0 - Move quality check logic to app/domains/synthesis/quality_check.py - All 49
  tests pass

- Remove backward compatibility, use direct domain imports
  ([`2be3a85`](https://github.com/getsimpledirect/ghost-narrator/commit/2be3a85055e71ee98870a29377d2185a2b410822))

- Remove redundant RESILIENCE.md, integrate into ARCHITECTURE.md
  ([`eb03f9e`](https://github.com/getsimpledirect/ghost-narrator/commit/eb03f9ed85684006229d3df736d8b3f65eed24d6))

### Testing

- Add missing test coverage and fix documentation
  ([`22aae8b`](https://github.com/getsimpledirect/ghost-narrator/commit/22aae8bd888d89994ac0f975b4894da3208d9b02))

- Fix job_id validation pattern consistency between route and config - Expand
  test_circuit_breaker.py with 4 new test cases - Add tests/test_job_store.py (5 tests for critical
  JobStore component) - Add tests/test_notification.py (4 tests for notification module) - Add
  tests/test_synthesis_service.py (4 tests for synthesis orchestration) - Fix README TTS_TIER →
  HARDWARE_TIER env var name - All tests pass

- Verify all tests pass and update coverage
  ([`c830ba0`](https://github.com/getsimpledirect/ghost-narrator/commit/c830ba0b6af8bff647436dac4187f640a39022fd))


## v2.1.1 (2026-04-03)

### Bug Fixes

- Resolve code review findings — security, race conditions, resource leaks
  ([`a0cd102`](https://github.com/getsimpledirect/ghost-narrator/commit/a0cd102a290c8319cb263fbf4ef05793257e55cd))

Critical: - C1: Fix TOCTOU race in job re-creation (return existing status, no overwrite) - C2: Add
  1000-job cap to in-memory store with LRU eviction - C3: Remove server path from voice sample error
  response

Warnings: - W1: Replace Redis KEYS with SCAN (non-blocking iteration) - W2: Check ffmpeg return code
  in pitch_shift_segment - W3: Fix temp file leak with try/finally cleanup - W6: Log OUTPUT_DIR
  creation failure instead of silent pass - W7: Split broad exception catch into specific types

Also fixed ruff warnings (unused imports, f-string, not-in)

- **tests**: Resolve CI test failures
  ([`10b80bb`](https://github.com/getsimpledirect/ghost-narrator/commit/10b80bb8b1824998ea41895ef2a932f68dbe90fa))

- test_hardware.py: mock _TORCH_AVAILABLE alongside torch (CI has no torch) and update HIGH_VRAM
  assertions for new config (14b, 2 workers) - test_narration_strategy.py: return longer mock text
  to pass word count ratio validation (was triggering retries and inflating call counts) -
  test_tts_job.py: fix get_tts_engine patch target (import is inside function) - test_storage.py:
  skip S3 tests when boto3 unavailable, fix boto3 patch target - ci.yml: add boto3 to test
  dependencies

### Chores

- **deps**: Bump the python-minor group in /tts-service with 31 updates
  ([#16](https://github.com/getsimpledirect/ghost-narrator/pull/16),
  [`f9ca2f8`](https://github.com/getsimpledirect/ghost-narrator/commit/f9ca2f8db2922e47f48734c653f0a3cd5403b2f4))

Bumps the python-minor group in /tts-service with 31 updates:

| Package | From | To | | --- | --- | --- | | [wheel](https://github.com/pypa/wheel) | `0.44.0` |
  `0.46.3` | | [torch](https://github.com/pytorch/pytorch) | `2.4.1` | `2.11.0` | |
  [torchaudio](https://github.com/pytorch/audio) | `2.4.1` | `2.11.0` | |
  [torchvision](https://github.com/pytorch/vision) | `0.19.1` | `0.26.0` | |
  [triton](https://github.com/triton-lang/triton) | `3.0.0` | `3.6.0` | |
  [lightning](https://github.com/Lightning-AI/pytorch-lightning) | `2.2.5` | `2.6.1` | |
  [pytorch-lightning](https://github.com/Lightning-AI/pytorch-lightning) | `2.2.5` | `2.6.1` | |
  [lightning-utilities](https://github.com/Lightning-AI/utilities) | `0.11.2` | `0.15.3` | |
  [torchmetrics](https://github.com/Lightning-AI/torchmetrics) | `1.4.0` | `1.9.0` | |
  [fastapi](https://github.com/fastapi/fastapi) | `0.111.0` | `0.135.3` | |
  [uvicorn](https://github.com/Kludex/uvicorn) | `0.30.1` | `0.42.0` | |
  [pydantic](https://github.com/pydantic/pydantic) | `2.9.2` | `2.12.5` | |
  [pydantic-core](https://github.com/pydantic/pydantic-core) | `2.23.4` | `2.45.0` | |
  [soundfile](https://github.com/bastibe/python-soundfile) | `0.12.1` | `0.13.1` | |
  [librosa](https://github.com/librosa/librosa) | `0.10.2` | `0.11.0` | |
  [numba](https://github.com/numba/numba) | `0.60.0` | `0.65.0` | |
  [llvmlite](https://github.com/numba/llvmlite) | `0.43.0` | `0.47.0` | |
  [google-auth](https://github.com/googleapis/google-auth-library-python) | `2.29.0` | `2.49.1` | |
  [google-crc32c](https://github.com/googleapis/python-crc32c) | `1.6.0` | `1.8.0` | |
  [httpx](https://github.com/encode/httpx) | `0.27.0` | `0.28.1` | |
  [python-multipart](https://github.com/Kludex/python-multipart) | `0.0.9` | `0.0.22` | |
  [typing-extensions](https://github.com/python/typing_extensions) | `4.11.0` | `4.15.0` | |
  [einx](https://github.com/fferflo/einx) | `0.2.2` | `0.4.3` | |
  [inflect](https://github.com/jaraco/inflect) | `7.0.0` | `7.5.0` | |
  [anyascii](https://github.com/anyascii/anyascii) | `0.3.2` | `0.3.3` | |
  [gruut](https://github.com/rhasspy/gruut) | `2.2.3` | `2.4.0` | |
  [bangla](https://github.com/arsho/bangla) | `0.0.2` | `0.0.5` | |
  [bnunicodenormalizer](https://github.com/mnansary/bnUnicodeNormalizer) | `0.1.6` | `0.1.7` | |
  [vector-quantize-pytorch](https://github.com/lucidrains/vector-quantizer-pytorch) | `1.14.24` |
  `1.28.1` | | [modelscope](https://github.com/modelscope/modelscope) | `1.17.1` | `1.35.3` | |
  [funasr](https://github.com/alibaba-damo-academy/FunASR) | `1.1.5` | `1.3.1` |

Updates `wheel` from 0.44.0 to 0.46.3 - [Release notes](https://github.com/pypa/wheel/releases) -
  [Changelog](https://github.com/pypa/wheel/blob/main/docs/news.rst) -
  [Commits](https://github.com/pypa/wheel/compare/0.44.0...0.46.3)

Updates `torch` from 2.4.1 to 2.11.0 - [Release notes](https://github.com/pytorch/pytorch/releases)
  - [Changelog](https://github.com/pytorch/pytorch/blob/main/RELEASE.md) -
  [Commits](https://github.com/pytorch/pytorch/compare/v2.4.1...v2.11.0)

Updates `torchaudio` from 2.4.1 to 2.11.0 - [Release
  notes](https://github.com/pytorch/audio/releases) -
  [Commits](https://github.com/pytorch/audio/compare/v2.4.1...v2.11.0)

Updates `torchvision` from 0.19.1 to 0.26.0 - [Release
  notes](https://github.com/pytorch/vision/releases) -
  [Commits](https://github.com/pytorch/vision/compare/v0.19.1...v0.26.0)

Updates `triton` from 3.0.0 to 3.6.0 - [Release
  notes](https://github.com/triton-lang/triton/releases) -
  [Changelog](https://github.com/triton-lang/triton/blob/main/RELEASE.md) -
  [Commits](https://github.com/triton-lang/triton/compare/v3.0.0...v3.6.0)

Updates `lightning` from 2.2.5 to 2.6.1 - [Release
  notes](https://github.com/Lightning-AI/pytorch-lightning/releases) -
  [Commits](https://github.com/Lightning-AI/pytorch-lightning/compare/2.2.5...2.6.1)

Updates `pytorch-lightning` from 2.2.5 to 2.6.1 - [Release
  notes](https://github.com/Lightning-AI/pytorch-lightning/releases) -
  [Commits](https://github.com/Lightning-AI/pytorch-lightning/compare/2.2.5...2.6.1)

Updates `lightning-utilities` from 0.11.2 to 0.15.3 - [Release
  notes](https://github.com/Lightning-AI/utilities/releases) -
  [Changelog](https://github.com/Lightning-AI/utilities/blob/main/CHANGELOG.md) -
  [Commits](https://github.com/Lightning-AI/utilities/compare/v0.11.2...v0.15.3)

Updates `torchmetrics` from 1.4.0 to 1.9.0 - [Release
  notes](https://github.com/Lightning-AI/torchmetrics/releases) -
  [Changelog](https://github.com/Lightning-AI/torchmetrics/blob/master/CHANGELOG.md) -
  [Commits](https://github.com/Lightning-AI/torchmetrics/compare/v1.4.0...v1.9.0)

Updates `fastapi` from 0.111.0 to 0.135.3 - [Release
  notes](https://github.com/fastapi/fastapi/releases) -
  [Commits](https://github.com/fastapi/fastapi/compare/0.111.0...0.135.3)

Updates `uvicorn` from 0.30.1 to 0.42.0 - [Release
  notes](https://github.com/Kludex/uvicorn/releases) -
  [Changelog](https://github.com/Kludex/uvicorn/blob/main/docs/release-notes.md) -
  [Commits](https://github.com/Kludex/uvicorn/compare/0.30.1...0.42.0)

Updates `pydantic` from 2.9.2 to 2.12.5 - [Release
  notes](https://github.com/pydantic/pydantic/releases) -
  [Changelog](https://github.com/pydantic/pydantic/blob/main/HISTORY.md) -
  [Commits](https://github.com/pydantic/pydantic/compare/v2.9.2...v2.12.5)

Updates `pydantic-core` from 2.23.4 to 2.45.0 - [Release
  notes](https://github.com/pydantic/pydantic-core/releases) -
  [Commits](https://github.com/pydantic/pydantic-core/commits)

Updates `soundfile` from 0.12.1 to 0.13.1 - [Release
  notes](https://github.com/bastibe/python-soundfile/releases) -
  [Commits](https://github.com/bastibe/python-soundfile/compare/0.12.1...0.13.1)

Updates `librosa` from 0.10.2 to 0.11.0 - [Release
  notes](https://github.com/librosa/librosa/releases) -
  [Changelog](https://github.com/librosa/librosa/blob/main/docs/changelog.rst) -
  [Commits](https://github.com/librosa/librosa/compare/0.10.2...0.11.0)

Updates `numba` from 0.60.0 to 0.65.0 - [Release notes](https://github.com/numba/numba/releases) -
  [Commits](https://github.com/numba/numba/compare/0.60.0...0.65.0)

Updates `llvmlite` from 0.43.0 to 0.47.0 - [Release
  notes](https://github.com/numba/llvmlite/releases) -
  [Commits](https://github.com/numba/llvmlite/compare/v0.43.0...v0.47.0)

Updates `google-auth` from 2.29.0 to 2.49.1 - [Release
  notes](https://github.com/googleapis/google-auth-library-python/releases) -
  [Changelog](https://github.com/googleapis/google-auth-library-python/blob/main/CHANGELOG.md) -
  [Commits](https://github.com/googleapis/google-auth-library-python/commits)

Updates `google-crc32c` from 1.6.0 to 1.8.0 - [Release
  notes](https://github.com/googleapis/python-crc32c/releases) -
  [Changelog](https://github.com/googleapis/python-crc32c/blob/main/CHANGELOG.md) -
  [Commits](https://github.com/googleapis/python-crc32c/compare/v1.6.0...v1.8.0)

Updates `httpx` from 0.27.0 to 0.28.1 - [Release notes](https://github.com/encode/httpx/releases) -
  [Changelog](https://github.com/encode/httpx/blob/master/CHANGELOG.md) -
  [Commits](https://github.com/encode/httpx/compare/0.27.0...0.28.1)

Updates `python-multipart` from 0.0.9 to 0.0.22 - [Release
  notes](https://github.com/Kludex/python-multipart/releases) -
  [Changelog](https://github.com/Kludex/python-multipart/blob/master/CHANGELOG.md) -
  [Commits](https://github.com/Kludex/python-multipart/compare/0.0.9...0.0.22)

Updates `typing-extensions` from 4.11.0 to 4.15.0 - [Release
  notes](https://github.com/python/typing_extensions/releases) -
  [Changelog](https://github.com/python/typing_extensions/blob/main/CHANGELOG.md) -
  [Commits](https://github.com/python/typing_extensions/compare/4.11.0...4.15.0)

Updates `einx` from 0.2.2 to 0.4.3 - [Release notes](https://github.com/fferflo/einx/releases) -
  [Changelog](https://github.com/fferflo/einx/blob/master/CHANGELOG.md) -
  [Commits](https://github.com/fferflo/einx/compare/v0.2.2...v0.4.3)

Updates `inflect` from 7.0.0 to 7.5.0 - [Release notes](https://github.com/jaraco/inflect/releases)
  - [Changelog](https://github.com/jaraco/inflect/blob/main/NEWS.rst) -
  [Commits](https://github.com/jaraco/inflect/compare/v7.0.0...v7.5.0)

Updates `anyascii` from 0.3.2 to 0.3.3 - [Release
  notes](https://github.com/anyascii/anyascii/releases) -
  [Changelog](https://github.com/anyascii/anyascii/blob/master/CHANGELOG.md) -
  [Commits](https://github.com/anyascii/anyascii/compare/0.3.2...0.3.3)

Updates `gruut` from 2.2.3 to 2.4.0 - [Release notes](https://github.com/rhasspy/gruut/releases) -
  [Changelog](https://github.com/rhasspy/gruut/blob/master/CHANGELOG) -
  [Commits](https://github.com/rhasspy/gruut/compare/v2.2.3...v2.4.0)

Updates `bangla` from 0.0.2 to 0.0.5 - [Release notes](https://github.com/arsho/bangla/releases) -
  [Changelog](https://github.com/arsho/bangla/blob/master/Changelog.rst) -
  [Commits](https://github.com/arsho/bangla/commits/0.0.5)

Updates `bnunicodenormalizer` from 0.1.6 to 0.1.7 -
  [Changelog](https://github.com/mnansary/bnUnicodeNormalizer/blob/main/CHANGELOG.txt) -
  [Commits](https://github.com/mnansary/bnUnicodeNormalizer/commits)

Updates `vector-quantize-pytorch` from 1.14.24 to 1.28.1 - [Release
  notes](https://github.com/lucidrains/vector-quantizer-pytorch/releases) -
  [Commits](https://github.com/lucidrains/vector-quantizer-pytorch/commits)

Updates `modelscope` from 1.17.1 to 1.35.3 - [Release
  notes](https://github.com/modelscope/modelscope/releases) -
  [Commits](https://github.com/modelscope/modelscope/compare/v1.17.1...v1.35.3)

Updates `funasr` from 1.1.5 to 1.3.1 - [Release
  notes](https://github.com/alibaba-damo-academy/FunASR/releases) -
  [Commits](https://github.com/alibaba-damo-academy/FunASR/commits)

--- updated-dependencies: - dependency-name: wheel dependency-version: 0.46.3

dependency-type: direct:production

update-type: version-update:semver-minor

dependency-group: python-minor

- dependency-name: torch dependency-version: 2.11.0

- dependency-name: torchaudio dependency-version: 2.11.0

- dependency-name: torchvision dependency-version: 0.26.0

- dependency-name: triton dependency-version: 3.6.0

- dependency-name: lightning dependency-version: 2.6.1

- dependency-name: pytorch-lightning dependency-version: 2.6.1

- dependency-name: lightning-utilities dependency-version: 0.15.3

- dependency-name: torchmetrics dependency-version: 1.9.0

- dependency-name: fastapi dependency-version: 0.135.3

- dependency-name: uvicorn dependency-version: 0.42.0

- dependency-name: pydantic dependency-version: 2.12.5

- dependency-name: pydantic-core dependency-version: 2.45.0

- dependency-name: soundfile dependency-version: 0.13.1

- dependency-name: librosa dependency-version: 0.11.0

- dependency-name: numba dependency-version: 0.65.0

- dependency-name: llvmlite dependency-version: 0.47.0

- dependency-name: google-auth dependency-version: 2.49.1

- dependency-name: google-crc32c dependency-version: 1.8.0

- dependency-name: httpx dependency-version: 0.28.1

- dependency-name: python-multipart dependency-version: 0.0.22

update-type: version-update:semver-patch

- dependency-name: typing-extensions dependency-version: 4.15.0

- dependency-name: einx dependency-version: 0.4.3

- dependency-name: inflect dependency-version: 7.5.0

- dependency-name: anyascii dependency-version: 0.3.3

- dependency-name: gruut dependency-version: 2.4.0

- dependency-name: bangla dependency-version: 0.0.5

- dependency-name: bnunicodenormalizer dependency-version: 0.1.7

- dependency-name: vector-quantize-pytorch dependency-version: 1.28.1

- dependency-name: modelscope dependency-version: 1.35.3

- dependency-name: funasr dependency-version: 1.3.1

dependency-group: python-minor ...

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

- **deps**: Update protobuf requirement in /tts-service
  ([#19](https://github.com/getsimpledirect/ghost-narrator/pull/19),
  [`88f3fd6`](https://github.com/getsimpledirect/ghost-narrator/commit/88f3fd654aeb14235105c1a70981a8fd0543a6f2))

Updates the requirements on [protobuf](https://github.com/protocolbuffers/protobuf) to permit the
  latest version. - [Release notes](https://github.com/protocolbuffers/protobuf/releases) -
  [Commits](https://github.com/protocolbuffers/protobuf/commits)

--- updated-dependencies: - dependency-name: protobuf dependency-version: 7.34.1

dependency-type: direct:production ...

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

- **deps**: Update tokenizers requirement in /tts-service
  ([#18](https://github.com/getsimpledirect/ghost-narrator/pull/18),
  [`08ecb0e`](https://github.com/getsimpledirect/ghost-narrator/commit/08ecb0e10cb5cffb21644f5dfb70edbcab34eece))

Updates the requirements on [tokenizers](https://github.com/huggingface/tokenizers) to permit the
  latest version. - [Release notes](https://github.com/huggingface/tokenizers/releases) -
  [Changelog](https://github.com/huggingface/tokenizers/blob/main/RELEASE.md) -
  [Commits](https://github.com/huggingface/tokenizers/compare/v0.20.0...v0.22.2)

--- updated-dependencies: - dependency-name: tokenizers dependency-version: 0.22.2

dependency-type: direct:production ...

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

### Continuous Integration

- Add CI pipeline with lint + test, gate auto-merge on CI pass
  ([`00436e9`](https://github.com/getsimpledirect/ghost-narrator/commit/00436e9667ead49edb255f14f0cd8918826e6ede))

- ci.yml: runs ruff lint/format check + pytest on every PR and push to main -
  dependabot-auto-merge.yml: waits for CI test job to pass before auto-merging - Major version bumps
  still require manual review

- Auto-create GitHub release on version tag push
  ([`26140ef`](https://github.com/getsimpledirect/ghost-narrator/commit/26140ef0c5c4d629d8b9988cc63411be850f221e))

Triggers on v* tags, extracts changelog section for that version, creates release with
  auto-generated notes appended.

- Auto-merge dependabot patch/minor updates, group PRs
  ([`a7dbd63`](https://github.com/getsimpledirect/ghost-narrator/commit/a7dbd63a3d9a60329b8df29d6894daebf2f37b3f))

- Add dependabot-auto-merge.yml: auto-squash-merge patch and minor updates - Group dependabot PRs:
  all minor/patch pip updates in one PR, all actions in one PR - Reduces PR noise from dozens of
  individual updates

- Fix dependabot groups config, exclude heavy deps from auto-update
  ([`9d436fe`](https://github.com/getsimpledirect/ghost-narrator/commit/9d436fed853cb46f92c0583a852610d99822b432))

- Remove invalid update-types key from groups - Group all pip deps into single PR (excluding
  torch/triton/transformers) - Reduce PR limits (pip: 3, actions: 2) - Add commit message prefixes

- Fix release changelog extraction — strip v prefix, disable auto-notes
  ([`557c99b`](https://github.com/getsimpledirect/ghost-narrator/commit/557c99b4c5b45e8e1f62dc4c80c1c731d30293b6))

- Simplify auto-merge — just gate on CI pass, skip broken metadata check
  ([`3c1846b`](https://github.com/getsimpledirect/ghost-narrator/commit/3c1846b52d32c3242ad7b59f58bf15ec43202651))

With grouped PRs, dependabot/fetch-metadata can't determine update-type reliably. Since grouping
  already excludes heavy deps (torch/transformers), any dependabot PR that passes CI is safe to
  merge.

### Documentation

- Add CI test fixes to v2.1.1 changelog
  ([`78a2bbd`](https://github.com/getsimpledirect/ghost-narrator/commit/78a2bbd4a19ee166fa690c7835d9ce9bb7eaad79))

- Add v2.1.0 changelog with all changes
  ([`0827aaf`](https://github.com/getsimpledirect/ghost-narrator/commit/0827aaf3e8b9cc5a189d5bc6553f36186f33e0d8))


## v2.1.0 (2026-04-02)

### Bug Fixes

- Resolve 5 logic bugs in tier detection, TTS concurrency, audio, and narration
  ([`c4236fa`](https://github.com/getsimpledirect/ghost-narrator/commit/c4236fa1a193bc9dd92545c94c8b714c9647b26f))

- tts_engine: acquire _synthesis_lock around load_reference/synthesize/save_wav to prevent
  concurrent inference corruption on GPU - hardware: raise MID_VRAM threshold 9→10 GB; set HIGH_VRAM
  synthesis_workers 1 (GPU inference is serial — 2 workers just queued behind the lock anyway) -
  audio: derive LUFS validation range from TARGET_LUFS±2 (was hardcoded -18/-14, wrong for HIGH_VRAM
  tier targeting -14 LUFS); drop dead -q:a VBR flag that ffmpeg ignores when -b:a CBR is set -
  strategy: fix _tail_sentences to split on [.?!] not just "."; add 120s timeout to _call_llm to
  prevent hangs on slow hardware - validator: remove \b\d{4}\b from NUMBER_RE — year matches cause
  false validation failures when LLM correctly spells out years in prose - tests: update HIGH_VRAM
  workers assertion; add 9 GB boundary test

- Resolve audit gaps — volumes, health endpoint, stale docs
  ([`0d002fd`](https://github.com/getsimpledirect/ghost-narrator/commit/0d002fdc9b6ff5f74afdf8f23750e5a11de73f23))

- docker-compose.yml: voices bind mount → voices_data named volume; VOICE_SAMPLE_PATH default →
  /app/voices/default/reference.wav; update stale VLLM_BASE_URL header comment to LLM_BASE_URL -
  config.py: VOICE_SAMPLE_PATH default matches new volume path - health.py: replace get_gcs_client()
  stub with get_storage_backend(); /health/detailed storage component now shows backend type -
  ARCHITECTURE.md: remove ChromaDB from diagram; update hardware-probe reference to
  scripts/init/hardware-probe.sh + tier_data volume; update scripts directory listing -
  tts-service/README.md + QUICKSTART.md: update project structure tree (narration/, voices/,
  storage/ packages); update module table; fix health response examples to include
  hardware_tier/tts_model/llm_model - CONTRIBUTING.md: Python 3.11+ → 3.12+ - SECURITY.md: remove
  ChromaDB/SearXNG/vLLM from scope (not in stack)

- **tests**: Rewrite test_tts_job.py to use get_storage_backend mock, fix upload_warning key
  ([`5917827`](https://github.com/getsimpledirect/ghost-narrator/commit/59178274e5c4785985eb6d973b499a9fa1c9789a))

- **tts**: Wire narration into pipeline, fix site slug, pipelining, and quality improvements
  ([`863fa75`](https://github.com/getsimpledirect/ghost-narrator/commit/863fa754c5ef5254b3dbed802369fa2a2150b394))

- CRITICAL: Wire LLM narration step into TTS job pipeline (was completely missing) - Fix
  gcs_object_path.split('/')[0] passing wrong site slug to storage - Pipeline LLM narration + TTS
  synthesis for overlapping execution - Replace engine readiness busy-poll with asyncio.Event -
  Batch parallel synthesis with cancellation checks between batches - Two-pass loudnorm for final
  mastering accuracy - Give MID_VRAM full pacing prompt (same model as HIGH_VRAM) - Add proper noun
  validation to narration validator - Narrow _TRANSITION_STARTERS to actual topic transitions -
  Enrich continuity seeding with source tail context - Skip per-chunk normalization for short (<10s)
  audio segments - Update stale docstring referencing old Fish Speech pipeline

### Chores

- Add .cz.toml, VERSION, .github/versioning.yml, dependabot.yml, fix CONTRIBUTING/SECURITY refs
  ([`e59c8df`](https://github.com/getsimpledirect/ghost-narrator/commit/e59c8df33392efad2a4d8ee038acf05af864dc58))

- Add .cz.toml, VERSION, .github/versioning.yml, dependabot.yml, fix CONTRIBUTING/SECURITY refs
  ([`aae15ba`](https://github.com/getsimpledirect/ghost-narrator/commit/aae15baecff307b16f6042ff88959a40754c323c))

- Exclude docs/superpowers from version control
  ([`31ba15c`](https://github.com/getsimpledirect/ghost-narrator/commit/31ba15c64ef42c4c87685b02e72faa7128007b75))

- Initial commit — ghost-narrator standalone fork
  ([`0cccb42`](https://github.com/getsimpledirect/ghost-narrator/commit/0cccb42b689fe6d833e12945a53befd7c329cd32))

Copied from workos-mvp/ghost-narrator. Deleted superseded
  docs/plans/2026-04-01-qwen3-tts-migration.md. Spec and implementation plans added to
  docs/superpowers/.

- **plan-c**: .env.example, .gitignore, minor refs, README, NOTICE, docs rewrite
  ([`0a9a10c`](https://github.com/getsimpledirect/ghost-narrator/commit/0a9a10cdb64b180adcaa8e4f94e1c76d6b12178c))

### Documentation

- Fix stale references in ARCHITECTURE.md and tts_engine.py
  ([`0c32e82`](https://github.com/getsimpledirect/ghost-narrator/commit/0c32e82b1c5793b643504f7b3e5ee3f42692cbee))

- Update n8n component description (no longer calls Ollama directly) - Update workflow descriptions
  (trigger + embed, not orchestrate) - Rewrite TTS Pipeline section with all 9 stages including
  narration, quality check, crossfade, silence trimming, two-pass mastering - Fix stale Fish Speech
  / CLI-based inference references - Update tts_engine.py docstring

- Replace ASCII architecture diagram with mermaid flowchart
  ([`96593b5`](https://github.com/getsimpledirect/ghost-narrator/commit/96593b58dcd9b119c2de1ce299888a3ce4a0456d))

- Rewrite all diagrams as clean LR mermaid flowcharts
  ([`3cd1007`](https://github.com/getsimpledirect/ghost-narrator/commit/3cd1007a2083f4b934e80795fd893d766bcce90b))

- Architecture Overview: TD subgraph mess → clean LR flowchart - Narration Pipeline: ASCII art →
  mermaid flowchart TD - README: TD → LR for consistency, simplified node labels

- Simplify diagrams — TD without subgraphs, no LR stretch
  ([`5f8cfd8`](https://github.com/getsimpledirect/ghost-narrator/commit/5f8cfd8cf3ca23e584db2ca7e50728fcc8ae67fe))

- Architecture Overview: TD, no subgraphs, short labels with \n - Narration Pipeline: TD linear
  chain, no subgraphs - README: matching TD style

- Sync architecture diagram fix from feature branch
  ([`f0f9982`](https://github.com/getsimpledirect/ghost-narrator/commit/f0f998217f2e680b56d9147885a48edf88379ff9))

- Sync diagram improvements to main
  ([`c2c2131`](https://github.com/getsimpledirect/ghost-narrator/commit/c2c2131460d48cb1db588ba347ce0bbfeb05f323))

- Sync simplified diagrams to main
  ([`7b35ecc`](https://github.com/getsimpledirect/ghost-narrator/commit/7b35ecca8218f724d1237c910765eab632ef746a))

- **readme**: Match workos-mvp style with banner, cost comparison, architecture diagram
  ([`6d6ff34`](https://github.com/getsimpledirect/ghost-narrator/commit/6d6ff347d917d47e193ea0ec9746bea4ded487fb))

- **readme**: Match workos-mvp style with banner, cost comparison, architecture diagram
  ([`3892e2c`](https://github.com/getsimpledirect/ghost-narrator/commit/3892e2c3ba77cbca354d0904a0613c4a26efbcc2))

### Features

- **audio**: Improve TTS output quality without performance cost
  ([`aeb8b3e`](https://github.com/getsimpledirect/ghost-narrator/commit/aeb8b3e1922ed26b5a6ac4765ee66c78a99c0c16))

1. Text preprocessing (clean_text_for_tts): strips stray markdown, smart quotes, URLs, expands
  abbreviations (Dr.→Doctor, e.g.→for example), normalizes ellipsis and special Unicode. ~1ms per
  chunk.

2. Crossfade at chunk boundaries: 15ms crossfade eliminates clicks/pops where one WAV ends and the
  next starts with different spectral character. ~2ms per join.

3. Prosodic-aware splitting: long sentences now split at clause boundaries (commas, semicolons,
  conjunctions) rather than arbitrary word positions. ~0.5ms per chunk.

4. Silence trimming per chunk: trims leading/trailing silence >100ms from each TTS chunk before
  concatenation. Removes ~6-15s of dead air from a typical 30-chunk article. ~5ms per chunk.

Total overhead for 30-chunk article: ~250ms.

- **audio**: Tiered quality — bitrate/samplerate/LUFS from EngineConfig
  ([`bb6054c`](https://github.com/getsimpledirect/ghost-narrator/commit/bb6054c47f26bf6b150f392bd85de49b7aef01d2))

- **config**: Wire ENGINE_CONFIG into config — hardware-aware settings
  ([`50a8afe`](https://github.com/getsimpledirect/ghost-narrator/commit/50a8afe22c98e62fba0e8835d58abcd1c53e74dd))

- **hardware**: Add HardwareTier probe and EngineConfig selector
  ([`5fb41a0`](https://github.com/getsimpledirect/ghost-narrator/commit/5fb41a01e880205d7b44a8e46668d1dce558f486))

- **high-vram**: Premium features for 20+ GB GPU tier
  ([`4c7e82d`](https://github.com/getsimpledirect/ghost-narrator/commit/4c7e82d19bd550b3c49d52a43710dc1e957249a0))

Config changes: - fp32 TTS precision (cleaner audio, less quantization noise) - 2 parallel TTS
  workers (~2x faster synthesis) - qwen3:14b-q4 LLM (significantly better narration quality) -
  Chunked narration strategy (enables pipelined narrate+synthesize)

New features: 1. Pre-computed voice reference tokens — cached at startup, saves 2-5s/job 2.
  Multi-voice for quoted speech — pitch-shifts quotes for speaker differentiation 3. Automatic
  quality re-synthesis — re-synthesizes chunks with excessive silence 4. Background ambience mixing
  — room tone overlay during mastering 5. Audio super-resolution — SoX resampler for upsampling

Updated docs: - README.md: hardware tiers table, architecture diagram, pipeline flow -
  ARCHITECTURE.md: tier detection table, VRAM budget breakdown

- **infra**: Hardware-probe, ollama, docker-compose overhaul, GPU overlay, n8n multi-scheme URIs
  ([`bb89a06`](https://github.com/getsimpledirect/ghost-narrator/commit/bb89a06819752434608d01fa22a915c18a38cd96))

- **job**: Wire NarrationStrategy into tts_job pipeline, update health + schemas
  ([`c365ceb`](https://github.com/getsimpledirect/ghost-narrator/commit/c365cebea8c62fcb9f43cd84f3b76f22a6145ba9))

- **narration**: Layered information preservation during LLM conversion
  ([`18dab78`](https://github.com/getsimpledirect/ghost-narrator/commit/18dab78f7bb2bd82a68f69c7fd6c2e314c0681fe))

Layer 1 — Prompt: restructured with 10-item preservation checklist covering numbers, dates, named
  entities, quotes, technical terms, URLs, sections, list items, causal relationships, and caveats.

Layer 2 — Validator: added date/time, URL, email regex patterns. Added word count ratio check (flags
  if narration <55% of source length).

Layer 3 — Chunk overlap: ChunkedStrategy now overlaps 1 paragraph at chunk boundaries so the LLM has
  context from the previous chunk's end.

Layer 4 — LLM completeness check: HIGH_VRAM tier gets a second LLM call that compares source vs
  narration and identifies missing items. If issues found, re-narrates with explicit missing-item
  list. Skipped in iter mode (chunks consumed immediately by TTS pipelining).

- **narration**: Narrationvalidator, prompts, ChunkedStrategy + SingleShotStrategy
  ([`a3de793`](https://github.com/getsimpledirect/ghost-narrator/commit/a3de793004db68077e930fd8e35af07cc558b1ef))

- **storage+voices**: Pluggable storage backends (local/GCS/S3) + voice profiles + upload API
  ([`04da680`](https://github.com/getsimpledirect/ghost-narrator/commit/04da6800f0e40d59878d9d54338475c36248e3aa))

### Refactoring

- Remove vLLM/ChromaDB/SearXNG — rename VLLM_ vars to LLM_
  ([`2bec514`](https://github.com/getsimpledirect/ghost-narrator/commit/2bec514d5a93df2f0cd6ed3ea75d563d05d34d4a))

- Rename VLLM_BASE_URL → LLM_BASE_URL and VLLM_MODEL_NAME → LLM_MODEL_NAME throughout:
  docker-compose.yml, n8n workflow JSONs, .env.example, SETUP_GUIDE.md, ARCHITECTURE.md, README.md,
  config.py, CHANGELOG.md - n8n workflows now read $env.LLM_BASE_URL / $env.LLM_MODEL_NAME -
  LLM_MODEL_NAME default in docker-compose n8n env is now empty (auto from tier) instead of
  hardcoded Qwen3-14B-AWQ - Remove ChromaDB and SearXNG references (not part of this stack) -
  Reframe override docs: "any OpenAI-compatible API" not "vLLM"

- **n8n**: Remove LLM narration from n8n, TTS service owns narration
  ([`a677f61`](https://github.com/getsimpledirect/ghost-narrator/commit/a677f61790fff0b413fcd2519d6d300d2c40ed06))

- Remove 'Convert to Narration (LLM)' and 'Parse Narration' nodes from ghost-audio-pipeline.json —
  n8n now sends raw article text directly - Remove same nodes from
  static-content-audio-pipeline.json - TTS service handles LLM narration internally (via narration/
  package) - Update SETUP_GUIDE.md: remove LLM_BASE_URL/LLM_MODEL_NAME from n8n required vars,
  update Ollama troubleshooting section - Update ARCHITECTURE.md: narration pipeline diagram,
  node-by-node explanation, orchestration flow

- **scripts**: Unified install.sh, move Docker internals to scripts/init/, delete redundant scripts
  ([`6dc57e0`](https://github.com/getsimpledirect/ghost-narrator/commit/6dc57e0665f0c6f7398498683c8cb5ea57955c12))
