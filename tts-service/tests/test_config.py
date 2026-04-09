"""Tests for configuration validation."""

import os
import pytest
from unittest.mock import patch


class TestConfigValues:
    """Test config values are loaded correctly."""

    def test_llm_timeout_default(self):
        """Test LLM_TIMEOUT default is 120."""
        from app.config import LLM_TIMEOUT

        assert LLM_TIMEOUT == 120.0

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
        from app.config import validate_config, STORAGE_BACKEND, TTS_API_KEY

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
