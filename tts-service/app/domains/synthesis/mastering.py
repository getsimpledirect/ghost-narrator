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
Audio mastering for TTS synthesis.

Provides functions for applying final mastering to the complete
concatenated audio file, including EBU R128 loudness normalization,
true peak limiting, and sample rate conversion.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Dict, Final, Optional, Tuple

from app.config import AUDIO_SAMPLE_RATE, MP3_BITRATE, TARGET_LUFS

logger = logging.getLogger(__name__)

DEFAULT_TARGET_LUFS: Final[float] = TARGET_LUFS
DEFAULT_TRUE_PEAK: Final[float] = -1.0
DEFAULT_LRA: Final[float] = 8.0


def _parse_loudnorm_stats(stderr: str) -> Optional[Dict[str, float]]:
    """Parse loudnorm statistics from ffmpeg stderr output."""
    try:
        json_start = stderr.rfind('{')
        json_end = stderr.rfind('}') + 1
        if json_start != -1 and json_end > json_start:
            stats = json.loads(stderr[json_start:json_end])
            return {
                'input_i': stats.get('input_i'),
                'input_tp': stats.get('input_tp'),
                'input_lra': stats.get('input_lra'),
                'input_thresh': stats.get('input_thresh'),
                'target_offset': stats.get('target_offset'),
            }
    except (json.JSONDecodeError, KeyError, ValueError):
        pass
    return None


def master_audio(
    input_path: str,
    output_path: str,
    target_lufs: float = DEFAULT_TARGET_LUFS,
    true_peak: float = DEFAULT_TRUE_PEAK,
    lra: float = DEFAULT_LRA,
    sample_rate: int = AUDIO_SAMPLE_RATE,
    bitrate: str = MP3_BITRATE,
) -> bool:
    """
    Apply final mastering to the complete concatenated audio file.

    Processing chain:
    1. Trim leading silence to max 0.2s
    2. Two-pass EBU R128 loudness normalization to target LUFS
       (first pass measures, second pass applies correction)
    3. True peak limiting to prevent clipping on playback
    4. Export at configured MP3 bitrate

    Hardware note: All ffmpeg operations, no GPU required.
    Typical processing time: 5-15 seconds for a 15-minute file on 4 vCPUs.

    Args:
        input_path: Path to the raw concatenated audio file.
        output_path: Path for the mastered output MP3.
        target_lufs: Target loudness in LUFS.
        true_peak: True peak limit in dBFS.
        lra: Loudness range in LU.
        sample_rate: Target sample rate in Hz.
        bitrate: Output MP3 bitrate.

    Returns:
        True if mastering succeeded, False otherwise.
    """
    try:
        # Broadcast mastering order: compress → normalise → limit.
        # The compressor runs first in both passes so pass-1 measures the
        # loudness of the already-compressed signal; pass-2 then applies the
        # correction to that same compressed signal, hitting the LUFS target
        # accurately. Reversing the order (normalise → compress) would cause
        # the compressor to alter the carefully measured level after the fact.
        _COMPRESSOR = (
            # threshold=0.125 ≈ -18 dBFS, ratio=3:1, attack=10ms, release=100ms
            # is the standard starting point for broadcast speech compression.
            'acompressor=threshold=0.125:ratio=3:attack=10:release=100'
        )

        measure_result = subprocess.run(
            [
                'ffmpeg',
                '-y',
                '-i',
                input_path,
                '-af',
                (
                    'silenceremove=start_periods=1:start_silence=0.2:start_threshold=-40dB,'
                    f'{_COMPRESSOR},'
                    f'loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}:print_format=json'
                ),
                '-f',
                'null',
                '-',
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        measured = _parse_loudnorm_stats(measure_result.stderr)

        if measured and all(v is not None for v in measured.values()):
            loudnorm_filter = (
                f'loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}:'
                f'measured_I={measured["input_i"]}:measured_TP={measured["input_tp"]}:'
                f'measured_LRA={measured["input_lra"]}:measured_thresh={measured["input_thresh"]}:'
                f'offset={measured["target_offset"]}:linear=true:print_format=none'
            )
            logger.debug('Using two-pass loudnorm with measured values')
        else:
            loudnorm_filter = f'loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}:print_format=none'
            logger.debug('Falling back to single-pass loudnorm')

        result = subprocess.run(
            [
                'ffmpeg',
                '-y',
                '-i',
                input_path,
                '-af',
                (
                    'silenceremove=start_periods=1:start_silence=0.2:start_threshold=-40dB,'
                    f'{_COMPRESSOR},'
                    f'{loudnorm_filter},'
                    'alimiter=level_in=1:level_out=1:limit=0.891:attack=5:release=50:level=disabled'
                ),
                '-ar',
                str(sample_rate),
                '-ac',
                '1',
                '-codec:a',
                'libmp3lame',
                '-b:a',
                bitrate,
                output_path,
            ],
            capture_output=True,
            timeout=300,
        )

        if result.returncode != 0:
            logger.error(
                f'Mastering failed (rc={result.returncode}): '
                f'{result.stderr.decode(errors="replace")[:500]}'
            )
            return False

        logger.info(
            f'Mastering complete: {output_path} '
            f'({Path(output_path).stat().st_size / (1024 * 1024):.2f} MB)'
        )
        return True

    except Exception as exc:
        logger.error(f'Mastering failed: {exc}. Using original file.')
        return False


def master_audio_with_fallback(
    input_path: str,
    output_path: str,
    target_lufs: float = DEFAULT_TARGET_LUFS,
    sample_rate: int = AUDIO_SAMPLE_RATE,
    bitrate: str = MP3_BITRATE,
) -> Tuple[bool, bool]:
    """
    Apply final mastering with fallback to raw export if mastering fails.

    Args:
        input_path: Path to the raw concatenated audio file.
        output_path: Path for the mastered output MP3.
        target_lufs: Target loudness in LUFS.
        sample_rate: Target sample rate in Hz.
        bitrate: Output MP3 bitrate.

    Returns:
        Tuple of (mastering_succeeded, fallback_used).
    """
    from pydub import AudioSegment

    master_ok = master_audio(
        input_path,
        output_path,
        target_lufs=target_lufs,
        sample_rate=sample_rate,
        bitrate=bitrate,
    )

    fallback_used = False
    if not master_ok:
        logger.warning('Mastering failed, falling back to raw export')
        if Path(input_path).exists():
            seg = AudioSegment.from_wav(input_path)
            seg.export(output_path, format='mp3', bitrate=bitrate)
            fallback_used = True

    return master_ok, fallback_used
