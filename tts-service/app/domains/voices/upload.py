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
Voice upload domain.

Validates and saves reference WAV files.
"""

from __future__ import annotations
import logging
import shutil
from pathlib import Path

try:
    import soundfile as sf

    SOUNDFILE_AVAILABLE = True
except ImportError:
    sf = None
    SOUNDFILE_AVAILABLE = False

from app.core.exceptions import TTSEngineError

logger = logging.getLogger(__name__)

MIN_DURATION_S = 5.0
MAX_DURATION_S = 120.0
MIN_SAMPLE_RATE = 16000


def validate_and_save(source_path: Path, dest_path: Path) -> None:
    """Validate WAV file quality and save to dest_path. Raises TTSEngineError on failure."""
    if not SOUNDFILE_AVAILABLE:
        raise TTSEngineError('soundfile library not installed - cannot validate audio')

    try:
        info = sf.info(str(source_path))
    except Exception as e:
        raise TTSEngineError(f'Cannot read audio file: {e}') from e

    duration = info.frames / info.samplerate
    if duration < MIN_DURATION_S:
        raise TTSEngineError(
            f'Voice sample too short ({duration:.1f}s) — minimum {MIN_DURATION_S}s'
        )
    if duration > MAX_DURATION_S:
        raise TTSEngineError(f'Voice sample too long ({duration:.1f}s) — maximum {MAX_DURATION_S}s')
    if info.samplerate < MIN_SAMPLE_RATE:
        raise TTSEngineError(
            f'Sample rate too low ({info.samplerate} Hz) — minimum {MIN_SAMPLE_RATE} Hz'
        )

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, dest_path)
    logger.info(
        'Voice profile saved: %s (%.1fs, %d Hz)',
        dest_path.name,
        duration,
        info.samplerate,
    )
