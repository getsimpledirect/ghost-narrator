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

from app.domains.synthesis import scorer


def _write_tone(path: str, freq_hz: float, duration_s: float = 2.0, sr: int = 22050) -> None:
    """Write a stable sine-wave tone as a 16-bit mono WAV."""
    t = np.arange(int(sr * duration_s)) / sr
    wav = 0.5 * np.sin(2 * np.pi * freq_hz * t)
    pcm = (wav * 32767).astype(np.int16)
    with wave.open(path, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def test_composite_score_returns_expected_shape(tmp_path):
    wav = str(tmp_path / 'a.wav')
    _write_tone(wav, 200.0)
    score = scorer.compute_composite_score(wav, text='', reference_f0=None)
    assert set(score.keys()) >= {'total', 'f0', 'wer', 'drops', 'flatness'}
    assert 0.0 <= score['total'] <= 1.0


def test_composite_score_missing_file_is_worst(tmp_path):
    score = scorer.compute_composite_score(
        str(tmp_path / 'missing.wav'), text='hello', reference_f0=200.0
    )
    assert score['total'] == 1.0
    assert score['f0'] == 1.0


def test_f0_score_no_reference_returns_zero(tmp_path):
    wav = str(tmp_path / 'tone.wav')
    _write_tone(wav, 200.0)
    assert scorer._f0_score(wav, reference_f0=None) == 0.0
    assert scorer._f0_score(wav, reference_f0=0.0) == 0.0


def test_f0_score_matching_pitch_is_low(tmp_path):
    wav = str(tmp_path / 'tone200.wav')
    _write_tone(wav, 200.0)
    # Reference within a few Hz — score should be well under 0.3 (which is 1.5 st).
    assert scorer._f0_score(wav, reference_f0=200.0) < 0.3


def test_f0_score_large_drift_clips_to_one(tmp_path):
    wav = str(tmp_path / 'tone400.wav')
    _write_tone(wav, 400.0)
    # 400 Hz vs 100 Hz reference = 24 st drift, well past the 5 st ceiling.
    assert scorer._f0_score(wav, reference_f0=100.0) == 1.0


def test_drops_score_tonal_signal_is_zero(tmp_path):
    wav = str(tmp_path / 'tone.wav')
    _write_tone(wav, 200.0, duration_s=3.0)
    # A steady tone has no amplitude drops.
    assert scorer._drops_score(wav) == 0.0


def test_flatness_score_tonal_signal_is_low(tmp_path):
    wav = str(tmp_path / 'tone.wav')
    _write_tone(wav, 200.0, duration_s=2.0)
    # Pure tone is highly tonal → low flatness → score near 0.
    assert scorer._flatness_score(wav) < 0.2


def test_wer_score_empty_text_returns_zero(tmp_path):
    wav = str(tmp_path / 'tone.wav')
    _write_tone(wav, 200.0)
    assert scorer._wer_score(wav, text='') == 0.0
    assert scorer._wer_score(wav, text='   ') == 0.0


def test_load_weights_normalises_to_one():
    weights = scorer._load_weights()
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_load_weights_env_override(monkeypatch):
    monkeypatch.setenv('COMPOSITE_SCORE_W_F0', '2.0')
    monkeypatch.setenv('COMPOSITE_SCORE_W_WER', '1.0')
    monkeypatch.setenv('COMPOSITE_SCORE_W_DROPS', '1.0')
    monkeypatch.setenv('COMPOSITE_SCORE_W_FLATNESS', '0.0')
    weights = scorer._load_weights()
    assert abs(sum(weights.values()) - 1.0) < 1e-9
    # F0 got half the total weight (2.0 / 4.0).
    assert abs(weights['f0'] - 0.5) < 1e-9
    assert weights['flatness'] == 0.0


def test_load_weights_invalid_env_falls_back(monkeypatch):
    monkeypatch.setenv('COMPOSITE_SCORE_W_F0', 'not-a-number')
    weights = scorer._load_weights()
    # Should still be normalised and contain all keys.
    assert abs(sum(weights.values()) - 1.0) < 1e-9
    assert weights['f0'] > 0


def test_composite_total_is_weighted_sum(tmp_path):
    wav = str(tmp_path / 'tone.wav')
    _write_tone(wav, 200.0, duration_s=2.0)
    score = scorer.compute_composite_score(wav, text='', reference_f0=200.0)
    weights = scorer._load_weights()
    expected = sum(weights[k] * score[k] for k in weights)
    assert abs(score['total'] - expected) < 1e-6


def test_skip_wer_does_not_call_asr(tmp_path, monkeypatch):
    """With skip_wer=True, _transcribe_wav must not be called — the expensive
    ASR pass is the whole point of skipping. Guard with a monkeypatched sentinel."""
    wav = str(tmp_path / 'tone.wav')
    _write_tone(wav, 200.0, duration_s=2.0)

    called = {'n': 0}

    def _should_not_run(_path):
        called['n'] += 1
        return 'unexpected'

    monkeypatch.setattr(scorer, '_transcribe_wav', _should_not_run)

    score = scorer.compute_composite_score(
        wav, text='some spoken text', reference_f0=200.0, skip_wer=True
    )
    assert called['n'] == 0
    # WER component is zeroed out; remaining components sum to 1.0 after rebalance.
    assert score['wer'] == 0.0


def test_skip_wer_total_in_unit_interval(tmp_path):
    """Skipped-WER total must stay in [0, 1]; skip mode drops WER's contribution
    to 0, so the total is strictly ≤ the full-WER total for the same audio."""
    wav = str(tmp_path / 'tone.wav')
    _write_tone(wav, 200.0, duration_s=2.0)

    score_skip = scorer.compute_composite_score(
        wav, text='some words', reference_f0=200.0, skip_wer=True
    )
    assert 0.0 <= score_skip['total'] <= 1.0
    assert score_skip['wer'] == 0.0
