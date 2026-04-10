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
