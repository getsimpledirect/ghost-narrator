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


def _write_wav(path: str, data: np.ndarray, sr: int = 22050) -> None:
    """Write float32 numpy array as 16-bit PCM mono WAV."""
    pcm = (data * 32767).clip(-32768, 32767).astype(np.int16)
    with wave.open(path, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def _make_silence(duration_s: float = 1.0, sr: int = 22050) -> np.ndarray:
    return np.zeros(int(sr * duration_s))


def _make_sine(freq: float, duration_s: float, sr: int = 22050, amp: float = 0.5) -> np.ndarray:
    t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
    return (np.sin(2 * np.pi * freq * t) * amp).astype(np.float32)


def _make_rapid_noise(rate_hz: float, duration_s: float, sr: int = 22050) -> np.ndarray:
    """Dense burst noise at given onset rate — simulates hallucination audio."""
    data = np.zeros(int(sr * duration_s))
    burst_len = int(sr * 0.05)  # 50ms bursts
    interval = int(sr / rate_hz)
    for start in range(0, len(data) - burst_len, interval):
        burst = np.random.randn(burst_len) * 0.3
        data[start : start + burst_len] = burst
    return data.astype(np.float32)


def _make_speech_like(word_rate: float, duration_s: float, sr: int = 22050) -> np.ndarray:
    """Simulate speech: harmonic carrier + sinusoidal amplitude envelope.

    Produces audio that passes ALL acoustic gate checks (low spectral flatness
    from harmonics, onset rate ≈ word_rate × 2, non-trivial F0).  Used for
    'normal speech' test cases so the signal is not random noise (which has
    near-unity spectral flatness and would fail the flatness gate).
    """
    t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
    # Harmonically rich carrier → low spectral flatness (tonal)
    carrier = (
        np.sin(2 * np.pi * 120 * t)
        + 0.6 * np.sin(2 * np.pi * 240 * t)
        + 0.3 * np.sin(2 * np.pi * 360 * t)
    )
    # Syllable-rate envelope → controlled onset rate ≈ word_rate × 2
    envelope = np.abs(np.sin(np.pi * word_rate * t)) ** 2
    return (carrier * envelope * 0.2).astype(np.float32)


class TestComputeOnsetRate:
    def test_silence_returns_zero(self, tmp_path):
        from app.domains.synthesis.quality_check import _compute_onset_rate

        p = str(tmp_path / 'silence.wav')
        _write_wav(p, _make_silence(2.0))
        assert _compute_onset_rate(p) < 1.0

    def test_rapid_noise_returns_high_rate(self, tmp_path):
        from app.domains.synthesis.quality_check import _compute_onset_rate

        p = str(tmp_path / 'rapid.wav')
        _write_wav(p, _make_rapid_noise(rate_hz=10.0, duration_s=3.0))
        assert _compute_onset_rate(p) > 6.0

    def test_speech_like_returns_normal_rate(self, tmp_path):
        from app.domains.synthesis.quality_check import _compute_onset_rate

        p = str(tmp_path / 'speech.wav')
        data = _make_rapid_noise(rate_hz=4.0, duration_s=3.0)
        _write_wav(p, data)
        rate = _compute_onset_rate(p)
        assert 1.0 < rate <= 9.0


class TestComputeSpectralFlatness:
    def test_pure_sine_has_low_flatness(self, tmp_path):
        from app.domains.synthesis.quality_check import _compute_spectral_flatness

        p = str(tmp_path / 'sine.wav')
        _write_wav(p, _make_sine(200.0, 2.0))
        flatness = _compute_spectral_flatness(p)
        assert flatness < 0.15

    def test_white_noise_has_high_flatness(self, tmp_path):
        from app.domains.synthesis.quality_check import _compute_spectral_flatness

        p = str(tmp_path / 'noise.wav')
        _write_wav(p, (np.random.randn(44100) * 0.3).astype(np.float32))
        flatness = _compute_spectral_flatness(p)
        assert flatness > 0.20

    def test_silence_returns_zero(self, tmp_path):
        from app.domains.synthesis.quality_check import _compute_spectral_flatness

        p = str(tmp_path / 'sil.wav')
        _write_wav(p, _make_silence(1.0))
        assert _compute_spectral_flatness(p) == 0.0


class TestEstimateMedianF0:
    def test_sine_200hz_returns_near_200(self, tmp_path):
        from app.domains.synthesis.quality_check import _estimate_median_f0

        p = str(tmp_path / 'f0.wav')
        _write_wav(p, _make_sine(200.0, 2.0))
        f0 = _estimate_median_f0(p)
        assert f0 is not None
        assert 170 < f0 < 240

    def test_silence_returns_none(self, tmp_path):
        from app.domains.synthesis.quality_check import _estimate_median_f0

        p = str(tmp_path / 'sil.wav')
        _write_wav(p, _make_silence(1.0))
        assert _estimate_median_f0(p) is None


class TestQualityCheckImports:
    def test_quality_check_module_imports(self):
        from app.domains.synthesis import quality_check

        assert quality_check is not None

    def test_resynthesize_function_exists(self):
        from app.domains.synthesis.quality_check import _quality_check_and_resynthesize

        assert callable(_quality_check_and_resynthesize)


class TestQualityCheckBoundary:
    def test_resynthesize_has_proper_signature(self):
        import inspect
        from app.domains.synthesis.quality_check import _quality_check_and_resynthesize

        sig = inspect.signature(_quality_check_and_resynthesize)
        params = list(sig.parameters.keys())
        assert 'chunk_wav_paths' in params
        assert 'chunk_texts' in params
        assert 'job_id' in params
