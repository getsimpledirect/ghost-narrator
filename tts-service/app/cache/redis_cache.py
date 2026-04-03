from typing import Optional
import logging

logger = logging.getLogger(__name__)

try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning('redis not installed, caching disabled')


class RedisCache:
    """Redis-backed caching with TTL support."""

    def __init__(self, redis_url: str = 'redis://localhost:6379', default_ttl: int = 3600):
        self.default_ttl = default_ttl
        self._client = None
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
