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

"""Composite quality scoring for best-of-N synthesis selection.

The score is a weighted sum of normalised per-metric scores in [0, 1], where
0 is ideal and 1 is the rejection threshold. Lower composite total = better
audio. Used to pick the best of N synthesised variants for each segment.
"""

from __future__ import annotations

import logging
import math
import os
from pathlib import Path

import soundfile as _sf

from app.domains.synthesis.quality_check import (
    _compute_spectral_flatness,
    _count_mid_phrase_drops,
    _estimate_median_f0,
    _transcribe_wav,
    _word_error_rate,
)


logger = logging.getLogger(__name__)


# Component weights — sum to 1.0. Tunable via env var for calibration runs.
# Rationale:
#   F0 drift (0.40): hard identity signal; wrong pitch = wrong speaker.
#   WER (0.30): semantic correctness; drops words and hallucinations.
#   drops (0.20): mid-phrase amplitude collapses; very audible when present.
#   flatness (0.10): spectral texture quality; subtle but additive.
_DEFAULT_WEIGHTS: dict[str, float] = {
    'f0': 0.40,
    'wer': 0.30,
    'drops': 0.20,
    'flatness': 0.10,
}


def _load_weights() -> dict[str, float]:
    """Read per-component weights from env (COMPOSITE_SCORE_W_<NAME>), fall back to defaults.

    Weights are normalised so the returned dict sums to 1.0 regardless of input.
    """
    weights = dict(_DEFAULT_WEIGHTS)
    for key in list(weights.keys()):
        env_val = os.environ.get(f'COMPOSITE_SCORE_W_{key.upper()}', '').strip()
        if env_val:
            try:
                weights[key] = max(0.0, float(env_val))
            except ValueError:
                logger.warning(
                    'Invalid COMPOSITE_SCORE_W_%s=%r — using default', key.upper(), env_val
                )
    total = sum(weights.values())
    if total <= 0:
        return dict(_DEFAULT_WEIGHTS)
    return {k: v / total for k, v in weights.items()}


def _f0_score(wav_path: str, reference_f0: float | None) -> float:
    """F0 drift in semitones, normalised. 0 = match, 1 = ≥5 st drift or undetectable."""
    if reference_f0 is None or reference_f0 <= 0:
        return 0.0
    chunk_f0 = _estimate_median_f0(wav_path)
    if chunk_f0 is None or chunk_f0 <= 0:
        return 1.0
    semitones = abs(12 * math.log2(chunk_f0 / reference_f0))
    return min(1.0, semitones / 5.0)


def _wer_score(wav_path: str, text: str) -> float:
    """Word error rate, normalised. 0 = perfect transcription, 1 = WER ≥ 0.5."""
    if not text or not text.strip():
        return 0.0
    transcript = _transcribe_wav(wav_path)
    if transcript is None:
        # ASR unavailable (e.g. model not loaded) — neutral contribution.
        return 0.0
    wer = _word_error_rate(text, transcript)
    return min(1.0, wer / 0.5)


def _drops_score(wav_path: str) -> float:
    """Mid-phrase drop density, normalised.

    The acoustic gate tolerates max(3, duration_s / 20) drops before rejecting;
    the scorer uses the same rate as its ceiling so a segment at the gate
    threshold scores 1.0 on this component.
    """
    try:
        data, sr = _sf.read(wav_path, dtype='float32', always_2d=False)
        if data.ndim > 1:
            data = data.mean(axis=1)
        duration_s = max(1.0, len(data) / sr)
    except Exception:
        return 0.0
    n_drops = _count_mid_phrase_drops(wav_path)
    tolerance = max(3.0, duration_s / 20.0)
    return min(1.0, n_drops / tolerance)


def _flatness_score(wav_path: str) -> float:
    """Spectral flatness deviation from voiced baseline.

    Clean TTS voice output sits around 0.05 flatness. The acoustic gate
    rejects at 0.18. Map 0.05 → 0.0 and 0.30 → 1.0 so typical noise fingerprints
    already score meaningfully before reaching the gate.
    """
    flatness = _compute_spectral_flatness(wav_path)
    if flatness <= 0:
        return 0.0
    return max(0.0, min(1.0, (flatness - 0.05) / 0.25))


def compute_composite_score(
    wav_path: str,
    text: str,
    reference_f0: float | None,
) -> dict[str, float]:
    """Return per-component scores plus the weighted total.

    All values in [0, 1] with 0 = ideal. The returned dict is safe to log and
    compare — best_of_n selection picks the variant with the lowest 'total'.
    """
    if not Path(wav_path).exists():
        return {'total': 1.0, 'f0': 1.0, 'wer': 1.0, 'drops': 1.0, 'flatness': 1.0}

    weights = _load_weights()
    components = {
        'f0': _f0_score(wav_path, reference_f0),
        'wer': _wer_score(wav_path, text),
        'drops': _drops_score(wav_path),
        'flatness': _flatness_score(wav_path),
    }
    total = sum(weights[k] * components[k] for k in components)
    return {'total': total, **components}
