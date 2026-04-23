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

"""Tests for the DeepFilterNet enhancement wrapper.

The real model is too heavy to load in unit tests; these tests verify the
fallback / error-handling behaviour around it so the pipeline stays correct
whether or not enhancement is available at runtime.
"""

import wave

import numpy as np

from app.domains.enhancement import deepfilternet as dfn


def _write_wav(path: str, data: np.ndarray, sr: int = 22050) -> None:
    pcm = (data * 32767).clip(-32768, 32767).astype(np.int16)
    with wave.open(path, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def _reset_module_cache():
    """Reset the lazy-loaded module state between tests."""
    dfn._model = None
    dfn._df_state = None


def test_enhance_audio_missing_package_falls_back_to_copy(tmp_path, monkeypatch):
    """When df is unavailable, enhance_audio copies input to output unchanged."""
    _reset_module_cache()
    # Force the model loader to the unavailable sentinel.
    monkeypatch.setattr(dfn, '_get_model', lambda: None)

    src = tmp_path / 'in.wav'
    dst = tmp_path / 'out.wav'
    _write_wav(str(src), np.sin(np.linspace(0, 100, 22050)).astype(np.float32))

    result = dfn.enhance_audio(str(src), str(dst))

    assert result == str(dst)
    assert dst.exists()
    assert dst.stat().st_size == src.stat().st_size


def test_enhance_audio_in_place_when_unavailable(tmp_path, monkeypatch):
    """Unavailable enhancement with output_path=None leaves the input file intact."""
    _reset_module_cache()
    monkeypatch.setattr(dfn, '_get_model', lambda: None)

    src = tmp_path / 'in.wav'
    _write_wav(str(src), np.sin(np.linspace(0, 100, 22050)).astype(np.float32))
    orig_size = src.stat().st_size

    result = dfn.enhance_audio(str(src))

    assert result == str(src)
    assert src.stat().st_size == orig_size


def test_is_available_reflects_model_state(monkeypatch):
    _reset_module_cache()
    monkeypatch.setattr(dfn, '_get_model', lambda: None)
    assert dfn.is_available() is False

    sentinel = (object(), object())
    monkeypatch.setattr(dfn, '_get_model', lambda: sentinel)
    assert dfn.is_available() is True


def test_enhance_audio_fallback_when_enhance_raises(tmp_path, monkeypatch):
    """A raised exception inside the df.enhance call path copies input → output."""
    _reset_module_cache()
    # Pretend the model loaded successfully.
    fake_state = object()
    fake_model = object()
    monkeypatch.setattr(dfn, '_get_model', lambda: (fake_model, fake_state))

    # Inject a fake df.enhance module whose load_audio raises.
    import sys
    import types

    fake_df = types.ModuleType('df')
    fake_enh = types.ModuleType('df.enhance')

    def _raising_load(*_a, **_kw):
        raise RuntimeError('simulated load failure')

    fake_enh.load_audio = _raising_load
    fake_enh.enhance = lambda *_a, **_kw: None
    fake_enh.save_audio = lambda *_a, **_kw: None
    fake_enh.init_df = lambda: (fake_model, fake_state, None)
    fake_df.enhance = fake_enh
    monkeypatch.setitem(sys.modules, 'df', fake_df)
    monkeypatch.setitem(sys.modules, 'df.enhance', fake_enh)

    src = tmp_path / 'in.wav'
    dst = tmp_path / 'out.wav'
    _write_wav(str(src), np.sin(np.linspace(0, 100, 22050)).astype(np.float32))

    result = dfn.enhance_audio(str(src), str(dst))

    assert result == str(dst)
    # Fallback copies the input verbatim to dst.
    assert dst.exists()
    assert dst.stat().st_size == src.stat().st_size
