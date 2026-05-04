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

"""In-place repair for detected mid-phrase amplitude drops.

Instead of resynthesising a whole segment to fix a few brief dropouts, we
excise each drop region and replace it with a linear crossfade between the
audio immediately before and after the drop. The listener hears a short
breath-like pause in place of a muddy vocoded dropout — a strictly better
trade in almost every case.
"""

from __future__ import annotations

import logging
from typing import Iterable

import numpy as np
import soundfile as _sf


logger = logging.getLogger(__name__)


# 40 ms crossfade window on each side of a drop. Long enough to avoid click
# artefacts at the splice boundaries, short enough that the resulting pause
# stays imperceptible as prosody.
_CROSSFADE_SECONDS: float = 0.040


def heal_drops(wav_path: str, drop_regions: Iterable[tuple[float, float]]) -> str:
    """Excise each drop region and crossfade its surrounding audio together.

    Writes the healed waveform back to wav_path and returns the path. Drops
    within a crossfade-length of a file edge or of a previous drop are
    skipped so the crossfade has clean audio on both sides. When there are
    no valid regions the file is left untouched.

    Raises OSError / RuntimeError from the underlying soundfile read/write.
    """
    regions_list = sorted([r for r in drop_regions if r[1] > r[0]], key=lambda r: r[0])
    if not regions_list:
        return wav_path

    data, sr = _sf.read(wav_path, dtype='float32', always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    xf = int(sr * _CROSSFADE_SECONDS)
    if xf <= 0 or len(data) <= 2 * xf:
        logger.debug('heal_drops: wav %s too short for crossfade; leaving untouched', wav_path)
        return wav_path

    pieces: list[np.ndarray] = []
    cursor = 0
    healed_count = 0
    skipped_count = 0

    for start_s, end_s in regions_list:
        start_idx = int(start_s * sr)
        end_idx = int(end_s * sr)
        if start_idx < cursor + xf or end_idx + xf > len(data):
            skipped_count += 1
            continue
        # Everything up to start_idx - xf is kept verbatim; the xf region on
        # each side of the drop is replaced by a single blended xf-length slice.
        pieces.append(data[cursor : start_idx - xf])
        pre_xf = data[start_idx - xf : start_idx]
        post_xf = data[end_idx : end_idx + xf]
        ramp = np.linspace(0.0, 1.0, xf, dtype=np.float32)
        blended = pre_xf * (1.0 - ramp) + post_xf * ramp
        pieces.append(blended.astype(np.float32))
        cursor = end_idx + xf
        healed_count += 1

    pieces.append(data[cursor:])
    new_data = np.concatenate(pieces).astype(np.float32) if pieces else data

    _sf.write(wav_path, new_data, sr)

    if healed_count:
        logger.info(
            'heal_drops: %s — healed %d / %d region(s) (%d skipped at edges)',
            wav_path,
            healed_count,
            len(regions_list),
            skipped_count,
        )
    return wav_path
