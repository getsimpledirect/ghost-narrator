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
import os
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
        voice_path: Optional explicit WAV path for voice conditioning. When None,
            the default reference audio at VOICE_SAMPLE_PATH is used.

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
    result = engine.synthesize_to_file(
        text,
        output_path,
        job_id,
        generation_kwargs=generation_kwargs,
        voice_override=voice_path,
    )
    # Trim leading and trailing silence from the raw synthesis output.
    # Qwen3-TTS sometimes emits silence tokens before the first word (causing
    # >50% silence quality-check failures) or trailing dead air. Both are
    # clipped so the segment contains speech-only content before concat.
    try:
        seg = AudioSegment.from_wav(result)
        trimmed = _trim_silence(seg)
        if len(trimmed) >= 100:
            trimmed.export(result, format='wav')
    except Exception as _trim_exc:
        logger.debug('[%s] Post-synthesis silence trim failed (non-fatal): %s', job_id, _trim_exc)
    return result


# Adaptive best-of-N thresholds (tuned from observed-score distributions where
# winning composite scores range 0.067–0.181 across 26 segments, median ~0.10).
# Conservative defaults — bump higher for more speed at modest quality cost.
# Scores are computed with skip_wer=True, so thresholds live below the full-WER
# gate bar (which evaluates WER on only the lazy-WER winner).
_DEFAULT_EARLY_EXIT_SCORE: float = 0.08  # very confident — skip remaining variants
_DEFAULT_GOOD_ENOUGH_SCORE: float = 0.13  # comfortable — stop after variant 1


def _load_adaptive_thresholds() -> tuple[float, float]:
    """Return (early_exit, good_enough) thresholds from env or defaults."""

    def _read(name: str, default: float) -> float:
        raw = os.environ.get(name, '').strip()
        if not raw:
            return default
        try:
            v = float(raw)
            return max(0.0, min(1.0, v))
        except ValueError:
            logger.warning('Invalid %s=%r — using default %.3f', name, raw, default)
            return default

    return (
        _read('BEST_OF_N_EARLY_EXIT', _DEFAULT_EARLY_EXIT_SCORE),
        _read('BEST_OF_N_GOOD_ENOUGH', _DEFAULT_GOOD_ENOUGH_SCORE),
    )


def synthesize_best_of_n(
    text: str,
    output_path: str,
    n_variants: int,
    reference_f0: Optional[float],
    job_id: str = 'default',
    generation_kwargs: Optional[dict] = None,
    voice_path: Optional[str] = None,
) -> tuple[str, dict]:
    """Adaptive best-of-N with early exit + lazy WER.

    Synthesises variants sequentially with distinct seeds, scoring each without
    Whisper (lazy WER). When a variant's score is comfortably below the
    early-exit threshold we ship it immediately without generating the rest;
    when it's above "good enough" after variant 1 we continue; only marginal
    cases burn the full N. The winning variant then gets a full-WER rescore so
    the downstream gate has a correct WER reading for its own pass.

    Variant 0 uses the caller's seed (or 0 if unset). Variants 1..N-1 use
    deterministically derived seeds (prime-offset arithmetic) so the same
    job_id + chunk_idx always explores the same audio space.

    When n_variants <= 1 this reduces to single synthesis + full-WER score.

    Returns (kept_path, score_dict). kept_path == output_path on success.
    Raises SynthesisError if every attempted variant fails to synthesize.
    """
    from app.domains.synthesis.scorer import compute_composite_score

    if n_variants <= 1:
        synthesize_single_shot(text, output_path, job_id, generation_kwargs, voice_path)
        score = compute_composite_score(output_path, text, reference_f0)
        return output_path, score

    early_exit, good_enough = _load_adaptive_thresholds()
    base_seed = int((generation_kwargs or {}).get('seed') or 0)
    out_path = Path(output_path)
    out_dir = out_path.parent
    stem = out_path.stem

    variant_paths: list[str] = []
    variant_scores: list[dict] = []
    best_idx_far: Optional[int] = None

    for n in range(n_variants):
        variant_path = str(out_dir / f'{stem}_v{n}.wav')
        variant_kw = dict(generation_kwargs or {})
        if n > 0:
            # 7919 is a large prime — successive seeds differ across many low
            # bits of the RNG state, so each variant explores a distinct AR path.
            variant_kw['seed'] = (base_seed + n * 7919) % (2**31)
        try:
            synthesize_single_shot(text, variant_path, job_id, variant_kw, voice_path)
        except SynthesisError as exc:
            logger.warning('[%s] Best-of-N variant %d synthesis failed: %s', job_id, n, exc)
            continue
        try:
            # Lazy WER: skip Whisper during selection — it adds ~5-10 s per call
            # and rarely flips which variant wins. The winner's full-WER score
            # is computed once below so the gate has correct WER signal.
            score = compute_composite_score(variant_path, text, reference_f0, skip_wer=True)
        except Exception as exc:
            logger.warning('[%s] Best-of-N variant %d scoring failed: %s', job_id, n, exc)
            score = {'total': 1.0}
        variant_paths.append(variant_path)
        variant_scores.append(score)

        # Track best-so-far for early-exit decisions.
        if best_idx_far is None or score['total'] < variant_scores[best_idx_far]['total']:
            best_idx_far = len(variant_scores) - 1
        best_far = variant_scores[best_idx_far]['total']

        # Early exit: this variant (or an earlier one) is already comfortably
        # under the gate — no expected gain from generating more.
        if best_far <= early_exit:
            break

        # Good-enough exit after variant 1: spent 2 variants, current best is
        # acceptable. Variant 2 might marginally improve the score but the
        # expected gain doesn't justify another ~30 s of synthesis.
        if n == 1 and best_far <= good_enough:
            break

    if not variant_paths:
        raise SynthesisError(
            f'All {n_variants} best-of-N variants failed to synthesize',
            details=f'text_len={len(text)}',
        )

    best_idx = min(range(len(variant_paths)), key=lambda i: variant_scores[i]['total'])
    best_path = variant_paths[best_idx]
    best_score_fast = variant_scores[best_idx]

    try:
        if best_path != output_path:
            shutil.move(best_path, output_path)
    except OSError as exc:
        logger.warning('[%s] Best-of-N move failed, falling back to copy: %s', job_id, exc)
        shutil.copy2(best_path, output_path)

    # Remove the rejected variants (and the best's original location if it was moved).
    for p in variant_paths:
        if p != output_path:
            try:
                os.unlink(p)
            except FileNotFoundError:
                pass

    # Final full-WER score for the winner — WER signal is needed by the
    # acoustic gate and the response ladder; computing it here avoids a
    # second Whisper call during the gate pass.
    try:
        best_score = compute_composite_score(output_path, text, reference_f0, skip_wer=False)
    except Exception as exc:
        logger.warning('[%s] Best-of-N final WER rescore failed: %s', job_id, exc)
        best_score = best_score_fast

    logger.info(
        '[%s] Best-of-%d for %s: variant %d kept after %d synths (score=%.3f, components=%s)',
        job_id,
        n_variants,
        out_path.name,
        best_idx,
        len(variant_paths),
        best_score.get('total', 1.0),
        {k: round(v, 3) for k, v in best_score.items() if k != 'total'},
    )
    return output_path, best_score


async def synthesize_best_of_n_async(
    text: str,
    output_path: str,
    n_variants: int,
    reference_f0: Optional[float],
    job_id: str = 'default',
    generation_kwargs: Optional[dict] = None,
    voice_path: Optional[str] = None,
) -> tuple[str, dict]:
    """Async wrapper for synthesize_best_of_n. Runs on the thread pool."""
    if not _executor:
        raise SynthesisError(
            'Executor not initialized',
            details='Call initialize_executor() during startup',
        )
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _executor,
        synthesize_best_of_n,
        text,
        output_path,
        n_variants,
        reference_f0,
        job_id,
        generation_kwargs,
        voice_path,
    )


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
    characteristics; when None, the default reference audio is used.
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
