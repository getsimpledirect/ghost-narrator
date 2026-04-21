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
        assert 300 <= tokens <= 500

    def test_compute_max_tokens_respects_minimum(self):
        from app.core.tts_engine import _compute_max_new_tokens

        assert _compute_max_new_tokens(word_count=1) >= 300

    def test_compute_max_tokens_for_300_words(self):
        from app.core.tts_engine import _compute_max_new_tokens

        tokens = _compute_max_new_tokens(word_count=300)
        # 300 × 0.42 × 12 × 1.3 = 1965.6 → 1966
        assert 1700 <= tokens <= 2300

    def test_compute_max_tokens_for_650_words(self):
        from app.core.tts_engine import _compute_max_new_tokens

        tokens = _compute_max_new_tokens(word_count=650)
        # 650 × 0.42 × 12 × 1.3 = 4258.8 → 4259
        assert 3800 <= tokens <= 4800


def test_tts_engine_has_reference_f0_property():
    from app.core.tts_engine import get_tts_engine

    engine = get_tts_engine()
    # reference_f0 is None when engine is not initialized (no voice sample loaded)
    assert hasattr(engine, 'reference_f0')
    assert engine.reference_f0 is None  # before initialize()
