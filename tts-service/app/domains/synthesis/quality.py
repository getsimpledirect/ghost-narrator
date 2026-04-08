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
Audio quality validation for TTS output.

Provides functions for validating final audio output quality
using ffmpeg-based analysis.
"""

from __future__ import annotations

import logging
import subprocess

from app.config import TARGET_LUFS

logger = logging.getLogger(__name__)


def apply_final_mastering(input_path: str, output_path: str) -> bool:
    """
    Apply final mastering to the complete concatenated audio file.

    Thin wrapper around master_audio_with_fallback that returns a single bool
    for backward compatibility with the old audio domain API.

    Args:
        input_path: Path to the raw concatenated audio file.
        output_path: Path for the mastered output MP3.

    Returns:
        True if mastering succeeded, False otherwise.
    """
    from app.domains.synthesis.mastering import master_audio_with_fallback

    success, _ = master_audio_with_fallback(input_path, output_path)
    return success


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
                'ffmpeg',
                '-i',
                mp3_path,
                '-filter_complex',
                'ebur128=peak=true',
                '-f',
                'null',
                '-',
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        output = r.stderr

        # Parse integrated loudness and true peak from the final ebur128 summary.
        # ffmpeg emits a measurement line per-frame during analysis (all showing
        # transient/silence values like -70 LUFS) followed by a single summary block.
        # Collect the last matching value for each metric so only the summary is used.
        last_lufs: float | None = None
        last_peak: float | None = None
        for line in output.split('\n'):
            if 'I:' in line and 'LUFS' in line:
                try:
                    last_lufs = float(line.split('I:')[1].split('LUFS')[0].strip())
                except (ValueError, IndexError):
                    pass
            if 'Peak:' in line and 'dBFS' in line:
                try:
                    last_peak = float(line.split('Peak:')[1].split('dBFS')[0].strip())
                except (ValueError, IndexError):
                    pass

        if last_lufs is not None:
            results['integrated_lufs'] = last_lufs
            if not (TARGET_LUFS - 2 <= last_lufs <= TARGET_LUFS + 2):
                logger.warning(
                    f'Integrated loudness {last_lufs:.1f} LUFS '
                    f'outside target range {TARGET_LUFS - 2:.0f} to {TARGET_LUFS + 2:.0f} LUFS'
                )
        if last_peak is not None:
            results['true_peak_dbfs'] = last_peak
            if last_peak > -1.0:
                logger.warning(f'True peak {last_peak:.1f} dBFS exceeds -1.0 dBFS limit')

        # Check for excessive silence gaps (> 1.2s)
        r2 = subprocess.run(
            [
                'ffmpeg',
                '-i',
                mp3_path,
                '-filter_complex',
                'silencedetect=noise=-40dB:d=1.2',
                '-f',
                'null',
                '-',
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        long_gaps = [line for line in r2.stderr.split('\n') if 'silence_duration' in line]
        results['long_silence_gaps_count'] = len(long_gaps)
        if long_gaps:
            logger.warning(f'{len(long_gaps)} silence gap(s) exceeding 1.2s detected in output')

    except Exception as exc:
        logger.warning(f'Quality validation error (non-fatal): {exc}')

    return results
