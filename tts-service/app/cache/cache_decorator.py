import json
import hashlib
from functools import wraps
from typing import Callable, Any
from app.cache.redis_cache import get_cache


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
            await cache.set(key, json.dumps(result), ttl)

            return result

        return wrapper

    return decorator
