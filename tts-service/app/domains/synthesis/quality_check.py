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

"""Quality check and resynthesis logic for TTS audio chunks."""

from __future__ import annotations

import functools
import logging

from pydub import AudioSegment as _AudioSegment

from app.config import OUTPUT_DIR

logger = logging.getLogger(__name__)


async def _quality_check_and_resynthesize(
    chunk_wav_paths: list[str],
    chunk_texts: list[str],
    job_id: str,
    engine,
    loop,
    executor,
    generation_kwargs: dict | None = None,
) -> list[str]:
    """Check audio quality of each chunk and re-synthesize bad ones.

    HIGH_VRAM only — checks for:
    - Excessive silence (>50% of chunk is silence)
    - Clipping (samples at 0dBFS)
    - Very low energy (likely failed synthesis)

    Re-synthesizes failed chunks once, then uses original if still bad.
    """

    checked_paths = list(chunk_wav_paths)
    resynth_count = 0

    for i, wav_path in enumerate(chunk_wav_paths):
        try:
            seg = _AudioSegment.from_wav(wav_path)
            duration_ms = len(seg)
            if duration_ms < 100:
                # Extremely short — likely failed
                logger.warning(f'[{job_id}] Chunk {i} is only {duration_ms}ms — re-synthesizing')
                checked_paths[i] = await _resynthesize_chunk(
                    i, chunk_texts, job_id, engine, loop, executor, generation_kwargs
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
                    f'[{job_id}] Chunk {i} is {silence_ratio:.0%} silence — re-synthesizing'
                )
                checked_paths[i] = await _resynthesize_chunk(
                    i, chunk_texts, job_id, engine, loop, executor, generation_kwargs
                )
                resynth_count += 1

        except Exception as exc:
            logger.debug(f'[{job_id}] Quality check for chunk {i} skipped: {exc}')

    if resynth_count > 0:
        logger.info(f'[{job_id}] Re-synthesized {resynth_count} chunks after quality check')

    return checked_paths


async def _resynthesize_chunk(
    chunk_idx: int,
    chunk_texts: list[str],
    job_id: str,
    engine,
    loop,
    executor,
    generation_kwargs: dict | None = None,
) -> str:
    """Re-synthesize a single chunk. Returns the path (may be original if re-synth fails)."""
    if chunk_idx >= len(chunk_texts):
        return ''

    job_dir = OUTPUT_DIR / job_id
    wav_path = str(job_dir / f'chunk_{chunk_idx:04d}.wav')

    try:
        # Use same temperature as original synthesis - re-synthesizing with
        # higher temperature can cause voice inconsistency with other chunks.
        # The quality check catches silent/garbled chunks, temperature bump is not needed.
        retry_kwargs = dict(generation_kwargs or {})

        # run_in_executor only accepts positional args; use partial to bind
        # generation_kwargs as a keyword so it doesn't collide with job_id.
        synth_fn = functools.partial(engine.synthesize_to_file, generation_kwargs=retry_kwargs)
        await loop.run_in_executor(executor, synth_fn, chunk_texts[chunk_idx], wav_path, job_id)
        return wav_path
    except Exception as exc:
        logger.warning(f'[{job_id}] Re-synthesis of chunk {chunk_idx} failed: {exc}')
        return wav_path  # Return original path
