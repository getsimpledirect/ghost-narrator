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

"""
TTS job runner service for background processing.

Provides the main job execution pipeline that orchestrates
text chunking, synthesis, per-chunk normalization, audio
concatenation with dynamic gaps, final mastering, upload,
and notifications.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
import shutil
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Optional

from pydub import AudioSegment as _AudioSegment

from app.core.exceptions import (
    ChunkExhaustedError,
    JobDeletedError,
    NarrationError,
    SynthesisError,
    StorageError,
    AudioProcessingError,
    StorageUploadError,
)
from app.config import (
    DEVICE,
    MAX_JOB_DURATION_SECONDS,
    MP3_BITRATE,
    OUTPUT_DIR,
    SINGLE_SHOT_OVERLAP_MS,
)
from app.domains.narration.factory import get_narration_strategy
from app.core.hardware import ENGINE_CONFIG, get_studio_segment_words
from app.domains.synthesis.quality import validate_audio_quality, apply_final_mastering
from app.domains.synthesis.quality_check import (
    _quality_check_and_resynthesize,
    _check_segment_consistency,
)
from app.domains.job.store import get_job_store
from app.domains.job.notification import notify_job_completed, notify_job_failed
from app.domains.storage import get_storage_backend
from app.domains.tts_config.store import get_effective_config
from app.domains.synthesis.service import (
    cleanup_chunk_files,
    get_executor,
    synthesize_best_of_n_async,
    synthesize_with_pauses,
)
from app.domains.synthesis.concatenate import concatenate_audio_with_overlap

logger = logging.getLogger(__name__)

# Process-wide GPU serialization semaphore — created lazily.
# asyncio.Semaphore requires no running event loop at construction time in
# Python 3.10+, and is always acquired from coroutines in a single event loop.
_gpu_semaphore: Optional[asyncio.Semaphore] = None


def get_gpu_semaphore() -> asyncio.Semaphore:
    """Return the process-wide GPU serialization semaphore (lazily created).

    Limits concurrent GPU-bound pipeline execution to one job at a time.
    Without this, concurrent jobs fight _synthesis_lock at the chunk level
    (~50% throughput each) and Ollama queues their LLM requests past
    LLM_TIMEOUT, triggering cascading retry storms.

    Non-GPU steps (quality validation, upload, cleanup, webhook) run outside
    the semaphore so the GPU slot is released as soon as the MP3 is ready.
    """
    global _gpu_semaphore
    if _gpu_semaphore is None:
        _gpu_semaphore = asyncio.Semaphore(1)
    return _gpu_semaphore


def _span(name: str):
    """Return an OTel span context manager, or a no-op if tracing is unavailable."""
    try:
        from app.core.tracing import tracer

        if tracer is not None:
            return tracer.start_as_current_span(name)
    except Exception:
        pass
    return nullcontext()


async def run_tts_job(
    job_id: str,
    text: str,
    gcs_object_path: str,
    site_slug: str = 'site',
) -> None:
    """
    Execute the complete TTS pipeline with parallel processing and optimizations.

    The pipeline is divided into two fully decoupled phases:
    1. Narration phase — LLM rewrites article text into a spoken script (no audio).
    2. Synthesis phase — Qwen3-TTS converts the script to audio (one path only).

    This decoupling eliminates the prior dual-path bug where chunked TTS ran
    during narration and was immediately discarded and re-synthesized via
    single-shot, causing up to 10× redundant GPU work and 7200s timeouts.

    Args:
        job_id: Unique identifier for tracking and file storage.
        text: The raw article text content to be narrated and synthesized.
        gcs_object_path: The target destination path in the GCS bucket.
        site_slug: Site identifier for storage path organization.

    Raises:
        JobDeletedError: If the job is removed by a user during processing.
        RuntimeError: For fatal pipeline initialization or processing failures.
    """
    start_time = time.time()
    loop = asyncio.get_running_loop()
    job_dir = OUTPUT_DIR / job_id
    raw_wav = str(OUTPUT_DIR / f'{job_id}_raw.wav')
    final_mp3 = str(OUTPUT_DIR / f'{job_id}.mp3')
    job_store = get_job_store()
    executor = get_executor()

    async def _check_status() -> None:
        """Check if job is deleted or paused."""
        paused_iterations = 0
        max_paused_iterations = 1800  # 30 minutes max pause
        while True:
            job = await job_store.get(job_id)
            if not job or job.get('status') == 'deleted':
                raise JobDeletedError(f'Job {job_id} was deleted')
            if job.get('status') == 'paused':
                paused_iterations += 1
                if paused_iterations >= max_paused_iterations:
                    raise JobDeletedError(f'Job {job_id} exceeded maximum pause duration')
                await asyncio.sleep(2)
                continue
            paused_iterations = 0  # Reset counter when job is no longer paused
            return

    # Track temp files for cleanup
    normalized_temp_files: list[str] = []

    # Validate executor is initialized
    if executor is None:
        logger.error(f'[{job_id}] Thread pool executor not initialized')
        await job_store.update(
            job_id,
            {
                'status': 'failed',
                'error': 'Service not properly initialized: executor unavailable',
                'completed_at': time.time(),
                'duration_seconds': 0,
            },
        )
        return

    # Create job directory
    try:
        job_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.error(f'[{job_id}] Failed to create job directory: {exc}')
        await job_store.update(
            job_id,
            {
                'status': 'failed',
                'error': f'Directory creation failed: {exc}',
                'completed_at': time.time(),
                'duration_seconds': 0,
            },
        )
        return

    logger.info(f'[{job_id}] Job started - {len(text)} chars, device={DEVICE}')

    try:
        # Mark as queued — will transition to 'processing' once GPU slot is acquired.
        # This keeps the status honest while the job waits behind other jobs.
        await job_store.update(job_id, {'status': 'queued'})

        # Wait for TTS engine to be ready (event-driven, no polling)
        from app.core.tts_engine import get_tts_engine, get_engine_ready_event

        engine = get_tts_engine()
        if not engine.is_ready:
            ready_event = get_engine_ready_event()
            # If engine was already initialized before this event was created, set it
            if engine.is_ready:
                ready_event.set()
            else:
                try:
                    await asyncio.wait_for(ready_event.wait(), timeout=60.0)
                except asyncio.TimeoutError:
                    raise RuntimeError('TTS engine failed to initialize within timeout')

        if not engine.is_ready:
            raise RuntimeError('TTS engine failed to initialize within timeout')

        # Clear any stale cancel flag from a previous run of the same job_id.
        # DELETE /tts/{job_id} calls engine.cancel_job() which persists in the
        # in-memory set until the engine restarts. If the same ID is resubmitted
        # without a restart, synthesis would immediately raise SynthesisError.
        engine.uncancel_job(job_id)

        # Validate reference voice quality — fail fast before any GPU work
        from app.config import VOICE_SAMPLE_PATH
        from app.domains.voices.validate import validate_reference_wav

        voice_errors = validate_reference_wav(VOICE_SAMPLE_PATH)
        if voice_errors:
            error_msg = '; '.join(voice_errors)
            logger.error('[%s] Reference voice validation failed: %s', job_id, error_msg)
            await job_store.update(
                job_id,
                {
                    'status': 'failed',
                    'error': f'Reference voice invalid: {error_msg}',
                    'completed_at': time.time(),
                    'duration_seconds': time.time() - start_time,
                },
            )
            return

        # Obtain reference F0 for speaker-drift gating — pre-computed from voice sample
        _reference_f0 = getattr(engine, 'reference_f0', None)

        # Fetch generation config once (async Redis read) before entering thread pool
        generation_kwargs, _overrides = await get_effective_config()

        # Fix seed per job — same job_id always produces the same audio on retry.
        # The seed is popped from gen_kw inside the engine before forwarding to the
        # model, so it never reaches generate_voice_clone as an unexpected kwarg.
        import hashlib as _hashlib

        _job_seed = int(_hashlib.sha256(job_id.encode()).hexdigest()[:8], 16) % (2**31)
        generation_kwargs = {**generation_kwargs, 'seed': _job_seed}

        # Acquire GPU slot — serializes narration + synthesis + mastering.
        # One job runs its full pipeline at a time; the next job waits here.
        # Upload, cleanup, and webhook fire AFTER release so the slot is not
        # held during network I/O.
        logger.info(f'[{job_id}] Waiting for GPU slot...')
        async with get_gpu_semaphore():
            logger.info(f'[{job_id}] GPU slot acquired')

            # Transition from 'queued' to 'processing' now that we hold the GPU slot.
            # started_at reflects when GPU work actually began, not queue entry time.
            await job_store.update(
                job_id,
                {
                    'status': 'processing',
                    'started_at': time.time(),
                },
            )

            # Hard wall-clock limit — if the job hangs (stuck synthesis, OOM recovery,
            # CUDA driver issue), the semaphore would be held forever without this.
            # asyncio.timeout cancels the current task after MAX_JOB_DURATION_SECONDS,
            # which unblocks any awaiting run_in_executor call and releases the semaphore.
            try:
                async with asyncio.timeout(MAX_JOB_DURATION_SECONDS):
                    # ─── PHASE 1: NARRATION ──────────────────────────────────────────
                    # LLM rewrites article text into a spoken-form narration script.
                    # No audio is generated in this phase — narration and synthesis are
                    # fully decoupled. The prior architecture synthesized TTS chunks
                    # during narration then discarded them to re-synthesize via
                    # single-shot, causing 5-10× redundant GPU work per job.
                    await _check_status()
                    logger.info(f'[{job_id}] Phase 1: narration...')
                    try:
                        narration = get_narration_strategy()
                    except Exception as exc:
                        logger.warning(f'[{job_id}] Narration strategy init failed: {exc}')
                        narration = None

                    chunk_wav_paths: list[str] = []
                    all_chunks: list[str] = []
                    narrated_segments: list[str] = []
                    total_words = 0
                    narration_skipped = False

                    with _span('tts.narration'):
                        if narration is not None:
                            try:
                                async for segment in narration.narrate_iter(text):
                                    await _check_status()
                                    narrated_segments.append(segment)
                                logger.info(
                                    f'[{job_id}] Narration complete — '
                                    f'{len(narrated_segments)} segments'
                                )
                            except NarrationError:
                                raise  # critical truncation — do not fall back to raw text
                            except Exception as exc:
                                logger.warning(
                                    f'[{job_id}] Narration failed, using raw text: {exc}'
                                )
                                from app.utils.normalize import normalize_for_narration

                                narrated_segments = [normalize_for_narration(text)]
                                narration_skipped = True
                        else:
                            from app.utils.normalize import normalize_for_narration

                            narrated_segments = [normalize_for_narration(text)]

                    full_narrated_text = '\n\n'.join(narrated_segments)
                    if not full_narrated_text.strip():
                        raise RuntimeError('Narrated text is empty')

                    total_words = len(full_narrated_text.split())
                    logger.info(f'[{job_id}] {total_words} narrated words')

                    # ─── PHASE 2: SYNTHESIS ──────────────────────────────────────────
                    # Exactly ONE synthesis path runs based on the final narrated word
                    # count. Choosing the path after narration (not before) is critical —
                    # we cannot know the output word count until the LLM finishes.
                    #
                    # seg_words is the studio-quality segment size per hardware tier
                    # (EngineConfig.studio_segment_words). Short segments (60-100 words)
                    # keep every synthesis call inside Qwen3-TTS's competent AR horizon,
                    # so voice timbre, pitch, and pacing stay stable throughout long
                    # narration. All segments condition on the same clean reference audio
                    # (VOICE_SAMPLE_PATH) to anchor voice identity; AR drift is bounded
                    # per-segment and does not propagate across segment boundaries.
                    #
                    #  ≤ seg_words → single synthesis call (very short content)
                    #  > seg_words → multi-segment synthesis with crossfade concat
                    seg_words = get_studio_segment_words()
                    await _check_status()

                    with _span('tts.synthesis'):
                        if total_words <= seg_words:
                            # Short content: synthesize with real silence at [LONG_PAUSE]
                            # boundaries. synthesize_with_pauses splits the narrated text
                            # at [LONG_PAUSE] markers, synthesizes each part independently,
                            # and joins with 800ms AudioSegment.silent() — deterministic
                            # gaps the autoregressive TTS model cannot produce reliably.
                            logger.info(f'[{job_id}] Phase 2: single-shot ({total_words} words)')
                            from app.utils.text import clean_text_for_tts

                            single_shot_wav = str(job_dir / 'single_shot.wav')
                            chunk_wav_paths = [
                                await synthesize_with_pauses(
                                    text=full_narrated_text,
                                    output_path=single_shot_wav,
                                    job_id=job_id,
                                    generation_kwargs=generation_kwargs,
                                )
                            ]
                            all_chunks = [clean_text_for_tts(full_narrated_text)]
                            logger.info(f'[{job_id}] Single-shot synthesis complete')
                        else:
                            # Long content: split at paragraph boundaries into short
                            # studio segments (~60-100 words per tier), synthesize each
                            # with consistent reference conditioning, then merge.
                            # Short segments keep every synthesis call inside Qwen3-TTS's
                            # competent AR horizon — voice timbre, pitch, and pacing stay
                            # stable because no call ever runs long enough to accumulate
                            # drift. Every segment conditions on the same clean reference
                            # (VOICE_SAMPLE_PATH) rather than the previous segment's tail,
                            # so per-segment AR drift cannot propagate across boundaries.
                            from app.utils.text import split_into_large_segments, clean_text_for_tts

                            sentence_segments = split_into_large_segments(
                                full_narrated_text, seg_words
                            )
                            logger.info(
                                f'[{job_id}] Phase 2: segment synthesis '
                                f'({len(sentence_segments)} × ~{seg_words}-word segments)'
                            )
                            logger.info(
                                '[%s] Segment plan: %d segments, word counts: %s',
                                job_id,
                                len(sentence_segments),
                                [len(s.split()) for s in sentence_segments],
                            )

                            # A segment occasionally exceeds seg_words when a single sentence
                            # is long — don't preemptively fragment it. Sentence prosody is
                            # worth preserving even at 80-90 words (~35s, still well inside
                            # Qwen3-TTS's competent range). If an oversized segment does
                            # fail the acoustic gate, the response ladder's split step
                            # halves it at punctuation and retries.
                            _max_seg = max((len(s.split()) for s in sentence_segments), default=0)
                            if _max_seg > seg_words:
                                logger.info(
                                    '[%s] Longest segment: %d words (target %d); '
                                    'response ladder handles any acoustic drift',
                                    job_id,
                                    _max_seg,
                                    seg_words,
                                )

                            segment_wavs: list[str] = []
                            segment_texts: list[str] = []
                            n_variants = ENGINE_CONFIG.best_of_n

                            for seg_idx, segment_text in enumerate(sentence_segments):
                                if not segment_text.strip():
                                    continue
                                await _check_status()
                                clean_seg = clean_text_for_tts(segment_text)
                                if not clean_seg.strip():
                                    continue
                                segment_wav = str(job_dir / f'segment_{seg_idx:04d}.wav')

                                # Per-segment best-of-N: synthesize n_variants, score each
                                # on F0 drift + WER + drops + flatness, keep the best. On
                                # CPU tier n_variants=1, so this degrades cleanly to a
                                # single synth + score.
                                segment_path, _seg_score = await synthesize_best_of_n_async(
                                    text=clean_seg,
                                    output_path=segment_wav,
                                    n_variants=n_variants,
                                    reference_f0=_reference_f0,
                                    job_id=job_id,
                                    generation_kwargs=generation_kwargs,
                                    voice_path=None,
                                )
                                segment_wavs.append(segment_path)
                                segment_texts.append(clean_seg)
                                logger.info(
                                    f'[{job_id}] Segment {seg_idx + 1}'
                                    f'/{len(sentence_segments)} complete'
                                )

                            if not segment_wavs:
                                raise RuntimeError('Segment synthesis produced no audio files')

                            # Batch quality check: silence / duration / drop / drift / WER
                            # gates per segment, with strategy retries for failures.
                            await _check_status()
                            logger.info(
                                f'[{job_id}] Quality check on {len(segment_wavs)} segments...'
                            )
                            try:
                                segment_wavs = await _quality_check_and_resynthesize(
                                    segment_wavs,
                                    segment_texts,
                                    job_id,
                                    engine,
                                    loop,
                                    executor,
                                    generation_kwargs,
                                    reference_f0=_reference_f0,
                                )
                            except ChunkExhaustedError as exc:
                                raise RuntimeError(
                                    f'Audio quality gate: chunk {exc.chunk_idx} failed all synthesis strategies. '
                                    'Job aborted to prevent shipping broken audio.'
                                ) from exc

                            # Loudness consistency: re-synthesize any segment whose
                            # loudness deviates > 3 dB from the median across segments.
                            await _check_status()
                            logger.info(
                                f'[{job_id}] Loudness consistency check across {len(segment_wavs)} segments...'
                            )
                            try:
                                segment_wavs = await _check_segment_consistency(
                                    segment_wavs,
                                    segment_texts,
                                    job_id,
                                    engine,
                                    loop,
                                    executor,
                                    generation_kwargs,
                                    reference_f0=_reference_f0,
                                )
                            except ChunkExhaustedError as exc:
                                raise RuntimeError(
                                    f'Audio quality gate: chunk {exc.chunk_idx} failed all synthesis strategies. '
                                    'Job aborted to prevent shipping broken audio.'
                                ) from exc

                            if len(segment_wavs) > 1:
                                merged_wav = await loop.run_in_executor(
                                    executor,
                                    functools.partial(
                                        concatenate_audio_with_overlap,
                                        overlap_ms=SINGLE_SHOT_OVERLAP_MS,
                                    ),
                                    segment_wavs,
                                    str(job_dir / 'merged.wav'),
                                )
                                chunk_wav_paths = [merged_wav]
                            else:
                                chunk_wav_paths = segment_wavs

                            # Single merged file — align metadata for concat step
                            all_chunks = [full_narrated_text]

                    if not chunk_wav_paths:
                        raise RuntimeError('No audio chunks were synthesized')

                    # Quality check for the single-shot path.
                    # Segment path already ran quality check before merging above.
                    if total_words <= seg_words:
                        await _check_status()
                        logger.info(
                            f'[{job_id}] Quality check on {len(chunk_wav_paths)} audio file(s)...'
                        )
                        try:
                            chunk_wav_paths = await _quality_check_and_resynthesize(
                                chunk_wav_paths,
                                all_chunks,
                                job_id,
                                engine,
                                loop,
                                executor,
                                generation_kwargs,
                                reference_f0=_reference_f0,
                            )
                        except ChunkExhaustedError as exc:
                            raise RuntimeError(
                                f'Audio quality gate: chunk {exc.chunk_idx} failed all synthesis strategies. '
                                'Job aborted to prevent shipping broken audio.'
                            ) from exc

                    # Step 3: Skip per-chunk normalization — it causes inconsistent loudness
                    # between chunks (single-pass loudnorm is inaccurate). Final mastering
                    # applies proper two-pass loudness normalization to the entire file.
                    await _check_status()
                    logger.info(
                        f'[{job_id}] Skipping per-chunk normalization (relying on final mastering)'
                    )
                    normalized_wav_paths = chunk_wav_paths

                    # Step 4: Copy single WAV to raw_wav — always exactly one file at this
                    # point (single-shot or pre-merged segments), so no concatenation needed.
                    await _check_status()
                    shutil.copy2(normalized_wav_paths[0], raw_wav)

                    # Verify raw WAV was created
                    if not Path(raw_wav).exists():
                        raise RuntimeError('Raw WAV file was not created')

                    raw_size = Path(raw_wav).stat().st_size / (1024 * 1024)
                    logger.info(f'[{job_id}] Raw WAV created ({raw_size:.2f} MB)')

                    # Step 4.5: Neural speech enhancement (DeepFilterNet).
                    # Runs before mastering so LUFS normalization and the
                    # true-peak limiter act on the enhanced signal. Falls back
                    # silently to the unenhanced raw WAV when the package or
                    # model is unavailable — enhancement is a quality pass,
                    # never a correctness prerequisite.
                    await _check_status()
                    from app.domains.enhancement import enhance_audio

                    logger.info(f'[{job_id}] Applying neural speech enhancement...')
                    try:
                        await loop.run_in_executor(executor, enhance_audio, raw_wav, None)
                    except Exception as enh_exc:
                        logger.warning(
                            f'[{job_id}] Enhancement raised unexpectedly: {enh_exc} - '
                            'proceeding with raw WAV'
                        )

                    # Step 5: Apply final mastering (tier-based LUFS, sample rate, bitrate)
                    await _check_status()
                    logger.info(f'[{job_id}] Applying final mastering...')
                    mastering_ok = await loop.run_in_executor(
                        executor,
                        apply_final_mastering,
                        raw_wav,
                        final_mp3,
                    )

                    mastering_used_fallback = False
                    if not mastering_ok:
                        # Fallback: use the raw MP3 if mastering fails
                        logger.warning(f'[{job_id}] Mastering failed, falling back to raw export')
                        # Fallback: export raw WAV to MP3 without mastering
                        if Path(raw_wav).exists():
                            seg = _AudioSegment.from_wav(raw_wav)
                            seg.export(final_mp3, format='mp3', bitrate=MP3_BITRATE)
                            mastering_used_fallback = True

                    # Verify final MP3 was created
                    if not Path(final_mp3).exists():
                        raise RuntimeError('Final MP3 file was not created')

                    mp3_size = Path(final_mp3).stat().st_size / (1024 * 1024)
                    logger.info(f'[{job_id}] Final MP3 created ({mp3_size:.2f} MB)')

            except asyncio.TimeoutError:
                raise RuntimeError(
                    f'[{job_id}] Job exceeded maximum duration of {MAX_JOB_DURATION_SECONDS}s — '
                    f'GPU slot released; check logs for stuck synthesis or LLM calls'
                )

        # GPU slot released — next queued job can start its pipeline.
        logger.info(f'[{job_id}] GPU slot released')

        # Step 6: Quality validation — gate on final file metrics.
        # validate_audio_quality already runs; we now fail the job if the output
        # exceeds safe thresholds rather than shipping broken audio silently.
        try:
            quality = await loop.run_in_executor(
                executor,
                validate_audio_quality,
                final_mp3,
            )
            if quality:
                logger.info(f'[{job_id}] Quality metrics: {quality}')
                _tp = quality.get('true_peak_dbfs')
                _lufs = quality.get('integrated_lufs')
                _silences = quality.get('long_silence_gaps_count', 0)
                from app.config import TARGET_LUFS as _TARGET_LUFS

                _lufs_target = float(_TARGET_LUFS)
                if _tp is not None and _tp > -1.0:
                    raise RuntimeError(
                        f'[{job_id}] Final audio exceeds true-peak limit: {_tp:.1f} dBTP > -1.0 dBTP. '
                        'Mastering limiter likely did not run (check mastering logs).'
                    )
                if _lufs is not None and abs(_lufs - _lufs_target) > 3.0:
                    raise RuntimeError(
                        f'[{job_id}] Final audio LUFS outside tolerance: {_lufs:.1f} LUFS '
                        f'(target {_lufs_target:.1f} ± 3.0). Mastering may have failed.'
                    )
                # Allow up to 3 long silences — legitimate paragraph breaks at
                # [LONG_PAUSE] markers can produce gaps up to ~1.5s.  More than 3
                # indicates dead chunks or synthesis failures, not natural pauses.
                if _silences and _silences > 3:
                    raise RuntimeError(
                        f'[{job_id}] Final audio contains {_silences} long silence gap(s) '
                        '(> 3 is abnormal). Check synthesis and mastering logs.'
                    )
        except RuntimeError:
            raise  # propagate quality gate failures
        except Exception as exc:
            logger.warning(f'[{job_id}] Quality check failed (non-fatal): {exc}')

        # Step 7: Upload to storage backend
        await _check_status()
        audio_uri: Optional[str] = None
        upload_failed = False
        try:
            with _span('tts.storage_upload'):
                backend = get_storage_backend()
                audio_uri = await backend.upload(
                    Path(final_mp3),
                    job_id,
                    site_slug,
                    storage_path=gcs_object_path,
                )
        except Exception as exc:
            logger.error(f'[{job_id}] Storage upload failed (non-fatal): {exc}')
            audio_uri = None
            upload_failed = True

        # Step 8: Cleanup chunk directory and temp files
        cleanup_chunk_files(job_dir, job_id)
        _cleanup_temp_files(normalized_temp_files, job_id)
        _cleanup_intermediate(raw_wav, job_id)

        # Calculate total duration
        total_duration = time.time() - start_time

        # Update job status to completed
        completed_data: dict = {
            'status': 'completed',
            'audio_uri': audio_uri,
            'gcs_uri': audio_uri,  # backward compat
            'local_path': final_mp3,
            'completed_at': time.time(),
            'duration_seconds': total_duration,
        }
        if narration_skipped:
            completed_data['narration_skipped'] = (
                'Narration failed; raw article text was synthesized'
            )
        if mastering_used_fallback:
            completed_data['mastering_warning'] = 'Audio mastering failed; raw export used'
        if upload_failed:
            completed_data['upload_warning'] = 'Storage upload failed; audio available locally only'
        await job_store.update(job_id, completed_data)

        # Record metrics for job completion
        from app.api.routes.metrics import record_job_completed

        record_job_completed(total_duration)

        logger.info(
            f'[{job_id}] ✓ Job completed in {total_duration:.1f}s '
            f'({total_words} words, {len(all_chunks)} chunks)'
        )

        # Step 9: Notify webhook
        await notify_job_completed(job_id, audio_uri)

    except (
        SynthesisError,
        StorageError,
        AudioProcessingError,
        StorageUploadError,
    ) as exc:
        duration = time.time() - start_time
        logger.error(
            f'[{job_id}] ✗ Job failed due to specific domain error after {duration:.1f}s: {exc}'
        )

        _cleanup_failed_job(job_dir, final_mp3, job_id)
        _cleanup_temp_files(normalized_temp_files, job_id)
        _cleanup_intermediate(raw_wav, job_id)

        error_name = exc.__class__.__name__
        error_msg = str(exc)[:450]

        await job_store.update(
            job_id,
            {
                'status': 'failed',
                'error': f'{error_name}: {error_msg}',
                'completed_at': time.time(),
                'duration_seconds': duration,
            },
        )

        # Record metrics for job failure
        from app.api.routes.metrics import record_job_failed

        record_job_failed()

        await notify_job_failed(job_id, f'{error_name}: {error_msg}')

    except Exception as exc:
        duration = time.time() - start_time
        logger.error(
            f'[{job_id}] ✗ Job failed after {duration:.1f}s: {exc}',
            exc_info=not isinstance(exc, JobDeletedError),
        )

        # Handle explicit deletion
        if isinstance(exc, JobDeletedError):
            logger.info(f'[{job_id}] Aborting job due to deletion')
            _cleanup_failed_job(job_dir, final_mp3, job_id)
            _cleanup_temp_files(normalized_temp_files, job_id)
            _cleanup_intermediate(raw_wav, job_id)
            return

        # Cleanup on failure
        _cleanup_failed_job(job_dir, final_mp3, job_id)
        _cleanup_temp_files(normalized_temp_files, job_id)
        _cleanup_intermediate(raw_wav, job_id)

        # Update job status to failed
        error_message = str(exc)[:450]  # Truncate long error messages
        await job_store.update(
            job_id,
            {
                'status': 'failed',
                'error': error_message,
                'completed_at': time.time(),
                'duration_seconds': duration,
            },
        )

        # Record metrics for job failure
        from app.api.routes.metrics import record_job_failed

        record_job_failed()

        # Notify webhook of failure
        await notify_job_failed(job_id, error_message)


def _cleanup_failed_job(job_dir: Path, final_mp3: str, job_id: str) -> None:
    """
    Clean up resources after a failed job.

    Args:
        job_dir: Directory containing chunk files.
        final_mp3: Path to the (possibly partial) MP3 file.
        job_id: Job identifier for logging.
    """
    # Remove chunk directory
    try:
        shutil.rmtree(job_dir, ignore_errors=True)
    except Exception as cleanup_exc:
        logger.warning(f'[{job_id}] Cleanup failed: {cleanup_exc}')

    # Remove partial MP3 if it exists
    try:
        mp3_path = Path(final_mp3)
        if mp3_path.exists():
            mp3_path.unlink(missing_ok=True)
    except Exception as cleanup_exc:
        logger.warning(f'[{job_id}] Failed to remove partial MP3: {cleanup_exc}')


def _cleanup_temp_files(temp_files: list[str], job_id: str) -> None:
    """
    Clean up temporary normalized WAV files.

    Args:
        temp_files: List of temp file paths to remove.
        job_id: Job identifier for logging.
    """
    for temp_file in temp_files:
        try:
            if os.path.exists(temp_file):
                os.unlink(temp_file)
        except Exception as exc:
            logger.warning(f'[{job_id}] Failed to remove temp file {temp_file}: {exc}')


def _cleanup_intermediate(path: str, job_id: str) -> None:
    """
    Clean up an intermediate file (raw WAV or MP3).

    Args:
        path: Path to the intermediate file.
        job_id: Job identifier for logging.
    """
    try:
        if os.path.exists(path):
            os.unlink(path)
    except Exception as exc:
        logger.warning(f'[{job_id}] Failed to remove {path}: {exc}')
