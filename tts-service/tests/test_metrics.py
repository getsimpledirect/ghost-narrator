import pytest
from fastapi.testclient import TestClient
from app.main import app


class TestMetricsEndpoint:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_metrics_endpoint_exists(self, client):
        response = client.get('/metrics')
        assert response.status_code == 200

    def test_metrics_contains_job_counter(self, client):
        response = client.get('/metrics')
        content = response.text
        assert 'tts_jobs_total' in content

    def test_metrics_contains_synthesis_duration(self, client):
        response = client.get('/metrics')
        content = response.text
        assert 'tts_synthesis_duration_seconds' in content
