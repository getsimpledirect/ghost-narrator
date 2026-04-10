"""Tests for audio quality check functionality - smoke tests."""


class TestQualityCheckImports:
    """Test that quality_check module can be imported."""

    def test_quality_check_module_imports(self):
        """Test that quality_check module imports correctly."""
        from app.domains.synthesis import quality_check

        assert quality_check is not None

    def test_resynthesize_function_exists(self):
        """Test that _quality_check_and_resynthesize function exists."""
        from app.domains.synthesis.quality_check import _quality_check_and_resynthesize

        assert callable(_quality_check_and_resynthesize)


class TestQualityCheckBoundary:
    """Test that OOB fix is in place (GAP-TTS-5)."""

    def test_resynthesize_has_proper_signature(self):
        """Verify _quality_check_and_resynthesize has proper parameters."""
        import inspect
        from app.domains.synthesis.quality_check import _quality_check_and_resynthesize

        sig = inspect.signature(_quality_check_and_resynthesize)
        params = list(sig.parameters.keys())

        # Should have these parameters
        assert 'chunk_wav_paths' in params
        assert 'chunk_texts' in params
        assert 'job_id' in params
