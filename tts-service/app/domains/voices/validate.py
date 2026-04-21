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

"""Reference voice WAV quality validation."""

from __future__ import annotations

import logging
import math
import os

import numpy as np

logger = logging.getLogger(__name__)

_MIN_DURATION_S: float = 5.0
_MAX_DURATION_S: float = 120.0
_MAX_NOISE_FLOOR_DBFS: float = -55.0  # quietest 5% of frames must be below this


def validate_reference_wav(path: str) -> list[str]:
    """Validate a reference WAV file for voice cloning suitability.

    Returns a list of error strings. Empty list = valid.

    Checks:
    - File exists and is readable
    - Duration 5–120 s
    - Noise floor of quiet regions ≤ -55 dBFS
    """
    errors: list[str] = []

    if not os.path.exists(path):
        errors.append(f'Reference WAV not found: {path}')
        return errors

    try:
        import soundfile as sf

        data, sr = sf.read(path, dtype='float32', always_2d=False)
        if data.ndim > 1:
            data = data.mean(axis=1)
    except Exception as exc:
        errors.append(f'Cannot read reference WAV ({path}): {exc}')
        return errors

    duration_s = len(data) / sr
    if duration_s < _MIN_DURATION_S:
        errors.append(f'Reference WAV too short: {duration_s:.1f}s (minimum {_MIN_DURATION_S}s)')
    if duration_s > _MAX_DURATION_S:
        errors.append(f'Reference WAV too long: {duration_s:.1f}s (maximum {_MAX_DURATION_S}s)')

    # Noise floor: compute RMS of 50ms frames, take 5th percentile as noise estimate
    frame_size = int(sr * 0.050)
    if frame_size > 0 and len(data) >= frame_size:
        rms_frames = np.array(
            [
                np.sqrt(np.mean(data[i : i + frame_size] ** 2))
                for i in range(0, len(data) - frame_size + 1, frame_size)
            ]
        )
        rms_frames = rms_frames[rms_frames > 0]
        if len(rms_frames) > 0:
            noise_rms = float(np.percentile(rms_frames, 5))
            eps = 1e-10
            noise_dbfs = 20 * math.log10(noise_rms + eps)
            if noise_dbfs > _MAX_NOISE_FLOOR_DBFS:
                errors.append(
                    f'Reference WAV noise floor too high: {noise_dbfs:.1f} dBFS '
                    f'(must be \u2264 {_MAX_NOISE_FLOOR_DBFS} dBFS). '
                    'Record in a quieter environment or use noise reduction.'
                )

    return errors
