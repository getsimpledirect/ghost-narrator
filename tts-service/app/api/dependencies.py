"""FastAPI dependencies for the TTS API."""

from __future__ import annotations

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import TTS_API_KEY

_bearer = HTTPBearer(auto_error=False, scheme_name='API Key')


async def require_api_key(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> None:
    """Validate Bearer token against TTS_API_KEY.

    Raises 503 if TTS_API_KEY is not configured (empty).
    Raises 401 if no Authorization header.
    Raises 403 if key is wrong.
    Open endpoints (health, metrics) should NOT include this dependency.
    """
    if not TTS_API_KEY:
        raise HTTPException(
            status_code=503,
            detail='Service not configured: TTS_API_KEY is not set',
        )
    if credentials is None:
        raise HTTPException(status_code=401, detail='Authorization header required')
    if credentials.credentials != TTS_API_KEY:
        raise HTTPException(status_code=403, detail='Invalid API key')
