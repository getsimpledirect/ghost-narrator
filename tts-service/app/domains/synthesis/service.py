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
Synthesis service domain for TTS chunk processing.

Provides functions for synthesizing text chunks into audio files
with support for both sequential and parallel processing.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Optional

from pydub import AudioSegment

from app.core.hardware import ENGINE_CONFIG
from app.core.exceptions import SynthesisError
from app.core.tts_engine import get_tts_engine
from app.utils.text import clean_text_for_tts, has_quoted_speech, split_at_quotes
from app.domains.synthesis.concatenate import _trim_silence

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Global executor instance
_executor: Optional[concurrent.futures.ThreadPoolExecutor] = None


def initialize_executor(max_workers: int) -> concurrent.futures.ThreadPoolExecutor:
    """
    Initialize the thread pool executor.

    Args:
        max_workers: Maximum number of worker threads.

    Returns:
        The initialized ThreadPoolExecutor.
    """
    global _executor

    _executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    logger.info(f'Thread pool executor initialized with {max_workers} workers')
    return _executor


def get_executor() -> Optional[concurrent.futures.ThreadPoolExecutor]:
    """
    Get the global executor instance.

    Returns:
        The executor if initialized, None otherwise.
    """
    return _executor


def shutdown_executor(wait: bool = True, cancel_futures: bool = True) -> None:
    """
    Shutdown the thread pool executor.

    Args:
        wait: Whether to wait for pending tasks to complete.
        cancel_futures: Whether to cancel pending futures.
    """
    global _executor

    if _executor:
        try:
            _executor.shutdown(wait=wait, cancel_futures=cancel_futures)
            logger.info('Thread pool executor shut down')
        except Exception as exc:
            logger.error(f'Error shutting down executor: {exc}')
        finally:
            _executor = None


def synthesize_chunk(
    text: str,
    output_path: str,
    job_id: str = 'default',
    generation_kwargs: Optional[dict] = None,
) -> str:
    """
    Synthesize a single text chunk using Qwen3-TTS voice cloning.

    When the chunk contains quoted speech (detected via double-quote marks),
    the text is split at quote boundaries and each segment is synthesized
    independently. Quoted segments use a higher sampling temperature to produce
    more expressive delivery, then all sub-segments are joined with an 80ms
    breath gap. This is the multi-voice path; chunks without quotes go through
    the fast single-synthesis path.

    This is a synchronous function designed to run in a thread pool.

    Args:
        text: The text to synthesize.
        output_path: Path where the WAV file will be saved.
        job_id: Job identifier for process tracking.
        generation_kwargs: Generation parameters forwarded to the TTS engine.

    Returns:
        The output path of the generated WAV file.

    Raises:
        SynthesisError: If synthesis fails.
    """
    if not text or not text.strip():
        raise SynthesisError(
            'Cannot synthesize empty text',
            details=f'output_path={output_path}',
        )

    engine = get_tts_engine()

    # Fast path: no quoted speech detected — single synthesis call.
    if not has_quoted_speech(text):
        return engine.synthesize_to_file(
            text, output_path, job_id, generation_kwargs=generation_kwargs
        )

    # Multi-voice path: split at quote boundaries, synthesize each segment
    # with per-type generation parameters, then concatenate.
    segments = split_at_quotes(text)
    if len(segments) <= 1:
        return engine.synthesize_to_file(
            text, output_path, job_id, generation_kwargs=generation_kwargs
        )

    out_path = Path(output_path)
    temp_dir = out_path.parent / f'_mv_{out_path.stem}'
    temp_dir.mkdir(exist_ok=True)
    try:
        sub_wav_paths: list[str] = []
        for i, (seg_text, is_quote) in enumerate(segments):
            if not seg_text.strip():
                continue
            seg_path = str(temp_dir / f'seg_{i:04d}.wav')
            seg_kwargs = dict(generation_kwargs or {})
            if is_quote:
                # Quoted speech: raise temperature and top_p for more expressive delivery.
                # Cap at 0.55/0.92 so voice identity is preserved — the reference prompt
                # still anchors timbre; only prosody variance increases.
                seg_kwargs['temperature'] = min((seg_kwargs.get('temperature') or 0.3) + 0.15, 0.55)
                seg_kwargs['top_p'] = min((seg_kwargs.get('top_p') or 0.85) + 0.05, 0.92)
            engine.synthesize_to_file(seg_text, seg_path, job_id, generation_kwargs=seg_kwargs)
            sub_wav_paths.append(seg_path)

        if not sub_wav_paths:
            raise SynthesisError(
                'Multi-voice synthesis produced no segments',
                details=f'output_path={output_path}',
            )

        # Join sub-segments with an 80ms breath gap — models the natural pause
        # between a narrator sentence and the start of quoted speech.
        # Derive silence properties from the first real segment so frame_rate,
        # channels, and sample_width match — pydub does not auto-resample on
        # concatenation, so a mismatched silent() causes audio glitches.
        combined = _trim_silence(AudioSegment.from_wav(sub_wav_paths[0]))
        # pydub.AudioSegment.silent() only accepts duration and frame_rate —
        # channels and sample_width must be set via chained method calls.
        breath = (
            AudioSegment.silent(duration=80, frame_rate=combined.frame_rate)
            .set_channels(combined.channels)
            .set_sample_width(combined.sample_width)
        )
        for path in sub_wav_paths[1:]:
            seg = _trim_silence(AudioSegment.from_wav(path))
            combined = combined + breath + seg

        combined.export(output_path, format='wav')
        logger.debug(
            '[%s] Multi-voice synthesis: %d segments → %s', job_id, len(sub_wav_paths), output_path
        )
        return output_path

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def synthesize_single_shot(
    text: str,
    output_path: str,
    job_id: str = 'default',
    generation_kwargs: Optional[dict] = None,
    voice_path: Optional[str] = None,
) -> str:
    """
    Synthesize a large text in a single pass using Qwen3-TTS.

    This produces studio-quality audio with no chunk boundaries,
    eliminating pitch/speed/volume variations between chunks.

    Args:
        text: The full text to synthesize (up to ~4000 words recommended).
        output_path: Path where the WAV file will be saved.
        job_id: Job identifier for process tracking.
        generation_kwargs: Generation parameters forwarded to the TTS engine.
        voice_path: Optional explicit WAV path for voice conditioning (e.g. tail
            of the previous segment for inter-segment voice consistency).

    Returns:
        The output path of the generated WAV file.

    Raises:
        SynthesisError: If synthesis fails.
    """
    if not text or not text.strip():
        raise SynthesisError(
            'Cannot synthesize empty text',
            details=f'output_path={output_path}',
        )

    from app.utils.text import is_speakable_text

    if not is_speakable_text(text):
        raise SynthesisError(
            'Text failed pre-TTS speakability check — likely contains code or URLs',
            details=f'text[:80]={text[:80]!r}',
        )

    engine = get_tts_engine()
    result = engine.synthesize_to_file(
        text,
        output_path,
        job_id,
        generation_kwargs=generation_kwargs,
        voice_override=voice_path,
    )
    # Trim leading and trailing silence from the raw synthesis output.
    # Leading silence: Qwen3-TTS sometimes emits silence tokens before the first
    # word, causing >50% silence quality-check failures and wasted re-synthesis.
    # Trailing silence: ensures the tail-conditioning reference (last 2.5 s of this
    # segment) ends on speech rather than silence, preventing cascading silence
    # across segment boundaries when the tail is used as voice_override for the
    # next segment.
    try:
        seg = AudioSegment.from_wav(result)
        trimmed = _trim_silence(seg)
        if len(trimmed) >= 100:
            trimmed.export(result, format='wav')
    except Exception as _trim_exc:
        logger.debug('[%s] Post-synthesis silence trim failed (non-fatal): %s', job_id, _trim_exc)
    return result


async def synthesize_single_shot_async(
    text: str,
    output_path: str,
    job_id: str = 'default',
    generation_kwargs: Optional[dict] = None,
    voice_path: Optional[str] = None,
) -> str:
    """
    Async wrapper for single-shot synthesis.

    Runs the synchronous single-shot synthesis in a thread pool.
    voice_path, when provided, conditions the TTS model on that WAV's voice
    characteristics (used for inter-segment tail conditioning).
    """
    if not _executor:
        raise SynthesisError(
            'Executor not initialized',
            details='Call initialize_executor() during startup',
        )

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _executor,
        synthesize_single_shot,
        text,
        output_path,
        job_id,
        generation_kwargs,
        voice_path,
    )


def _extract_tail_wav(wav_path: str, duration_ms: int, output_path: str) -> str:
    """Extract the last duration_ms of a WAV file as a voice conditioning reference.

    Used for inter-segment tail conditioning: the tail of segment N is passed as
    the voice reference for segment N+1, anchoring timbre and speaking rate across
    the segment boundary. pydub clips to available length if the segment is shorter
    than duration_ms, so short final segments are handled gracefully.
    """
    seg = AudioSegment.from_wav(wav_path)
    tail = seg[-duration_ms:]
    tail.export(output_path, format='wav')
    return output_path


async def synthesize_chunks_sequential(
    chunks: list[str],
    job_dir: Path,
    job_id: str,
    status_check_callback: Optional[Callable[[], Coroutine[Any, Any, None]]] = None,
    chunk_offset: int = 0,
    generation_kwargs: Optional[dict] = None,
) -> list[str]:
    """
    Synthesize multiple chunks sequentially.

    This method is preferred when running on GPU to avoid memory issues.

    Args:
        chunks: List of text chunks to synthesize.
        job_dir: Directory for output chunk files.
        job_id: Job identifier for logging.
        chunk_offset: Starting index for chunk file naming (for pipelined synthesis).

    Returns:
        List of paths to generated WAV files.

    Raises:
        SynthesisError: If synthesis fails for any chunk.
    """
    if not chunks:
        raise SynthesisError('Cannot synthesize empty chunks list')

    if not _executor:
        raise SynthesisError(
            'Executor not initialized',
            details='Call initialize_executor() during startup',
        )

    loop = asyncio.get_running_loop()
    chunk_wav_paths: list[str] = []

    for idx, chunk in enumerate(chunks):
        # Check job status before each chunk
        if status_check_callback:
            await status_check_callback()

        chunk_wav = str(job_dir / f'chunk_{chunk_offset + idx:04d}.wav')
        word_count = len(chunk.split())

        logger.info(f'[{job_id}] Synthesizing chunk {idx + 1}/{len(chunks)} ({word_count} words)')

        try:
            wav_path = await loop.run_in_executor(
                _executor,
                synthesize_chunk,
                chunk,
                chunk_wav,
                job_id,
                generation_kwargs,
            )
            chunk_wav_paths.append(wav_path)
        except Exception as exc:
            raise SynthesisError(
                f'Sequential synthesis failed at chunk {idx + 1}',
                details=str(exc),
            ) from exc

    logger.info(f'[{job_id}] Sequential synthesis complete - {len(chunks)} chunks')
    return chunk_wav_paths


async def synthesize_chunks_parallel(
    chunks: list[str],
    job_dir: Path,
    job_id: str,
    status_check_callback: Optional[Callable[[], Coroutine[Any, Any, None]]] = None,
    chunk_offset: int = 0,
    generation_kwargs: Optional[dict] = None,
) -> list[str]:
    """
    Synthesize multiple chunks in parallel using thread pool.

    This method is preferred when running on CPU with multiple workers.

    Args:
        chunks: List of text chunks to synthesize.
        job_dir: Directory for output chunk files.
        job_id: Job identifier for logging.
        chunk_offset: Starting index for chunk file naming (for pipelined synthesis).

    Returns:
        List of paths to generated WAV files (in order).

    Raises:
        SynthesisError: If synthesis fails for any chunk.
    """
    if not chunks:
        raise SynthesisError('Cannot synthesize empty chunks list')

    if not _executor:
        raise SynthesisError(
            'Executor not initialized',
            details='Call initialize_executor() during startup',
        )

    loop = asyncio.get_running_loop()

    # Dispatch in batches of synthesis_workers so cancellation is checked between batches
    workers = ENGINE_CONFIG.synthesis_workers
    chunk_wav_paths: list[str] = []

    for batch_start in range(0, len(chunks), workers):
        # Check job status before each batch
        if status_check_callback:
            await status_check_callback()

        batch = chunks[batch_start : batch_start + workers]
        tasks: list[asyncio.Future[str]] = []

        for offset, chunk in enumerate(batch):
            idx = batch_start + offset
            chunk_wav = str(job_dir / f'chunk_{chunk_offset + idx:04d}.wav')
            task = loop.run_in_executor(
                _executor, synthesize_chunk, chunk, chunk_wav, job_id, generation_kwargs
            )
            tasks.append(task)

        logger.info(
            f'[{job_id}] Synthesizing batch {batch_start // workers + 1} ({len(batch)} chunks)'
        )

        try:
            batch_paths = await asyncio.gather(*tasks, return_exceptions=False)
            chunk_wav_paths.extend(batch_paths)
        except Exception as exc:
            # Cancel any remaining tasks and wait for them to finish cancelling
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

            raise SynthesisError(
                f'Parallel synthesis failed at batch starting chunk {batch_start}',
                details=str(exc),
            ) from exc

    logger.info(f'[{job_id}] Parallel synthesis complete - {len(chunks)} chunks')
    return chunk_wav_paths


async def synthesize_chunks_auto(
    chunks: list[str],
    job_dir: Path,
    job_id: str,
    status_check_callback: Optional[Callable[[], Coroutine[Any, Any, None]]] = None,
    chunk_offset: int = 0,
    generation_kwargs: Optional[dict] = None,
) -> list[str]:
    """
    Automatically choose the best synthesis strategy based on EngineConfig.

    - synthesis_workers == 1: sequential (GPU path)
    - synthesis_workers > 1: parallel (CPU 4 workers)

    Args:
        chunks: List of text chunks to synthesize.
        job_dir: Directory for output chunk files.
        job_id: Job identifier for logging.
        chunk_offset: Starting index for chunk file naming (for pipelined synthesis).

    Returns:
        List of paths to generated WAV files.

    Raises:
        SynthesisError: If synthesis fails.
    """
    workers = ENGINE_CONFIG.synthesis_workers

    if workers <= 1 or len(chunks) <= 1:
        logger.debug(
            f'[{job_id}] Using sequential synthesis for {len(chunks)} chunks (workers={workers})'
        )
        return await synthesize_chunks_sequential(
            chunks, job_dir, job_id, status_check_callback, chunk_offset, generation_kwargs
        )
    else:
        logger.debug(
            f'[{job_id}] Using parallel synthesis for {len(chunks)} chunks with {workers} workers'
        )
        return await synthesize_chunks_parallel(
            chunks, job_dir, job_id, status_check_callback, chunk_offset, generation_kwargs
        )


async def synthesize_with_pauses(
    text: str,
    output_path: str,
    job_id: str = 'default',
    generation_kwargs: Optional[dict] = None,
) -> str:
    """Synthesize narrated text, inserting real silence gaps at [LONG_PAUSE] markers.

    Unlike synthesize_single_shot_async (which converts [LONG_PAUSE] to paragraph
    breaks and relies on the TTS model to pause naturally), this function splits at
    each [LONG_PAUSE] boundary, synthesizes each part independently, then joins them
    with 800ms AudioSegment.silent() — a deterministic gap unaffected by model
    sampling temperature or token budget.

    [PAUSE] markers within each part are converted to commas by clean_text_for_tts.
    Falls back to single synthesis call when no [LONG_PAUSE] markers are present.
    """
    if not text or not text.strip():
        raise SynthesisError('Cannot synthesize empty text', details=f'output_path={output_path}')

    if not _executor:
        raise SynthesisError(
            'Executor not initialized',
            details='Call initialize_executor() during startup',
        )

    parts = [p.strip() for p in re.split(r'\[LONG_PAUSE\]', text, flags=re.IGNORECASE) if p.strip()]
    if not parts:
        raise SynthesisError('Cannot synthesize empty text', details=f'output_path={output_path}')

    loop = asyncio.get_running_loop()

    if len(parts) == 1:
        # No LONG_PAUSE markers — single synthesis call.
        clean = clean_text_for_tts(parts[0])
        return await loop.run_in_executor(
            _executor, synthesize_single_shot, clean, output_path, job_id, generation_kwargs
        )

    # Multi-part path: synthesize each part, then join with 800ms silence gaps.
    out_path = Path(output_path)
    temp_dir = out_path.parent / f'_pauses_{out_path.stem}'
    temp_dir.mkdir(exist_ok=True)
    try:
        part_wavs: list[str] = []
        for i, part_text in enumerate(parts):
            clean = clean_text_for_tts(part_text)
            if not clean.strip():
                continue
            part_wav = str(temp_dir / f'part_{i:04d}.wav')
            await loop.run_in_executor(
                _executor, synthesize_single_shot, clean, part_wav, job_id, generation_kwargs
            )
            part_wavs.append(part_wav)

        if not part_wavs:
            raise SynthesisError(
                'Pause-aware synthesis produced no audio parts',
                details=f'output_path={output_path}',
            )

        if len(part_wavs) == 1:
            shutil.copy2(part_wavs[0], output_path)
            return output_path

        combined = _trim_silence(AudioSegment.from_wav(part_wavs[0]))
        pause_800ms = (
            AudioSegment.silent(duration=800, frame_rate=combined.frame_rate)
            .set_channels(combined.channels)
            .set_sample_width(combined.sample_width)
        )
        for wav_path in part_wavs[1:]:
            seg = _trim_silence(AudioSegment.from_wav(wav_path))
            combined = combined + pause_800ms + seg

        combined.export(output_path, format='wav')
        logger.debug('[%s] Pause synthesis: %d parts → %s', job_id, len(part_wavs), output_path)
        return output_path

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def cleanup_chunk_files(job_dir: Path, job_id: str) -> None:
    """
    Clean up temporary chunk WAV files.

    Args:
        job_dir: Directory containing chunk files.
        job_id: Job identifier for logging.
    """
    try:
        import shutil

        if job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
            logger.debug(f'[{job_id}] Cleaned up chunk files in {job_dir}')
    except Exception as exc:
        logger.warning(f'[{job_id}] Failed to cleanup chunk files: {exc}')
