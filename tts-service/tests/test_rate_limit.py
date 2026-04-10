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
