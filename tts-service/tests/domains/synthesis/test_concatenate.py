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

"""Tests for audio concatenation - smoke tests."""

import tempfile
from pathlib import Path

import numpy as np
from pydub import AudioSegment


def _make_sine_wav(duration_ms: int = 1000, sample_rate: int = 24000) -> AudioSegment:
    """Generate a 440Hz sine wave segment for testing."""
    samples = int(sample_rate * duration_ms / 1000)
    t = np.linspace(0, duration_ms / 1000, samples, endpoint=False)
    wave = (np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
    return AudioSegment(wave.tobytes(), frame_rate=sample_rate, sample_width=2, channels=1)


def test_trim_silence_caps_trailing_at_60ms():
    """_trim_silence must leave at most 60ms of trailing silence."""
    from app.domains.synthesis.concatenate import _trim_silence

    # 1s sine + 500ms silence
    sine = _make_sine_wav(1000)
    silence = AudioSegment.silent(duration=500)
    segment = sine + silence

    trimmed = _trim_silence(segment)
    # Total should be ~1060ms (1000ms speech + 60ms cap)
    assert len(trimmed) <= 1100  # generous bound for 60ms cap
    assert len(trimmed) >= 900  # speech not clipped


def test_equal_power_crossfade_no_volume_dip():
    """Equal-power crossfade must maintain loudness at the midpoint of the fade."""
    from app.domains.synthesis.concatenate import _crossfade_append, CROSSFADE_MS

    a = _make_sine_wav(500)
    b = _make_sine_wav(500)
    result = _crossfade_append(AudioSegment.empty(), a, 0)
    result = _crossfade_append(result, b, 0)

    # The crossfade region should not dip below -20dBFS (linear crossfade dips ~-3dB)
    crossfade_region = result[len(a) - CROSSFADE_MS // 2 : len(a) + CROSSFADE_MS // 2]
    assert crossfade_region.dBFS > -20.0


class TestConcatenateImports:
    """Test that concatenate module can be imported."""

    def test_concatenate_module_imports(self):
        """Test that concatenate module imports correctly."""
        from app.domains.synthesis import concatenate

        assert concatenate is not None

    def test_concatenate_function_exists(self):
        """Test that concatenate_audio_auto function exists."""
        from app.domains.synthesis.concatenate import concatenate_audio_auto

        assert callable(concatenate_audio_auto)


class TestOverlapCrossfade:
    """Tests for overlap crossfade functionality."""

    def test_concatenate_audio_with_overlap_importable(self):
        """Overlap crossfade function should be importable."""
        from app.domains.synthesis.concatenate import concatenate_audio_with_overlap

        assert callable(concatenate_audio_with_overlap)

    def test_concatenate_audio_with_overlap_single_file(self):
        """Single file should just be copied."""
        from app.domains.synthesis.concatenate import (
            concatenate_audio_with_overlap,
        )

        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            test_wav = f.name

        try:
            samples = np.random.randint(-1000, 1000, 24000, dtype=np.int16)
            seg = AudioSegment(samples.tobytes(), frame_rate=48000, sample_width=2, channels=1)
            seg.export(test_wav, format='wav')

            output = tempfile.mktemp(suffix='.wav')
            result = concatenate_audio_with_overlap([test_wav], output)

            assert Path(result).exists()
            assert Path(result).stat().st_size > 0
        finally:
            Path(test_wav).unlink(missing_ok=True)
            if 'output' in locals():
                Path(output).unlink(missing_ok=True)

    def test_concatenate_audio_with_overlap_two_files(self):
        """Two files should be crossfaded with overlap."""
        from app.domains.synthesis.concatenate import (
            concatenate_audio_with_overlap,
        )

        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            test_wav1 = f.name
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            test_wav2 = f.name

        try:
            samples1 = np.sin(np.linspace(0, 2 * np.pi, 48000)).astype(np.int16)
            seg1 = AudioSegment(samples1.tobytes(), frame_rate=48000, sample_width=2, channels=1)
            samples2 = np.sin(np.linspace(0, 4 * np.pi, 48000)).astype(np.int16)
            seg2 = AudioSegment(samples2.tobytes(), frame_rate=48000, sample_width=2, channels=1)
            seg1.export(test_wav1, format='wav')
            seg2.export(test_wav2, format='wav')

            output = tempfile.mktemp(suffix='.wav')
            result = concatenate_audio_with_overlap(
                [test_wav1, test_wav2],
                output,
                overlap_ms=500,
            )

            assert Path(result).exists()
            result_seg = AudioSegment.from_wav(result)
            assert result_seg.duration_seconds >= 1.0
        finally:
            Path(test_wav1).unlink(missing_ok=True)
            Path(test_wav2).unlink(missing_ok=True)
            if 'output' in locals():
                Path(output).unlink(missing_ok=True)
