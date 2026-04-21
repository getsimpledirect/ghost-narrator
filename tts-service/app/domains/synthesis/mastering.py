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
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Final, Optional, Tuple

from app.config import AUDIO_SAMPLE_RATE, MP3_BITRATE, TARGET_LUFS

logger = logging.getLogger(__name__)

DEFAULT_TARGET_LUFS: Final[float] = TARGET_LUFS
DEFAULT_TRUE_PEAK: Final[float] = -2.0
DEFAULT_LRA: Final[float] = 9.0  # Podcast standard; 7.0 over-compressed natural emphasis


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
        # Conservative mastering chain: minimal processing to avoid artifacts.
        # - silenceremove: trim leading silence
        # - compressor: gentle 2:1 compression for consistency
        # - loudnorm: two-pass EBU R128 for accurate final loudness
        # - limiter: prevent clipping
        # Removed: highpass (causes harshness), equalizer (unnecessary for TTS)
        _COMPRESSOR = (
            # threshold=0.25 ≈ -12 dBFS; 1.5:1 ratio preserves speech dynamics.
            # attack=300ms catches loud transients without over-clamping voiced consonants.
            # release=800ms prevents gain pumping on sentence pauses — the primary
            # cause of audible pumping in speech compressors is release < 400ms.
            'acompressor=threshold=0.25:ratio=1.5:attack=300:release=800'
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
                    'areverse,'
                    'silenceremove=start_periods=1:start_silence=0.2:start_threshold=-40dB,'
                    'areverse,'
                    f'{_COMPRESSOR},'
                    f'loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}:print_format=json'
                ),
                '-f',
                'null',
                '-',
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )

        measured = _parse_loudnorm_stats(measure_result.stderr)

        if measured and all(v is not None for v in measured.values()):
            logger.info(
                'Loudnorm pass-1 measured: I=%s, TP=%s, LRA=%s, thresh=%s',
                measured.get('input_i'),
                measured.get('input_tp'),
                measured.get('input_lra'),
                measured.get('input_thresh'),
            )
            loudnorm_filter = (
                f'loudnorm=I={target_lufs}:TP={true_peak}:LRA=11:'
                f'measured_I={measured["input_i"]}:measured_TP={measured["input_tp"]}:'
                f'measured_LRA={measured["input_lra"]}:measured_thresh={measured["input_thresh"]}:'
                f'offset={measured["target_offset"]}:linear=true:print_format=summary'
            )
            logger.debug('Using two-pass loudnorm with measured values')
        else:
            loudnorm_filter = f'loudnorm=I={target_lufs}:TP={true_peak}:LRA=11:print_format=summary'
            logger.debug('Falling back to single-pass loudnorm')

        _SILENCE_TRIM = (
            'silenceremove=start_periods=1:start_silence=0.2:start_threshold=-40dB,'
            'areverse,'
            'silenceremove=start_periods=1:start_silence=0.2:start_threshold=-40dB,'
            'areverse'
        )

        # Defensive alimiter after loudnorm — loudnorm's TP control has ~1 dB
        # uncertainty and does not catch intersample peaks from the MP3 encoder's
        # reconstruction filter. limit=0.794 = -2.0 dBFS sample peak; with
        # loudnorm-normalized input this rarely triggers but prevents +1 dBTP
        # excursions empirically observed with linear=true on L4/Ada.
        filter_chain = (
            f'{_SILENCE_TRIM},'
            f'{_COMPRESSOR},'
            f'{loudnorm_filter},'
            'alimiter=level_in=1:level_out=1:limit=0.794:attack=5:release=50:level=disabled'
        )

        result = subprocess.run(
            [
                'ffmpeg',
                '-y',
                '-i',
                input_path,
                '-af',
                filter_chain,
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
            timeout=600,
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

        # Post-write true-peak verification: loudnorm's TP control has ~1 dB
        # uncertainty.  If the output still exceeds -1.0 dBTP, apply a
        # compensating gain + tight alimiter remediation pass.
        try:
            verify_result = subprocess.run(
                [
                    'ffmpeg',
                    '-i',
                    output_path,
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
            measured_tp: Optional[float] = None
            for _line in verify_result.stderr.split('\n'):
                if 'Peak:' in _line and 'dBFS' in _line:
                    try:
                        measured_tp = float(_line.split('Peak:')[1].split('dBFS')[0].strip())
                    except (ValueError, IndexError):
                        pass
            if measured_tp is not None:
                logger.info('Post-master true peak: %.1f dBTP', measured_tp)
                if measured_tp > -1.0:
                    logger.warning(
                        'Post-master true peak %.1f dBTP exceeds -1.0 — '
                        'applying remediation pass with LUFS preservation',
                        measured_tp,
                    )
                    # Strategy: re-run loudnorm on the mastered output targeting
                    # the original LUFS — preserves loudness while tightening TP.
                    # Follow with tight alimiter as hard ceiling.
                    # limit=0.708 = -3.0 dBFS sample peak → ~-1.5 dBTP true peak.
                    temp_path = output_path + '.remaster.mp3'
                    remedy_filter = (
                        f'loudnorm=I={target_lufs}:TP=-2.5:LRA=11:print_format=summary,'
                        'alimiter=level_in=1:level_out=1:limit=0.708:attack=5:release=50:level=disabled'
                    )
                    remedy_result = subprocess.run(
                        [
                            'ffmpeg',
                            '-y',
                            '-i',
                            output_path,
                            '-af',
                            remedy_filter,
                            '-codec:a',
                            'libmp3lame',
                            '-b:a',
                            bitrate,
                            temp_path,
                        ],
                        capture_output=True,
                        timeout=600,
                    )
                    if remedy_result.returncode == 0:
                        shutil.move(temp_path, output_path)
                        logger.info('True-peak remediation with LUFS preservation applied')
                        verify2 = subprocess.run(
                            [
                                'ffmpeg',
                                '-i',
                                output_path,
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
                        tp2: Optional[float] = None
                        for _line2 in verify2.stderr.split('\n'):
                            if 'Peak:' in _line2 and 'dBFS' in _line2:
                                try:
                                    tp2 = float(_line2.split('Peak:')[1].split('dBFS')[0].strip())
                                except (ValueError, IndexError):
                                    pass
                        logger.info('Post-remediation true peak: %s dBTP', tp2)
                    else:
                        logger.error('True-peak remediation failed; keeping original output')
                        if Path(temp_path).exists():
                            Path(temp_path).unlink()
        except Exception as _verify_exc:
            logger.warning('Post-master true-peak verification failed (non-fatal): %s', _verify_exc)

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
