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

from contextlib import asynccontextmanager
import asyncio
from typing import Any, Callable, TypeVar, Optional
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')


class ConnectionPool:
    """
    Generic async connection pool with configurable max size.

    Usage:
        pool = ConnectionPool(factory=create_connection, max_size=10)

        async with pool.acquire() as conn:
            await conn.do_something()
    """

    def __init__(
        self,
        factory: Callable[..., Any],
        max_size: int = 10,
        min_size: int = 1,
        health_check: Optional[Callable[[Any], bool]] = None,
    ):
        """
        Initialize connection pool.

        Args:
            factory: Async function to create new connections
            max_size: Maximum number of connections in pool
            min_size: Minimum number of connections to keep alive
            health_check: Optional callable to verify connection health before returning
        """
        self.factory = factory
        self.max_size = max_size
        self.min_size = min_size
        self._health_check = health_check
        self._pool: asyncio.Queue = asyncio.Queue(max_size)
        self._created = 0
        self._lock = asyncio.Lock()
        self._init_task: Optional[asyncio.Task] = None

    async def _initialize(self):
        """Initialize minimum number of connections."""
        async with self._lock:
            for _ in range(self.min_size):
                if self._created >= self.max_size:
                    break
                try:
                    conn = await self.factory()
                    self._pool.put_nowait(conn)
                    self._created += 1
                except Exception as e:
                    logger.warning(f'Failed to create initial connection: {e}')

    async def _ensure_initialized(self):
        """Lazy initialization."""
        async with self._lock:
            if self._init_task is None:
                self._init_task = asyncio.create_task(self._initialize())

    @asynccontextmanager
    async def acquire(self):
        """Acquire a connection from the pool."""
        await self._ensure_initialized()

        conn = None
        try:
            # Try to get from pool without waiting first
            try:
                conn = self._pool.get_nowait()
            except asyncio.QueueEmpty:
                # Pool empty - create new if under max
                async with self._lock:
                    if self._created < self.max_size:
                        conn = await self.factory()
                        self._created += 1
                    else:
                        # Wait for available connection
                        conn = await self._pool.get()

            # Verify connection health if a health_check is configured
            if self._health_check is not None and not self._health_check(conn):
                await self._close_connection(conn)
                async with self._lock:
                    self._created -= 1
                conn = None
                # Retry: create a new connection
                async with self._lock:
                    if self._created < self.max_size:
                        conn = await self.factory()
                        self._created += 1
                    else:
                        conn = await self._pool.get()

            try:
                yield conn
            finally:
                # Return connection to pool
                if conn is not None:
                    try:
                        self._pool.put_nowait(conn)
                    except asyncio.QueueFull:
                        # Pool full, close the connection
                        await self._close_connection(conn)
                        async with self._lock:
                            self._created -= 1
        except Exception as e:
            # Connection failed - remove from pool
            logger.error(f'Connection execution failed: {e}')
            if conn is not None:
                try:
                    await self._close_connection(conn)
                except Exception as close_e:
                    logger.warning(f'Failed to close connection: {close_e}')
                async with self._lock:
                    self._created -= 1
            raise

    async def _close_connection(self, conn):
        """Close a connection."""
        if hasattr(conn, 'close'):
            if asyncio.iscoroutinefunction(conn.close):
                await conn.close()
            else:
                conn.close()
        elif hasattr(conn, 'aclose'):
            if asyncio.iscoroutinefunction(conn.aclose):
                await conn.aclose()

    async def close_all(self):
        """Close all connections in the pool."""
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                await self._close_connection(conn)
            except asyncio.QueueEmpty:
                break
        async with self._lock:
            self._created = 0

    @property
    def available(self) -> int:
        """Number of available connections."""
        return self._pool.qsize()

    @property
    def in_use(self) -> int:
        """Number of connections in use."""
        return self._created - self._pool.qsize()


# Helper function for HTTP client pooling
def create_http_pool(max_connections: int = 10) -> ConnectionPool:
    """Create a connection pool for HTTP clients."""
    import aiohttp

    return ConnectionPool(
        factory=lambda: aiohttp.ClientSession(),
        max_size=max_connections,
        min_size=1,
    )
