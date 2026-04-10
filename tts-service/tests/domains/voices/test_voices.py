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

import pytest
import sys
import types
from unittest.mock import MagicMock

# Mock qwen_tts before any app imports
_mock = types.ModuleType('qwen_tts')
_mock.Qwen3TTSModel = MagicMock
sys.modules.setdefault('qwen_tts', _mock)

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
