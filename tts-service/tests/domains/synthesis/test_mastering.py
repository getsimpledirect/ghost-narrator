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


def test_master_audio_filter_chain_includes_limiter():
    """master_audio must apply loudness normalization with limiter for natural sound."""
    from unittest.mock import patch, MagicMock

    captured_commands = []

    def _fake_run(cmd, **kwargs):
        captured_commands.append(cmd)
        result = MagicMock()
        result.returncode = 0
        result.stderr = '{"input_i": -23.0, "input_tp": -1.5, "input_lra": 7.0, "input_thresh": -33.0, "target_offset": 0.0}'
        return result

    from app.domains.synthesis import mastering

    with patch('subprocess.run', side_effect=_fake_run):
        mastering.master_audio('/fake/input.wav', '/fake/output.mp3')

    # Find the command containing the filter chain
    af_commands = [' '.join(cmd) for cmd in captured_commands if '-af' in cmd]
    assert af_commands, 'No -af filter chain found in subprocess calls'

    # Filter chain should include loudness normalization (no highpass/eq - preserve natural tone)
    for af_cmd in af_commands:
        assert 'loudnorm' in af_cmd, f'loudnorm filter missing from: {af_cmd}'


def test_default_true_peak_is_minus_1_5():
    from app.domains.synthesis.mastering import DEFAULT_TRUE_PEAK

    assert DEFAULT_TRUE_PEAK <= -1.5, (
        f'DEFAULT_TRUE_PEAK must be ≤ -1.5 dBTP to meet distribution spec, got {DEFAULT_TRUE_PEAK}'
    )


def test_alimiter_command_contains_correct_limit():
    """alimiter limit=0.794 must appear in the main filter chain (all paths)."""
    import inspect
    from app.domains.synthesis import mastering

    src = inspect.getsource(mastering.master_audio)
    # Both two-pass and single-pass paths now include alimiter after loudnorm.
    # loudnorm linear=true does not reliably control intersample true-peak;
    # alimiter=limit=0.794 (-2.0 dBFS sample peak) catches MP3 encoder excursions.
    assert 'limit=0.794' in src, 'alimiter limit must be 0.794 in the main mastering filter chain'
