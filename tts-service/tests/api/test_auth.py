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

"""Tests for API key auth dependency."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch


def _make_app():
    from app.api.dependencies import require_api_key
    from fastapi import Depends

    app = FastAPI()

    @app.get('/protected')
    async def protected(_=Depends(require_api_key)):
        return {'ok': True}

    return app


def test_missing_auth_header_returns_401():
    with patch('app.config.TTS_API_KEY', 'secret-key'):
        with patch('app.api.dependencies.TTS_API_KEY', 'secret-key'):
            client = TestClient(_make_app())
            r = client.get('/protected')
    assert r.status_code == 401


def test_wrong_key_returns_403():
    with patch('app.config.TTS_API_KEY', 'secret-key'):
        with patch('app.api.dependencies.TTS_API_KEY', 'secret-key'):
            client = TestClient(_make_app())
            r = client.get('/protected', headers={'Authorization': 'Bearer wrong'})
    assert r.status_code == 403


def test_correct_key_passes():
    with patch('app.config.TTS_API_KEY', 'secret-key'):
        with patch('app.api.dependencies.TTS_API_KEY', 'secret-key'):
            client = TestClient(_make_app())
            r = client.get('/protected', headers={'Authorization': 'Bearer secret-key'})
    assert r.status_code == 200


def test_empty_api_key_returns_503():
    with patch('app.api.dependencies.TTS_API_KEY', ''):
        client = TestClient(_make_app())
        r = client.get('/protected', headers={'Authorization': 'Bearer anything'})
    assert r.status_code == 503
