# CHANGELOG


## v2.13.9 (2026-04-22)

### Chores

- **tts-service**: Add MIT license header to remaining test files
  ([`8cef539`](https://github.com/getsimpledirect/ghost-narrator/commit/8cef53996579fde574fc3203085b6ad37aafc3e8))

Three non-empty test files were missed by the earlier blanket sweep in 30ca49d. Brings the
  tts-service/tests/ tree to full MIT header coverage on all files that contain code. Empty
  __init__.py package markers remain header-less, matching existing convention.

- tts-service/tests/core/test_tts_engine.py: prepend 21-line MIT header -
  tts-service/tests/utils/test_normalize.py: prepend 21-line MIT header -
  tts-service/tests/utils/test_text_pause.py: prepend 21-line MIT header

### Refactoring

- **tts-service**: Expose package API via __init__ re-exports
  ([`0315a05`](https://github.com/getsimpledirect/ghost-narrator/commit/0315a05e84dc7911d3accdc4f826f4378d7930fd))

Align three outlier packages with the re-export convention already used in storage/, synthesis/, and
  api/.

- app/domains/voices: VoiceRegistry, validate_and_save, validate_reference_wav -
  app/domains/tts_config: initialize, get/save/clear_overrides, get_effective_config,
  get_tier_defaults - app/api/rate_limit_middleware: RateLimitMiddleware


## v2.13.8 (2026-04-22)

### Bug Fixes

- **quality-check**: Scale mid-phrase drop threshold with chunk duration
  ([`11b326a`](https://github.com/getsimpledirect/ghost-narrator/commit/11b326ae9f35854b4263a43ce8151d8f2e13388d))

The fixed threshold of >3 drops rejected healthy long-form narration: a 400-word (~160s) segment
  contains 20+ sentence boundaries, many of which register as 0.3-1.5s amplitude dips under the
  rolling-median check. Production logs showed a clean retry producing only 6 drops in 160s (1 per
  27s — natural cadence) still being aborted after exhausting all 4 resynthesis strategies.

- tts-service/app/domains/synthesis/quality_check.py: - tighten drop-duration window from 0.3-1.5s
  to 0.6-2.0s; natural Qwen3-TTS punctuation pauses are 200-500ms, so the previous 0.3s floor
  counted them as drops - scale rejection threshold from fixed >3 to >max(3, duration_s / 20); ~1
  drop per 20s of audio tolerated, floor preserves short-chunk behaviour - include duration-aware
  tolerance in the failure reason string - update docstring listing the 9 gate checks

- tts-service/tests/domains/synthesis/test_quality_check.py: - retarget existing drop tests to
  drop_dur_s=0.8 so they sit unambiguously inside the new 0.6-2.0s window -
  test_too_short_drops_ignored now uses 400ms drops to validate the 600ms floor covers the
  natural-pause range - add test_threshold_scales_with_duration: 160s chunk + 6 drops now passes
  (would have failed before) - add test_threshold_scaling_still_rejects_excessive_drops: 100s chunk
  + 8 drops still fails — scaling loosens, does not remove the gate


## v2.13.7 (2026-04-22)

### Bug Fixes

- **config**: Handle empty-string env vars from docker-compose ${VAR:-} expansion
  ([`d5c0b94`](https://github.com/getsimpledirect/ghost-narrator/commit/d5c0b94620c4be9310fb8988507278dedb60f544))

docker-compose.yml passes "" (empty string) for AUDIO_SAMPLE_RATE, TARGET_LUFS, MP3_BITRATE, and
  SINGLE_SHOT_SEGMENT_WORDS when they are absent from .env, using the ${VAR:-} syntax.
  os.environ.get(key, default) only uses the default when the key is absent — not when it is
  present-but-empty — so int("") and float("") raised ValueError at import time, crashing the
  service on startup.

- config.py: switch affected lines to `os.environ.get(key) or fallback` pattern so an empty string
  falls through to the hardware-tier default, matching the documented behaviour ("leave blank to use
  hardware-tier defaults") - Covers: AUDIO_SAMPLE_RATE, TARGET_LUFS, MP3_BITRATE,
  SINGLE_SHOT_SEGMENT_WORDS


## v2.13.6 (2026-04-22)

### Bug Fixes

- **quality-check**: Add windowed F0 gate, mid-phrase drop detection, retry seed variation
  ([`da6b7ba`](https://github.com/getsimpledirect/ghost-narrator/commit/da6b7ba70138e2df41e1ca6c84e4cc4d2fd54058))

Addresses three failure modes observed in long-form synthesis where the existing whole-chunk
  acoustic gate passed bad regions:

- tts-service/app/domains/synthesis/quality_check.py: - Add windowed F0 gate (Fix 1): 3 s sliding
  windows with 50% overlap, each analyzed independently for F0 drift from reference. Rejects chunk
  if >5% of windows show >6 semitones drift. Catches garbled regions that whole-chunk median
  smoothing masks — a 20 s garbled region inside a 180 s chunk shifts the overall median ~11% (under
  the 2.5 st hard threshold) but produces >11% bad windows. Gate is a no-op when reference_f0 is
  None. - Add mid-phrase drop detection (Fix 2): rejects chunk if >3 drops of 0.3–1.5 s where RMS
  falls below 10% of the rolling 2 s local median. Catches mid-sentence amplitude collapses from
  Qwen3-TTS coherence loss. Up to 3 drops tolerated — natural hesitation pauses can look similar. -
  Both analyses share a single soundfile.read() call and run inside a non-fatal try/except so gate
  errors fail open, consistent with existing gate behavior. - Vary seed across retry strategies (Fix
  3): each of the 4 re-synthesis strategies now receives seed = (original_seed + attempt × 7919) %
  2³¹. Prime offset prevents all seeds landing on the same residue class modulo any small number.
  Previously all retries reused the original seed, which could replay the same failing decoding
  path. - Update _chunk_passes_acoustic_gate docstring to list all 9 checks.

- tts-service/tests/domains/synthesis/test_quality_check.py: - TestWindowedF0Gate: localized drift
  fails, uniform pitch passes, no-ref skip - TestMidPhraseDropDetection: >3 drops fail, ≤3 pass,
  <300 ms ignored - TestRetrySeeds: source inspection confirms prime-offset arithmetic present;
  arithmetic correctness verified directly

- docs/ARCHITECTURE.md: - Stage 4 section rewritten: removes three non-existent checks (silence
  ratio, clipping, low energy) and documents the actual acoustic gate (hard/soft/regional checks)
  including the two new regional checks - "Seed determinism" bullet corrected to "Seed variation
  across retries"

- .gitignore: add AI coding tool artifacts (CLAUDE.md, .claude/, graphify-out/, .code-review-graph/,
  .opencode/, .swarm/, .claude-flow/, AGENTS.md)


## v2.13.5 (2026-04-22)

### Bug Fixes

- **install**: Harden installer — secrets, validation, LLM override, summary
  ([`97a9641`](https://github.com/getsimpledirect/ghost-narrator/commit/97a9641dc414accfff339925cf604b6a751ea5b1))

- Move secret auto-generation (N8N_ENCRYPTION_KEY, REDIS_PASSWORD, N8N_GHOST_WEBHOOK_SECRET,
  TTS_API_KEY) outside the configure prompt so they are always generated even when user skips
  interactive setup; TTS_API_KEY is required by validate_config() and was silently missing on skip -
  Change 'Configure .env now?' default from N to Y — first-time users always need to configure - Add
  HARDWARE_TIER input validation loop; reject values other than cpu_only|low_vram|mid_vram|high_vram
  with a clear error message - Create secrets/ directory unconditionally; docker-compose.yml
  bind-mounts it and older Docker versions error when the host path does not exist - Add external
  LLM override prompt (LLM_BASE_URL, LLM_API_KEY, LLM_MODEL_NAME) for users who want a hosted
  OpenAI-compatible API instead of bundled Ollama/vLLM - Rewrite completion summary as numbered
  steps with actual n8n workflow import instructions, Ghost webhook setup steps, TTS API docs URL,
  and a highlighted block showing N8N_GHOST_WEBHOOK_SECRET so it cannot be missed


## v2.13.4 (2026-04-22)

### Bug Fixes

- Forward all user-configurable env vars and add TTS_LANGUAGE to installer
  ([`a6e7c44`](https://github.com/getsimpledirect/ghost-narrator/commit/a6e7c448708f01cd4c9efd18eb056e1cf8b6f970))

- docker-compose.yml: add SINGLE_SHOT_SEGMENT_WORDS, SINGLE_SHOT_MAX_WORDS, SINGLE_SHOT_OVERLAP_MS,
  MP3_BITRATE, AUDIO_SAMPLE_RATE, TARGET_LUFS, and MAX_JOB_DURATION_SECONDS to tts-service
  environment block — these were documented in README but silently dropped by Docker Compose when
  unlisted - .env.example: add TTS_LANGUAGE, SINGLE_SHOT_SEGMENT_WORDS/MAX_WORDS/OVERLAP_MS,
  MAX_JOB_DURATION_SECONDS, LOG_LEVEL, LOG_FORMAT as commented template entries - install.sh: add
  TTS_LANGUAGE prompt in voice setup section so non-English users can set the language code (zh, ja,
  de, etc.) at install time

### Chores

- Sync scripts and env.example with fp16 and DRY_RUN_GATE
  ([`ca8135a`](https://github.com/getsimpledirect/ghost-narrator/commit/ca8135a1943aa49efb237158ee1c21cff2953300))

- scripts/init/vllm-init.sh: fix stale bf16→fp16 in TTS reserve comment - .env.example: add
  DRY_RUN_GATE commented entry under Audio Quality Override

### Documentation

- Sync bf16→fp16 and add DRY_RUN_GATE across all docs
  ([`2dbade9`](https://github.com/getsimpledirect/ghost-narrator/commit/2dbade9262b2099a1b68c9d0cc53c74bccd201f7))

- tts-service/README.md, QUICKSTART.md, docs/ARCHITECTURE.md: replace remaining stale bf16
  references with fp16 for HIGH_VRAM tier - tts-service/README.md, docs/ARCHITECTURE.md: add
  DRY_RUN_GATE env var entry (default false = enforce, true = shadow/calibration) - test cleanup:
  remove unused imports and variable in test_tts_job.py and test_narration_strategy.py (pre-existing
  lint noise)


## v2.13.3 (2026-04-22)

### Bug Fixes

- **tts-service**: Propagate DRY_RUN_GATE into container; flip default to false
  ([`d9340a9`](https://github.com/getsimpledirect/ghost-narrator/commit/d9340a9f0e0832d7c2b3a6a5be47d9e643ea3758))

- docker-compose.yml: add DRY_RUN_GATE=${DRY_RUN_GATE:-false} to tts-service environment block so
  the value from .env reaches the container (was silently ignored — env var never forwarded) -
  quality_check.py: change _DRY_RUN_GATE default from 'true' to 'false' so a missing env var
  enforces the gate rather than silently bypassing it

Shadow mode (DRY_RUN_GATE=true) now requires explicit opt-in; the safe default is enforcement. This
  matches the semantics of every other quality gate in the pipeline.


## v2.13.2 (2026-04-21)

### Bug Fixes

- **mastering**: Preserve LUFS during true-peak remediation
  ([`e74f5e4`](https://github.com/getsimpledirect/ghost-narrator/commit/e74f5e4707f988e57f3035b445c9e6bc1ed21c73))

- mastering.py: replace flat volume reduction in remediation pass with a second loudnorm pass
  (I=target_lufs, TP=-2.5, LRA=11) followed by alimiter=limit=0.708 (-3.0 dBFS sample peak → ~-1.5
  dBTP true peak) - mastering.py: add post-remediation ebur128 verification and log the resulting
  true peak so loudness outcome is visible in logs - tts_job.py: loosen LUFS gate tolerance from
  ±2.5 to ±3.0 LUFS

Previous remediation did compensation_db = -(measured_tp + 2.0) flat volume reduction which fixed TP
  but knocked LUFS from -14.7 to -17.8, failing the loudness gate. The new loudnorm-based
  remediation targets the original LUFS while tightening the true-peak ceiling.

±3.0 LUFS matches AES podcast distribution acceptable range (-11 to -17 LUFS) and accounts for the
  mastering pipeline's TP/loudness tradeoff inherent in loudnorm + alimiter chains.

- **mastering**: Restore defensive alimiter after loudnorm pass-2
  ([`a17bc2d`](https://github.com/getsimpledirect/ghost-narrator/commit/a17bc2d5bb412e0cab6e19795bda5efe286eb329))

- mastering.py: add alimiter=limit=0.794 after loudnorm in both two-pass and single-pass paths
  (previously removed from two-pass) - mastering.py: add INFO-level logging of pass-1 loudnorm
  measurements (I, TP, LRA, thresh) for diagnostics - mastering.py: harden LRA to 11 in all loudnorm
  calls; switch print_format to summary for pass-2 so ffmpeg logs loudnorm result - tests: update
  test_alimiter_command_contains_correct_limit comment to reflect that alimiter is now present in
  all filter chain paths

Empirical test showed loudnorm linear=true output +1.1 dBTP despite TP=-2.0 target. loudnorm's TP
  control does not catch intersample peaks from the MP3 encoder's reconstruction filter.
  alimiter=limit=0.794 (-2.0 dBFS sample peak) is the only reliable hard ceiling.


## v2.13.1 (2026-04-21)

### Performance Improvements

- **tts-service**: Reduce 1.7B noise ceiling to 400 words + fp16 precision
  ([`af191cc`](https://github.com/getsimpledirect/ghost-narrator/commit/af191cc766fb6c622f96ab2d9e88b8a023efa062))

- hardware.py: switch HIGH_VRAM tts_precision bf16 → fp16 - fp16 has 10 mantissa bits vs bf16's 7,
  improving pitch stability for the speaker encoder's fine pitch features on Ada (sm_89 / L4) -
  Existing fp32 overflow fallback in tts_engine.py handles rare NaN cases - hardware.py: reduce
  _NOISE_CEILING['1.7B'] 650 → 400 words - 400-word segments ≈ 170s autoregressive generation vs
  270s at 650 words - Shorter generation windows reduce the distance voice identity can drift -
  hardware.py: reduce HIGH_VRAM tts_chunk_words 300 → 200 words - Smaller chunk-level splits inside
  each segment for additional safety margin - hardware.py: update tts_max_new_tokens comment (3.16×
  headroom at 400 words) - config.py, text.py: update noise ceiling references 650 → 400 -
  tests/core/test_hardware.py: update 3 assertions from 650 → 400 - docs/ARCHITECTURE.md, README.md:
  update tier tables (bf16 → fp16, 650 → 400) - run-docker.sh: remove stale
  SINGLE_SHOT_SEGMENT_WORDS=3000 default (now passes empty string; auto-probe from VRAM takes
  effect)

Intervention 2 + 3 of the voice-drift mitigation sequence.


## v2.13.0 (2026-04-21)

### Features

- **tts-service**: Cascading segment splitter with pipeline guard
  ([`6fc35ee`](https://github.com/getsimpledirect/ghost-narrator/commit/6fc35eedd807ac007a6518b6af5f76650db24489))

- app/utils/text.py: rewrite split_into_large_segments with 4-stage cascade - Stage 1: paragraph
  split (fast path for well-formatted narration) - Stage 2: sentence-boundary split for oversized
  paragraphs (new _SENTENCE_BOUNDARY_RE) - Stage 3: emergency word-count split when no sentence
  boundaries exist - Stage 4: accumulate expanded units into final ~target_words segments - Safety
  log at ERROR level if any segment still exceeds target × 1.3 - app/domains/job/tts_job.py: add
  hard guard after split_into_large_segments - Raises RuntimeError if any segment exceeds seg_words
  × 1.3 words - Logs segment plan (count + per-segment word counts) before synthesis loop -
  tests/utils/test_text_split.py: new test file covering all 4 stages plus trailing-merge, hard-cap
  invariants, and real-world narration simulation

Fixes the 5,719-word single-segment failure mode where a narration with no paragraph breaks produced
  one giant segment, causing 9+ minutes of voice drift in a single Qwen3-TTS call.


## v2.12.6 (2026-04-21)

### Bug Fixes

- **mastering**: Replace alimiter with loudnorm true-peak control and add post-write verification
  ([`a5c4c07`](https://github.com/getsimpledirect/ghost-narrator/commit/a5c4c07e318e0648658950a50cb5d69410cba289))

alimiter caps sample peak but not intersample (true) peak. Observed result: mastering completed
  successfully but output measured +1.6 dBTP.

- Two-pass path now drops alimiter entirely: loudnorm with linear=true and measured_TP feeds the
  exact measured overshoot back into the gain calculation, making it the true-peak limiter -
  Single-pass fallback retains alimiter at 0.794 (tighter than old 0.891) as safety net since
  single-pass loudnorm doesn't apply reliable TP control - Add post-write true-peak verification via
  ebur128=peak=true; if output still exceeds -1.0 dBTP, apply compensating gain + alimiter
  remediation pass - DEFAULT_TRUE_PEAK lowered -1.5 → -2.0 to give loudnorm 1 dB margin against its
  own TP measurement uncertainty


## v2.12.5 (2026-04-21)

### Bug Fixes

- **quality-gate**: Recalibrate thresholds against real TTS output
  ([`3f73823`](https://github.com/getsimpledirect/ghost-narrator/commit/3f7382387d0b56b7060cfd8219d46976771ef772))

- Loosen flatness ceiling 0.025 → 0.18 (real Qwen3-TTS voice-cloned output measures ~0.15 flatness —
  old threshold rejected healthy chunks) - Loosen onset rate ceiling 6.5 → 8.0 (narration pace
  commonly 6.5-7.0/s) - Tighten F0 deviation threshold 3.0 → 2.5 semitones; F0 drift is a hard
  identity signal and now fails independently as a hard check - Convert flatness + onset_rate from
  independent hard checks to a co-occurrence gate: both must trip simultaneously to reject a chunk;
  a single-flag trip logs INFO and passes (normal TTS variation) - Add DRY_RUN_GATE env var (default
  true): gate logs failures but always returns pass, enabling threshold calibration from production
  data before enforcing; conftest.py sets it to false for tests - Add regression test for healthy
  high-flatness single-flag pass - Fix burst rate in test_high_onset_rate_fails (10Hz not 20Hz): at
  20Hz burst_len equals interval so no silent gaps form and onset detection returns 0/s despite the
  nominal rate


## v2.12.4 (2026-04-21)

### Bug Fixes

- **tts-engine**: Move self._ready = True before warmup synthesis call
  ([`31e865e`](https://github.com/getsimpledirect/ghost-narrator/commit/31e865e294032924f2240cb41e9ced9a430d272c))

synthesize_to_file() guards on self._ready, so calling it from inside initialize() while _ready is
  still False raises TTSEngineError and the warmup silently degrades to a warning — leaving the
  cold-start path unprotected. All model loading, voice caching, and probing are complete at the
  point of warmup, so setting the flag first is semantically correct and safe (the engine readiness
  event is not signalled until initialize() returns, so no jobs can race in through the API).


## v2.12.3 (2026-04-21)

### Bug Fixes

- **tts-service**: Promote acoustic gate logs to INFO and add warmup synthesis
  ([`6336f61`](https://github.com/getsimpledirect/ghost-narrator/commit/6336f61aada56ea4f23de841590c7d7e568085cb))

- _chunk_passes_acoustic_gate: return type bool → tuple[bool, str]; callers updated to unpack or
  index [0] so gate reason is propagated to the WARNING log at the resynthesis dispatch site - All 6
  gate-failure logger.debug calls promoted to logger.info so which check fired is visible in
  production without enabling debug logging - tts_engine.py: burn one short warmup synthesis after
  probe_optimal_segment_words to normalise KV-cache and codec dynamics before the first real job —
  prevents cold-start acoustic artefacts on Chunk 0 of the first article - tests: assertions updated
  to unpack (passed, reason) and assert reason is non-empty on failure paths, empty string on pass


## v2.12.2 (2026-04-21)

### Bug Fixes

- **tts-service**: Stop shipping broken audio — acoustic quality gate, hallucination loop
  prevention, voice drift cascade fix
  ([`d3a5562`](https://github.com/getsimpledirect/ghost-narrator/commit/d3a5562383267fa386a32dc95ff2755bb575d925))

## Problem

The pipeline was shipping broken audio silently. A 32-minute narration exhibited: - 9+ minutes of
  hallucinated buzz (F0 pinned at 380–400 Hz, onset rate 8+ /s) - Voice identity drift across four
  distinct pitch ranges within one file (90 → 400 → 190 → back) - +1.01 dBTP true peak with 3,552
  clipping events (mastering fell through to raw-export fallback) - 29 seam-level shifts ≥ 2.5 dB

No error was raised. The job completed with status `done`.

---

## Root causes fixed

### 1. Hallucination loop ran to near-full budget (`tts_engine.py`)

`_TTS_TOKENS_PER_SECOND` was `50` — Qwen3-TTS-12Hz models emit **12** codec tokens/second. A
  300-word segment had an 8,400-token budget (~700 s of headroom) instead of the correct 1,966 (~164
  s). A stuck decoder could run uninterrupted for nearly 12 minutes.

**Fix:** codec rate corrected to 12, `_SECONDS_PER_WORD` to 0.42 (143 WPM), headroom to 1.3×.
  300-word budget: **8,400 → 1,966 tokens**.

### 2. No detection of hallucinated chunks (`quality_check.py`)

No acoustic check existed before concatenation. Hallucinated output was stitched in silently.

**Fix:** `_chunk_passes_acoustic_gate` on every synthesized chunk: - Duration ratio vs expected
  (×0.4–1.6 from word count) - Onset rate ≤ 6.5 /s - Spectral flatness ≤ 0.025 - F0 within 3
  semitones of reference voice

Failures trigger `_resynthesize_with_strategies` — 4 input-modifying strategies in escalating order:
  1. `repetition_penalty=1.2` — targets repetition loops 2. Half-split on any punctuation,
  bidirectional search from midpoint 3. Quarter-split 4. Aggressive text sanitization (strip
  parentheticals, digits, ALL-CAPS)

Exhausting all strategies raises `ChunkExhaustedError`, failing the job.

### 3. Autocorrelation F0 estimator had octave errors (`quality_check.py`)

The naive estimator returned F0/2 or 2×F0 when even harmonics were strong — the hallucination region
  (380–400 Hz) is exactly 4× the 95 Hz reference, consistent with this failure mode. This caused the
  speaker-drift gate to compare the wrong number against the reference.

**Fix:** voicing threshold `0.3 → 0.5`, octave-down correction (`corr[peak_lag//2] ≥ 0.9 ×
  corr[peak_lag]`), minimum 10 voiced frames required.

### 4. Tail conditioning propagated drifted voice embeddings (`tts_job.py`)

On HIGH_VRAM, each segment conditions on the last 2.5 s of the previous segment. Once segment K
  hallucinated, segment K+1 inherited the bad embedding — drift cascaded for the rest of the job.
  The four distinct F0 ranges in the analysed file trace directly to this.

**Fix:** before extracting the tail, check the synthesized segment's F0 against the reference. If
  drift > 3 semitones or F0 is undetectable, discard the tail — next segment falls back to the
  default voice sample, breaking the cascade.

### 5. Critical LLM truncation silently fed raw text to synthesis (`strategy.py`, `tts_job.py`)

When the LLM truncated below `CRITICAL_WORD_RATIO`, the strategy returned raw HTML-normalized
  article text — with markdown residue, URLs, and code identifiers — directly to synthesis. Those
  inputs are known hallucination triggers.

**Fix:** both `return chunk` / `return text` fallbacks replaced with `raise NarrationError`. Added
  `except NarrationError: raise` in `tts_job.py` so it propagates instead of being caught by the
  generic narration fallback handler (which would have re-applied the same raw-text path).

### 6. Speakability check had no recovery path (`service.py` → `strategy.py`)

`is_speakable_text` was called inside `synthesize_single_shot`. At that point the only option on
  failure is to abort the job.

**Fix:** moved to the narration retry loop. The LLM gets a targeted one-shot retry ("Your narration
  contained a URL; rewrite without it") before synthesis runs. Snake_case rule softened from 2+ to
  3+ components (`open_source`, `well_known` no longer rejected). Return type changed to
  `tuple[bool, str | None]`.

### 7. Mastering failure shipped unmastered audio silently (`tts_job.py`)

The raw-export fallback (`AudioSegment.export`) has zero limiting. The +1.01 dBTP / 3,552 clipping
  events were produced on this path — mastering had timed out and the fallback ran without anyone
  noticing.

**Fix:** `validate_audio_quality` already measured true peak, LUFS, and silence gaps on every job —
  it just never failed the job. Now it does: - `true_peak_dbfs > −1.0 dBTP` → `RuntimeError` -
  `|integrated_lufs − TARGET_LUFS| > 2.5 LU` → `RuntimeError` - `long_silence_gaps_count > 0` →
  `RuntimeError`

`alimiter` limit corrected to `0.891` (was `0.794`), `DEFAULT_TRUE_PEAK` to `−1.5` (was `−2.0`).

### 8. Reference voice not validated before GPU work (`voices/validate.py`)

A corrupt or too-short reference WAV would fail mid-job after minutes of GPU time.

**Fix:** validated at job start — duration 5–120 s, noise floor ≤ −55 dBFS.

## Files changed

| File | What changed | |---|---| | `app/core/tts_engine.py` | Codec rate constants,
  `_compute_max_new_tokens` | | `app/core/exceptions.py` | `ChunkExhaustedError` | |
  `app/domains/synthesis/quality_check.py` | Acoustic gate, F0 octave correction, 4-strategy retry |
  | `app/domains/job/tts_job.py` | Tail F0 gate, `NarrationError` propagation, final-file quality
  gate | | `app/domains/narration/strategy.py` | Speakability check at narration stage, fallback
  removal | | `app/domains/synthesis/mastering.py` | Limiter tightening | |
  `app/domains/voices/validate.py` | Reference voice validation (new) | | `app/utils/text.py` |
  `is_speakable_text` tuple return, softened snake_case rule |

16 files changed, +1,493 / −149 lines. **259 tests passing.**

## Test plan

- [ ] Deploy to staging; submit an article that previously hallucinated — expect clean audio or
  `ChunkExhaustedError` with clear logs, not silent `done` - [ ] Verify `NarrationError` surfaces as
  a job failure (not silent raw-text synthesis) when the LLM truncates critically - [ ] Verify
  final-file gate fires when mastering subprocess is forced to fail - [ ] Monitor
  `ChunkExhaustedError` rate over first 20 production jobs — target < 5% - [ ] Monitor
  `is_speakable_text` rejection rate — target < 1% of narrated chunks

### Continuous Integration

- **release**: Rewrite release workflow with structured AI-free notes
  ([`308a55f`](https://github.com/getsimpledirect/ghost-narrator/commit/308a55fd51a3dc81646b7ba0b6e777522cac1c55))

.github/workflows/release.yml: - Replace raw commit-dump approach with a Python script that parses
  the PSR-generated CHANGELOG.md section for the current version - Strip PSR hash-link lines from
  section bodies before rendering - Emit sections only when they contain content — empty sections
  are silently skipped, so docs-only releases don't show empty Bug Fixes headers - Auto-detect
  configuration default changes via regex (VAR → newval patterns) and render a Configuration Changes
  table only when matches are found - Generate "What's Unchanged" dynamically: candidate bullets are
  suppressed when their trigger scopes (api, n8n, redis, storage, etc.) appear in the CHANGELOG, so
  only genuinely untouched subsystems are listed - Derive release title in format "v{VERSION}
  {emoji} {Descriptive Title}": dominant section determines emoji; up to two commit scopes
  (tts-service, hardware, n8n, etc.) are resolved to readable English and combined with an action
  word (Fixes, Improvements, Performance, etc.) - Create release with softprops/action-gh-release
  then update title via gh release edit so the name file written by Python drives the final title


## v2.12.1 (2026-04-20)

### Bug Fixes

- **tts-service**: Raise MAX_JOB_DURATION_SECONDS default from 3 h to 8 h
  ([`c3c48f9`](https://github.com/getsimpledirect/ghost-narrator/commit/c3c48f99be37a9694cd0a13cb3033a18c251acc3))

tts-service/app/config.py: - Default raised 10800 → 28800 (3 h → 8 h) - Updated comment: reflects
  real observed timing — 6000-word book chapter synthesizes ~10 × 650-word segments at ~19
  min/segment ≈ 3.2 h, leaving headroom for Phase 1 narration and quality-check re-synthesis

tts-service/README.md: - Config table default updated: 10800 → 28800

### Documentation

- Fix stale config values and LLM references across docs
  ([`d60bd97`](https://github.com/getsimpledirect/ghost-narrator/commit/d60bd97b739784777763d006a8b2b1c9578f660e))

README.md: - Fix "Using an External LLM Provider" intro: now correctly states Ollama handles cpu/low
  VRAM tiers and vLLM handles mid/high VRAM tiers - Add vLLM port 8000 to Production Deployment
  firewall checklist - Rename "Qwen3 LLM" → "Qwen3.5 LLM" in Licensing section

tts-service/README.md: - Fix SINGLE_SHOT_MAX_WORDS default: 4000 → 400 in local dev .env example and
  config table - Remove SINGLE_SHOT_SEGMENT_WORDS from local dev .env example (auto-probed) - Update
  SINGLE_SHOT_SEGMENT_WORDS config table description: default now shown as *(auto)* with VRAM probe
  explanation - Fix OOM troubleshooting: remove wrong "SINGLE_SHOT_MAX_WORDS=4000" advice; replace
  with actionable segment-size and chunk-size guidance - Fix poor audio troubleshooting: remove
  misleading "SINGLE_SHOT_MAX_WORDS=4000" tip; replace with hardware tier upgrade recommendation -
  Credits: add vLLM as bundled LLM backend for mid/high VRAM tiers

tts-service/QUICKSTART.md: - Fix SINGLE_SHOT_MAX_WORDS env example: "4000" → "400" - Remove
  SINGLE_SHOT_SEGMENT_WORDS env example line (auto-probed at runtime) - Fix CPU-only hardware tier
  table: "44.1kHz" → "48kHz"

- **architecture**: Fix stale LLM references and document static content pipeline
  ([`a1b59d0`](https://github.com/getsimpledirect/ghost-narrator/commit/a1b59d01f547abcf0b325ceac0c3e23e75338526))

Qwen3.5 / vLLM coverage: - Fix document header and all prose still saying "Qwen3 model" or "Ollama"
  only; Qwen3.5 is the LLM family used across all tiers - Expand Ollama section into "Ollama / vLLM
  — The Script Writer" with a tier lookup table, explanation of when each backend runs, and why
  Qwen3.5 improved narration quality (better factual preservation, fewer hallucinations) - Stage 1
  LLM narration: clarify Ollama (cpu/low VRAM) vs vLLM (mid/high VRAM) - Narration Pipeline step 4:
  remove "Ollama only" wording - Service startup sequence: add vLLM as the GPU-tier alternative to
  Ollama - Step 6 n8n credentials: correct LLM_BASE_URL note for both backends - Production
  checklist: add vLLM port 8000, fix Ollama-only service check - Cost table: split "Ollama + Qwen3"
  into separate Ollama and vLLM rows

Static content pipeline: - What This Pipeline Does: split into Mode 1 (Ghost) and Mode 2
  (static/arbitrary text) with a curl example and explanation of the static-content-audio n8n
  workflow - Component Deep Dive workflows list: document static-content-audio-pipeline.json fields
  and use cases (book chapters, series content, non-Ghost sources)

Qwen3-TTS implementation details: - Implementation approach section: replace inaccurate
  model.synthesize() / save_wav() references with accurate generate_voice_clone() +
  soundfile.write() API - Document torch.compile() sub-module compilation (talker, code_predictor,
  speaker_encoder) and the 30-60s first-call JIT penalty / 2-4x speedup - Document automatic
  fp16→fp32 fallback on NaN/inf logits

Correctness fixes: - Stage 7 export: 44.1 kHz → 48 kHz (matches all tier configs); 256 kbps
  HIGH_VRAM → 320 kbps (matches hardware.py HIGH_VRAM mp3_bitrate='320k') - ollama-init.sh directory
  entry: Qwen3 → Qwen3.5

- **hardware**: Fix stale 10 GB comment in hardware-probe.sh
  ([`417d09f`](https://github.com/getsimpledirect/ghost-narrator/commit/417d09f24810fe84bc6ef68521e5bb03a93173dd))

- Line 92: "10–18 GB" → "12–18 GB" to match the mid_vram threshold raised in a previous fix (< 12288
  MiB → low_vram)

- **readme**: Center badge row using HTML alignment
  ([`bc22027`](https://github.com/getsimpledirect/ghost-narrator/commit/bc2202757ca35cc33c1681802cdd7343f7a74cf5))

- README.md: wrap all six shield badges in <p align="center"> so they render centered beneath the
  banner image, matching GitHub's HTML rendering behaviour

- **readme,architecture**: Sync docs with dynamic VRAM probe implementation
  ([`e909065`](https://github.com/getsimpledirect/ghost-narrator/commit/e90906596bed515e2628db044dfdfa0764fda787))

README.md: - Add GitHub Stars, Issues, Last Commit, Python 3.11+, Docker Compose v2 badges - Fix
  latency row: ~2-5 min → ~5-30 min (GPU) / longer on CPU - Fix quality row: Good (some trade-offs)
  → Good to excellent (depends on tier) - Add VRAM-probed segments (up to 650 words) to Mid and High
  tier feature columns - Fix SINGLE_SHOT_MAX_WORDS default: 4000 → 400 - Fix
  SINGLE_SHOT_SEGMENT_WORDS: stale 3000 default → *(auto)* with probe note - Quick Start: remove
  redundant docker compose up -d (install.sh already starts) - Quick Start: add GPU compose variant
  note - Quick Start: add n8n workflow import steps (was entirely missing) - Quick Start: add health
  check verification commands

ARCHITECTURE.md: - Add vLLM node to architecture overview diagram (was missing for mid/high VRAM) -
  Add VRAM-probed segments to Mid and High tier feature columns - Replace stale single-shot ≤4000
  words description with seg_words probe logic - Stage 2: replace
  SINGLE_SHOT_MAX_WORDS(4000)/SEGMENT_WORDS(3000) with seg_words and document the probe formula -
  Stage 3: replace hardcoded 4000-word thresholds with seg_words - Troubleshooting: replace wrong
  SINGLE_SHOT_MAX_WORDS=4000 tuning advice with SINGLE_SHOT_SEGMENT_WORDS=200 and remove stale OOM
  entry


## v2.12.0 (2026-04-20)

### Documentation

- **tts-service**: Fix stale context window comment in strategy.py
  ([`07e78dd`](https://github.com/getsimpledirect/ghost-narrator/commit/07e78dd10abb0551e49a4d88d6107fe55f67d7fd))

- Update HIGH_VRAM completeness check comment: "64K context window" → "~29K KV cache" to reflect
  actual --language-model-only KV budget

### Features

- **tts-service**: Dynamic segment sizing from free VRAM post-init
  ([`058671a`](https://github.com/getsimpledirect/ghost-narrator/commit/058671a2b139fdceef3ca51db6e541cb29495a0a))

- Add probe_optimal_segment_words() to hardware.py — measures free VRAM after both models +
  torch.compile() are loaded, computes optimal segment size, clamps to empirical noise ceiling (650
  words for 1.7B, 300 for 0.6B) - Add get_optimal_segment_words() — priority:
  SINGLE_SHOT_SEGMENT_WORDS env var > probed value > hardcoded fallback of 400 - Call probe from
  TTSEngine.initialize() after compile scratch is allocated so free VRAM reflects true runtime
  budget - Replace SINGLE_SHOT_SEGMENT_WORDS/SINGLE_SHOT_MAX_WORDS constants in tts_job.py with
  get_optimal_segment_words() for both the single-shot threshold and segment split size — articles ≤
  seg_words go zero-boundary single-shot; larger articles split at seg_words per segment - Raise
  tts_max_new_tokens HIGH_VRAM: 4000 → 7000, MID_VRAM: 4500 → 7000 to cover 650-word segments (3601
  codec tokens) with 1.94× headroom - Update tests: rename max_new_tokens assertions, add 12 new
  probe tests covering VRAM-limited, noise-limited, CPU, exception, and env override paths


## v2.11.7 (2026-04-20)

### Performance Improvements

- **vllm**: Disable multimodal encoder and enable accurate CUDA graph profiling
  ([`1a2f9d8`](https://github.com/getsimpledirect/ghost-narrator/commit/1a2f9d8021e5c41a6793f8e1aedd2c4a27d95f68))

- Add --language-model-only to vllm-init.sh: Qwen3.5-9B is detected as
  Qwen3_5ForConditionalGeneration and triggers VIT encoder initialization, reserving ~2 GiB of VRAM
  for encoder cache that narration never uses; this flag skips that entirely and redirects the
  memory to decoder KV cache, raising effective context from ~25K to ~40K tokens - Add
  VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=1 to vllm environment: vLLM v0.19.1 recommends this for
  accurate CUDA graph memory accounting during KV cache allocation; previously ~33 MB was
  over-reserved for CUDA graphs and unavailable to the KV cache


## v2.11.6 (2026-04-20)

### Bug Fixes

- **tts-service**: Correct three bugs causing failures on GPU tiers
  ([`1f2fd98`](https://github.com/getsimpledirect/ghost-narrator/commit/1f2fd98b07edb82de63867ea7c74ac84ec970dfa))

- vLLM max_tokens is output-only; sending llm_num_ctx (65536) left no room for prompt input,
  returning HTTP 400 on every narration call - install.sh vLLM routing threshold was 10 GB but
  hardware-probe.sh had already raised the boundary to 12 GB; 10-11 GB GPUs received vLLM config
  with Ollama model tags in tier.env, causing load failure - ffmpeg loudnorm measure pass had a 120
  s ceiling that fires on ~500 MB WAVs from long articles, silently activating the raw-export
  fallback

### Documentation

- Sync all tier tables and component breakdown with current architecture
  ([`871de82`](https://github.com/getsimpledirect/ghost-narrator/commit/871de8259bac97f701d841c0550033e6bf887c15))

Follow-up to the hardware VRAM fixes — documentation was still referencing old boundaries, Ollama
  for GPU tiers, and weights-only TTS VRAM figures.

Changes: - `tts-service/README.md`: update tier table — low <12 GB (was <10 GB), mid 12–18 GB (was
  10–18 GB); correct LLM column to show vLLM/HuggingFace IDs for mid (Qwen/Qwen3.5-4B) and high
  (Qwen/Qwen3.5-9B) tiers. - `tts-service/QUICKSTART.md`: update tier table boundaries (4–8→<12,
  10–16→12–18, 20+→18+) and output quality values to match hardware.py (192k/256k/320k at 48kHz);
  update HARDWARE_TIER example comment. - `docs/ARCHITECTURE.md`: fix HIGH_VRAM tier row — replace
  Ollama model name with HuggingFace vLLM ID (Qwen/Qwen3.5-9B vLLM fp8, 64K ctx); rewrite component
  breakdown table — replace two stale Ollama GPU rows with vLLM rows for mid/high, keep Ollama only
  for low/cpu tiers; update TTS-1.7B VRAM from ~3.4 GB (weights only) to ~5.1 GB (measured runtime)
  for both bf16 and fp16 rows; update LLM_MODEL_NAME config note to clarify the backend format
  difference between Ollama and vLLM tiers.


## v2.11.5 (2026-04-20)

### Bug Fixes

- **hardware**: Raise mid_vram threshold to 12 GB and lower vLLM floor clamp
  ([`912a317`](https://github.com/getsimpledirect/ghost-narrator/commit/912a3172dac8d7053067668ae8817be45fdbba07))

Two related correctness issues introduced by the TTS_RESERVE_MIB=6144 fix:

1. The 0.60 minimum clamp in vllm-init.sh caused OOM on any GPU ≤ 15 GB. After raising TTS reserve
  to 6 GB, the formula gives < 0.60 for all GPUs under 15 GB. The clamp forced vLLM to request more
  VRAM than free (e.g. 0.60 × 12 GB = 7.2 GiB > 6.9 GiB free after TTS). Floor lowered to 0.45 — the
  formula naturally gives ≥ 0.50 for all auto-detected mid_vram GPUs (≥ 12 GB), so the floor only
  applies when a user manually overrides HARDWARE_TIER on an 11 GB GPU.

2. The 10 GB mid_vram threshold was too low. TTS-1.7B (~5.1 GB runtime) + vLLM-4B fp8 (~4.25 GB min)
  + KV cache exceeds 10 GB — a 10 GB GPU would pass the startup check but have < 0.25 GB for KV,
  making the 8K context window effectively unusable for narration. 12 GB provides 1.75 GB of KV
  headroom at mid_vram utilization, enough for full 8K context.

Changes: - `scripts/init/vllm-init.sh`: lower minimum clamp from 0.60 to 0.45; update header comment
  to document the floor and when it applies. - `scripts/init/hardware-probe.sh`: raise low→mid
  boundary from 10240 MiB (10 GB) to 12288 MiB (12 GB). - `tts-service/app/core/hardware.py`: raise
  Python probe threshold from 10 GB to 12 GB; update two stale "TTS (3.4 GB)" inline comments to
  reflect measured ~5.1 GB runtime. - `tts-service/tests/core/test_hardware.py`: add
  test_low_vram_when_11gb to pin the new boundary; update docstrings to reference the 12 GB
  threshold; fix stale "TTS (3.4 GB)" docstring. - `README.md` + `docs/ARCHITECTURE.md`: update tier
  VRAM range tables from <10 GB / 10–18 GB to <12 GB / 12–18 GB; correct ARCHITECTURE.md mid-tier
  row to show vLLM (not Ollama) and current model names.


## v2.11.4 (2026-04-20)

### Bug Fixes

- **hardware**: Correct TTS runtime VRAM estimates across all tiers
  ([`71006da`](https://github.com/getsimpledirect/ghost-narrator/commit/71006dadcdae22cb3411596cc631c242d66e7b83))

The original TTS_SIZE_MIB values used bare model weight sizes, not actual runtime VRAM consumption.
  This caused the Ollama parallel-slot formula (low_vram) to over-allocate slots and both
  documentation values (mid/high_vram) to be inconsistent with the measured runtime of ~5.1 GiB now
  reflected in vllm-init.sh.

Changes: - `scripts/init/hardware-probe.sh`: update TTS_SIZE_MIB comment from "model weights" to
  "runtime VRAM (weights + torch.compile + activations)" to clarify the intended semantic. -
  `scripts/init/hardware-probe.sh` low_vram: TTS_SIZE_MIB 2400 → 3200 (Qwen3-TTS-0.6B fp32: ~2.4 GiB
  weights + ~0.8 GiB torch.compile and activation overhead). On an 8 GB GPU this corrects
  OLLAMA_NUM_PARALLEL from 3 (over-allocated, OOM risk) to 1 (safe). -
  `scripts/init/hardware-probe.sh` mid/high_vram: TTS_SIZE_MIB 3584 → 6144 to match the measured
  runtime value already applied to vllm-init.sh; these fields are unused in the OLLAMA_NUM_PARALLEL
  formula for vLLM tiers but were stale documentation. - `scripts/init/hardware-probe.sh` mid/high
  tier comments: update "TTS (3.4 GB)" → "TTS (~5.1 GB)" to reflect actual measured runtime. -
  `scripts/init/hardware-probe.sh` worked example: recalculate the 8 GB low_vram example with the
  corrected TTS value (result 1, not 3). - `scripts/init/vllm-init.sh` header comment: update
  formula examples to show TTS_RESERVE_MIB=6144 (24 GB L4 ≈ 0.75, 18 GB GPU ≈ 0.67).


## v2.11.3 (2026-04-20)

### Bug Fixes

- **vllm**: Increase TTS VRAM reserve to eliminate startup OOM
  ([`fa7641a`](https://github.com/getsimpledirect/ghost-narrator/commit/fa7641afc50086e8c7c3a59c6182d2e33e366031))

The GPU memory utilization formula assumed TTS needed only 3.5 GiB (bare Qwen3-TTS-1.7B bf16 weight
  size), which caused vLLM to request 18.51 GiB — exceeding the 16.95 GiB available on a 22 GB GPU
  after TTS loaded.

Actual measured TTS runtime consumption on a 22 GB GPU is ~5.1 GiB: - Qwen3-TTS-1.7B bf16 weights:
  ~3.4 GiB - torch.compile scratch + activation buffers: ~0.8 GiB - CUDA context + memory
  fragmentation: ~0.9 GiB

Additionally, each crashed vLLM attempt leaks ~30–40 MiB because NCCL process groups are not
  destroyed on exit, which progressively reduces available VRAM across restarts.

Changes: - `scripts/init/vllm-init.sh`: raise TTS_RESERVE_MIB from 3584 to 6144 (3.5 GiB → 6 GiB),
  yielding GPU_UTIL ≈ 0.73 on a 22 GB GPU and requesting ~16.0 GiB — within the ~16.95 GiB
  available. Updated comment with measured runtime data and restart-leak rationale.


## v2.11.2 (2026-04-20)

### Bug Fixes

- **vllm,install**: Fix python3 binary and restructure installer flow
  ([`5da727e`](https://github.com/getsimpledirect/ghost-narrator/commit/5da727ecc1136ca98d7f87dcb2862c5f9ee41e89))

vllm-init.sh: - Replace `python` with `python3` — the vllm/vllm-openai image follows Debian
  convention and does not provide a python symlink; every container start was exiting with code 127
  before the API server could launch, causing the service to restart in a tight loop

install.sh: - Move GPU detection and LLM backend selection before the "Configure .env now?" prompt
  so the hardware tier override question shows the auto-detected tier as context - Split
  GPU_DETECTED (any NVIDIA GPU → apply docker-compose.gpu.yml overlay for CUDA TTS) from VLLM_TIER
  (>=10240 MiB VRAM → vLLM backend) — low_vram machines now get the CUDA overlay without being
  routed to vLLM - Move storage backend, voice sample, and voice reference text prompts inside the
  configure block so re-run users on an existing .env skip all interaction when answering N - Run
  legacy voice migration (voices/ → voices/default/) and voice directory creation unconditionally
  before the prompt so they are never skipped on re-runs


## v2.11.1 (2026-04-20)

### Bug Fixes

- **install**: Correct GPU tier detection and backend selection
  ([`733585e`](https://github.com/getsimpledirect/ghost-narrator/commit/733585eff4f32d808a5b7c694ea92d71f7495a70))

Three bugs in the Ollama / vLLM setup:

1. install.sh conflated GPU presence with vLLM eligibility. Any machine with an NVIDIA GPU (even 4
  GB VRAM = low_vram tier) received COMPOSE_PROFILES=gpu and LLM_BASE_URL=http://vllm:8000/v1.
  vllm-init.sh then tried to load the Ollama tag 'qwen3.5:4b' as a HuggingFace model, crashing
  immediately. Fix: split into GPU_DETECTED (any GPU) and VLLM_TIER (VRAM ≥ 10 GB). The GPU overlay
  is still applied for any GPU machine — hardware-probe needs the CUDA base image and tts-service
  needs device reservations for CUDA TTS synthesis. COMPOSE_PROFILES=gpu is only set when
  VLLM_TIER=true (mid/high_vram).

2. vllm-init.sh passed --kv-cache-dtype fp8 alongside --quantization fp8. FP8 KV cache requires
  hardware fp8 support (compute capability ≥ 8.9, i.e. Ada Lovelace / Hopper only). T4 (cc 7.5) and
  A100 (cc 8.0) are common mid/high_vram cards that would fail with this flag. Weight-only fp8
  quantization (--quantization fp8) is sufficient for VRAM reduction and runs on any CUDA GPU.
  Removed --kv-cache-dtype.

3. hardware-probe container only received HARDWARE_TIER, not the SELECTED_LLM_NUM_CTX /
  SELECTED_LLM_MODEL / SELECTED_TTS_MODEL user overrides. hardware-probe.sh's override logic (lines
  123-126) was silently ignored, so vllm-init.sh always used the tier-default max-model-len
  regardless of what the user set in .env. Added the three SELECTED_* vars to hardware-probe's
  environment block.

### Documentation

- Sync README and vllm-init comment with vLLM migration
  ([`cf21c02`](https://github.com/getsimpledirect/ghost-narrator/commit/cf21c02fec29c2d1d24794f2e3f7a29c71e6c679))

Update stale content following the Ollama → vLLM GPU migration:

- vllm-init.sh: remove --kv-cache-dtype from comment (flag was dropped in previous commit; comment
  still named it) - README.md hardware tier table: Mid/High rows now show HuggingFace model IDs with
  vLLM backend label; drop the obsolete "9B on ≥13 GB" sub-tier - README.md architecture diagram:
  add vLLM node alongside Ollama so the mid/high_vram path is visible - README.md LLM override
  table: add vLLM row; update intro sentence to name both backends - README.md troubleshooting:
  split Ollama row into cpu/low vs mid/high; add vLLM health check URL

### Refactoring

- **ollama**: Drop ghost-narrator-llm Modelfile alias
  ([`50dcaa8`](https://github.com/getsimpledirect/ghost-narrator/commit/50dcaa8b978baf2f690f707c07783c2dfbd0259e))

The custom Modelfile was created under ghost-narrator-llm to bake num_ctx into the model manifest
  and pre-warm it, avoiding a mid-request KV cache reload. This is now redundant: OLLAMA_NUM_CTX is
  exported before ollama serve starts (so KV is pre-allocated server-wide), and strategy.py passes
  options.num_ctx per-request as a belt-and-suspenders override.

More importantly, the alias actively breaks vLLM tiers — tts-service was calling
  model=ghost-narrator-llm but vLLM only registered the HuggingFace ID. Removing the default from
  docker-compose lets config.py fall through to ENGINE_CONFIG.llm_model, which resolves to the
  correct native name for each backend (qwen3.5:2b for CPU, Qwen/Qwen3.5-9B for HIGH_VRAM, etc.).

Changes: - ollama-init.sh: remove Modelfile creation; pre-warm directly on the base model tag -
  docker-compose.yml: LLM_MODEL_NAME default changed from ghost-narrator-llm to empty for ollama,
  n8n, and tts-service services; add comment explaining the blank-default + ENGINE_CONFIG fallback
  contract


## v2.11.0 (2026-04-20)

### Features

- **narration**: Migrate GPU tiers to vLLM for unlimited generation time
  ([`fbd5ec0`](https://github.com/getsimpledirect/ghost-narrator/commit/fbd5ec03bf5dc8abebb0b2bae895ac28b8610fcb))

Ollama imposes a 120-second server-side generation timeout that kills narration of long articles
  (7000+ words at 25 tok/s = 420+ seconds). vLLM has no per-request timeout and runs 3-5x faster via
  PagedAttention.

GPU tier changes (mid_vram / high_vram): - docker-compose.yml: add vllm service (profiles: [gpu]);
  ollama gets profiles: [cpu]; remove obsolete ollama health dep from n8n; add vllm_models volume -
  docker-compose.gpu.yml: GPU reservation moves from ollama → vllm - scripts/init/vllm-init.sh: NEW
  — sources tier.env, computes safe gpu-memory-utilization leaving ~3.5 GB for TTS, starts vLLM with
  --reasoning-parser qwen3 and --default-chat-template-kwargs to disable thinking server-wide; fp8
  quantization when set - scripts/init/hardware-probe.sh: MID/HIGH VRAM model IDs switch to
  HuggingFace format (Qwen/Qwen3.5-4B, Qwen/Qwen3.5-9B); adds VLLM_QUANTIZATION=fp8 and VRAM_MIB to
  tier.env; OLLAMA_NUM_PARALLEL is 0 for GPU tiers (vLLM manages its own queue) - hardware.py:
  update _TIER_CONFIGS llm_model to HuggingFace IDs - strategy.py: add _VLLM_ENDPOINT flag; vLLM
  gets extra_body.chat_template_kwargs.enable_thinking=False (no /no_think prefix — vLLM chat
  template handles it server-side) - install.sh: writes COMPOSE_PROFILES and LLM_BASE_URL to .env
  based on GPU detection; pulls correct LLM image per profile - .env.example: document
  COMPOSE_PROFILES, fix LLM_TIMEOUT to 300s

CPU / LOW_VRAM tiers continue using bundled Ollama unchanged. The Modelfile custom-model approach
  (ghost-narrator-llm) is preserved for cpu/low-vram tiers — only GPU tiers switch backends.


## v2.10.4 (2026-04-20)

### Bug Fixes

- **ollama**: Sync custom model name between Ollama and tts-service
  ([`b5f66ae`](https://github.com/getsimpledirect/ghost-narrator/commit/b5f66ae0ae41972cae0335008f803967a8a95ac4))

- LLM_MODEL_NAME now passed to the Ollama container so ollama-init.sh creates the Modelfile model
  under the same name tts-service calls - If .env had LLM_MODEL_NAME=qwen3.5:9b, Ollama loaded
  ghost-narrator-llm but tts-service sent model=qwen3.5:9b — Ollama then unloaded and reloaded the
  raw model (no baked num_ctx) taking ~2 min → 500 on every narration request - CUSTOM_MODEL now
  uses LLM_MODEL_NAME env var, falling back to ghost-narrator-llm if unset — both sides always agree
  on the name - Remove unused HardwareTier import in factory.py; ruff format pass


## v2.10.3 (2026-04-19)

### Bug Fixes

- **ollama**: Upgrade to latest and set OLLAMA_REQUEST_TIMEOUT=600
  ([`9286170`](https://github.com/getsimpledirect/ghost-narrator/commit/9286170eeef3fbacf13bc06b953619930a24714e))

- Ollama 0.20.x has a hardcoded 120-second HTTP response deadline that fires before long articles
  finish generating (7000+ words at 9B model speed takes 150-180 s), returning 500 on every
  narration job - Upgraded from ollama/ollama:0.20.4 to ollama/ollama:latest which removes the
  hardcoded limit (fixed in 0.21.0+) - Added OLLAMA_REQUEST_TIMEOUT=600 as defence-in-depth for the
  same class of timeout across any future version pinned here


## v2.10.2 (2026-04-19)

### Bug Fixes

- **narration**: Stream LLM responses to prevent Ollama idle timeout
  ([`b95f5b5`](https://github.com/getsimpledirect/ghost-narrator/commit/b95f5b55b507aa8d1bfaf83cfd76bfda3a4e261b))

- Ollama's HTTP server drops connections idle for more than 120 seconds; non-streaming completions
  hold the socket silent while the model computes the full response, causing 500 on every
  long-article request - Switched _call_llm to stream=True so tokens keep the connection alive as
  they arrive, eliminating the idle timeout regardless of article length - Updated test helpers to
  yield async generators matching the OpenAI streaming response shape instead of the non-streaming
  MagicMock


## v2.10.1 (2026-04-19)

### Bug Fixes

- **ollama**: Bake num_ctx into Modelfile to prevent mid-request reload
  ([`221087e`](https://github.com/getsimpledirect/ghost-narrator/commit/221087e513fc7c5dd8aabe92fafbf29530df7631))

Ollama 0.20.4 ignores OLLAMA_NUM_CTX at server startup and defaults every model to its card context
  (4096 for qwen3.5:9b). The mismatch with the 65536 tts-service requests causes a mid-flight model
  reload that hits Ollama's 2-minute internal timeout, returning 500 on every narration job.

ollama-init.sh now writes a Modelfile with the tier-correct num_ctx baked in and creates a custom
  model named ghost-narrator-llm. The pre-warm loads it at the right context size, so the first real
  request finds no mismatch and no reload occurs. LLM_MODEL_NAME in docker-compose defaults to
  ghost-narrator-llm for both tts-service and n8n.

The stale num_ctx=8192 assertion in test_narration_strategy.py is also corrected to read from
  ENGINE_CONFIG at runtime rather than a hardcoded value that diverged from the cpu_only tier
  default.


## v2.10.0 (2026-04-19)

### Features

- **hardware**: Upgrade all tiers to qwen3.5 and expand HIGH_VRAM to 64K context
  ([`9b6f2d9`](https://github.com/getsimpledirect/ghost-narrator/commit/9b6f2d9a396d9b0d483e48192962e42d999a619a))

Replaces qwen3 with qwen3.5 across all hardware tiers for improved narration quality and
  performance. HIGH_VRAM gains a 64K context window, doubling the single-shot narration threshold
  from 4000 to 8000 words without requiring chunked fallback for long-form content.

Model mapping: - CPU_ONLY: qwen3:1.7b → qwen3.5:2b (llm_num_ctx 4096) - LOW_VRAM: qwen3:4b →
  qwen3.5:4b (llm_num_ctx 4096) - MID_VRAM: qwen3:8b → qwen3.5:4b default; hardware-probe.sh selects
  qwen3.5:9b for GPUs ≥13 GB (10-12 GB would OOM with 9b + TTS 1.7B) - HIGH_VRAM: qwen3:8b →
  qwen3.5:9b (llm_num_ctx 65536)

Context window changes: - hardware-probe.sh writes SELECTED_LLM_NUM_CTX and OLLAMA_NUM_CTX to
  tier.env so Ollama pre-allocates the correct KV cache at startup, preventing a model reload on the
  first narration API call. - ollama-init.sh exports OLLAMA_NUM_CTX before ollama serve. -
  docker-compose.yml passes SELECTED_LLM_NUM_CTX to tts-service for optional user overrides. -
  factory.py replaces hardcoded thresholds with min(8000, llm_num_ctx/6) so the single-shot window
  auto-scales with the configured context.

Additional fixes: - Suppress qwen_tts INFO spam ("X_config is None") via logging.py. -
  MAX_JOB_DURATION_SECONDS default raised 7200 → 10800 (3 h) to cover 18-segment book chapters
  without timeout. - Completeness check moved from dead ChunkedStrategy path into
  SingleShotStrategy.narrate() where HIGH_VRAM actually exercises it. - HIGH_VRAM KV_PER_SLOT
  updated 1000 → 2000 MiB to reflect 64K context (15 attn layers × fp16 ≈ 1920 MiB/slot).


## v2.9.5 (2026-04-19)

### Bug Fixes

- **tts-engine**: Prevent per-segment torch.compile recompilation
  ([`70b0157`](https://github.com/getsimpledirect/ghost-narrator/commit/70b01575ee2c0d114124a728c7a17cd8dd08cc4e))

- Add dynamic=True to torch.compile so the compiler does not specialize on fixed tensor shapes -
  Without this, each segment with a different input length triggers a full recompilation, adding
  30-60s overhead per segment after the first - Qwen3-TTS code_predictor generates 15 codec tokens
  per frame and accounts for ~71% of total synthesis time — recompilation cost dominates segment 2+


## v2.9.4 (2026-04-19)

### Bug Fixes

- **tts-engine**: Add 'model' to torch.compile sub-module probe list
  ([`ab847d3`](https://github.com/getsimpledirect/ghost-narrator/commit/ab847d3c1025586751e738bd9fff14e5df809eeb))

Qwen3TTSModel exposes the underlying nn.Module as .model (standard HuggingFace convention), not
  .talker/.code_predictor/.speaker_encoder which were guesses. The warning printed the actual
  attribute list; 'model' was visible in it.


## v2.9.3 (2026-04-19)

### Bug Fixes

- **tts-service**: Fix systematic silence, cascading tail, and torch.compile no-op
  ([`4864c28`](https://github.com/getsimpledirect/ghost-narrator/commit/4864c28edbb75188a2140a23f53e99d156581cb6))

- Fix 4 (torch.compile): Qwen3TTSModel is a Python wrapper, not an nn.Module — compiling the wrapper
  was a silent no-op completing in ~1s with no speedup. Now probes
  talker/code_predictor/speaker_encoder by name, compiles each nn.Module sub-component individually,
  and logs a warning with available attributes if none are found. Achieves the intended 2-4x
  inference speedup.

- Fix 1 (leading silence): synthesize_single_shot now applies _trim_silence to the output WAV after
  engine.synthesize_to_file returns. Qwen3-TTS emits silence tokens before the first word on some
  inputs, producing >50% silence segments that fail the quality check and waste 5-minute retries.
  The trim eliminates these failures before they reach the quality check loop.

- Fix 5 (cascading silence): same _trim_silence call trims trailing silence from the segment output.
  When tail conditioning extracts the last 2.5s as voice_override for the next segment, a
  silence-ended reference conditioned the model to start the next segment with silence — producing
  the systematic pattern of silence failures on segments 2, 3, 4... observed in production logs.

- Fix 3 (smarter retry): _resynthesize_chunk now strips leading punctuation (quotes, dashes,
  bullets, ellipsis) from the retry text. Opening with a direct-quote or non-word character is a
  known Qwen3-TTS silence trigger; a word-first entry point on the retry gives the sampler a clean
  start.

### Documentation

- **tts-service**: Sync ARCHITECTURE.md with pipeline implementation
  ([`b36d022`](https://github.com/getsimpledirect/ghost-narrator/commit/b36d02235f2b7379e8313f5f26f1758686d03e5a))

- Stage 0 (Preprocessing): document normalize_for_narration as the deterministic URL/Markdown/email
  stripping step before LLM, not the LLM - Stage 1 (LLM Narration): replace stale prompt description
  with accurate one (fact preservation, number spell-out, no framing, PAUSE markers); document
  per-chunk validation and HIGH_VRAM completeness check - Stage 2 (Text Preparation): remove
  chunk-based fallback references; document single-shot vs. segment mode split at 4000 words - Stage
  3 (Synthesis): document tail conditioning (HIGH_VRAM); remove temperature-bump re-synthesis (was
  never implemented that way) - Stage 4 (Quality Check): promote to all tiers; document WER
  re-synthesis and ±3 dB loudness consistency check as HIGH_VRAM-only layers - Stage 7 (Mastering):
  update compressor (1.5:1, attack 300 ms, release 800 ms), loudnorm linear=true, true-peak limiter
  (release 150 ms), and TARGET_LUFS - Remove per-chunk LUFS normalization from semaphore scope
  description - Remove outdated Ollama prompt bullets (URLs, transitions, abbreviations) - Update
  TTS Service key features block to reflect single-shot strategy


## v2.9.2 (2026-04-19)

### Bug Fixes

- **tts-service**: Align pipeline with production TTS best practices
  ([`dd501b2`](https://github.com/getsimpledirect/ghost-narrator/commit/dd501b227715696edeeb23f8132274cc251e31dc))

- Add WER-based re-synthesis to quality_check using Whisper base (CPU) via the transformers pipeline
  already in the dependency tree; detects hallucinated, skipped, and repeated words that dBFS checks
  cannot catch; degrades gracefully if the model is unavailable (air-gapped or test env) - Tighten
  loudness consistency threshold from 6 dB to 3 dB; at 6 dB a segment sounds twice as loud —
  listeners notice at ±3 LU per EBU R128 - Fix compressor release time from 100ms to 800ms and
  attack from 10ms to 300ms; 100ms release causes audible gain pumping on sentence pauses, which is
  the primary DRC artifact in speech mastering - Fix alimiter release from 50ms to 150ms; 50ms is
  below the minimum recommended for speech limiters and introduces inter-sample artifacts - Add full
  PyTorch seed pattern: random.seed, numpy.random.seed, and cuDNN deterministic mode alongside the
  existing torch.manual_seed; cuDNN deterministic is set once at engine init, not per synthesis call
  - Add URL and email stripping to normalize_for_narration after Markdown image/link removal so bare
  https:// strings do not reach the LLM or TTS - Add 25-word sentence length instruction to system
  prompt so the LLM produces sentences within the range where TTS intonation modeling is reliable
  (>30 words degrades prosody in autoregressive models)


## v2.9.1 (2026-04-19)

### Bug Fixes

- **tts-service**: Add completeness check to narrate_iter
  ([`a6392fc`](https://github.com/getsimpledirect/ghost-narrator/commit/a6392fcd9cac89ab08482def97d9d237045465a3))

- ChunkedStrategy.narrate_iter skipped the Layer 4 LLM completeness check that narrate() applies on
  HIGH_VRAM for short articles - Missing entities only visible at the full-narration level were
  invisible on the streaming path used by tts_job.py in production - Buffer all chunk outputs before
  yielding so the same completeness guard (HIGH_VRAM + combined words <= 4000) can run consistently
  - Renumber duplicate Step 4 comment in tts_job.py to Step 3


## v2.9.0 (2026-04-19)

### Features

- **tts-service**: Add tail conditioning, seed determinism, and loudness consistency
  ([`62990fe`](https://github.com/getsimpledirect/ghost-narrator/commit/62990fe1a0369dab11e5dda62a9369aab08b8bae))

- Tail conditioning (HIGH_VRAM): each segment is conditioned on the last 2.5s of the preceding
  segment via voice_override, anchoring timbre and speaking rate across autoregressive synthesis
  boundaries

- Seed determinism: job_id is hashed via SHA-256 to a stable 31-bit seed and set via
  torch.manual_seed inside the synthesis lock, making retries reproduce the same audio rather than
  rolling a new voice sample

- Per-segment quality check interleaved with tail extraction on HIGH_VRAM so the tail reference is
  always from a verified segment, not a silent one

- Loudness consistency check (_check_segment_consistency): after HIGH_VRAM synthesis, segments
  deviating > 6 dB from the median dBFS are re-synthesized, catching volume-level sampling artifacts
  invisible to per-chunk silence check

- voice_path parameter added to synthesize_single_shot/async to support tail conditioning without
  breaking existing callers

- _extract_tail_wav helper slices the last N ms of a WAV for conditioning


## v2.8.17 (2026-04-19)

### Bug Fixes

- **tts-service**: Fix narration fidelity and text normalization gaps
  ([`70ee9a9`](https://github.com/getsimpledirect/ghost-narrator/commit/70ee9a96d21ae529ab10a85651cf2233b4760e77))

- Prompt rule 1 previously demanded output match input length exactly, causing the LLM to truncate
  structured content (bullet lists, tables) rather than prose-ifying it; changed to "preserve all
  facts" - Ghost kg-card divs injected raw URLs and bookmark metadata into the narration text
  because only <figure> cards were stripped, not <div> variants used by newer Ghost; added
  _KG_CARD_RE with iterative loop - Percentages (12.5%), ordinals (1st/2nd/3rd), 24/7, and P&L were
  passed raw to TTS, producing garbled letter-by-letter output; added _PERCENT_RE, _ORDINAL_RE,
  _24_7_RE, and P&L acronym registry entry - Compressor threshold 0.125 (-18 dBFS) activated on
  nearly every spoken sentence, audibly pumping quieter passages; relaxed to 0.25 (-12 dBFS) with
  1.5:1 ratio and faster attack/release - [LONG_PAUSE] markers were converted to \n\n by
  clean_text_for_tts and relied on the autoregressive model to pause — unreliable across sampling
  temperatures; replaced single-shot path with synthesize_with_pauses which splices 800ms
  AudioSegment.silent() - split_into_chunks produced mid-sentence splits that caused prosody
  discontinuities; removed the function and its _split_sentence_at_clauses helper since
  split_into_large_segments is the correct segmentation path


## v2.8.16 (2026-04-19)

### Bug Fixes

- **tts-service**: Fix token starvation artifacts and mastering errors
  ([`ede6329`](https://github.com/getsimpledirect/ghost-narrator/commit/ede6329170de4bb4a8ffbdf6545c9582194ebfc0))

Audible disturbances in final audio traced to four independent causes:

- Qwen3-TTS at 12 Hz needs ~2200 codec tokens for 400 words; 3000 left only 35% headroom at normal
  speaking rates, clipping synthesis mid-word - Short trailing segments (single paragraph) hit the
  same budget with no prior context to anchor a clean phoneme close - Multi-voice sub-segments
  joined without silence trimming, letting TTS start-of-clip transients accumulate as pops at quote
  boundaries - Mastering alimiter at 0.708 (-3.0 dBFS) sat 1.5 dB below the loudnorm TP target;
  trailing silence also not removed before normalization

Also removes prepare_text_for_synthesis and concatenate_wavs_auto from tts_job.py — both were
  overwritten immediately after being called.


## v2.8.15 (2026-04-19)

### Bug Fixes

- **tts-service**: Preserve content on LLM truncation and eliminate silence gaps
  ([`76237ec`](https://github.com/getsimpledirect/ghost-narrator/commit/76237ecca8b05294206ae8c90f55d0ab52013e88))

Three pipeline bugs caused unusable audio for content-dense chapters.

Critical truncation fallback: when the LLM returns fewer than 25% of expected words (e.g. 3 words
  for a 799-word pricing table chunk), the narration strategy now returns the normalized source text
  instead of the 3-word output. Podcast narration is still preferred, but no content is silently
  discarded when the LLM fails catastrophically.

Silence gap elimination: concatenate_audio_with_overlap now calls _trim_silence() on each segment
  before crossfading. The function already existed and was used by concatenate_audio and
  concatenate_audio_streaming, but was missing from the overlap path — causing 1-3 second silence
  gaps at segment boundaries that showed up as deadspace mid-article.

Narration chunk size: reduced narration_chunk_words from 800 to 400 for both MID_VRAM and HIGH_VRAM
  tiers. 800-word chunks fed entire pricing tables and email templates to the LLM as a single unit,
  making the "match source length" instruction impossible to satisfy — triggering the critical
  truncation path on nearly every structured-content section.

Also fix the test_concatenate_audio_with_overlap_two_files test which used unscaled np.sin() casts
  to int16, producing near-zero samples that _trim_silence correctly identified as silence and
  emptied.

### Code Style

- **tts-service**: Remove unused imports and reformat long lines
  ([`d0e7469`](https://github.com/getsimpledirect/ghost-narrator/commit/d0e7469affb3763746a06c44343f58282f03c5ba))


## v2.8.14 (2026-04-18)

### Bug Fixes

- **tts-service**: Cap segment size at 400 words to stay within model context
  ([`76ca4f8`](https://github.com/getsimpledirect/ghost-narrator/commit/76ca4f8968c99cd8fc8d263912c3edc0781b3512))

Qwen3-TTS-1.7B generates audio codec tokens at ~75 tokens/sec; a 2500-word segment (~25 min of
  audio) requires ~112,500 codec tokens, far exceeding the model's effective context window. The
  result is valid speech for the opening few hundred words followed by garbage noise for the rest of
  the segment.

SINGLE_SHOT_MAX_WORDS and SINGLE_SHOT_SEGMENT_WORDS both default to 400, which matches
  MAX_CHUNK_WORDS and the pre-refactor chunk size that produced good audio. A 5000-word article now
  produces ~12 × 400-word segments that are crossfaded into a seamless file, instead of 2 ×
  2500-word segments that degrade to noise.

Also fixes the mastering alimiter true-peak limit: MP3 MDCT reconstruction adds 1-3 dB of
  inter-sample overshoot, so limiting PCM to -1 dBFS (0.891 linear) was too close to 0 dBFS. Changed
  to -3 dBFS (0.708 linear) to leave encoding headroom and prevent the measured +2.2 dBFS true peak
  in the final MP3.


## v2.8.13 (2026-04-18)

### Bug Fixes

- **tts-service**: Fix 5 bugs found in codebase audit
  ([`3a6d3f5`](https://github.com/getsimpledirect/ghost-narrator/commit/3a6d3f58106d77763752fdd4dda36a059bfcdf7b))

- tts_engine: cancel flag was discarded in finally block, so cancelled jobs continued synthesizing
  after the first segment raised SynthesisError; discard now only happens on the success path

- concatenate: _trim_silence set trailing=0 for all-silent segments, then segment[:0] produced an
  empty AudioSegment that silenced all subsequent audio; all-silent segments are now left untouched
  for quality_check to handle

- concatenate: overlap guard multiplied len(ms) * frame_rate(Hz) / 1000 — a dimension error that
  always evaluated False; fixed to len(combined) < overlap_ms

- quality_check: _resynthesize_chunk hardcoded chunk_{idx}.wav path, diverging from
  segment_{idx}.wav used in the segment synthesis path; now receives the actual wav_path from the
  caller

- strategy: retry loop did not break on CRITICAL_WORD_RATIO, wasting up to 2 × LLM_TIMEOUT on
  outputs so truncated that retries cannot help; both ChunkedStrategy and SingleShotStrategy now
  break immediately on critical truncation


## v2.8.12 (2026-04-18)

### Bug Fixes

- **tts-service**: Fix segment synthesis creating 67 tiny chunks instead of 2 large ones
  ([`f680900`](https://github.com/getsimpledirect/ghost-narrator/commit/f6809004e056d6973477d119694c7071e335ac48))

split_into_chunks flushes at every paragraph boundary (>=15 words), so passing it
  SINGLE_SHOT_SEGMENT_WORDS=3000 still produced one chunk per paragraph (~63 words each) instead of
  grouping paragraphs into ~3000-word segments. Added split_into_large_segments for the segment
  synthesis path, which only splits at paragraph boundaries when the target word count is exceeded.
  Also fixed [PAUSE] conversion from '...' to ',' — the ellipsis was immediately collapsed to '.' by
  the multi-punct normalizer downstream.

### Code Style

- **tts-service**: Ruff format
  ([`a3118ab`](https://github.com/getsimpledirect/ghost-narrator/commit/a3118ab518f58442175db15e3ba1eac32b51b795))


## v2.8.11 (2026-04-18)

### Bug Fixes

- **tts-service**: Convert pause markers to punctuation cues instead of reading them aloud
  ([`c93c829`](https://github.com/getsimpledirect/ghost-narrator/commit/c93c8295a83334a5493141c4d07fee83633d0643))

[PAUSE] and [LONG_PAUSE] markers were passed raw to Qwen3-TTS, which narrated them as literal text.
  clean_text_for_tts now converts them to natural punctuation the model responds to prosodically:
  [PAUSE] becomes an ellipsis and [LONG_PAUSE] becomes a paragraph break. The single-shot synthesis
  path is preserved as a single TTS call.


## v2.8.10 (2026-04-18)

### Bug Fixes

- **narration**: Suppress qwen3 thinking tokens and add word-count target
  ([`47bcb70`](https://github.com/getsimpledirect/ghost-narrator/commit/47bcb708199c118fc918604aacbcb9452e3bcd1f))

Three root-cause fixes for the 7-45% word-ratio truncation failures seen in production (CRITICAL: 59
  words from 797-word chunks):

1. /no_think prepended to every user message (strategy.py _call_llm). qwen3:8b generates 5000-8000
  thinking tokens before narrating when thinking is not disabled. Those tokens count against
  max_tokens=8192, leaving as few as 59 tokens for the actual narration. think: False in extra_body
  is an Ollama API flag added in 0.6.x; older container images silently ignore it. /no_think is a
  model-level instruction the qwen3 family was trained to respect regardless of Ollama version.

2. Explicit word-count target in every chunk's user message (_narrate_chunk). [SECTION X of Y |
  SOURCE: ~N words → narrate approximately N words] gives the model a concrete numeric target. The
  system prompt's "match source length" is categorical; a number in the user turn is harder to
  ignore and catches truncation even when thinking is not the cause.

3. Word-count-aware retry prompt (validator.py build_retry_prompt). CRITICAL retries (<25% ratio)
  now say "your output was 7% of source, must be ~800 words, narrate the complete text" instead of
  listing five missing entities. Moderate retries include both the missing list and the target word
  count.


## v2.8.9 (2026-04-18)

### Refactoring

- **tts-service**: Remove dead import and update stale test mocks
  ([`213b075`](https://github.com/getsimpledirect/ghost-narrator/commit/213b0752e1273197e1ac228275096264e2f432ba))

synthesize_chunks_auto was imported in tts_job.py but never called after the two-phase pipeline
  refactor. Five tests patched it as a mock that silently went uncalled, and the synthesis failure
  test relied on Redis failing rather than the mock raising SynthesisError.

Replace all five synthesize_chunks_auto patches with synthesize_single_shot_async (the function that
  is actually invoked in Phase 2). Add get_narration_strategy and get_effective_config patches to
  the synthesis failure test so the error fires at synthesis, not Redis. Rewrite the timeout test to
  use a slow async generator for narration, which is the deterministic hang point in the new
  architecture.

Add 10 direct tests for filter_non_narrable_content covering fenced code blocks, inline code, HTML
  pre/table, markdown tables, footnote markers, CTA lines, prose preservation, and whitespace
  collapse.


## v2.8.8 (2026-04-18)

### Bug Fixes

- **tts-service**: Decouple narration from synthesis and add content pre-filter
  ([`d4ce79f`](https://github.com/getsimpledirect/ghost-narrator/commit/d4ce79fdd838e0fd9b1f0c0481813ea3bb4a0efa))

The prior architecture ran pipelined chunked TTS synthesis concurrently with LLM narration, then
  immediately discarded all synthesized audio and re-synthesized from scratch via single-shot
  segment mode for articles above 4000 words. This caused 5-10x redundant GPU work and was the
  primary driver of the 7200s job timeouts seen on all three test articles.

The pipeline is now split into two fully sequential phases: - Phase 1 (narration): LLM rewrites
  article text into spoken script, no audio - Phase 2 (synthesis): one path chosen based on final
  narrated word count - <= SINGLE_SHOT_MAX_WORDS: single full-text synthesis pass - >
  SINGLE_SHOT_MAX_WORDS: segment synthesis with quality check before merge

This eliminates the dual-path synthesis entirely. For a 6000-word article the previous architecture
  ran ~70 chunk synthesis passes then 2 segment passes; the new architecture runs 2 segment passes
  only.

Also fix three compounding issues: - normalize.py: add filter_non_narrable_content() called before
  LLM narration to strip fenced code blocks, HTML pre/table/figure elements, markdown tables,
  footnote markers, and CTA boilerplate. Ghost CMS articles contain significant non-prose content
  that inflates LLM token count and triggers summarization. - strategy.py: guard
  _llm_completeness_check with a 4000-word combined budget check. The prior code sent source +
  narration (~16k tokens) into an 8192-token context, producing truncated garbage JSON that
  triggered unnecessary re-narration. - validator.py: raise MIN_WORD_RATIO from 0.40 to 0.60 so
  content truncation (>40% loss) is caught and retried sooner rather than passing validation
  silently.


## v2.8.7 (2026-04-17)

### Bug Fixes

- **tts-service**: Fix stale cancel flag, tiny chunk explosion, and container rebuild note
  ([`95096ad`](https://github.com/getsimpledirect/ghost-narrator/commit/95096adc0aedeb614b0a33e485db9527df0cdd35))

Three causes of slow processing surfaced from live logs.

Fix 1 — Stale cancel flag on job resubmission The DELETE /tts/{job_id} endpoint calls
  engine.cancel_job(), which adds the job_id to an in-memory set that persists until engine restart.
  When the same job_id is resubmitted without a restart, the first synthesize_to_file call finds the
  id in _cancelled_jobs and raises SynthesisError immediately, triggering the pipeline fallback and
  doubling all LLM narration work. Fix: add TTSEngine.uncancel_job() and call it at the start of
  run_tts_job before any synthesis work begins.

Fix 2 — Tiny TTS chunk explosion from truncated narration split_into_chunks was flushing at every
  paragraph boundary regardless of accumulated word count. Truncated narration output (section
  headings, year labels, single-line numbers from the VC math tables) produces many paragraphs of
  2-15 words. Each became its own synthesis call taking 15-25 seconds due to Qwen3-TTS per-call
  model initialization overhead — a 244-chunk job for a single chapter, projecting to ~80 minutes of
  synthesis time. Fix: only flush at paragraph boundaries when accumulated content >= 15 words.
  Short paragraphs carry over into the next paragraph instead of becoming isolated synthesis calls.
  A final flush handles any remaining content after the last paragraph.

Fix 3 — Container must be rebuilt to apply num_ctx fix The num_ctx=8192 and
  narration_chunk_words=800 fixes committed earlier require docker compose build to take effect.
  Restarting without rebuilding leaves the old 2048-token context active, continuing to truncate
  narration output and producing the tiny-chunk explosion described above. Run: docker compose build
  && docker compose up -d on the server to apply all pending fixes.


## v2.8.6 (2026-04-17)

### Bug Fixes

- **tts-service**: Fix multi-voice crash and Ollama context truncation
  ([`7cc4498`](https://github.com/getsimpledirect/ghost-narrator/commit/7cc44981ecaba64b2dff78825ae8adb04da84cdd))

Two production bugs surfaced from live logs.

Fix 1 — AudioSegment.silent() crash (multi-voice path)
  ------------------------------------------------------ pydub's AudioSegment.silent() only accepts
  duration and frame_rate parameters. Passing channels= raised TypeError on every chunk containing
  quoted speech, which crashed the pipelined synthesis and forced a full sequential re-run. Fixed by
  chaining .set_channels() and .set_sample_width() after the silent() call to match the first real
  segment's properties.

Fix 2 — Ollama context window truncation (narration quality)
  ------------------------------------------------------------ Ollama defaults qwen3:8b to a
  2048-token context window. The narration system prompt consumes ~1050 tokens, leaving only ~998
  tokens for input and output combined. A 2500-word chunk requires ~3750 input tokens alone — Ollama
  silently truncated the input and the model faithfully narrated the partial content it received,
  producing outputs at 11–28% of the expected length. This looked like summarization but was
  actually correct behaviour on truncated input.

Three changes address this:

strategy.py: Pass options.num_ctx=8192 in extra_body on Ollama endpoints, alongside the existing
  think=False. This raises the effective context window from 2048 to 8192 tokens so the full chunk
  and its output can coexist.

hardware.py: Reduce narration_chunk_words from 2500 to 800 for MID_VRAM and HIGH_VRAM tiers. With
  num_ctx=8192 and ~1050 token system prompt, an 800-word chunk (≈1200 tokens) leaves ~5942 tokens
  for output — comfortable headroom. 2500-word chunks leave only ~3392 tokens for output, which is
  insufficient for faithful full-length narration even with 8192 context.

factory.py: Reduce MID_VRAM single-shot fallback threshold from 3000 to 1200 words. Single-shot
  sends the entire article in one call; at 3000 words input (≈4500 tokens) + 4500 tokens expected
  output the total exceeds 8192. At 1200 words the total fits comfortably within context.

Tests: update extra_body assertion to verify both think=False and options.num_ctx=8192 are present
  in Ollama calls.


## v2.8.5 (2026-04-17)

### Bug Fixes

- **tts-service**: Fix audio artifacts, speed/pitch variance, and wire multi-voice synthesis
  ([`0f01f01`](https://github.com/getsimpledirect/ghost-narrator/commit/0f01f0128ba2bafbb701d69cbcd6fc2bce4a1017))

Addresses a cluster of audio quality issues — disturbances, inter-chunk speed and pitch changes, and
  glitches at segment joins — plus several correctness and quality improvements identified in a
  systematic pipeline audit.

Bug fixes --------- concatenate.py: Fix reversed crossfade curves in concatenate_audio_with_overlap.
  The fade_out was sin(0→π/2)=0→1 (increasing) and fade_in was sin(π/2→0)=1→0 (decreasing) — the
  opposite of what a crossfade requires. Corrected to cos(0→π/2)=1→0 for fade_out and sin(0→π/2)=0→1
  for fade_in, matching the equal-power implementation already used in _crossfade_append. This bug
  only manifested on articles >4000 words where concatenate_audio_with_overlap joins independently
  synthesised segments.

tts_job.py: Replace raw word-count segment splitting with sentence-boundary-aware
  split_into_chunks(). The previous code sliced full_narrated_text.split() at a fixed word index,
  which cut mid-sentence and handed the TTS model incomplete input. Autoregressive TTS generates
  rising/hanging prosody on sentence fragments, causing audible pitch artifacts at every segment
  boundary.

service.py: Fix AudioSegment.silent() frame_rate mismatch in multi-voice path. The breath gap
  between narrator and quoted segments was created with pydub's default 11025 Hz, which differs from
  the TTS model's native output rate. Pydub does not auto-resample on concatenation, so the mismatch
  caused audio glitches. Silence is now derived from the first real segment's frame_rate, channels,
  and sample_width.

Audio quality improvements -------------------------- hardware.py: Reduce TTS sampling temperature
  from 0.4 to 0.3 (and top_k 50→40, top_p 0.92→0.85) across all hardware tiers. Each
  generate_voice_clone() call is an independent autoregressive generation; higher temperature widens
  the duration distribution, producing perceptible speaking-rate and pitch shifts between chunks.
  Lower temperature narrows this variance while remaining above the robotic range.

tts_job.py: Track raw LLM narration output in narrated_segments before TTS chunking. Single-shot and
  segment-based synthesis paths previously joined TTS chunks with spaces, discarding all paragraph
  structure. Now narrated_segments is joined with double newlines so the TTS model receives natural
  paragraph breaks as topic-boundary cues for better prosody.

mastering.py: Raise DEFAULT_LRA from 7.0 to 9.0 LU (podcast standard range 8–12 LU). At 7 LU the
  loudnorm filter removed the natural emphasis dynamics the TTS model generates, flattening the
  audio.

mastering.py: Lower compressor threshold from -15 dBFS (0.177) to -18 dBFS (0.125) and extend
  release from 150 ms to 250 ms. The shorter release caused audible gain pumping between sentences;
  250 ms is transparent for speech content.

normalize.py: Expand SaaS/PaaS/IaaS to full spoken phrases rather than capitalised tokens ("Saas",
  "Paas", "Iaas") that TTS reads as nonsense words. Remove AI and ML from the acronym registry —
  Qwen3-TTS pronounces them correctly natively and hyphenated letter-spelling (A-I, M-L) sounds
  choppy in fast narration.

prompt.py: Populate _PACING_ADDON with explicit [PAUSE]/[LONG_PAUSE] placement guidance for MID_VRAM
  and HIGH_VRAM tiers. The base prompt instructed the model to insert pause markers but gave no
  frequency guidance; LLM models rarely inserted them unprompted, losing natural pacing at section
  and topic boundaries.

Multi-voice synthesis (new capability) --------------------------------------- service.py: Wire the
  existing has_quoted_speech/split_at_quotes utilities into synthesize_chunk(). Chunks containing
  double-quoted speech are now split at quote boundaries and each segment synthesised independently.
  Narrator segments use the tier default parameters; quoted segments receive temperature +0.15
  (capped at 0.55) and top_p +0.05 (capped at 0.92) for more expressive delivery while preserving
  voice identity through the shared reference prompt. Sub-segments are joined with an 80 ms breath
  gap whose silence properties are derived from the first segment to avoid sample-rate mismatches.
  Chunks without quotes take the unchanged fast single-synthesis path.

Tests: update test_all_tiers_use_temperature_03 assertion to match new value.


## v2.8.4 (2026-04-14)

### Bug Fixes

- **prompt**: Add hedging instruction back for test compatibility
  ([`24ec3fc`](https://github.com/getsimpledirect/ghost-narrator/commit/24ec3fcc767aa7f00c63cfb0583aae87846d5aec))


## v2.8.3 (2026-04-14)

### Bug Fixes

- **prompt**: Optimize for strict content preservation - no summarization
  ([`03453a0`](https://github.com/getsimpledirect/ghost-narrator/commit/03453a0ae5ca42d0d4a41e62218e9687d4f1c0d8))

Based on research findings: - LLMs struggle with verbatim fidelity in long-text generation -
  Summarization causes content loss; verbatim compaction preserves better - Key: explicit
  constraints, no creative instructions

New prompt: - Strict content editor role (not host/storyteller) - Output length MUST match input
  length - Forbidden: summarization, filler, bridges, hooks, analogies not in source - Only audio
  adaptation: spell numbers, dates, active voice, [PAUSE] markers - Removed all podcast-style
  instructions that add content

This is the optimal prompt for preserving source content exactly.


## v2.8.2 (2026-04-14)

### Bug Fixes

- **prompt**: Remove instruction to add content not in source
  ([`f37849e`](https://github.com/getsimpledirect/ghost-narrator/commit/f37849e4d4b21775c5b26002b1a95a964ae41287))

- Removed 'Tell mini-stories' instruction - Removed 'Add verbal bridges between sections'
  instruction - Removed 'End strong' hook instruction - Added explicit 'DO NOT ADD CONTENT' rule -
  LLM should now preserve original meaning without adding filler


## v2.8.1 (2026-04-14)

### Bug Fixes

- **narration**: Add max_tokens=8192 to prevent output truncation
  ([`48ed9ca`](https://github.com/getsimpledirect/ghost-narrator/commit/48ed9cab038ff38662a9d792f7af02ec2ab2bdce))

Without max_tokens, Ollama defaults to 2048/4096 which can truncate output mid-sentence and cause
  the LLM to drop content. This was a major cause of narration being significantly different from
  source.

Also clarified in prompt that output should be approximately equal in length to source (not shorter
  or summarized).

- **narration**: Emphasize output must be equal length, not shorter
  ([`f4295af`](https://github.com/getsimpledirect/ghost-narrator/commit/f4295af917d8db726567aa278548ac933a787fe4))

Clarify in system prompt that this is format conversion NOT summarization. Output should be
  approximately equal in length to source.


## v2.8.0 (2026-04-13)

### Bug Fixes

- **concatenate**: Use equal-power crossfade in concatenate_audio_with_overlap
  ([`1f4e0a3`](https://github.com/getsimpledirect/ghost-narrator/commit/1f4e0a33b27b98cd5477aa62219e13f6e0186e07))

- **tts**: Add edge case handling for empty narrated text
  ([`830e0a7`](https://github.com/getsimpledirect/ghost-narrator/commit/830e0a774cdb39763d227e2ccc18461c77e9bad5))

### Chores

- Remove superpowers plans and specs from repo
  ([`369427d`](https://github.com/getsimpledirect/ghost-narrator/commit/369427d5d3b19b635664c8012eba0be6dccc5024))

- **docker**: Add single-shot env vars to docker scripts
  ([`116190c`](https://github.com/getsimpledirect/ghost-narrator/commit/116190c6547145114b6da425e5af2f33ab89e0f9))

- **text**: Increase DEFAULT_MAX_CHUNK_WORDS to 400 for single-shot fallback
  ([`da3e36b`](https://github.com/getsimpledirect/ghost-narrator/commit/da3e36bc0cd5b9c396ab54ba128bf87bc294cae3))

### Documentation

- Add single-shot audio synthesis implementation plan
  ([`1a196c2`](https://github.com/getsimpledirect/ghost-narrator/commit/1a196c2c5d22a366ee81e1d9c00e7f1500f237d9))

- Add single-shot env vars to QUICKSTART
  ([`b7588bd`](https://github.com/getsimpledirect/ghost-narrator/commit/b7588bdae26ed343e2aab5a60f42b4890d10ae1f))

- Add single-shot environment variables to README
  ([`9c769ea`](https://github.com/getsimpledirect/ghost-narrator/commit/9c769ead2436d969d1c057216135032ac8d1b097))

- Update all docs with single-shot synthesis configuration
  ([`0b2e781`](https://github.com/getsimpledirect/ghost-narrator/commit/0b2e78192b908a34bf5398d4522d24a9b9e0e634))

- Update plan with all affected files
  ([`5e245ab`](https://github.com/getsimpledirect/ghost-narrator/commit/5e245ab042ec081798547657fe68fb58f09a8f43))

### Features

- **concatenate**: Add overlap crossfade for single-shot segments
  ([`76187f9`](https://github.com/getsimpledirect/ghost-narrator/commit/76187f9ee65d77bc0b97e668bc872be36d62290e))

- **config**: Add single-shot synthesis settings
  ([`8df0a0a`](https://github.com/getsimpledirect/ghost-narrator/commit/8df0a0a9df354d29ef6e4d8989b4837b325c04d0))

- **synthesis**: Add single-shot synthesis function
  ([`1441495`](https://github.com/getsimpledirect/ghost-narrator/commit/1441495c08f153aacff45dcd9b30a4e5fdf2ffcf))

- **tts**: Integrate single-shot synthesis into job pipeline
  ([`6d04126`](https://github.com/getsimpledirect/ghost-narrator/commit/6d04126e9eae0549c92bca5d6cca0b2225beb139))

### Testing

- **concatenate**: Add overlap crossfade tests
  ([`a21b679`](https://github.com/getsimpledirect/ghost-narrator/commit/a21b679e29209faa10ba2cd97d4fc080c51b4be4))

Also fix pydub AudioSegment creation in concatenate_audio_with_overlap to properly convert numpy
  array to bytes before passing to constructor.

- **job**: Fix run_tts_job tests with missing mocks for narration strategy
  ([`5288cb4`](https://github.com/getsimpledirect/ghost-narrator/commit/5288cb46d9ba5edca0fa84de1afae2f8e07d648b))

- **synthesis**: Add single-shot synthesis tests
  ([`4b619be`](https://github.com/getsimpledirect/ghost-narrator/commit/4b619be987bb64b52fe4e18fff6a82fad2fa531f))


## v2.7.1 (2026-04-13)

### Bug Fixes

- **narration**: Balance validation thresholds to 60% compression max
  ([`8a18033`](https://github.com/getsimpledirect/ghost-narrator/commit/8a18033209aeafc965d27c64979312f6a33a6f20))

- MIN_WORD_RATIO: 0.20 → 0.40 (60% max compression, 40% preserved) - WARNING_WORD_RATIO: 0.30 → 0.50
  (50% triggers warning, not retry) - CRITICAL_WORD_RATIO: 0.15 → 0.25 (skip only extreme cases)


## v2.7.0 (2026-04-13)

### Features

- **narration**: Combine all three optimization options
  ([`39eca90`](https://github.com/getsimpledirect/ghost-narrator/commit/39eca9020cc9d0aa5ce5b1dececbdb4204a05740))

Option A - Hybrid threshold: - MIN_WORD_RATIO = 0.20 (pass) - WARNING_WORD_RATIO = 0.30 (log
  warning) - CRITICAL_WORD_RATIO = 0.15 (no retries)

Option B - Larger chunks: - MAX_CHUNK_WORDS: 200 → 400 (more context = better preservation)

Option C - Document-level validation is now implicit: - Per-chunk validation uses 20% threshold - At
  15% critical threshold, retries stop automatically

This combination addresses the root cause: larger chunks provide more context, reducing LLM
  compression and validation failures.


## v2.6.3 (2026-04-13)

### Bug Fixes

- **narration**: Make word ratio the primary pass/fail check
  ([`9b043ce`](https://github.com/getsimpledirect/ghost-narrator/commit/9b043cecb5ab04f9c7b31638c2258539688869ed))

- Entity validation now purely informational (for logging only) - Word ratio (20%) is now the ONLY
  pass/fail criteria - This prevents all-or-nothing validation loops while still catching genuine
  content drops (when ratio <20%) - Updated tests to reflect new behavior


## v2.6.2 (2026-04-13)

### Bug Fixes

- **narration**: Relax validation to prevent retry loops
  ([`ebfdd39`](https://github.com/getsimpledirect/ghost-narrator/commit/ebfdd39009d56a57e8486a04e6847f51cf1d3026))

- Lower MIN_WORD_RATIO from 0.55 to 0.20 (allow natural compression) - Add MAX_ENTITY_MISSING_RATE =
  0.30 (allow up to 30% missing entities) - Simplify retry prompt to top 5 critical items only -
  Previous strict all-or-nothing validation caused validation loops


## v2.6.1 (2026-04-13)

### Bug Fixes

- **code-quality**: Improve error handling, edge cases, and remove dead code
  ([`61919c9`](https://github.com/getsimpledirect/ghost-narrator/commit/61919c9e2fcc653e71a51036e08bdf2aa4b28112))

Error Handling: - Add proper logging to silent exception handlers in validator.py - Add exception
  context logging in connection_pool.py - Add bounds check for LLM response.choices in strategy.py -
  Fix bare except: clauses to use logger.debug

Edge Cases: - Add guard for empty crossfade arrays in concatenate.py - Fix redundant .lower() call
  in storage/__init__.py (already lowercased in config)

Dead Code: - Clean up unreachable code in retry.py (comment improvement)

Tests: - Update test_hardware.py for 320k MP3 bitrate and 48000 sample rate - Update
  test_mastering.py to test for loudnorm instead of removed highpass/eq - Remove obsolete
  normalize_chunk_to_target_lufs patches from tts_job tests


## v2.6.0 (2026-04-13)

### Features

- **audio**: Studio-quality improvements for podcast production
  ([`9576405`](https://github.com/getsimpledirect/ghost-narrator/commit/95764050f7043ae300e2e2f9b6454c66331281d0))

- Reduce TTS temperature to 0.4 for consistent voice across all tiers - Increase sample rate to
  48000 for studio quality on all tiers - Increase TTS chunk sizes for better context preservation -
  Increase crossfade to 300ms for seamless transitions - Improve narration prompt with podcast-style
  rules - Increase pause durations (500ms/1000ms) for natural pacing - Reduce mastering LRA to 7.0
  for balanced dynamics - Increase MP3 bitrate to 320k for HIGH_VRAM tier - Increase max_new_tokens
  to 4000 for HIGH_VRAM tier - Remove per-chunk normalization (done at mastering only) - Remove
  highpass/eq from mastering (preserve natural tone) - Remove temperature bump on re-synthesized
  chunks


## v2.5.4 (2026-04-13)

### Bug Fixes

- **audio**: Improve audio quality by addressing root causes
  ([`3a4c710`](https://github.com/getsimpledirect/ghost-narrator/commit/3a4c7106466316f65a6bf409caab30e9d84568b4))

- Increase crossfade from 60ms to 200ms for smoother transitions - Use soft cap for trailing silence
  instead of hard 60ms - Skip per-chunk normalization to avoid inconsistent loudness - Remove
  temperature bump on re-synthesis (causes voice inconsistency) - Remove highpass and equalizer from
  mastering (causes harshness) - Use gentler compression in mastering chain


## v2.5.3 (2026-04-13)

### Bug Fixes

- **audio**: Defensively truncate crossfade arrays to matching lengths
  ([`d1bc8c4`](https://github.com/getsimpledirect/ghost-narrator/commit/d1bc8c4c1b6e4dd1a89dc69c906e651d52b35245))


## v2.5.2 (2026-04-13)

### Bug Fixes

- **audio**: Ensure segment matches combined channels and frame rate before crossfade
  ([#73](https://github.com/getsimpledirect/ghost-narrator/pull/73),
  [`5fd3db2`](https://github.com/getsimpledirect/ghost-narrator/commit/5fd3db2d1b1f501d752dffbf2e797ee9a185927e))


## v2.5.1 (2026-04-13)

### Bug Fixes

- **tts-service**: Compile underlying PyTorch module instead of wrapper class
  ([`3406d21`](https://github.com/getsimpledirect/ghost-narrator/commit/3406d21733b1a30ece39394646a31d655539e65c))

Fixes a non-fatal warning where torch.compile() failed because it was attempting to compile the
  Qwen3TTSModel wrapper class instead of the underlying PyTorch nn.Module. This ensures the 2-4x
  inference speedup is actually applied on CUDA hardware.


## v2.5.0 (2026-04-13)

### Bug Fixes

- **narration**: Add validation retry limits and proper result validation
  ([`c0681bc`](https://github.com/getsimpledirect/ghost-narrator/commit/c0681bc801a19faf98d5d7d3fc9b214a16a612dc))


## v2.4.5 (2026-04-13)

### Bug Fixes

- **narration**: Strip Qwen3 think tokens and remove chunk overlap duplication
  ([`32b7dee`](https://github.com/getsimpledirect/ghost-narrator/commit/32b7dee20406cf104c901239673a49e20c4fff59))

Qwen3 models emit <think>...</think> reasoning blocks before their actual response. These were
  passing straight through _call_llm into the validator and TTS engine, producing garbled audio
  noise and inflating synthesis time in proportion to thinking token length.

Two fixes applied:

1. _strip_llm_artifacts() strips <think>...</think> blocks, common LLM preamble lines ('Here is the
  narration:'), and trailing meta-commentary from all LLM responses at the source.
  clean_text_for_tts() applies a safety-net pass for any path that bypasses narration.

2. _split_into_chunks() was called with overlap_paragraphs=1 (default), prepending the last
  paragraph of chunk N into chunk N+1. The LLM narrated the full chunk text including the overlap,
  so the overlapping paragraph was spoken twice in the final audio. Removed the overlap — the
  existing continuity instruction (previous_output_tail / previous_source_tail) already handles
  cross-chunk flow correctly.

3. On Ollama endpoints, _call_llm now passes extra_body={'think': False} to prevent Qwen3 from
  generating thinking tokens entirely, eliminating the generation overhead rather than just
  discarding the output.

### Features

- Modify ghost-narrator storage to accept custom storage_path parameter
  ([`a8f06a8`](https://github.com/getsimpledirect/ghost-narrator/commit/a8f06a80d2fcb5c412ca8dba5be9037c946e8d96))

Update all storage backends (GCS, Local, S3) to accept and use an optional storage_path parameter in
  the upload method, allowing clients to specify exact storage paths for audio files.

Changes: 1. StorageBackend base class: added optional storage_path parameter to upload method 2.
  GCSStorageBackend: uses provided storage_path when available, ensures .mp3 extension 3.
  LocalStorageBackend: uses provided storage_path for local file destination 4. S3StorageBackend:
  uses provided storage_path as S3 object key 5. TTS job runner: passes gcs_object_path from API
  request to storage backend


## v2.4.4 (2026-04-12)

### Bug Fixes

- Resolve CHANGELOG merge conflict with emojis
  ([`94da44c`](https://github.com/getsimpledirect/ghost-narrator/commit/94da44c56b9bfc96906c2d948aa58182125f2f90))

- **ci**: Fix shell variable scoping in release workflow
  ([`6e82792`](https://github.com/getsimpledirect/ghost-narrator/commit/6e827927601e250d1c4e736ddbf33ba3ed878688))


## v2.4.3 (2026-04-12)

### Bug Fixes

- **ci**: Add emoji sections to release notes, fix CHANGELOG formatting
  ([`b97ba7e`](https://github.com/getsimpledirect/ghost-narrator/commit/b97ba7e451f7bb5eced1adea94e4e389229e158a))

- **ci**: Add emojis to release notes for better visual appeal
  ([`98cf58d`](https://github.com/getsimpledirect/ghost-narrator/commit/98cf58d11e2001b41721950671cc48d086555568))

- **ci**: Improve release notes format and disable auto-generated notes
  ([`53f6c33`](https://github.com/getsimpledirect/ghost-narrator/commit/53f6c336606a66367e2f74e590db86ac8f9aa951))

### Chores

- Remove VERSION file - not needed, version tracked in pyproject.toml and __init__.py
  ([`78abdbc`](https://github.com/getsimpledirect/ghost-narrator/commit/78abdbccdedb44467f5d5a60fe93d8b4e1e7bc37))


## v2.4.0 (2026-04-12)

### Bug Fixes

- **ci**: Add emojis to release notes for better visual appeal
  ([`53069c3`](https://github.com/getsimpledirect/ghost-narrator/commit/53069c3a0224db2bda4f102bc10b009a622e6959))

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
