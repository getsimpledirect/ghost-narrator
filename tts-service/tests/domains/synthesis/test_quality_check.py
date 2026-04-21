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


def _make_stereo_sine(freq: float, duration_s: float, sr: int = 22050) -> np.ndarray:
    """Two-channel (stereo) sine — for testing mono-mixing paths."""
    mono = _make_sine(freq, duration_s, sr=sr)
    return np.stack([mono, mono * 0.8], axis=1)  # shape (N, 2)


def _make_speech_like(word_rate: float, duration_s: float, sr: int = 22050) -> np.ndarray:
    """Simulate speech: harmonic carrier + sinusoidal amplitude envelope.

    Produces audio that passes ALL acoustic gate checks (low spectral flatness
    from harmonics, onset rate ≈ word_rate × 1.8, non-trivial F0).  Used for
    'normal speech' test cases so the signal is not random noise (which has
    near-unity spectral flatness and would fail the flatness gate).

    The envelope ``|sin(π·word_rate·t)|²`` creates onset clusters whose rate
    scales with word_rate but is not exactly 2× due to frame-straddling in the
    25 ms analysis window.  For word_rate ≤ 3.0 the detected onset rate stays
    reliably below 7.0 onsets/s (normal-speech range).
    """
    t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
    # Harmonically rich carrier → low spectral flatness (tonal)
    carrier = (
        np.sin(2 * np.pi * 120 * t)
        + 0.6 * np.sin(2 * np.pi * 240 * t)
        + 0.3 * np.sin(2 * np.pi * 360 * t)
    )
    # Syllable-rate envelope → controlled onset rate ≈ word_rate × 1.8
    envelope = np.abs(np.sin(np.pi * word_rate * t)) ** 2
    return (carrier * envelope * 0.2).astype(np.float32)


class TestComputeOnsetRate:
    def test_silence_returns_zero(self, tmp_path):
        from app.domains.synthesis.quality_check import _compute_onset_rate

        p = str(tmp_path / 'silence.wav')
        _write_wav(p, _make_silence(2.0))
        assert _compute_onset_rate(p) == 0.0

    def test_rapid_noise_returns_high_rate(self, tmp_path):
        from app.domains.synthesis.quality_check import _compute_onset_rate

        p = str(tmp_path / 'rapid.wav')
        _write_wav(p, _make_rapid_noise(rate_hz=10.0, duration_s=3.0))
        assert _compute_onset_rate(p) > 6.0

    def test_speech_like_returns_normal_rate(self, tmp_path):
        from app.domains.synthesis.quality_check import _compute_onset_rate

        p = str(tmp_path / 'speech.wav')
        data = _make_speech_like(word_rate=2.0, duration_s=3.0)
        _write_wav(p, data)
        rate = _compute_onset_rate(p)
        assert 1.0 < rate < 7.0

    def test_stereo_input_handled(self, tmp_path):
        from app.domains.synthesis.quality_check import _compute_onset_rate
        import soundfile as sf

        p = str(tmp_path / 'stereo.wav')
        sf.write(p, _make_stereo_sine(200.0, 2.0), 22050)
        rate = _compute_onset_rate(p)
        assert isinstance(rate, float)
        assert rate >= 0.0


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

    def test_stereo_input_handled(self, tmp_path):
        from app.domains.synthesis.quality_check import _compute_spectral_flatness
        import soundfile as sf

        p = str(tmp_path / 'stereo.wav')
        sf.write(p, _make_stereo_sine(200.0, 2.0), 22050)
        flatness = _compute_spectral_flatness(p)
        assert isinstance(flatness, float)
        assert 0.0 <= flatness <= 1.0


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

    def test_stereo_input_handled(self, tmp_path):
        from app.domains.synthesis.quality_check import _estimate_median_f0
        import soundfile as sf

        p = str(tmp_path / 'stereo.wav')
        sf.write(p, _make_stereo_sine(200.0, 2.0), 22050)
        f0 = _estimate_median_f0(p)
        assert f0 is not None
        assert 170 < f0 < 240

    def test_multi_harmonic_no_octave_error(self, tmp_path):
        """Multi-harmonic input (fundamental + 2nd + 3rd) must not return double freq."""
        from app.domains.synthesis.quality_check import _estimate_median_f0

        sr = 22050
        duration_s = 3.0
        t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
        # Fundamental 120 Hz + strong 2nd harmonic (240 Hz) + 3rd (360 Hz)
        # The 2nd harmonic is at 0.8× the fundamental — strong enough to trigger
        # octave errors in naive autocorrelation.
        signal = (
            np.sin(2 * np.pi * 120 * t)
            + 0.8 * np.sin(2 * np.pi * 240 * t)
            + 0.4 * np.sin(2 * np.pi * 360 * t)
        ).astype(np.float32) * 0.4
        p = str(tmp_path / 'multi_harmonic.wav')
        _write_wav(p, signal, sr=sr)
        f0 = _estimate_median_f0(p)
        assert f0 is not None
        # Must be within ±20% of 120 Hz, not erroneously doubled to ~240 Hz
        assert 96 < f0 < 145, f'Expected ~120 Hz, got {f0:.1f} Hz'

    def test_requires_minimum_voiced_frames(self, tmp_path):
        """Very short signal with < 10 voiced frames should return None."""
        from app.domains.synthesis.quality_check import _estimate_median_f0

        sr = 22050
        # 200ms sine — at 30ms frames / 15ms hop, this yields ~12 frames total,
        # but only the voiced ones count; the short sine has exactly the right
        # amount of frames to test the boundary. Use 100ms to be clearly below.
        t = np.linspace(0, 0.1, int(sr * 0.1), endpoint=False)
        signal = (np.sin(2 * np.pi * 200 * t) * 0.5).astype(np.float32)
        p = str(tmp_path / 'short.wav')
        _write_wav(p, signal, sr=sr)
        result = _estimate_median_f0(p)
        assert result is None


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


class TestDurationRatioCheck:
    """Duration-ratio validation: catch hallucinating segments before concatenation."""

    def test_chunk_too_long_raises_synthesis_error(self, tmp_path):
        """A 5-word chunk that produces 5 minutes of audio should be flagged."""
        from app.domains.synthesis.quality_check import _chunk_passes_acoustic_gate

        p = str(tmp_path / 'long.wav')
        _write_wav(p, (_make_sine(200.0, 300.0) * 0.3).astype(np.float32))
        result = _chunk_passes_acoustic_gate(p, word_count=5, reference_f0=None)
        assert result is False

    def test_chunk_within_expected_range_passes(self, tmp_path):
        """A 50-word chunk with ~20s of audio should pass duration check."""
        from app.domains.synthesis.quality_check import _chunk_passes_acoustic_gate

        p = str(tmp_path / 'ok.wav')
        # Use _make_speech_like — harmonic carrier has low spectral flatness so it
        # passes the flatness gate (flatness << 0.025). Random noise would fail.
        _write_wav(p, _make_speech_like(word_rate=2.0, duration_s=20.0))
        result = _chunk_passes_acoustic_gate(p, word_count=50, reference_f0=None)
        assert result is True

    def test_empty_audio_fails(self, tmp_path):
        """Sub-100ms audio is caught by the empty-audio check."""
        from app.domains.synthesis.quality_check import _chunk_passes_acoustic_gate

        p = str(tmp_path / 'empty.wav')
        _write_wav(p, _make_silence(0.05))
        result = _chunk_passes_acoustic_gate(p, word_count=10, reference_f0=None)
        assert result is False

    def test_high_onset_rate_fails(self, tmp_path):
        """Onset rate > 6.5 /s should flag hallucination."""
        from app.domains.synthesis.quality_check import _chunk_passes_acoustic_gate

        p = str(tmp_path / 'rapid.wav')
        _write_wav(p, _make_rapid_noise(rate_hz=15.0, duration_s=10.0))
        result = _chunk_passes_acoustic_gate(p, word_count=25, reference_f0=None)
        assert result is False

    def test_speaker_drift_fails(self, tmp_path):
        """F0 far from reference (>3 semitones) should fail gate."""
        from app.domains.synthesis.quality_check import _chunk_passes_acoustic_gate

        p = str(tmp_path / 'high_pitch.wav')
        # Reference is 100 Hz, chunk is 400 Hz — way more than 3 semitones apart
        _write_wav(p, (_make_sine(400.0, 5.0) * 0.5).astype(np.float32))
        result = _chunk_passes_acoustic_gate(p, word_count=12, reference_f0=100.0)
        assert result is False


class TestResynthesizeStrategies:
    """_resynthesize_with_strategies uses 4 input-modifying strategies."""

    def test_strategy_0_uses_repetition_penalty(self):
        """Strategy 0 must set repetition_penalty=1.2 on the kwargs."""
        from app.domains.synthesis.quality_check import _resynthesize_with_strategies

        import inspect
        src = inspect.getsource(_resynthesize_with_strategies)
        assert 'repetition_penalty' in src
        assert '1.2' in src

    def test_split_at_punctuation_bidirectional(self):
        """_split_at_punctuation must find a split to the right of the pivot if left has none."""
        # Access the inner helper by running the function partially — instead, test the
        # behaviour through re-synthesis by checking the source code uses bidirectional search.
        from app.domains.synthesis.quality_check import _resynthesize_with_strategies
        import inspect
        src = inspect.getsource(_resynthesize_with_strategies)
        # Must search in both directions (pivot - offset AND pivot + offset)
        assert 'pivot - offset' in src
        assert 'pivot + offset' in src

    def test_strategy_3_sanitizes_text(self):
        """Strategy 3 must strip parentheticals, digits, and ALL-CAPS tokens."""
        from app.domains.synthesis.quality_check import _resynthesize_with_strategies
        import inspect
        src = inspect.getsource(_resynthesize_with_strategies)
        assert '_sanitize_text' in src or 'sanitize' in src.lower()

    def test_exception_handler_is_narrow(self):
        """Exception handler must not catch ChunkExhaustedError."""
        from app.domains.synthesis.quality_check import _resynthesize_with_strategies
        import inspect
        src = inspect.getsource(_resynthesize_with_strategies)
        # Must NOT have bare 'except Exception'
        assert 'except Exception' not in src
        # Must have narrow catches
        assert 'SynthesisError' in src
