"""Tests for audio mastering functionality - smoke tests."""


class TestMasteringImports:
    """Test that mastering modules can be imported."""

    def test_quality_module_imports(self):
        """Test that quality module imports correctly."""
        from app.domains.synthesis import quality

        assert hasattr(quality, 'apply_final_mastering')

    def test_normalize_module_imports(self):
        """Test that normalize module imports correctly."""
        from app.domains.synthesis import normalize

        assert hasattr(normalize, 'normalize_audio')


class TestMasteringFunctions:
    """Test mastering function signatures."""

    def test_apply_final_mastering_exists(self):
        """Test that apply_final_mastering function exists."""
        from app.domains.synthesis.quality import apply_final_mastering

        assert callable(apply_final_mastering)

    def test_normalize_audio_exists(self):
        """Test that normalize_audio function exists."""
        from app.domains.synthesis.normalize import normalize_audio

        assert callable(normalize_audio)
