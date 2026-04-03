"""
Rate limiting middleware for the TTS service API.

WARNING: This rate limiter uses an in-memory dictionary to track requests.
It is NOT distributed-safe — each worker process maintains its own independent
counter. In a multi-worker deployment (e.g., multiple gunicorn workers or
Kubernetes pods), the effective rate limit will be multiplied by the number
of workers.

For multi-worker deployments, replace this with a Redis-backed rate limiter
(e.g., using Redis INCR/EXPIRE or a dedicated library like slowapi with
Redis storage) to ensure consistent rate limiting across all workers.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from collections import defaultdict
from datetime import datetime, timedelta
import threading


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.window = timedelta(minutes=1)
        self._requests: dict = defaultdict(list)
        self._lock = threading.Lock()

    def _clean_old_requests(self, key: str):
        cutoff = datetime.now() - self.window
        self._requests[key] = [ts for ts in self._requests[key] if ts > cutoff]

    def _is_rate_limited(self, key: str) -> bool:
        with self._lock:
            self._clean_old_requests(key)
            return len(self._requests[key]) >= self.requests_per_minute

    def _record_request(self, key: str):
        with self._lock:
            self._requests[key].append(datetime.now())

    async def dispatch(self, request: Request, call_next):
        if request.url.path in ['/health', '/health/ready', '/metrics']:
            return await call_next(request)

        client_ip = request.headers.get('X-Forwarded-For', request.client.host)
        key = f'{client_ip}:{request.url.path}'

        if self._is_rate_limited(key):
            return JSONResponse(
                status_code=429,
                content={
                    'error': 'Rate limit exceeded',
                    'retry_after': 60,
                },
                headers={'Retry-After': '60'},
            )

        self._record_request(key)
        return await call_next(request)
