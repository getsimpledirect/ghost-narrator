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
Audio normalization for TTS synthesis.

Provides functions for normalizing audio chunks to target loudness
using EBU R128 loudness normalization.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from typing import Final

from app.config import AUDIO_SAMPLE_RATE

logger = logging.getLogger(__name__)

DEFAULT_TARGET_LUFS: Final[float] = -23.0
MIN_CHUNK_DURATION_MS: Final[int] = 10_000


def normalize_audio(
    input_wav_path: str,
    target_lufs: float = DEFAULT_TARGET_LUFS,
) -> str:
    """
    Normalize a single audio chunk to target LUFS using ffmpeg loudnorm filter.

    Uses EBU R128 loudness normalization (single-pass for speed).
    Target: -23 LUFS per chunk (conservative — final file will be re-normalized
    to -16 LUFS in the mastering step).

    Hardware note: ffmpeg loudnorm runs on CPU only, no GPU usage.
    Memory: processes chunk-by-chunk, never loads full article into RAM.

    Args:
        input_wav_path: Path to the input WAV file.
        target_lufs: Target loudness in LUFS (default: -23.0).

    Returns:
        Path to the normalized WAV file. If normalization fails, returns the
        original path as a graceful fallback.
    """
    fd, normalized_path = tempfile.mkstemp(suffix='_norm.wav', dir=os.path.dirname(input_wav_path))
    os.close(fd)

    try:
        result = subprocess.run(
            [
                'ffmpeg',
                '-y',
                '-i',
                input_wav_path,
                '-af',
                f'loudnorm=I={target_lufs}:TP=-1.5:LRA=7',
                '-ar',
                str(AUDIO_SAMPLE_RATE),
                '-ac',
                '1',
                normalized_path,
            ],
            capture_output=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.warning(
                f'Chunk normalization failed (rc={result.returncode}), '
                f'using original: {input_wav_path}'
            )
            os.unlink(normalized_path)
            return input_wav_path

        return normalized_path

    except Exception as exc:
        logger.warning(f'Chunk normalization error: {exc}. Using original.')
        if os.path.exists(normalized_path):
            os.unlink(normalized_path)
        return input_wav_path


def normalize_audio_if_long_enough(
    input_wav_path: str,
    target_lufs: float = DEFAULT_TARGET_LUFS,
    min_duration_ms: int = MIN_CHUNK_DURATION_MS,
) -> str:
    """
    Normalize audio chunk only if it's long enough for accurate loudness measurement.

    Skip normalization for very short chunks (<10s) — not enough
    signal for loudnorm to measure accurately, and final mastering
    will re-normalize the concatenated file.

    Args:
        input_wav_path: Path to the input WAV file.
        target_lufs: Target loudness in LUFS.
        min_duration_ms: Minimum duration in milliseconds to normalize.

    Returns:
        Path to the normalized WAV file, or original if skipped/failed.
    """
    from pydub import AudioSegment

    try:
        seg = AudioSegment.from_wav(input_wav_path)
        if len(seg) < min_duration_ms:
            logger.debug(
                f'Chunk is {len(seg) / 1000:.1f}s — skipping per-chunk norm '
                f'(minimum: {min_duration_ms / 1000:.0f}s)'
            )
            return input_wav_path

        return normalize_audio(input_wav_path, target_lufs)

    except Exception as exc:
        logger.warning(f'Chunk normalization check failed, using original: {exc}')
        return input_wav_path
