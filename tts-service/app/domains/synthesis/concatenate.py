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

from pydub import AudioSegment

from app.config import MP3_BITRATE, STREAMING_THRESHOLD_MS
from app.core.exceptions import AudioProcessingError

logger = logging.getLogger(__name__)

DEFAULT_BITRATE: Final[str] = MP3_BITRATE
STREAMING_THRESHOLD: Final[int] = STREAMING_THRESHOLD_MS
CROSSFADE_MS: Final[int] = 60
SILENCE_THRESHOLD_DB: Final[int] = -40
MIN_SILENCE_MS: Final[int] = 100


def _trim_silence(segment: AudioSegment) -> AudioSegment:
    """Trim leading and trailing silence from an audio segment."""
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

    return segment


def _crossfade_append(
    combined: AudioSegment,
    segment: AudioSegment,
    pause_ms: int,
) -> AudioSegment:
    """Append a segment with crossfade at the boundary."""
    if len(combined) == 0:
        return segment

    combined += AudioSegment.silent(duration=pause_ms)

    if len(combined) > CROSSFADE_MS and len(segment) > CROSSFADE_MS:
        combined = combined.append(segment, crossfade=CROSSFADE_MS)
    else:
        combined += segment

    return combined


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
) -> str:
    """
    Join all chunk WAVs into a single file with context-aware pauses.

    Args:
        wav_paths: List of paths to WAV files to concatenate.
        output_path: Output path for the resulting file.
        chunk_texts: Original text of each chunk (for dynamic pause detection).
        bitrate: Output MP3 bitrate.
        pause_ms: Default pause duration in milliseconds.

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
                if chunk_texts and i - 1 < len(chunk_texts):
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
) -> str:
    """
    Join all chunk WAVs into a single file with streaming to reduce memory.

    Args:
        wav_paths: List of paths to WAV files to concatenate.
        output_path: Output path for the resulting file.
        chunk_texts: Original text of each chunk (for dynamic pause detection).
        bitrate: Output MP3 bitrate.
        threshold_ms: Memory threshold in milliseconds before flushing to disk.

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
            if chunk_texts and i - 1 < len(chunk_texts):
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
) -> str:
    """
    Automatically choose the best concatenation strategy based on input size.

    Args:
        wav_paths: List of paths to WAV files.
        output_path: Output path for the resulting file.
        chunk_texts: Original text of each chunk.
        bitrate: Output MP3 bitrate.
        streaming_threshold_chunks: Number of chunks above which to use streaming.

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
        )
    else:
        logger.debug(f'Using standard concatenation for {len(wav_paths)} chunks')
        return concatenate_audio(wav_paths, output_path, chunk_texts, bitrate)
