"""Tests for RedisCache async client usage."""



class TestRedisCacheImport:
    """Test that RedisCache uses async client."""

    def test_redis_cache_uses_async(self):
        """Verify RedisCache uses async redis client."""
        import inspect

        # Check that the module uses redis.asyncio
        import app.cache.redis_cache as cache_module

        source = inspect.getsource(cache_module)

        # Should use redis.asyncio, not sync redis
        assert 'redis.asyncio' in source or 'AsyncRedis' in source

    def test_cache_class_exists(self):
        """Test that RedisCache class exists."""
        from app.cache.redis_cache import RedisCache

        assert RedisCache is not None

    def test_cache_has_async_methods(self):
        """Test that cache has async get/set methods."""
        from app.cache.redis_cache import RedisCache

        # RedisCache should have get and set methods
        assert hasattr(RedisCache, 'get')
        assert hasattr(RedisCache, 'set')
        assert hasattr(RedisCache, 'delete')

    def test_get_cache_function_exists(self):
        """Test that get_cache function exists."""
        from app.cache.redis_cache import get_cache

        assert callable(get_cache)
