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

from typing import Optional
import logging

logger = logging.getLogger(__name__)

try:
    import redis.asyncio as redis
    from redis.asyncio import Redis as AsyncRedis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning('redis.asyncio not installed, caching disabled')


class RedisCache:
    """Redis-backed caching with TTL support (async)."""

    def __init__(self, redis_url: str = 'redis://localhost:6379', default_ttl: int = 3600):
        self.default_ttl = default_ttl
        self._client: Optional[AsyncRedis] = None
        self._redis_url = redis_url

        if REDIS_AVAILABLE:
            try:
                self._client = redis.from_url(redis_url)
            except Exception as e:
                logger.warning(f'Failed to connect to Redis: {e}')
                self._client = None

    async def get(self, key: str) -> Optional[str]:
        """Get value from cache."""
        if not self._client:
            return None
        try:
            return await self._client.get(key)
        except Exception as e:
            logger.warning(f'Cache get error: {e}')
            return None

    async def set(self, key: str, value: str, ttl: Optional[int] = None):
        """Set value in cache."""
        if not self._client:
            return
        try:
            await self._client.setex(key, ttl or self.default_ttl, value)
        except Exception as e:
            logger.warning(f'Cache set error: {e}')

    async def delete(self, key: str):
        """Delete key from cache."""
        if not self._client:
            return
        try:
            await self._client.delete(key)
        except Exception as e:
            logger.warning(f'Cache delete error: {e}')

    async def clear(self):
        """Clear all keys (for testing)."""
        if not self._client:
            return
        try:
            await self._client.flushdb()
        except Exception as e:
            logger.warning(f'Cache clear error: {e}')

    @property
    def is_available(self) -> bool:
        """Check if cache is available."""
        return self._client is not None


_cache: Optional[RedisCache] = None


def get_cache() -> RedisCache:
    """Get global cache instance."""
    global _cache
    if _cache is None:
        _cache = RedisCache()
    return _cache
