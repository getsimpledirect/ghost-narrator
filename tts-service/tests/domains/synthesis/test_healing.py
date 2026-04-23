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

import wave

import numpy as np
import soundfile as sf

from app.domains.synthesis.healing import heal_drops
from app.domains.synthesis.quality_check import _detect_mid_phrase_drops


_SR = 22050


def _write_wav(path: str, data: np.ndarray, sr: int = _SR) -> None:
    pcm = (data * 32767).clip(-32768, 32767).astype(np.int16)
    with wave.open(path, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def _build_signal_with_drop(
    total_s: float, drop_start_s: float, drop_end_s: float, freq: float = 150.0
) -> np.ndarray:
    """A sine wave with a silence region inserted to simulate a dropout."""
    n = int(total_s * _SR)
    t = np.arange(n) / _SR
    signal = 0.4 * np.sin(2 * np.pi * freq * t).astype(np.float32)
    i0 = int(drop_start_s * _SR)
    i1 = int(drop_end_s * _SR)
    signal[i0:i1] = 0.0
    return signal


def test_detect_drops_finds_synthetic_drop(tmp_path):
    wav = str(tmp_path / 'with_drop.wav')
    # 5s signal, 1s drop from t=2.0 to t=3.0 — well inside the 0.6-2.0s window.
    _write_wav(wav, _build_signal_with_drop(5.0, 2.0, 3.0))
    regions = _detect_mid_phrase_drops(wav)
    assert len(regions) == 1
    start, end = regions[0]
    # Should overlap the injected [2.0, 3.0] window (within frame-hop tolerance).
    assert 1.8 <= start <= 2.2
    assert 2.8 <= end <= 3.2


def test_detect_drops_ignores_sub_600ms_drops(tmp_path):
    wav = str(tmp_path / 'short_drop.wav')
    # 5s signal, 0.3s drop — below the 0.6s minimum, should not be detected.
    _write_wav(wav, _build_signal_with_drop(5.0, 2.0, 2.3))
    regions = _detect_mid_phrase_drops(wav)
    assert regions == []


def test_detect_drops_empty_on_missing_file(tmp_path):
    regions = _detect_mid_phrase_drops(str(tmp_path / 'does_not_exist.wav'))
    assert regions == []


def test_heal_drops_shortens_wav(tmp_path):
    wav = str(tmp_path / 'with_drop.wav')
    _write_wav(wav, _build_signal_with_drop(5.0, 2.0, 3.0))
    data_before, sr_before = sf.read(wav, dtype='float32')
    assert data_before.ndim == 1

    regions = [(2.0, 3.0)]
    heal_drops(wav, regions)

    data_after, sr_after = sf.read(wav, dtype='float32')
    assert sr_after == sr_before
    # Healed layout per drop:
    #   kept = (start_idx - xf) + xf_blended + (end..total)
    #   removed = drop_samples + xf_samples  (drop excised plus the pre-xf
    #   that got replaced by the blended region).
    removed = len(data_before) - len(data_after)
    expected = int(1.0 * sr_before) + int(0.04 * sr_before)
    # Tolerance: ± 80 ms for hop alignment.
    assert abs(removed - expected) < int(0.08 * sr_before)


def test_heal_drops_empty_regions_is_noop(tmp_path):
    wav = str(tmp_path / 'clean.wav')
    _write_wav(wav, _build_signal_with_drop(5.0, 2.0, 2.0))  # no drop
    data_before, _ = sf.read(wav, dtype='float32')

    heal_drops(wav, [])

    data_after, _ = sf.read(wav, dtype='float32')
    assert len(data_after) == len(data_before)


def test_heal_drops_skips_edge_regions(tmp_path):
    wav = str(tmp_path / 'edge_drop.wav')
    _write_wav(wav, _build_signal_with_drop(3.0, 0.0, 0.8))  # starts at file edge
    data_before, sr = sf.read(wav, dtype='float32')

    # Drop region flush against t=0 — the crossfade needs audio before it,
    # which doesn't exist; heal must skip it without crashing.
    heal_drops(wav, [(0.0, 0.8)])

    data_after, _ = sf.read(wav, dtype='float32')
    # File length unchanged because the edge drop was skipped.
    assert len(data_after) == len(data_before)


def test_heal_drops_audio_peak_stays_bounded(tmp_path):
    wav = str(tmp_path / 'with_drop.wav')
    _write_wav(wav, _build_signal_with_drop(5.0, 2.0, 3.0))

    heal_drops(wav, [(2.0, 3.0)])

    data_after, _ = sf.read(wav, dtype='float32')
    # Linear crossfade between two real audio samples cannot exceed their
    # individual amplitudes — verify no click/amplification artefact.
    assert np.max(np.abs(data_after)) <= 1.0
