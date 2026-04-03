"""
API versioning middleware.

NOTE: This is a placeholder implementation that currently supports only a
single API version ('v1'). It validates the Accept-Version header against
a hardcoded set of supported versions and rejects unsupported versions
with a 406 response.

Future work should implement a proper versioning strategy, such as:
- URL-based versioning (/v1/, /v2/, etc.)
- Header-based version negotiation with version-specific route resolution
- Deprecation headers and sunset policies for old versions
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


SUPPORTED_VERSIONS = {'v1'}


class APIVersionMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, default_version: str = 'v1'):
        super().__init__(app)
        self.default_version = default_version

    async def dispatch(self, request: Request, call_next):
        version = request.headers.get('Accept-Version', self.default_version)

        if version not in SUPPORTED_VERSIONS:
            return JSONResponse(
                status_code=406,
                content={
                    'error': 'Unsupported API version',
                    'supported_versions': list(SUPPORTED_VERSIONS),
                    'requested_version': version,
                },
            )

        request.state.api_version = version
        response = await call_next(request)
        response.headers['API-Version'] = version
        return response
