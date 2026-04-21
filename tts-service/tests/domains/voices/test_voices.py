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

from __future__ import annotations

import wave

import numpy as np
import pytest

from app.domains.voices.registry import VoiceRegistry


@pytest.fixture
def voices_dir(tmp_path):
    default_dir = tmp_path / 'default'
    default_dir.mkdir()
    profiles_dir = tmp_path / 'profiles'
    profiles_dir.mkdir()
    return tmp_path


def test_resolve_default_new_path(voices_dir):
    ref = voices_dir / 'default' / 'reference.wav'
    ref.write_bytes(b'fake-wav')
    reg = VoiceRegistry(voices_dir)
    assert reg.resolve('default') == ref


def test_resolve_default_fallback_old_path(voices_dir):
    old_ref = voices_dir / 'reference.wav'
    old_ref.write_bytes(b'fake-wav')
    reg = VoiceRegistry(voices_dir)
    assert reg.resolve('default') == old_ref


def test_resolve_named_profile(voices_dir):
    profile = voices_dir / 'profiles' / 'narrator-warm.wav'
    profile.write_bytes(b'fake-wav')
    reg = VoiceRegistry(voices_dir)
    assert reg.resolve('narrator-warm') == profile


def test_resolve_unknown_raises(voices_dir):
    reg = VoiceRegistry(voices_dir)
    with pytest.raises(FileNotFoundError, match='Voice profile not found'):
        reg.resolve('ghost-voice')


def test_list_profiles(voices_dir):
    (voices_dir / 'profiles' / 'voice-a.wav').write_bytes(b'x')
    (voices_dir / 'profiles' / 'voice-b.wav').write_bytes(b'x')
    reg = VoiceRegistry(voices_dir)
    profiles = reg.list_profiles()
    assert set(profiles) == {'default', 'voice-a', 'voice-b'}


def _write_test_wav(path: str, data: np.ndarray, sr: int = 22050) -> None:
    pcm = (data * 32767).clip(-32768, 32767).astype(np.int16)
    with wave.open(path, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


class TestReferenceVoiceValidation:
    def test_clean_voice_passes(self, tmp_path):
        from app.domains.voices.validate import validate_reference_wav

        sr = 22050
        n_total = int(sr * 10.0)
        # 150 Hz sine burst for first 5s, then a very quiet floor for 5s.
        # Amplitude 1e-3 survives int16 quantization (rounds to ~32 LSBs,
        # giving RMS ≈ -70 dBFS after read-back) and drives the 5th-percentile
        # frame well below -55 dBFS — mimicking breath gaps in a voice recording.
        burst = np.sin(2 * np.pi * 150 * np.linspace(0, 5.0, int(sr * 5.0), endpoint=False)) * 0.25
        quiet = np.ones(n_total - len(burst), dtype=np.float32) * 1e-3
        data = np.concatenate([burst, quiet]).astype(np.float32)
        p = str(tmp_path / 'ref.wav')
        _write_test_wav(p, data, sr)
        errors = validate_reference_wav(p)
        assert errors == []

    def test_too_short_fails(self, tmp_path):
        from app.domains.voices.validate import validate_reference_wav

        sr = 22050
        data = (np.random.randn(sr * 3) * 0.1).astype(np.float32)  # 3 seconds
        p = str(tmp_path / 'short.wav')
        _write_test_wav(p, data, sr)
        errors = validate_reference_wav(p)
        assert any('too short' in e.lower() for e in errors)

    def test_too_long_fails(self, tmp_path):
        from app.domains.voices.validate import validate_reference_wav

        sr = 22050
        # 130 seconds > 120s limit
        data = (np.random.randn(sr * 130) * 0.1).astype(np.float32)
        p = str(tmp_path / 'long.wav')
        _write_test_wav(p, data, sr)
        errors = validate_reference_wav(p)
        assert any('too long' in e.lower() for e in errors)

    def test_noisy_floor_fails(self, tmp_path):
        from app.domains.voices.validate import validate_reference_wav

        sr = 22050
        # Pure noise at -26 dBFS — noise floor well above -55 dBFS threshold
        data = (np.random.randn(sr * 10) * 0.05).astype(np.float32)
        p = str(tmp_path / 'noisy.wav')
        _write_test_wav(p, data, sr)
        errors = validate_reference_wav(p)
        assert any('noise floor' in e.lower() for e in errors)

    def test_missing_file_returns_error(self):
        from app.domains.voices.validate import validate_reference_wav

        errors = validate_reference_wav('/nonexistent/path.wav')
        assert len(errors) > 0
