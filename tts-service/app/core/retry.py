import asyncio
import logging
from functools import wraps
from typing import Any, Callable, Type, Tuple, Optional

logger = logging.getLogger(__name__)


def retry_with_backoff(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    """
    Decorator for retrying async functions with exponential backoff.

    Args:
        max_attempts: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay between retries
        exponential_base: Base for exponential backoff
        exceptions: Tuple of exception types to retry on

    Usage:
        @retry_with_backoff(max_attempts=3, base_delay=2.0)
        async def call_api():
            ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_attempts - 1:
                        # Last attempt failed
                        logger.error(
                            f'Retry exhausted for {func.__name__} after {max_attempts} attempts: {e}'
                        )
                        raise

                    # Calculate delay with exponential backoff
                    delay = min(base_delay * (exponential_base**attempt), max_delay)

                    logger.warning(
                        f'Attempt {attempt + 1}/{max_attempts} failed for {func.__name__}: {e}. '
                        f'Retrying in {delay:.2f}s...'
                    )

                    await asyncio.sleep(delay)

            # This should never be reached, but just in case
            if last_exception:
                raise last_exception

        return wrapper

    return decorator


async def retry_async(
    func: Callable,
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
) -> Any:
    """
    Utility function for retrying async operations.

    Args:
        func: Async function to retry
        max_attempts: Maximum number of attempts
        delay: Initial delay between retries
        backoff: Exponential backoff multiplier
        exceptions: Exceptions to catch and retry

    Returns:
        Result of the function call

    Raises:
        Last exception if all attempts fail
    """
    last_error = None

    for attempt in range(max_attempts):
        try:
            return await func()
        except exceptions as e:
            last_error = e

            if attempt < max_attempts - 1:
                wait_time = delay * (backoff**attempt)
                logger.warning(f'Attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s...')
                await asyncio.sleep(wait_time)

    raise last_error


# Combined retry with circuit breaker
async def retry_with_circuit_breaker(
    func: Callable,
    circuit_breaker,
    max_attempts: int = 3,
    base_delay: float = 1.0,
) -> Any:
    """
    Retry a function with circuit breaker protection.

    Args:
        func: Async function to execute
        circuit_breaker: CircuitBreaker instance
        max_attempts: Maximum retry attempts
        base_delay: Initial delay for backoff

    Returns:
        Result of the function call

    Raises:
        CircuitBreakerOpenError if circuit is open
        Exception if all attempts fail
    """
    from app.core.circuit_breaker import CircuitBreakerOpenError

    last_error = None

    for attempt in range(max_attempts):
        try:
            return await circuit_breaker.call(func)
        except CircuitBreakerOpenError:
            # Don't retry if circuit is open
            raise
        except Exception as e:
            last_error = e
            circuit_breaker.record_failure()

            if attempt < max_attempts - 1:
                delay = base_delay * (2**attempt)
                logger.warning(f'Attempt {attempt + 1} failed: {e}. Retrying in {delay}s...')
                await asyncio.sleep(delay)

    raise last_error
