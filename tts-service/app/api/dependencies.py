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
