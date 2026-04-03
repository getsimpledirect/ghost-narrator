import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from app.api.middleware import APIVersionMiddleware


class TestAPIVersionMiddleware:
    @pytest.fixture
    def app(self):
        app = FastAPI()
        app.add_middleware(APIVersionMiddleware, default_version="v1")
        return app

    def test_default_version_without_header(self, app):
        @app.get("/test")
        def test_endpoint():
            return {"version": "v1"}

        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200

    def test_explicit_version_v1(self, app):
        @app.get("/test")
        def test_endpoint():
            return {"version": "v1"}

        client = TestClient(app, headers={"Accept-Version": "v1"})
        response = client.get("/test")
        assert response.status_code == 200

    def test_version_rejected_for_unsupported(self, app):
        @app.get("/test")
        def test_endpoint():
            return {"version": "v1"}

        client = TestClient(app, headers={"Accept-Version": "v99"})
        response = client.get("/test")
        assert response.status_code == 406
