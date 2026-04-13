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
    JobDeletedError,
    SynthesisError,
    StorageError,
    AudioProcessingError,
    StorageUploadError,
)
from app.config import (
    DEVICE,
    MAX_CHUNK_WORDS,
    MAX_JOB_DURATION_SECONDS,
    MP3_BITRATE,
    OUTPUT_DIR,
)
from app.domains.narration.factory import get_narration_strategy
from app.domains.synthesis.concatenate import concatenate_audio_auto as concatenate_wavs_auto
from app.domains.synthesis.quality import validate_audio_quality, apply_final_mastering
from app.domains.synthesis.quality_check import (
    _quality_check_and_resynthesize,
)
from app.domains.job.store import get_job_store
from app.domains.job.notification import notify_job_completed, notify_job_failed
from app.domains.storage import get_storage_backend
from app.domains.tts_config.store import get_effective_config
from app.domains.synthesis.service import (
    cleanup_chunk_files,
    get_executor,
    prepare_text_for_synthesis,
    synthesize_chunks_auto,
)

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

    This orchestrator manages:
    1. Status tracking via JobStore (Redis).
    2. TTS engine readiness check.
    3. LLM narration (article text → spoken podcast script).
    4. Text chunking for TTS synthesis.
    5. Chunk synthesis (sequential on GPU, parallel on CPU).
    6. Per-chunk normalization and concatenation with dynamic gaps.
    7. Final mastering (EBU R128 loudness normalization).
    8. Quality validation, upload, and webhook notification.

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

        # Fetch generation config once (async Redis read) before entering thread pool
        generation_kwargs, _overrides = await get_effective_config()

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
                    # Step 1+2+3: Narrate, chunk, and synthesize (pipelined when possible)
                    await _check_status()
                    logger.info(f'[{job_id}] Starting narration + synthesis pipeline...')
                    try:
                        narration = get_narration_strategy()
                    except Exception as exc:
                        logger.warning(f'[{job_id}] Narration strategy init failed: {exc}')
                        narration = None

                    chunk_wav_paths: list[str] = []
                    all_chunks: list[str] = []
                    chunk_pause_durations: list[int] = []
                    total_words = 0
                    chunk_index = 0
                    narration_skipped = False
                    with _span('tts.narration_synthesis'):
                        if narration is not None:
                            # True pipelined: LLM narration of chunk N+1 runs concurrently with
                            # TTS synthesis of chunk N via asyncio producer-consumer with a queue.
                            #
                            # The original `async for` loop was NOT pipelined — Python's async
                            # generator only advances when __anext__() is called, which happens
                            # after the loop body (TTS synthesis) fully completes. Using a
                            # background task + Queue decouples the two stages so the LLM HTTP
                            # call and Ollama inference genuinely overlap with TTS thread work.
                            try:
                                _narration_queue: asyncio.Queue[Optional[str]] = asyncio.Queue(
                                    maxsize=2
                                )
                                _producer_errors: list[BaseException] = []

                                async def _narration_producer() -> None:
                                    try:
                                        async for segment in narration.narrate_iter(text):
                                            await _check_status()
                                            await _narration_queue.put(segment)
                                    except Exception as exc:
                                        _producer_errors.append(exc)
                                    finally:
                                        # Always deliver sentinel so consumer can exit cleanly
                                        await _narration_queue.put(None)

                                async def _synthesis_consumer() -> None:
                                    nonlocal total_words, chunk_index
                                    while True:
                                        segment = await _narration_queue.get()
                                        if segment is None:
                                            break
                                        await _check_status()
                                        tts_chunks, seg_words, seg_pauses = (
                                            prepare_text_for_synthesis(segment, MAX_CHUNK_WORDS)
                                        )
                                        all_chunks.extend(tts_chunks)
                                        chunk_pause_durations.extend(seg_pauses)
                                        total_words += seg_words
                                        paths = await synthesize_chunks_auto(
                                            chunks=tts_chunks,
                                            job_dir=job_dir,
                                            job_id=job_id,
                                            status_check_callback=_check_status,
                                            chunk_offset=chunk_index,
                                            generation_kwargs=generation_kwargs,
                                        )
                                        chunk_wav_paths.extend(paths)
                                        chunk_index += len(tts_chunks)

                                _producer_task = asyncio.create_task(_narration_producer())
                                try:
                                    await _synthesis_consumer()
                                finally:
                                    if not _producer_task.done():
                                        _producer_task.cancel()
                                    # Drain the queue so the producer's blocked put() can
                                    # complete and the task can exit.  get_nowait() calls
                                    # _wakeup_next internally, waking the awaiting putter;
                                    # await sleep(0) yields the event loop so it can run.
                                    for _ in range(50):
                                        if _producer_task.done():
                                            break
                                        while not _narration_queue.empty():
                                            try:
                                                _narration_queue.get_nowait()
                                            except asyncio.QueueEmpty:
                                                break
                                        await asyncio.sleep(0)
                                    try:
                                        await _producer_task
                                    except (asyncio.CancelledError, Exception):
                                        pass

                                if _producer_errors:
                                    raise _producer_errors[0]

                                logger.info(
                                    f'[{job_id}] Pipelined narration+synthesis complete — '
                                    f'{len(chunk_wav_paths)} audio chunks, {total_words} words'
                                )
                            except Exception as exc:
                                logger.warning(
                                    f'[{job_id}] Pipelined narration failed, falling back to sequential: {exc}'
                                )
                                # Fallback: narrate all, then synthesize all
                                try:
                                    narrated_text = await narration.narrate(text)
                                except Exception as narration_exc:
                                    logger.warning(
                                        f'[{job_id}] Sequential narration also failed, using raw text: {narration_exc}'
                                    )
                                    from app.utils.normalize import normalize_for_narration

                                    narrated_text = normalize_for_narration(text)
                                    narration_skipped = True
                                all_chunks, total_words, chunk_pause_durations = (
                                    prepare_text_for_synthesis(narrated_text, MAX_CHUNK_WORDS)
                                )
                                chunk_wav_paths = await synthesize_chunks_auto(
                                    chunks=all_chunks,
                                    job_dir=job_dir,
                                    job_id=job_id,
                                    status_check_callback=_check_status,
                                    generation_kwargs=generation_kwargs,
                                )
                        else:
                            # No narration available — synthesize raw text directly
                            from app.utils.normalize import normalize_for_narration

                            normalized_text = normalize_for_narration(text)
                            all_chunks, total_words, chunk_pause_durations = (
                                prepare_text_for_synthesis(normalized_text, MAX_CHUNK_WORDS)
                            )
                            chunk_wav_paths = await synthesize_chunks_auto(
                                chunks=all_chunks,
                                job_dir=job_dir,
                                job_id=job_id,
                                status_check_callback=_check_status,
                                generation_kwargs=generation_kwargs,
                            )

                    if not chunk_wav_paths:
                        raise RuntimeError('No audio chunks were synthesized')

                    # Step 3b: Quality check and re-synthesis
                    await _check_status()
                    logger.info(
                        f'[{job_id}] Running quality check on {len(chunk_wav_paths)} chunks...'
                    )
                    chunk_wav_paths = await _quality_check_and_resynthesize(
                        chunk_wav_paths,
                        all_chunks,
                        job_id,
                        engine,
                        loop,
                        executor,
                        generation_kwargs,
                    )

                    # Step 4: Skip per-chunk normalization — it causes inconsistent loudness
                    # between chunks (single-pass loudnorm is inaccurate). Final mastering
                    # applies proper two-pass loudness normalization to the entire file.
                    await _check_status()
                    logger.info(
                        f'[{job_id}] Skipping per-chunk normalization (relying on final mastering)'
                    )
                    normalized_wav_paths = chunk_wav_paths

                    # Step 4: Concatenate WAVs with dynamic gaps into raw WAV
                    await _check_status()
                    try:
                        _concat_fn = functools.partial(
                            concatenate_wavs_auto,
                            explicit_pause_durations=chunk_pause_durations,
                        )
                        await loop.run_in_executor(
                            executor,
                            _concat_fn,
                            normalized_wav_paths,
                            raw_wav,
                            all_chunks,  # Pass chunk texts for dynamic pause detection
                        )
                    except Exception as exc:
                        raise RuntimeError(f'Audio concatenation failed: {exc}') from exc

                    # Verify raw WAV was created
                    if not Path(raw_wav).exists():
                        raise RuntimeError('Raw WAV file was not created')

                    raw_size = Path(raw_wav).stat().st_size / (1024 * 1024)
                    logger.info(f'[{job_id}] Raw WAV created ({raw_size:.2f} MB)')

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

        # Step 6: Quality validation (non-fatal, log only)
        try:
            quality = await loop.run_in_executor(
                executor,
                validate_audio_quality,
                final_mp3,
            )
            if quality:
                logger.info(f'[{job_id}] Quality metrics: {quality}')
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
