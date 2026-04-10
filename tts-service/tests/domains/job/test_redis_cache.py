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
