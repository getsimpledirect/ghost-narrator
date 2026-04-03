from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from typing import Optional


SUPPORTED_VERSIONS = {"v1"}


class APIVersionMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, default_version: str = "v1"):
        super().__init__(app)
        self.default_version = default_version

    async def dispatch(self, request: Request, call_next):
        version = request.headers.get("Accept-Version", self.default_version)

        if version not in SUPPORTED_VERSIONS:
            return JSONResponse(
                status_code=406,
                content={
                    "error": "Unsupported API version",
                    "supported_versions": list(SUPPORTED_VERSIONS),
                    "requested_version": version,
                },
            )

        request.state.api_version = version
        response = await call_next(request)
        response.headers["API-Version"] = version
        return response
