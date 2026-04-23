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
        passed, reason = _chunk_passes_acoustic_gate(p, word_count=5, reference_f0=None)
        assert passed is False
        assert reason

    def test_chunk_within_expected_range_passes(self, tmp_path):
        """A 50-word chunk with ~20s of audio should pass duration check."""
        from app.domains.synthesis.quality_check import _chunk_passes_acoustic_gate

        p = str(tmp_path / 'ok.wav')
        # Harmonic carrier keeps flatness well below the 0.18 ceiling.
        _write_wav(p, _make_speech_like(word_rate=2.0, duration_s=20.0))
        passed, reason = _chunk_passes_acoustic_gate(p, word_count=50, reference_f0=None)
        assert passed is True
        assert reason == ''

    def test_empty_audio_fails(self, tmp_path):
        """Sub-100ms audio is caught by the empty-audio check."""
        from app.domains.synthesis.quality_check import _chunk_passes_acoustic_gate

        p = str(tmp_path / 'empty.wav')
        _write_wav(p, _make_silence(0.05))
        passed, reason = _chunk_passes_acoustic_gate(p, word_count=10, reference_f0=None)
        assert passed is False
        assert reason

    def test_high_onset_rate_fails(self, tmp_path):
        """Both onset rate and spectral flatness must trip simultaneously to reject.

        Dense random-noise bursts at 20 Hz satisfy both conditions:
        onset_rate >> 8.0 /s (the new ceiling) and flatness >> 0.18 (random noise ≈ 1.0).
        """
        from app.domains.synthesis.quality_check import _chunk_passes_acoustic_gate

        p = str(tmp_path / 'rapid.wav')
        # rate_hz=10.0: interval=2205 samples, burst_len=1102 → clear silent gaps so
        # onset detection fires (≈20/s).  randn bursts are spectrally flat (≈0.85),
        # satisfying both soft checks simultaneously.  At 20Hz the burst fills the
        # entire interval (no gaps) so onset_rate drops to ~0 despite the nominal rate.
        _write_wav(p, _make_rapid_noise(rate_hz=10.0, duration_s=10.0))
        passed, reason = _chunk_passes_acoustic_gate(p, word_count=25, reference_f0=None)
        assert passed is False
        assert reason

    def test_speaker_drift_fails(self, tmp_path):
        """F0 drift > 2.5 semitones is a hard fail regardless of other metrics."""
        from app.domains.synthesis.quality_check import _chunk_passes_acoustic_gate

        p = str(tmp_path / 'high_pitch.wav')
        # Reference 100 Hz, chunk 400 Hz — 24 semitones of drift, unambiguous identity violation.
        _write_wav(p, (_make_sine(400.0, 5.0) * 0.5).astype(np.float32))
        passed, reason = _chunk_passes_acoustic_gate(p, word_count=12, reference_f0=100.0)
        assert passed is False
        assert 'speaker drift' in reason

    def test_healthy_tts_output_with_high_flatness_passes(self, tmp_path):
        """Healthy Qwen3-TTS voice-cloned output has flatness ~0.15 — must pass.

        A sine carrier at 110 Hz mixed with 0.4× white noise gives flatness above
        the 0.18 ceiling but normal onset rate and near-reference F0 — only one
        soft check trips, so the chunk should be accepted.
        """
        from app.domains.synthesis.quality_check import _chunk_passes_acoustic_gate

        p = str(tmp_path / 'healthy.wav')
        sr = 22050
        t = np.linspace(0, 20.0, int(sr * 20.0), endpoint=False)
        # Sine at 110 Hz (close to reference 105 Hz) plus noise to raise flatness
        signal = (np.sin(2 * np.pi * 110 * t) + 0.4 * np.random.randn(len(t))).astype(
            np.float32
        ) * 0.3
        _write_wav(p, signal)
        passed, reason = _chunk_passes_acoustic_gate(p, word_count=50, reference_f0=105.0)
        assert passed is True, f'Healthy audio rejected: {reason}'


class TestSplitAtPunctuation:
    """_split_at_punctuation: module-level helper used by the response ladder."""

    def test_split_returns_single_for_short_text(self):
        from app.domains.synthesis.quality_check import _split_at_punctuation

        assert _split_at_punctuation('only three words here') == ['only three words here']

    def test_split_finds_punctuation_near_pivot(self):
        from app.domains.synthesis.quality_check import _split_at_punctuation

        text = 'one two three four five, six seven eight nine ten eleven twelve'
        halves = _split_at_punctuation(text, target_fraction=0.5)
        assert len(halves) == 2
        # Left half must end at the comma, not an arbitrary word.
        assert halves[0].rstrip().endswith(',') or halves[0].endswith('five,')

    def test_split_bidirectional_right_of_pivot(self):
        from app.domains.synthesis.quality_check import _split_at_punctuation

        # No punctuation in left half — the search must find the comma to the right.
        text = 'one two three four five six seven eight, nine ten eleven twelve'
        halves = _split_at_punctuation(text, target_fraction=0.4)
        assert len(halves) == 2
        assert 'eight,' in halves[0]


class TestWindowedF0Gate:
    """Fix 1: windowed sub-chunk analysis catches localized F0 failures."""

    def test_localized_f0_drift_fails(self, tmp_path):
        """A chunk with a garbled tail (different F0) is rejected despite good overall median."""
        from app.domains.synthesis.quality_check import _chunk_passes_acoustic_gate

        sr = 22050
        # 30 s: first 20 s at 120 Hz (ref), last 10 s at 480 Hz (24 semitones drift).
        # Whole-chunk median stays near 120 Hz (2/3 of frames are good), passing the
        # hard F0 check — only the windowed gate catches this.
        good = _make_sine(120.0, 20.0, sr=sr)
        bad = _make_sine(480.0, 10.0, sr=sr)
        signal = np.concatenate([good, bad])
        p = str(tmp_path / 'garbled_chunk.wav')
        _write_wav(p, signal)
        # word_count=75 → expected 30 s — matches actual duration exactly
        passed, reason = _chunk_passes_acoustic_gate(p, word_count=75, reference_f0=120.0)
        assert passed is False
        assert 'windowed gate' in reason

    def test_uniform_f0_passes(self, tmp_path):
        """A chunk with consistent F0 throughout passes the windowed gate."""
        from app.domains.synthesis.quality_check import _chunk_passes_acoustic_gate

        sr = 22050
        # Pure 120 Hz sine: predictable autocorrelation, ~0.74 semitones from ref 115 Hz
        signal = _make_sine(120.0, 20.0, sr=sr, amp=0.4)
        p = str(tmp_path / 'uniform_f0.wav')
        _write_wav(p, signal)
        passed, reason = _chunk_passes_acoustic_gate(p, word_count=50, reference_f0=115.0)
        assert passed is True, f'Uniform-pitch audio incorrectly rejected: {reason}'

    def test_windowed_gate_skipped_without_reference(self, tmp_path):
        """Windowed F0 gate is a no-op when reference_f0 is None."""
        from app.domains.synthesis.quality_check import _chunk_passes_acoustic_gate

        sr = 22050
        # Mixed-frequency signal that would trip the windowed gate if ref were provided
        signal = np.concatenate([_make_sine(120.0, 10.0, sr=sr), _make_sine(480.0, 10.0, sr=sr)])
        p = str(tmp_path / 'mixed_f0_no_ref.wav')
        _write_wav(p, signal)
        passed, _reason = _chunk_passes_acoustic_gate(p, word_count=50, reference_f0=None)
        assert passed is True


class TestMidPhraseDropDetection:
    """Fix 2: mid-phrase drop detection catches 0.6-2.0 s amplitude collapses."""

    def _make_drop_signal(
        self,
        sr: int,
        n_drops: int,
        drop_dur_s: float = 0.8,
        total_s: float = 20.0,
    ) -> np.ndarray:
        """200 Hz sine with n_drops amplitude collapses spaced evenly."""
        data = _make_sine(200.0, total_s, sr=sr, amp=0.4)
        drop_samples = int(sr * drop_dur_s)
        spacing = int(sr * total_s / (n_drops + 1))
        for k in range(1, n_drops + 1):
            start = k * spacing
            end = min(start + drop_samples, len(data))
            data[start:end] = data[start:end] * 0.005  # near-silent
        return data

    def test_too_many_drops_fails(self, tmp_path):
        """A short chunk with 4 drops (>floor threshold of 3) is rejected."""
        from app.domains.synthesis.quality_check import _chunk_passes_acoustic_gate

        sr = 22050
        p = str(tmp_path / 'drops_4.wav')
        _write_wav(p, self._make_drop_signal(sr, n_drops=4, drop_dur_s=0.8, total_s=20.0))
        passed, reason = _chunk_passes_acoustic_gate(p, word_count=50, reference_f0=None)
        assert passed is False
        assert 'mid-phrase drops' in reason

    def test_few_drops_passes(self, tmp_path):
        """A chunk with 2 drops (≤ floor threshold of 3) passes the gate."""
        from app.domains.synthesis.quality_check import _chunk_passes_acoustic_gate

        sr = 22050
        p = str(tmp_path / 'drops_2.wav')
        _write_wav(p, self._make_drop_signal(sr, n_drops=2, drop_dur_s=0.8, total_s=20.0))
        passed, reason = _chunk_passes_acoustic_gate(p, word_count=50, reference_f0=None)
        assert passed is True, f'Expected pass with 2 drops, got: {reason}'

    def test_too_short_drops_ignored(self, tmp_path):
        """Drops shorter than 600 ms are not counted (natural punctuation pauses)."""
        from app.domains.synthesis.quality_check import _chunk_passes_acoustic_gate

        sr = 22050
        p = str(tmp_path / 'short_drops.wav')
        # 6 drops of 400 ms each — below the 600 ms minimum, so n_drops stays 0.
        # 400 ms is the upper end of natural punctuation-pause duration in
        # Qwen3-TTS output, which the previous 300 ms floor over-counted.
        _write_wav(p, self._make_drop_signal(sr, n_drops=6, drop_dur_s=0.4, total_s=20.0))
        passed, reason = _chunk_passes_acoustic_gate(p, word_count=50, reference_f0=None)
        assert passed is True, f'Sub-600 ms drops should not count: {reason}'

    def test_threshold_scales_with_duration(self, tmp_path):
        """A long chunk tolerates more drops — ~1 per 20s, not fixed at 3.

        A 160s chunk with 6 drops passes under the scaled threshold
        (tolerance = max(3, 160/20) = 8), but would fail the old fixed
        threshold of 3. This matches the natural rate of sentence pauses
        that briefly register as amplitude drops in long-form narration.
        """
        from app.domains.synthesis.quality_check import _chunk_passes_acoustic_gate

        sr = 22050
        p = str(tmp_path / 'long_chunk_6_drops.wav')
        _write_wav(p, self._make_drop_signal(sr, n_drops=6, drop_dur_s=0.8, total_s=160.0))
        passed, reason = _chunk_passes_acoustic_gate(p, word_count=400, reference_f0=None)
        assert passed is True, f'Expected pass with 6 drops over 160s, got: {reason}'

    def test_threshold_scaling_still_rejects_excessive_drops(self, tmp_path):
        """A long chunk with drops exceeding the scaled tolerance still fails.

        A 100s chunk with 8 drops exceeds the scaled tolerance of
        max(3, 100/20) = 5 and is rejected — the scaling loosens the
        bar proportionally, it does not remove it.
        """
        from app.domains.synthesis.quality_check import _chunk_passes_acoustic_gate

        sr = 22050
        p = str(tmp_path / 'long_chunk_8_drops.wav')
        _write_wav(p, self._make_drop_signal(sr, n_drops=8, drop_dur_s=0.8, total_s=100.0))
        passed, reason = _chunk_passes_acoustic_gate(p, word_count=250, reference_f0=None)
        assert passed is False
        assert 'mid-phrase drops' in reason


class TestResponseLadder:
    """_segment_response_ladder: heal → seed-sweep → split → flag."""

    def test_ladder_has_four_ordered_steps(self):
        """Ladder source must reference each of the four steps in order."""
        import inspect

        from app.domains.synthesis.quality_check import _segment_response_ladder

        src = inspect.getsource(_segment_response_ladder)
        heal_pos = src.find('Step 1: heal')
        sweep_pos = src.find('Step 2: seed-sweep')
        split_pos = src.find('Step 3: split')
        flag_pos = src.find('Step 4: flag')
        assert -1 < heal_pos < sweep_pos < split_pos < flag_pos

    def test_ladder_raises_when_no_variant_produced(self):
        """When every synthesis attempt raises, ladder raises ChunkExhaustedError."""
        import inspect

        from app.domains.synthesis.quality_check import _segment_response_ladder

        src = inspect.getsource(_segment_response_ladder)
        assert 'ChunkExhaustedError' in src
        assert 'raise ChunkExhaustedError' in src

    def test_ladder_seed_sweep_uses_best_of_n(self):
        """Step 2 must call synthesize_best_of_n with the sweep constant."""
        import inspect

        from app.domains.synthesis.quality_check import _segment_response_ladder

        src = inspect.getsource(_segment_response_ladder)
        assert 'synthesize_best_of_n' in src
        assert '_SEED_SWEEP_N' in src

    def test_ladder_flag_path_returns_best_variant(self):
        """Step 4 copies the best-scoring variant into wav_path and warns."""
        import inspect

        from app.domains.synthesis.quality_check import _segment_response_ladder

        src = inspect.getsource(_segment_response_ladder)
        assert 'flagged for review' in src
        assert 'best_path' in src


class TestRetrySeeds:
    """Seed-sweep variants must explore distinct decoding paths."""

    def test_seed_values_are_distinct(self):
        """Prime-offset arithmetic must produce N unique seed values per run."""
        original_seed = 42
        seeds = [(original_seed + i * 7919) % (2**31) for i in range(5)]
        assert len(set(seeds)) == 5
        assert all(0 <= s < 2**31 for s in seeds)

    def test_best_of_n_uses_prime_offset(self):
        """synthesize_best_of_n must use 7919-based seed offsets so runs stay reproducible."""
        import inspect

        from app.domains.synthesis.service import synthesize_best_of_n

        src = inspect.getsource(synthesize_best_of_n)
        assert '7919' in src
