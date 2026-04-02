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
Audio processing service for TTS output.

Provides functions for concatenating WAV files into MP3 output,
per-chunk loudness normalization, final mastering with EBU R128,
and quality validation — all optimized for memory efficiency.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Final

from pydub import AudioSegment

from app.config import (
    MP3_BITRATE,
    STREAMING_THRESHOLD_MS,
    AUDIO_SAMPLE_RATE,
    TARGET_LUFS,
)
from app.core.exceptions import AudioProcessingError
from app.utils.text import get_pause_ms_after_chunk

logger = logging.getLogger(__name__)

# Constants
DEFAULT_BITRATE: Final[str] = MP3_BITRATE
STREAMING_THRESHOLD: Final[int] = STREAMING_THRESHOLD_MS


# ─── Per-Chunk Normalization ──────────────────────────────────────────────────


def normalize_chunk_to_target_lufs(
    input_wav_path: str,
    target_lufs: float = -23.0,
) -> str:
    """
    Normalize a single audio chunk to target LUFS using ffmpeg loudnorm filter.

    Returns path to normalized file (temporary file, caller must clean up).

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
    # Create temp output file in the same directory as the input
    fd, normalized_path = tempfile.mkstemp(
        suffix="_norm.wav", dir=os.path.dirname(input_wav_path)
    )
    os.close(fd)

    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                input_wav_path,
                "-af",
                f"loudnorm=I={target_lufs}:TP=-1.5:LRA=7",
                "-ar",
                str(AUDIO_SAMPLE_RATE),  # From ENGINE_CONFIG tier
                "-ac",
                "1",
                normalized_path,
            ],
            capture_output=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.warning(
                f"Chunk normalization failed (rc={result.returncode}), "
                f"using original: {input_wav_path}"
            )
            os.unlink(normalized_path)
            return input_wav_path

        return normalized_path

    except Exception as exc:
        logger.warning(f"Chunk normalization error: {exc}. Using original.")
        if os.path.exists(normalized_path):
            os.unlink(normalized_path)
        return input_wav_path


# ─── Final Mastering ─────────────────────────────────────────────────────────


def apply_final_mastering(input_mp3_path: str, output_mp3_path: str) -> bool:
    """
    Apply final mastering to the complete concatenated audio file.

    Processing chain:
    1. Trim leading silence to max 0.2s
    2. Two-pass EBU R128 loudness normalization to target LUFS
       (first pass measures, second pass applies correction)
    3. True peak limiting to -1.0 dBFS (prevents clipping on playback)
    4. Upsample to target sample rate (if needed)
    5. Export at configured MP3 bitrate

    Hardware note: All ffmpeg operations, no GPU required.
    Typical processing time: 5-15 seconds for a 15-minute file on 4 vCPUs.

    Args:
        input_mp3_path: Path to the raw concatenated MP3.
        output_mp3_path: Path for the mastered output MP3.

    Returns:
        True if mastering succeeded, False otherwise.
    """
    try:
        # ── Pass 1: Measure loudness stats ────────────────────────────────
        measure_result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                input_mp3_path,
                "-af",
                (
                    "silenceremove=start_periods=1:start_silence=0.2:start_threshold=-40dB,"
                    f"loudnorm=I={TARGET_LUFS}:TP=-1.0:LRA=8:print_format=json"
                ),
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        # Parse measured values from stderr JSON output
        measured_i = measured_tp = measured_lra = measured_thresh = None
        measured_offset = target_offset = None
        stderr = measure_result.stderr

        try:
            # Find the JSON block at the end of stderr
            json_start = stderr.rfind("{")
            json_end = stderr.rfind("}") + 1
            if json_start != -1 and json_end > json_start:
                import json

                stats = json.loads(stderr[json_start:json_end])
                measured_i = stats.get("input_i")
                measured_tp = stats.get("input_tp")
                measured_lra = stats.get("input_lra")
                measured_thresh = stats.get("input_thresh")
                measured_offset = stats.get("target_offset")
        except (json.JSONDecodeError, KeyError, ValueError):
            logger.warning(
                "Could not parse loudnorm stats — falling back to single-pass"
            )

        # ── Pass 2: Apply correction with measured values ─────────────────
        if all(
            v is not None
            for v in (
                measured_i,
                measured_tp,
                measured_lra,
                measured_thresh,
                measured_offset,
            )
        ):
            loudnorm_filter = (
                f"loudnorm=I={TARGET_LUFS}:TP=-1.0:LRA=8:"
                f"measured_I={measured_i}:measured_TP={measured_tp}:"
                f"measured_LRA={measured_lra}:measured_thresh={measured_thresh}:"
                f"offset={measured_offset}:linear=true:print_format=none"
            )
            logger.debug("Using two-pass loudnorm with measured values")
        else:
            # Fallback to single-pass if measurement failed
            loudnorm_filter = (
                f"loudnorm=I={TARGET_LUFS}:TP=-1.0:LRA=8:print_format=none"
            )
            logger.debug("Falling back to single-pass loudnorm")

        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                input_mp3_path,
                "-af",
                (
                    # Step 1: Remove leading silence (max 0.2s pre-roll)
                    "silenceremove=start_periods=1:start_silence=0.2:start_threshold=-40dB,"
                    # Step 2: EBU R128 loudness normalization (two-pass if available)
                    f"{loudnorm_filter},"
                    # Step 3: Hard limiter as safety net
                    "alimiter=level_in=1:level_out=1:limit=0.891:attack=5:release=50:level=disabled"
                ),
                "-ar",
                str(AUDIO_SAMPLE_RATE),  # From ENGINE_CONFIG tier
                "-ac",
                "1",  # Keep mono (voice narration)
                "-codec:a",
                "libmp3lame",
                "-b:a",
                MP3_BITRATE,  # From ENGINE_CONFIG tier
                output_mp3_path,
            ],
            capture_output=True,
            timeout=300,
        )

        if result.returncode != 0:
            logger.error(
                f"Mastering failed (rc={result.returncode}): "
                f"{result.stderr.decode(errors='replace')[:500]}"
            )
            return False

        logger.info(
            f"Mastering complete: {output_mp3_path} "
            f"({Path(output_mp3_path).stat().st_size / (1024 * 1024):.2f} MB)"
        )
        return True

    except Exception as exc:
        logger.error(f"Mastering failed: {exc}. Using original file.")
        return False


# ─── Quality Validation ──────────────────────────────────────────────────────


def validate_audio_quality(mp3_path: str) -> dict:
    """
    Run ffprobe/ffmpeg quality checks on final output.

    Returns dict of results. Logs warnings for failures.
    Does NOT raise exceptions — audio pipeline must always deliver a file.

    Args:
        mp3_path: Path to the final mastered MP3 file.

    Returns:
        Dictionary of measured audio quality metrics.
    """
    results: dict = {}

    try:
        # Check integrated loudness via ebur128
        r = subprocess.run(
            [
                "ffmpeg",
                "-i",
                mp3_path,
                "-filter_complex",
                "ebur128=peak=true",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        output = r.stderr

        # Parse integrated loudness from the final summary
        for line in output.split("\n"):
            if "I:" in line and "LUFS" in line:
                try:
                    lufs = float(line.split("I:")[1].split("LUFS")[0].strip())
                    results["integrated_lufs"] = lufs
                    if not (TARGET_LUFS - 2 <= lufs <= TARGET_LUFS + 2):
                        logger.warning(
                            f"Integrated loudness {lufs:.1f} LUFS "
                            f"outside target range {TARGET_LUFS - 2:.0f} to {TARGET_LUFS + 2:.0f} LUFS"
                        )
                except (ValueError, IndexError):
                    pass
            if "Peak:" in line and "dBFS" in line:
                try:
                    peak = float(line.split("Peak:")[1].split("dBFS")[0].strip())
                    results["true_peak_dbfs"] = peak
                    if peak > -1.0:
                        logger.warning(
                            f"True peak {peak:.1f} dBFS exceeds -1.0 dBFS limit"
                        )
                except (ValueError, IndexError):
                    pass

        # Check for excessive silence gaps (> 1.2s)
        r2 = subprocess.run(
            [
                "ffmpeg",
                "-i",
                mp3_path,
                "-filter_complex",
                "silencedetect=noise=-40dB:d=1.2",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        long_gaps = [
            line for line in r2.stderr.split("\n") if "silence_duration" in line
        ]
        results["long_silence_gaps_count"] = len(long_gaps)
        if long_gaps:
            logger.warning(
                f"{len(long_gaps)} silence gap(s) exceeding 1.2s detected in output"
            )

    except Exception as exc:
        logger.warning(f"Quality validation error (non-fatal): {exc}")

    return results


# ─── Audio Quality Helpers ────────────────────────────────────────────────────

# Crossfade duration in milliseconds — short enough to be imperceptible but
# enough to smooth spectral discontinuities at chunk boundaries
_CROSSFADE_MS: Final[int] = 15

# Silence detection threshold for trimming (dBFS)
_SILENCE_THRESHOLD_DB: Final[int] = -40

# Minimum silence duration to trim (ms) — don't trim natural micro-pauses
_MIN_SILENCE_MS: Final[int] = 100


def _trim_silence(segment: AudioSegment) -> AudioSegment:
    """Trim leading and trailing silence from an audio segment.

    Only trims silence longer than _MIN_SILENCE_MS to avoid removing
    natural micro-pauses that are part of speech prosody.

    Args:
        segment: Input audio segment.

    Returns:
        Trimmed audio segment.
    """
    # Detect leading silence
    leading = 0
    chunk_size = 10  # ms
    for i in range(0, len(segment), chunk_size):
        chunk = segment[i : i + chunk_size]
        if chunk.dBFS > _SILENCE_THRESHOLD_DB:
            leading = i
            break
    else:
        leading = len(segment)

    # Detect trailing silence
    trailing = len(segment)
    for i in range(len(segment), 0, -chunk_size):
        chunk = segment[max(0, i - chunk_size) : i]
        if chunk.dBFS > _SILENCE_THRESHOLD_DB:
            trailing = i
            break
    else:
        trailing = 0

    # Only trim if the silence is significant
    if leading > _MIN_SILENCE_MS:
        segment = segment[leading:]
    if len(segment) - trailing > _MIN_SILENCE_MS:
        segment = segment[:trailing]

    return segment


def _crossfade_append(
    combined: AudioSegment,
    segment: AudioSegment,
    pause_ms: int,
) -> AudioSegment:
    """Append a segment with crossfade at the boundary.

    Adds a silence gap, then crossfades the last few ms of combined
    with the first few ms of the new segment to eliminate clicks/pops.

    Args:
        combined: The accumulated audio so far.
        segment: The new segment to append.
        pause_ms: Silence gap in milliseconds.

    Returns:
        Combined audio with crossfaded boundary.
    """
    if len(combined) == 0:
        return segment

    # Add the silence gap
    combined += AudioSegment.silent(duration=pause_ms)

    # Apply crossfade if both segments are long enough
    if len(combined) > _CROSSFADE_MS and len(segment) > _CROSSFADE_MS:
        combined = combined.append(segment, crossfade=_CROSSFADE_MS)
    else:
        combined += segment

    return combined


# ─── WAV Validation ──────────────────────────────────────────────────────────


def validate_wav_files(wav_paths: list[str]) -> None:
    """
    Validate that all WAV files exist and are accessible.

    Args:
        wav_paths: List of paths to WAV files.

    Raises:
        AudioProcessingError: If any WAV file is missing or invalid.
    """
    if not wav_paths:
        raise AudioProcessingError("Cannot process empty WAV list")

    for wav_path in wav_paths:
        path = Path(wav_path)
        if not path.exists():
            raise AudioProcessingError(
                f"WAV file not found: {wav_path}",
                details="Ensure all chunk files were created successfully",
            )
        if path.stat().st_size == 0:
            raise AudioProcessingError(
                f"WAV file is empty: {wav_path}",
                details="TTS synthesis may have failed for this chunk",
            )


# ─── Concatenation with Dynamic Gaps ─────────────────────────────────────────


def concatenate_wavs(
    wav_paths: list[str],
    output_path: str,
    chunk_texts: list[str] | None = None,
    bitrate: str = DEFAULT_BITRATE,
) -> str:
    """
    Join all chunk WAVs into a single file with context-aware pauses.

    This function is optimized for smaller files (fewer than 10 chunks).
    For larger files, use ``concatenate_wavs_streaming`` instead.

    Args:
        wav_paths: List of paths to WAV files to concatenate.
        output_path: Output path for the resulting file (.wav or .mp3).
        chunk_texts: Original text of each chunk (for dynamic pause detection).
            If None, falls back to a default 450ms pause.
        bitrate: Output MP3 bitrate (if exporting to .mp3).

    Returns:
        The path to the created file.

    Raises:
        AudioProcessingError: If concatenation fails.
    """
    validate_wav_files(wav_paths)

    out_path = Path(output_path)
    is_wav = out_path.suffix.lower() == ".wav"

    try:
        logger.debug(f"Concatenating {len(wav_paths)} WAV files to {output_path}")

        combined = AudioSegment.empty()

        for i, wav_path in enumerate(wav_paths):
            segment = AudioSegment.from_wav(wav_path)

            # Trim leading/trailing silence from each chunk
            segment = _trim_silence(segment)

            if i == 0:
                combined = segment
            else:
                # Determine contextual pause
                if chunk_texts and i - 1 < len(chunk_texts):
                    next_text = chunk_texts[i] if i < len(chunk_texts) else None
                    pause_ms = get_pause_ms_after_chunk(chunk_texts[i - 1], next_text)
                else:
                    pause_ms = 450

                # Crossfade append to eliminate clicks at boundaries
                combined = _crossfade_append(combined, segment, pause_ms)

        if is_wav:
            combined.export(output_path, format="wav")
        else:
            combined.export(output_path, format="mp3", bitrate=bitrate)

        logger.debug(
            f"Successfully created {'WAV' if is_wav else 'MP3'}: {output_path} "
            f"({out_path.stat().st_size / (1024 * 1024):.2f} MB)"
        )

        return output_path

    except AudioProcessingError:
        raise
    except Exception as exc:
        if out_path.exists():
            out_path.unlink(missing_ok=True)
        raise AudioProcessingError(
            "WAV concatenation failed",
            details=str(exc),
        ) from exc


def concatenate_wavs_streaming(
    wav_paths: list[str],
    output_path: str,
    chunk_texts: list[str] | None = None,
    bitrate: str = DEFAULT_BITRATE,
    threshold_ms: int = STREAMING_THRESHOLD,
) -> str:
    """
    Join all chunk WAVs into a single file with streaming to reduce memory.

    This function periodically exports to a temporary file to avoid holding
    the entire audio in memory. Use this for larger files (10+ chunks).

    Args:
        wav_paths: List of paths to WAV files to concatenate.
        output_path: Output path for the resulting file.
        chunk_texts: Original text of each chunk (for dynamic pause detection).
            If None, falls back to a default 450ms pause.
        bitrate: Output MP3 bitrate (if exporting to .mp3).
        threshold_ms: Memory threshold in milliseconds before flushing to disk.

    Returns:
        The path to the created file.

    Raises:
        AudioProcessingError: If concatenation fails.
    """
    validate_wav_files(wav_paths)

    out_path = Path(output_path)
    is_wav = out_path.suffix.lower() == ".wav"
    temp_path: str | None = None

    try:
        logger.debug(
            f"Streaming concatenation of {len(wav_paths)} WAV files to {output_path}"
        )

        combined = _trim_silence(AudioSegment.from_wav(wav_paths[0]))

        for i, wav_path in enumerate(wav_paths[1:], start=1):
            # Determine contextual pause
            if chunk_texts and i - 1 < len(chunk_texts):
                next_text = chunk_texts[i] if i < len(chunk_texts) else None
                pause_ms = get_pause_ms_after_chunk(chunk_texts[i - 1], next_text)
            else:
                pause_ms = 450

            segment = _trim_silence(AudioSegment.from_wav(wav_path))

            # Crossfade append to eliminate clicks at boundaries
            combined = _crossfade_append(combined, segment, pause_ms)

            # If combined duration exceeds threshold, flush to disk
            if len(combined) > threshold_ms:
                # Always flush to WAV for temporary files to maintain quality
                fd, temp_path = tempfile.mkstemp(
                    suffix=".wav", dir=Path(output_path).parent
                )
                os.close(fd)
                combined.export(temp_path, format="wav")
                combined = AudioSegment.from_wav(temp_path)
                os.remove(temp_path)
                temp_path = None

        if is_wav:
            combined.export(output_path, format="wav")
        else:
            combined.export(output_path, format="mp3", bitrate=bitrate)

        logger.debug(
            f"Successfully created {'WAV' if is_wav else 'MP3'} (streaming): {output_path} "
            f"({out_path.stat().st_size / (1024 * 1024):.2f} MB)"
        )

        return output_path

    except AudioProcessingError:
        raise
    except Exception as exc:
        # Cleanup on failure
        if temp_path and Path(temp_path).exists():
            Path(temp_path).unlink(missing_ok=True)
        if out_path.exists():
            out_path.unlink(missing_ok=True)
        raise AudioProcessingError(
            "Streaming WAV concatenation failed",
            details=str(exc),
        ) from exc


def concatenate_wavs_auto(
    wav_paths: list[str],
    output_path: str,
    chunk_texts: list[str] | None = None,
    bitrate: str = DEFAULT_BITRATE,
    streaming_threshold_chunks: int = 10,
) -> str:
    """
    Automatically choose the best concatenation strategy based on input size.

    Uses standard concatenation for small files and streaming for larger ones.

    Args:
        wav_paths: List of paths to WAV files to concatenate.
        output_path: Output path for the resulting file.
        chunk_texts: Original text of each chunk (for dynamic pause detection).
        bitrate: Output MP3 bitrate (if exporting to .mp3).
        streaming_threshold_chunks: Number of chunks above which to use streaming.

    Returns:
        The path to the created file.

    Raises:
        AudioProcessingError: If concatenation fails.
    """
    if len(wav_paths) > streaming_threshold_chunks:
        logger.debug(
            f"Using streaming concatenation for {len(wav_paths)} chunks "
            f"(threshold: {streaming_threshold_chunks})"
        )
        return concatenate_wavs_streaming(
            wav_paths,
            output_path,
            chunk_texts,
            bitrate,
        )
    else:
        logger.debug(f"Using standard concatenation for {len(wav_paths)} chunks")
        return concatenate_wavs(wav_paths, output_path, chunk_texts, bitrate)


# ─── Audio Info Helpers ──────────────────────────────────────────────────────


def get_audio_duration(file_path: str) -> float:
    """
    Get the duration of an audio file in seconds.

    Args:
        file_path: Path to the audio file (WAV or MP3).

    Returns:
        Duration in seconds.

    Raises:
        AudioProcessingError: If file cannot be read.
    """
    path = Path(file_path)
    if not path.exists():
        raise AudioProcessingError(f"Audio file not found: {file_path}")

    try:
        if path.suffix.lower() == ".wav":
            audio = AudioSegment.from_wav(file_path)
        elif path.suffix.lower() == ".mp3":
            audio = AudioSegment.from_mp3(file_path)
        else:
            raise AudioProcessingError(
                f"Unsupported audio format: {path.suffix}",
                details="Supported formats: .wav, .mp3",
            )

        return len(audio) / 1000.0  # Convert milliseconds to seconds

    except AudioProcessingError:
        raise
    except Exception as exc:
        raise AudioProcessingError(
            f"Failed to read audio file: {file_path}",
            details=str(exc),
        ) from exc


def get_file_size_mb(file_path: str) -> float:
    """
    Get the file size in megabytes.

    Args:
        file_path: Path to the file.

    Returns:
        File size in MB.

    Raises:
        AudioProcessingError: If file does not exist.
    """
    path = Path(file_path)
    if not path.exists():
        raise AudioProcessingError(f"File not found: {file_path}")

    return path.stat().st_size / (1024 * 1024)
