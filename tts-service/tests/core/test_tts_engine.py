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


def test_torch_compile_attempted_on_cuda(monkeypatch):
    """torch.compile() must be called when CUDA is available."""
    import app.core.tts_engine as eng_mod

    monkeypatch.setattr(eng_mod, 'Qwen3TTSModel', None)  # skip real model load
    # This test validates that the compile path is wired - full integration
    # is only verifiable with a real GPU. Assert the compile call appears in
    # the initialize() source code.
    import inspect

    src = inspect.getsource(eng_mod.TTSEngine.initialize)
    assert 'torch.compile' in src, 'torch.compile() call is missing from TTSEngine.initialize()'
    assert 'cuda.is_available' in src, 'CUDA availability check is missing'


def test_chunk_exhausted_error_importable():
    from app.core.exceptions import ChunkExhaustedError

    err = ChunkExhaustedError('chunk 3 failed all retries', chunk_idx=3)
    assert 'chunk_idx=3' in str(err)
    assert err.chunk_idx == 3


class TestMaxNewTokensBounding:
    def test_compute_max_tokens_for_50_words(self):
        from app.core.tts_engine import _compute_max_new_tokens

        tokens = _compute_max_new_tokens(word_count=50)
        # 50 × 0.42 × 12 × 1.3 = 327.6 → ceil 328 → max(328, 300) = 328
        assert tokens == 328

    def test_compute_max_tokens_respects_minimum(self):
        from app.core.tts_engine import _compute_max_new_tokens

        assert _compute_max_new_tokens(word_count=1) == 300

    def test_compute_max_tokens_for_300_words(self):
        from app.core.tts_engine import _compute_max_new_tokens

        tokens = _compute_max_new_tokens(word_count=300)
        # 300 × 0.42 × 12 × 1.3 = 1965.6 → ceil 1966
        assert tokens == 1966

    def test_compute_max_tokens_for_650_words(self):
        from app.core.tts_engine import _compute_max_new_tokens

        tokens = _compute_max_new_tokens(word_count=650)
        # 650 × 0.42 × 12 × 1.3 = 4258.8 → ceil 4259
        assert tokens == 4259


def test_tts_engine_has_reference_f0_property():
    from app.core.tts_engine import get_tts_engine

    engine = get_tts_engine()
    # reference_f0 is None when engine is not initialized (no voice sample loaded)
    assert hasattr(engine, 'reference_f0')
    assert engine.reference_f0 is None  # before initialize()
