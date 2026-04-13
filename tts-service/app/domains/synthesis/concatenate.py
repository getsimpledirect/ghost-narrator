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
Audio concatenation for TTS synthesis.

Provides functions for concatenating audio chunks into a single file
with context-aware pauses between chunks.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Final, List, Optional

import numpy as np
from pydub import AudioSegment

from app.config import MP3_BITRATE, STREAMING_THRESHOLD_MS
from app.core.exceptions import AudioProcessingError

logger = logging.getLogger(__name__)

DEFAULT_BITRATE: Final[str] = MP3_BITRATE
STREAMING_THRESHOLD: Final[int] = STREAMING_THRESHOLD_MS
CROSSFADE_MS: Final[int] = 60
SILENCE_THRESHOLD_DB: Final[int] = -50  # was -35; more aggressive trailing trim
MIN_SILENCE_MS: Final[int] = 100
TRAILING_HARD_CAP_MS: Final[int] = 60  # New: exact trailing silence after trim


def _trim_silence(segment: AudioSegment) -> AudioSegment:
    """Trim leading and trailing silence, capping trailing at 60ms.

    Uses -50dBFS threshold (was -35) for more aggressive silence detection.
    After trimming to the last speech sample, appends exactly 60ms of silence
    so [PAUSE]/[LONG_PAUSE] markers can add semantic gaps without fighting
    leftover TTS padding.
    """
    leading = 0
    chunk_size = 10
    for i in range(0, len(segment), chunk_size):
        chunk = segment[i : i + chunk_size]
        if chunk.dBFS > SILENCE_THRESHOLD_DB:
            leading = i
            break
    else:
        leading = len(segment)

    trailing = len(segment)
    for i in range(len(segment), 0, -chunk_size):
        chunk = segment[max(0, i - chunk_size) : i]
        if chunk.dBFS > SILENCE_THRESHOLD_DB:
            trailing = i
            break
    else:
        trailing = 0

    if leading > MIN_SILENCE_MS:
        segment = segment[leading:]
    if len(segment) - trailing > MIN_SILENCE_MS:
        segment = segment[:trailing]

    # Hard cap: always end with exactly TRAILING_HARD_CAP_MS of silence.
    # Prevents TTS padding from accumulating into audible gaps between chunks.
    return segment + AudioSegment.silent(duration=TRAILING_HARD_CAP_MS)


def _crossfade_append(
    combined: AudioSegment,
    segment: AudioSegment,
    pause_ms: int,
) -> AudioSegment:
    """Append a segment with equal-power crossfade — maintains constant perceived loudness.

    Linear crossfade (pydub default) creates a ~3dB volume dip at the midpoint
    because both signals are at 50% simultaneously (0.5² + 0.5² = 0.5, -3dB).
    Equal-power uses sin/cos curves so the power sum stays constant (sin²+cos²=1).
    """
    if len(combined) == 0:
        return segment

    combined += AudioSegment.silent(duration=pause_ms)

    n = CROSSFADE_MS
    if len(combined) < n or len(segment) < n:
        combined += segment
        return combined

    # Extract the crossfade regions as float32 numpy arrays
    tail = np.array(combined[-n:].get_array_of_samples(), dtype=np.float32)
    head = np.array(segment[:n].get_array_of_samples(), dtype=np.float32)

    # Stereo: arrays are interleaved [L, R, L, R, ...] — preserve shape
    if combined.channels == 2:
        fade_len = len(tail) // 2
        t = np.linspace(0.0, np.pi / 2, fade_len)
        fade_out = np.cos(t)
        fade_in = np.sin(t)
        # Apply per-channel via reshape
        tail_stereo = tail.reshape(-1, 2)
        head_stereo = head.reshape(-1, 2)
        mixed = (
            (tail_stereo * fade_out[:, None] + head_stereo * fade_in[:, None])
            .reshape(-1)
            .clip(-32768, 32767)
            .astype(np.int16)
        )
    else:
        t = np.linspace(0.0, np.pi / 2, len(tail))
        fade_out = np.cos(t)
        fade_in = np.sin(t)
        mixed = (tail * fade_out + head * fade_in).clip(-32768, 32767).astype(np.int16)

    xfade_segment = AudioSegment(
        mixed.tobytes(),
        frame_rate=combined.frame_rate,
        sample_width=combined.sample_width,
        channels=combined.channels,
    )

    return combined[:-n] + xfade_segment + segment[n:]


def _validate_wav_files(wav_paths: List[str]) -> None:
    """Validate that all WAV files exist and are accessible."""
    if not wav_paths:
        raise AudioProcessingError('Cannot process empty WAV list')

    for wav_path in wav_paths:
        path = Path(wav_path)
        if not path.exists():
            raise AudioProcessingError(
                f'WAV file not found: {wav_path}',
                details='Ensure all chunk files were created successfully',
            )
        if path.stat().st_size == 0:
            raise AudioProcessingError(
                f'WAV file is empty: {wav_path}',
                details='TTS synthesis may have failed for this chunk',
            )


def concatenate_audio(
    wav_paths: List[str],
    output_path: str,
    chunk_texts: Optional[List[str]] = None,
    bitrate: str = DEFAULT_BITRATE,
    pause_ms: int = 450,
    explicit_pause_durations: Optional[List[int]] = None,
) -> str:
    """
    Join all chunk WAVs into a single file with context-aware pauses.

    Args:
        wav_paths: List of paths to WAV files to concatenate.
        output_path: Output path for the resulting file.
        chunk_texts: Original text of each chunk (for dynamic pause detection).
        bitrate: Output MP3 bitrate.
        pause_ms: Default pause duration in milliseconds.
        explicit_pause_durations: Per-boundary pause durations (ms) from LLM;
            overrides heuristic when non-zero.

    Returns:
        The path to the created file.

    Raises:
        AudioProcessingError: If concatenation fails.
    """
    from app.utils.text import get_pause_ms_after_chunk as _get_pause

    _validate_wav_files(wav_paths)

    out_path = Path(output_path)
    is_wav = out_path.suffix.lower() == '.wav'

    try:
        logger.debug(f'Concatenating {len(wav_paths)} WAV files to {output_path}')

        combined = AudioSegment.empty()

        for i, wav_path in enumerate(wav_paths):
            segment = AudioSegment.from_wav(wav_path)
            segment = _trim_silence(segment)

            if i == 0:
                combined = segment
            else:
                # Pause selection: explicit → heuristic → default
                explicit = (
                    explicit_pause_durations[i - 1]
                    if explicit_pause_durations and i - 1 < len(explicit_pause_durations)
                    else 0
                )
                if explicit > 0:
                    pause = explicit
                elif chunk_texts and i - 1 < len(chunk_texts):
                    next_text = chunk_texts[i] if i < len(chunk_texts) else None
                    pause = _get_pause(chunk_texts[i - 1], next_text)
                else:
                    pause = pause_ms

                combined = _crossfade_append(combined, segment, pause)

        if is_wav:
            combined.export(output_path, format='wav')
        else:
            combined.export(output_path, format='mp3', bitrate=bitrate)

        logger.debug(
            f'Successfully created {"WAV" if is_wav else "MP3"}: {output_path} '
            f'({out_path.stat().st_size / (1024 * 1024):.2f} MB)'
        )

        return output_path

    except AudioProcessingError:
        raise
    except Exception as exc:
        if out_path.exists():
            out_path.unlink(missing_ok=True)
        raise AudioProcessingError(
            'WAV concatenation failed',
            details=str(exc),
        ) from exc


def concatenate_audio_streaming(
    wav_paths: List[str],
    output_path: str,
    chunk_texts: Optional[List[str]] = None,
    bitrate: str = DEFAULT_BITRATE,
    threshold_ms: int = STREAMING_THRESHOLD,
    explicit_pause_durations: Optional[List[int]] = None,
) -> str:
    """
    Join all chunk WAVs into a single file with streaming to reduce memory.

    Args:
        wav_paths: List of paths to WAV files to concatenate.
        output_path: Output path for the resulting file.
        chunk_texts: Original text of each chunk (for dynamic pause detection).
        bitrate: Output MP3 bitrate.
        threshold_ms: Memory threshold in milliseconds before flushing to disk.
        explicit_pause_durations: Per-boundary pause durations (ms) from LLM;
            overrides heuristic when non-zero.

    Returns:
        The path to the created file.

    Raises:
        AudioProcessingError: If concatenation fails.
    """
    from app.utils.text import get_pause_ms_after_chunk as _get_pause

    _validate_wav_files(wav_paths)

    out_path = Path(output_path)
    is_wav = out_path.suffix.lower() == '.wav'
    temp_path: Optional[str] = None

    try:
        logger.debug(f'Streaming concatenation of {len(wav_paths)} WAV files to {output_path}')

        combined = _trim_silence(AudioSegment.from_wav(wav_paths[0]))

        for i, wav_path in enumerate(wav_paths[1:], start=1):
            # Pause selection: explicit → heuristic → default
            explicit = (
                explicit_pause_durations[i - 1]
                if explicit_pause_durations and i - 1 < len(explicit_pause_durations)
                else 0
            )
            if explicit > 0:
                pause = explicit
            elif chunk_texts and i - 1 < len(chunk_texts):
                next_text = chunk_texts[i] if i < len(chunk_texts) else None
                pause = _get_pause(chunk_texts[i - 1], next_text)
            else:
                pause = 450

            segment = _trim_silence(AudioSegment.from_wav(wav_path))
            combined = _crossfade_append(combined, segment, pause)

            if len(combined) > threshold_ms:
                fd, temp_path = tempfile.mkstemp(suffix='.wav', dir=Path(output_path).parent)
                os.close(fd)
                combined.export(temp_path, format='wav')
                combined = AudioSegment.from_wav(temp_path)
                os.remove(temp_path)
                temp_path = None

        if is_wav:
            combined.export(output_path, format='wav')
        else:
            combined.export(output_path, format='mp3', bitrate=bitrate)

        logger.debug(
            f'Successfully created {"WAV" if is_wav else "MP3"} (streaming): {output_path} '
            f'({out_path.stat().st_size / (1024 * 1024):.2f} MB)'
        )

        return output_path

    except AudioProcessingError:
        raise
    except Exception as exc:
        if temp_path and Path(temp_path).exists():
            Path(temp_path).unlink(missing_ok=True)
        if out_path.exists():
            out_path.unlink(missing_ok=True)
        raise AudioProcessingError(
            'Streaming WAV concatenation failed',
            details=str(exc),
        ) from exc


def concatenate_audio_auto(
    wav_paths: List[str],
    output_path: str,
    chunk_texts: Optional[List[str]] = None,
    bitrate: str = DEFAULT_BITRATE,
    streaming_threshold_chunks: int = 10,
    explicit_pause_durations: Optional[List[int]] = None,
) -> str:
    """
    Automatically choose the best concatenation strategy based on input size.

    Args:
        wav_paths: List of paths to WAV files.
        output_path: Output path for the resulting file.
        chunk_texts: Original text of each chunk.
        bitrate: Output MP3 bitrate.
        streaming_threshold_chunks: Number of chunks above which to use streaming.
        explicit_pause_durations: Per-boundary pause durations (ms) from LLM;
            overrides heuristic when non-zero.

    Returns:
        The path to the created file.

    Raises:
        AudioProcessingError: If concatenation fails.
    """
    if len(wav_paths) > streaming_threshold_chunks:
        logger.debug(
            f'Using streaming concatenation for {len(wav_paths)} chunks '
            f'(threshold: {streaming_threshold_chunks})'
        )
        return concatenate_audio_streaming(
            wav_paths,
            output_path,
            chunk_texts,
            bitrate,
            explicit_pause_durations=explicit_pause_durations,
        )
    else:
        logger.debug(f'Using standard concatenation for {len(wav_paths)} chunks')
        return concatenate_audio(
            wav_paths,
            output_path,
            chunk_texts,
            bitrate,
            explicit_pause_durations=explicit_pause_durations,
        )
