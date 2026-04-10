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

"""Tests for TTS HTTP routes - smoke tests."""


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
