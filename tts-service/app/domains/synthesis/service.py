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
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Optional

from pydub import AudioSegment

from app.config import MAX_CHUNK_WORDS
from app.core.hardware import ENGINE_CONFIG
from app.core.exceptions import SynthesisError
from app.core.tts_engine import get_tts_engine
from app.utils.text import split_into_chunks, clean_text_for_tts, has_quoted_speech, split_at_quotes
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
    return engine.synthesize_to_file(text, output_path, job_id, generation_kwargs=generation_kwargs)


async def synthesize_single_shot_async(
    text: str,
    output_path: str,
    job_id: str = 'default',
    generation_kwargs: Optional[dict] = None,
) -> str:
    """
    Async wrapper for single-shot synthesis.

    Runs the synchronous single-shot synthesis in a thread pool.
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
    )


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


def prepare_text_for_synthesis(
    text: str,
    max_chunk_words: int = MAX_CHUNK_WORDS,
) -> tuple[list[str], int, list[int]]:
    """Prepare text for synthesis by cleaning, splitting at pause markers, and chunking.

    Returns:
        A tuple of (chunks, total_word_count, pause_after_chunk) where
        pause_after_chunk[i] is the ms of silence to insert after chunks[i].
        A value of 0 means "use the heuristic from get_pause_ms_after_chunk".

    Raises:
        SynthesisError: If text is empty or chunking fails.
    """
    from app.utils.text import parse_pause_markers

    if not text or not text.strip():
        raise SynthesisError('Cannot prepare empty text for synthesis')

    # Split at [PAUSE]/[LONG_PAUSE] markers first, then clean and chunk each segment
    pause_segments = parse_pause_markers(text)

    all_chunks: list[str] = []
    pause_after_chunk: list[int] = []

    for segment_text, pause_ms in pause_segments:
        cleaned = clean_text_for_tts(segment_text)
        seg_chunks = split_into_chunks(cleaned, max_chunk_words)

        if not seg_chunks:
            continue

        # All chunks in this segment get pause_ms=0 except the last one,
        # which gets the pause that follows this segment.
        for chunk in seg_chunks[:-1]:
            all_chunks.append(chunk)
            pause_after_chunk.append(0)
        all_chunks.append(seg_chunks[-1])
        pause_after_chunk.append(pause_ms)

    if not all_chunks:
        raise SynthesisError(
            'Text chunking resulted in empty chunks',
            details=f'Original text length: {len(text)}',
        )

    total_words = sum(len(chunk.split()) for chunk in all_chunks)

    logger.debug(
        f'Prepared {len(all_chunks)} chunks with {total_words} total words '
        f'(max {max_chunk_words} words per chunk)'
    )

    return all_chunks, total_words, pause_after_chunk


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
