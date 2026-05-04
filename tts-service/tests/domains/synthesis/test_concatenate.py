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

import numpy as np
from pydub import AudioSegment


def _make_sine_wav(duration_ms: int = 1000, sample_rate: int = 24000) -> AudioSegment:
    """Generate a 440Hz sine wave segment for testing."""
    samples = int(sample_rate * duration_ms / 1000)
    t = np.linspace(0, duration_ms / 1000, samples, endpoint=False)
    wave = (np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
    return AudioSegment(wave.tobytes(), frame_rate=sample_rate, sample_width=2, channels=1)


def test_trim_silence_removes_trailing_silence_block():
    """_trim_silence must trim trailing silence beyond MIN_SILENCE_MS."""
    from app.domains.synthesis.concatenate import _trim_silence

    # 1s sine + 500ms silence — trailing silence is 500ms, well above
    # MIN_SILENCE_MS (100ms), so it should be trimmed to ~the speech end.
    sine = _make_sine_wav(1000)
    silence = AudioSegment.silent(duration=500)
    segment = sine + silence

    trimmed = _trim_silence(segment)
    # Trailing silence stripped to within one chunk-size (10ms) of the
    # last speech sample. Allow a small tolerance for the chunk granularity.
    assert 990 <= len(trimmed) <= 1100, f'Expected ~1000ms, got {len(trimmed)}'


def test_trim_silence_preserves_speech_with_no_trailing_silence():
    """Regression: _trim_silence must not destroy speech when there is
    no trailing silence to trim. The previous soft-cap branch replaced
    the last 200ms of every segment with hard silence regardless of
    content, cutting actual speech audio. For the last segment of the
    concatenated file, mastering's silenceremove then stripped that
    silence, producing an abrupt mid-decay end.
    """
    from app.domains.synthesis.concatenate import _trim_silence

    # Pure 1s sine, no silence anywhere.
    sine = _make_sine_wav(1000)

    trimmed = _trim_silence(sine)

    # Length must be unchanged — no silence to trim, nothing to cut.
    assert len(trimmed) == 1000, f'Expected 1000ms preserved, got {len(trimmed)}'
    # Last 200ms must still be speech, not silence (the bug).
    last_200ms = trimmed[-200:]
    assert last_200ms.dBFS > -40, (
        f'Last 200ms should still contain speech, got dBFS={last_200ms.dBFS} (silence ≈ -inf)'
    )


def test_trim_preserves_audio_above_noise_floor():
    """Regression: speech-tail audio in the -50 to -60 dBFS range is the
    *natural acoustic decay* of word endings, not silence. The trim must
    NOT cut it. With the previous SILENCE_THRESHOLD_DB=-50, the trim was
    chopping mid-decay and producing audible "cut-off" segment endings.
    With -60, only true noise floor is trimmed.
    """
    from app.domains.synthesis.concatenate import _trim_silence

    # 800ms of audible content: 600ms full-amplitude sine + 200ms decaying
    # sine that ends around -55 dBFS (well above the new -60 threshold but
    # below the old -50 threshold — the "danger zone" the bug lived in).
    sample_rate = 24000
    full = _make_sine_wav(600, sample_rate)
    # Build a 200ms decaying sine: amplitude ramps linearly from 1.0 to ~0.0017
    # so the dBFS at the end is ~-55, decay region average ~-30 dBFS.
    decay_samples = int(sample_rate * 200 / 1000)
    t = np.linspace(0, 200 / 1000, decay_samples, endpoint=False)
    envelope = np.linspace(1.0, 0.0017, decay_samples)  # peak → -55 dBFS
    decay_wave = (np.sin(2 * np.pi * 440 * t) * envelope * 32767).astype(np.int16)
    decay = AudioSegment(decay_wave.tobytes(), frame_rate=sample_rate, sample_width=2, channels=1)
    silence_tail = AudioSegment.silent(duration=300)  # true silence
    segment = full + decay + silence_tail  # 600 + 200 + 300 = 1100ms total

    trimmed = _trim_silence(segment)

    # The 300ms of true silence should be trimmed, but the 800ms of audible
    # content (full sine + decay) should survive. Allow a small tolerance
    # for the chunk-aligned trim boundary (~10 ms granularity).
    assert 790 <= len(trimmed) <= 820, (
        f'Expected ~800ms (full + decay preserved), got {len(trimmed)}ms — '
        'trim may be cutting the natural decay region again'
    )


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


def test_crossfade_inserts_audible_silent_pause_between_segments():
    """Regression: between A's last loud sample and the crossfade region,
    there must be `pause_ms` of pure silence — that's the audible inter-
    segment gap. The previous behaviour appended only `pause_ms` of silence,
    so when pause_ms < CROSSFADE_MS the crossfade overlapped real speech
    from A with real speech from B (audible doubled voice). The fix
    appends `pause_ms + CROSSFADE_MS` so the crossfade region is silence
    on the A side, fading cleanly into B's start.
    """
    from app.domains.synthesis.concatenate import _crossfade_append, CROSSFADE_MS

    a = _make_sine_wav(500)
    b = _make_sine_wav(500)
    pause_ms = 200  # deliberately < CROSSFADE_MS to trigger the pre-fix bug

    result = _crossfade_append(AudioSegment.empty(), a, 0)
    result = _crossfade_append(result, b, pause_ms)

    # Length: a + pause_ms (audible gap) + CROSSFADE_MS (xfade region) + (b - n)
    expected_len = len(a) + pause_ms + CROSSFADE_MS + (len(b) - CROSSFADE_MS)
    assert len(result) == expected_len, (
        f'Expected {expected_len}ms join (a + pause + crossfade + b_post), '
        f'got {len(result)}ms — fix may have regressed'
    )

    # Region between A's end and the crossfade start must be pure silence.
    # That is the user-perceived gap; before the fix, this region was
    # actually part of A's speech overlapping with B.
    pause_region = result[len(a) : len(a) + pause_ms]
    # pydub's AudioSegment for true silence returns dBFS of -inf; the safe
    # assertion is "well below speech levels" — any speech is > -40 dBFS.
    assert pause_region.dBFS < -40.0, (
        f'Region between A and crossfade should be silent (audible gap), '
        f'got dBFS={pause_region.dBFS} — speech leaking from A or B'
    )


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
