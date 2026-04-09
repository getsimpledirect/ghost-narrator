"""Tests for audio concatenation - smoke tests."""

import pytest


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
