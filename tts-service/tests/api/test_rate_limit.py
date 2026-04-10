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

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from app.api.rate_limit_middleware.rate_limit import RateLimitMiddleware


class TestRateLimitMiddleware:
    @pytest.fixture
    def app(self):
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, requests_per_minute=10)
        return app

    def test_allows_requests_under_limit(self, app):
        @app.get('/test')
        def test_endpoint():
            return {'status': 'ok'}

        client = TestClient(app)
        for _ in range(10):
            response = client.get('/test')
            assert response.status_code == 200

    def test_blocks_requests_over_limit(self, app):
        @app.get('/test')
        def test_endpoint():
            return {'status': 'ok'}

        client = TestClient(app)
        # First 10 should succeed
        for _ in range(10):
            client.get('/test')
        # 11th should be rate limited
        response = client.get('/test')
        assert response.status_code == 429
