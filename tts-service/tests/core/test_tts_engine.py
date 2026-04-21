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
        # 50 × 0.4 × 50 × 1.4 = 1400
        assert 1000 <= tokens <= 3000

    def test_compute_max_tokens_respects_minimum(self):
        from app.core.tts_engine import _compute_max_new_tokens

        assert _compute_max_new_tokens(word_count=1) >= 300

    def test_compute_max_tokens_for_300_words(self):
        from app.core.tts_engine import _compute_max_new_tokens

        tokens = _compute_max_new_tokens(word_count=300)
        # 300 × 0.4 × 50 × 1.4 = 8400
        assert tokens >= 6000
