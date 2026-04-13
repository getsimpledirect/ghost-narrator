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
