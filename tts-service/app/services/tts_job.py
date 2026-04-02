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
import logging
import os
import shutil
import time
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
    GCS_BUCKET_NAME,
    MAX_CHUNK_WORDS,
    MP3_BITRATE,
    OUTPUT_DIR,
    get_narration_strategy,
)
from app.services.audio import (
    apply_final_mastering,
    concatenate_wavs_auto,
    normalize_chunk_to_target_lufs,
    validate_audio_quality,
)
from app.services.job_store import get_job_store
from app.services.notification import notify_job_completed, notify_job_failed
from app.services.storage import get_storage_backend
from app.services.synthesis import (
    cleanup_chunk_files,
    get_executor,
    prepare_text_for_synthesis,
    synthesize_chunks_auto,
)

logger = logging.getLogger(__name__)


async def _quality_check_and_resynthesize(
    chunk_wav_paths: list[str],
    chunk_texts: list[str],
    job_id: str,
    engine,
    loop,
    executor,
) -> list[str]:
    """Check audio quality of each chunk and re-synthesize bad ones.

    HIGH_VRAM only — checks for:
    - Excessive silence (>50% of chunk is silence)
    - Clipping (samples at 0dBFS)
    - Very low energy (likely failed synthesis)

    Re-synthesizes failed chunks once, then uses original if still bad.
    """
    from app.services.audio import get_audio_duration

    checked_paths = list(chunk_wav_paths)
    resynth_count = 0

    for i, wav_path in enumerate(chunk_wav_paths):
        try:
            seg = _AudioSegment.from_wav(wav_path)
            duration_ms = len(seg)
            if duration_ms < 100:
                # Extremely short — likely failed
                logger.warning(
                    f"[{job_id}] Chunk {i} is only {duration_ms}ms — re-synthesizing"
                )
                checked_paths[i] = await _resynthesize_chunk(
                    i, chunk_texts, job_id, engine, loop, executor
                )
                resynth_count += 1
                continue

            # Check silence ratio
            silence_threshold = seg.dBFS - 30  # 30dB below average = silence
            silence_ms = 0
            chunk_size = 50  # ms
            for j in range(0, duration_ms, chunk_size):
                c = seg[j : j + chunk_size]
                if c.dBFS < silence_threshold:
                    silence_ms += chunk_size
            silence_ratio = silence_ms / duration_ms

            if silence_ratio > 0.5:
                logger.warning(
                    f"[{job_id}] Chunk {i} is {silence_ratio:.0%} silence — re-synthesizing"
                )
                checked_paths[i] = await _resynthesize_chunk(
                    i, chunk_texts, job_id, engine, loop, executor
                )
                resynth_count += 1

        except Exception as exc:
            logger.debug(f"[{job_id}] Quality check for chunk {i} skipped: {exc}")

    if resynth_count > 0:
        logger.info(
            f"[{job_id}] Re-synthesized {resynth_count} chunks after quality check"
        )

    return checked_paths


async def _resynthesize_chunk(
    chunk_idx: int,
    chunk_texts: list[str],
    job_id: str,
    engine,
    loop,
    executor,
) -> str:
    """Re-synthesize a single chunk. Returns the path (may be original if re-synth fails)."""
    from app.config import OUTPUT_DIR

    if chunk_idx >= len(chunk_texts):
        return ""

    job_dir = OUTPUT_DIR / job_id
    wav_path = str(job_dir / f"chunk_{chunk_idx:04d}.wav")

    try:
        await loop.run_in_executor(
            executor,
            engine.synthesize_to_file,
            chunk_texts[chunk_idx],
            wav_path,
            job_id,
        )
        return wav_path
    except Exception as exc:
        logger.warning(f"[{job_id}] Re-synthesis of chunk {chunk_idx} failed: {exc}")
        return wav_path  # Return original path


async def run_tts_job(
    job_id: str,
    text: str,
    gcs_object_path: str,
    site_slug: str = "site",
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
    raw_wav = str(OUTPUT_DIR / f"{job_id}_raw.wav")
    final_mp3 = str(OUTPUT_DIR / f"{job_id}.mp3")
    job_store = get_job_store()
    executor = get_executor()

    async def _check_status() -> None:
        """Check if job is deleted or paused."""
        paused_iterations = 0
        max_paused_iterations = 1800  # 30 minutes max pause
        while True:
            job = await job_store.get(job_id)
            if not job or job.get("status") == "deleted":
                raise JobDeletedError(f"Job {job_id} was deleted")
            if job.get("status") == "paused":
                paused_iterations += 1
                if paused_iterations >= max_paused_iterations:
                    raise JobDeletedError(
                        f"Job {job_id} exceeded maximum pause duration"
                    )
                await asyncio.sleep(1)
                continue
            paused_iterations = 0  # Reset counter when job is no longer paused
            return

    # Track temp files for cleanup
    normalized_temp_files: list[str] = []

    # Validate executor is initialized
    if executor is None:
        logger.error(f"[{job_id}] Thread pool executor not initialized")
        await job_store.update(
            job_id,
            {
                "status": "failed",
                "error": "Service not properly initialized: executor unavailable",
                "completed_at": time.time(),
                "duration_seconds": 0,
            },
        )
        return

    # Create job directory
    try:
        job_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.error(f"[{job_id}] Failed to create job directory: {exc}")
        await job_store.update(
            job_id,
            {
                "status": "failed",
                "error": f"Directory creation failed: {exc}",
                "completed_at": time.time(),
                "duration_seconds": 0,
            },
        )
        return

    logger.info(f"[{job_id}] Job started - {len(text)} chars, device={DEVICE}")

    try:
        # Update status to processing
        await job_store.update(
            job_id,
            {
                "status": "processing",
                "started_at": start_time,
            },
        )

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
                    raise RuntimeError("TTS engine failed to initialize within timeout")

        if not engine.is_ready:
            raise RuntimeError("TTS engine failed to initialize within timeout")

        # Step 1+2+3: Narrate, chunk, and synthesize (pipelined when possible)
        await _check_status()
        logger.info(f"[{job_id}] Starting narration + synthesis pipeline...")
        try:
            narration = get_narration_strategy()
        except Exception as exc:
            logger.warning(f"[{job_id}] Narration strategy init failed: {exc}")
            narration = None

        chunk_wav_paths: list[str] = []
        all_chunks: list[str] = []
        total_words = 0
        chunk_index = 0

        if narration is not None:
            # Pipelined: narrate chunk N, synthesize chunk N while narrating chunk N+1
            try:
                async for narrated_segment in narration.narrate_iter(text):
                    await _check_status()
                    # Split this narrated segment into TTS-sized chunks
                    tts_chunks, seg_words = prepare_text_for_synthesis(
                        narrated_segment, MAX_CHUNK_WORDS
                    )
                    all_chunks.extend(tts_chunks)
                    total_words += seg_words

                    # Synthesize these TTS chunks immediately (don't wait for next narration)
                    segment_paths = await synthesize_chunks_auto(
                        chunks=tts_chunks,
                        job_dir=job_dir,
                        job_id=f"{job_id}",
                        status_check_callback=_check_status,
                        chunk_offset=chunk_index,
                    )
                    chunk_wav_paths.extend(segment_paths)
                    chunk_index += len(tts_chunks)

                logger.info(
                    f"[{job_id}] Pipelined narration+synthesis complete — "
                    f"{len(chunk_wav_paths)} audio chunks, {total_words} words"
                )
            except Exception as exc:
                logger.warning(
                    f"[{job_id}] Pipelined narration failed, falling back to sequential: {exc}"
                )
                # Fallback: narrate all, then synthesize all
                try:
                    narrated_text = await narration.narrate(text)
                except Exception:
                    narrated_text = text
                all_chunks, total_words = prepare_text_for_synthesis(
                    narrated_text, MAX_CHUNK_WORDS
                )
                chunk_wav_paths = await synthesize_chunks_auto(
                    chunks=all_chunks,
                    job_dir=job_dir,
                    job_id=job_id,
                    status_check_callback=_check_status,
                )
        else:
            # No narration available — synthesize raw text directly
            all_chunks, total_words = prepare_text_for_synthesis(text, MAX_CHUNK_WORDS)
            chunk_wav_paths = await synthesize_chunks_auto(
                chunks=all_chunks,
                job_dir=job_dir,
                job_id=job_id,
                status_check_callback=_check_status,
            )

        if not chunk_wav_paths:
            raise RuntimeError("No audio chunks were synthesized")

        # Step 3b: Quality check and re-synthesis (HIGH_VRAM only)
        from app.core.hardware import ENGINE_CONFIG, HardwareTier

        if ENGINE_CONFIG.tier == HardwareTier.HIGH_VRAM:
            await _check_status()
            logger.info(
                f"[{job_id}] Running quality check on {len(chunk_wav_paths)} chunks..."
            )
            chunk_wav_paths = await _quality_check_and_resynthesize(
                chunk_wav_paths, all_chunks, job_id, engine, loop, executor
            )

        # Step 4: Normalize chunks to -23 LUFS (skip very short chunks —
        # single-pass loudnorm is inaccurate under ~10s, and final mastering
        # re-normalizes the whole file anyway)
        await _check_status()
        logger.info(
            f"[{job_id}] Normalizing {len(chunk_wav_paths)} chunks (parallel)..."
        )

        async def _normalize_one(i: int, wav_path: str) -> str:
            try:
                # Skip normalization for very short chunks (<10s) — not enough
                # signal for loudnorm to measure accurately, and final mastering
                # will re-normalize the concatenated file
                seg = _AudioSegment.from_wav(wav_path)
                if len(seg) < 10_000:  # <10 seconds
                    logger.debug(
                        f"[{job_id}] Chunk {i} is {len(seg) / 1000:.1f}s — skipping per-chunk norm"
                    )
                    return wav_path

                normalized_path = await loop.run_in_executor(
                    executor,
                    normalize_chunk_to_target_lufs,
                    wav_path,
                    -23.0,
                )
                if normalized_path != wav_path:
                    normalized_temp_files.append(normalized_path)
                return normalized_path
            except Exception as exc:
                logger.warning(
                    f"[{job_id}] Chunk {i} normalization failed, using original: {exc}"
                )
                return wav_path

        normalized_wav_paths = list(
            await asyncio.gather(
                *[_normalize_one(i, p) for i, p in enumerate(chunk_wav_paths)]
            )
        )

        logger.info(f"[{job_id}] Normalization complete")

        # Step 4: Concatenate WAVs with dynamic gaps into raw WAV
        await _check_status()
        try:
            await loop.run_in_executor(
                executor,
                concatenate_wavs_auto,
                normalized_wav_paths,
                raw_wav,
                all_chunks,  # Pass chunk texts for dynamic pause detection
            )
        except Exception as exc:
            raise RuntimeError(f"Audio concatenation failed: {exc}") from exc

        # Verify raw WAV was created
        if not Path(raw_wav).exists():
            raise RuntimeError("Raw WAV file was not created")

        raw_size = Path(raw_wav).stat().st_size / (1024 * 1024)
        logger.info(f"[{job_id}] Raw WAV created ({raw_size:.2f} MB)")

        # Step 5: Apply final mastering (tier-based LUFS, sample rate, bitrate)
        await _check_status()
        logger.info(f"[{job_id}] Applying final mastering...")
        mastering_ok = await loop.run_in_executor(
            executor,
            apply_final_mastering,
            raw_wav,
            final_mp3,
        )

        mastering_used_fallback = False
        if not mastering_ok:
            # Fallback: use the raw MP3 if mastering fails
            logger.warning(f"[{job_id}] Mastering failed, falling back to raw export")
            # Fallback: export raw WAV to MP3 without mastering
            if Path(raw_wav).exists():
                seg = _AudioSegment.from_wav(raw_wav)
                seg.export(final_mp3, format="mp3", bitrate=MP3_BITRATE)
                mastering_used_fallback = True

        # Verify final MP3 was created
        if not Path(final_mp3).exists():
            raise RuntimeError("Final MP3 file was not created")

        mp3_size = Path(final_mp3).stat().st_size / (1024 * 1024)
        logger.info(f"[{job_id}] Final MP3 created ({mp3_size:.2f} MB)")

        # Step 6: Quality validation (non-fatal, log only)
        try:
            quality = await loop.run_in_executor(
                executor,
                validate_audio_quality,
                final_mp3,
            )
            if quality:
                logger.info(f"[{job_id}] Quality metrics: {quality}")
        except Exception as exc:
            logger.warning(f"[{job_id}] Quality check failed (non-fatal): {exc}")

        # Step 7: Upload to storage backend
        await _check_status()
        audio_uri: Optional[str] = None
        upload_failed = False
        try:
            backend = get_storage_backend()
            audio_uri = await backend.upload(
                Path(final_mp3),
                job_id,
                site_slug,
            )
        except Exception as exc:
            logger.error(f"[{job_id}] Storage upload failed (non-fatal): {exc}")
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
            "status": "completed",
            "audio_uri": audio_uri,
            "gcs_uri": audio_uri,  # backward compat
            "local_path": final_mp3,
            "completed_at": time.time(),
            "duration_seconds": total_duration,
        }
        if mastering_used_fallback:
            completed_data["mastering_warning"] = (
                "Audio mastering failed; raw export used"
            )
        if upload_failed:
            completed_data["upload_warning"] = (
                "Storage upload failed; audio available locally only"
            )
        await job_store.update(job_id, completed_data)

        logger.info(
            f"[{job_id}] ✓ Job completed in {total_duration:.1f}s "
            f"({total_words} words, {len(all_chunks)} chunks)"
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
            f"[{job_id}] ✗ Job failed due to specific domain error after {duration:.1f}s: {exc}"
        )

        _cleanup_failed_job(job_dir, final_mp3, job_id)
        _cleanup_temp_files(normalized_temp_files, job_id)
        _cleanup_intermediate(raw_wav, job_id)

        error_name = exc.__class__.__name__
        error_msg = str(exc)[:450]

        await job_store.update(
            job_id,
            {
                "status": "failed",
                "error": f"{error_name}: {error_msg}",
                "completed_at": time.time(),
                "duration_seconds": duration,
            },
        )
        await notify_job_failed(job_id, f"{error_name}: {error_msg}")

    except Exception as exc:
        duration = time.time() - start_time
        logger.error(
            f"[{job_id}] ✗ Job failed after {duration:.1f}s: {exc}",
            exc_info=not isinstance(exc, JobDeletedError),
        )

        # Handle explicit deletion
        if isinstance(exc, JobDeletedError):
            logger.info(f"[{job_id}] Aborting job due to deletion")
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
                "status": "failed",
                "error": error_message,
                "completed_at": time.time(),
                "duration_seconds": duration,
            },
        )

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
        logger.warning(f"[{job_id}] Cleanup failed: {cleanup_exc}")

    # Remove partial MP3 if it exists
    try:
        mp3_path = Path(final_mp3)
        if mp3_path.exists():
            mp3_path.unlink(missing_ok=True)
    except Exception as cleanup_exc:
        logger.warning(f"[{job_id}] Failed to remove partial MP3: {cleanup_exc}")


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
            logger.warning(f"[{job_id}] Failed to remove temp file {temp_file}: {exc}")


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
        logger.warning(f"[{job_id}] Failed to remove {path}: {exc}")
