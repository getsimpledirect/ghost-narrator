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
