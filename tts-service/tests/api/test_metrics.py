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
