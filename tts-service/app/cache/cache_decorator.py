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

import json
import hashlib
import logging
from functools import wraps
from typing import Callable, Any
from app.cache.redis_cache import get_cache

logger = logging.getLogger(__name__)


def cached(key_template: str, ttl: int = 3600):
    """
    Decorator for caching function results.

    Args:
        key_template: Format string for cache key, e.g., "hardware:{gpu_id}"
        ttl: Time to live in seconds

    Returns:
        Decorated function with caching
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            cache = get_cache()

            try:
                key = key_template.format(*args, **kwargs)
            except (IndexError, KeyError):
                key = f'{func.__name__}:{hashlib.md5(str(args).encode()).hexdigest()}'

            cached_value = await cache.get(key)
            if cached_value:
                return json.loads(cached_value)

            result = await func(*args, **kwargs)
            try:
                await cache.set(key, json.dumps(result), ttl)
            except TypeError as exc:
                logger.warning(
                    f"Result for key '{key}' is not JSON-serializable, skipping cache: {exc}"
                )

            return result

        return wrapper

    return decorator
