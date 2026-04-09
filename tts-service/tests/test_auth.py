"""Tests for API key auth dependency."""
import pytest
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
