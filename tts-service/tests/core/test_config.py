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

"""Tests for configuration validation."""

import pytest


class TestConfigValues:
    """Test config values are loaded correctly."""

    def test_llm_timeout_default(self):
        """Test LLM_TIMEOUT default is 300 (raised from 120 — qwen3.5 models need headroom)."""
        from app.config import LLM_TIMEOUT

        assert LLM_TIMEOUT == 300.0

    def test_log_format_default(self):
        """Test LOG_FORMAT defaults to empty (auto-detect)."""
        from app.config import LOG_FORMAT

        assert LOG_FORMAT == ''

    def test_log_level_default(self):
        """Test LOG_LEVEL defaults to INFO."""
        from app.config import LOG_LEVEL

        assert LOG_LEVEL == 'INFO'

    def test_trusted_proxy_count_default(self):
        """Test TRUSTED_PROXY_COUNT defaults to 0."""
        from app.config import TRUSTED_PROXY_COUNT

        assert TRUSTED_PROXY_COUNT == 0


class TestValidateConfig:
    """Test config validation at startup."""

    def test_validate_config_exists(self):
        """Test that validate_config function exists."""
        from app.config import validate_config

        assert callable(validate_config)

    def test_validate_config_can_run(self):
        """Test that validate_config can run without error."""
        from app.config import validate_config, TTS_API_KEY

        # Only test if we have valid config (TTS_API_KEY might be empty in test env)
        if TTS_API_KEY:
            try:
                validate_config()
            except RuntimeError as e:
                # If it raises, it should be about missing config, not bugs
                assert 'Configuration errors' in str(e) or 'TTS_API_KEY' in str(e)
        else:
            # If no API key, should raise
            with pytest.raises(RuntimeError) as exc:
                validate_config()
            assert 'TTS_API_KEY' in str(exc.value)
