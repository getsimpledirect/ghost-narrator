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

"""Tests for API middleware - smoke tests."""


class TestMiddlewareExists:
    """Test that middleware modules exist."""

    def test_rate_limit_middleware_exists(self):
        """Test that rate limit middleware exists."""
        from app.api.rate_limit_middleware.rate_limit import RateLimitMiddleware

        assert RateLimitMiddleware is not None

    def test_trusted_proxy_config_exists(self):
        """Test that trusted proxy config can be loaded."""
        from app.config import TRUSTED_PROXY_COUNT

        assert TRUSTED_PROXY_COUNT is not None
        assert isinstance(TRUSTED_PROXY_COUNT, int)


class TestRateLimiterFunctionality:
    """Test rate limiter can be instantiated."""

    def test_rate_limiter_init(self):
        """Test that rate limiter can be initialized."""
        from fastapi import FastAPI
        from app.api.rate_limit_middleware.rate_limit import RateLimitMiddleware

        app = FastAPI()
        # Create with default settings
        middleware = RateLimitMiddleware(app, requests_per_minute=60)

        assert middleware is not None
        assert hasattr(middleware, 'requests_per_minute')
