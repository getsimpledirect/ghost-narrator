"""Tests for TTS HTTP routes - smoke tests."""

import pytest
from unittest.mock import patch


class TestRoutesExist:
    """Test that route modules can be imported."""

    def test_tts_routes_import(self):
        """Test that tts routes module imports."""
        from app.api.routes import tts

        assert tts is not None

    def test_voices_routes_import(self):
        """Test that voices routes module imports."""
        from app.api.routes import voices

        assert voices is not None


class TestDependencies:
    """Test that auth dependency exists."""

    def test_require_api_key_exists(self):
        """Test that require_api_key dependency exists."""
        from app.api.dependencies import require_api_key

        assert callable(require_api_key)


class TestRateLimiter:
    """Test rate limiter exists."""

    def test_rate_limit_middleware_exists(self):
        """Test that rate limit middleware exists."""
        from app.api.rate_limit_middleware.rate_limit import RateLimitMiddleware

        assert RateLimitMiddleware is not None
