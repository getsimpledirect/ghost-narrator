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

"""
Job storage domain.

Provides a unified interface for job storage with Redis as primary
backend and in-memory fallback for development/resilience.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from typing import Any, Optional

import redis.asyncio as redis

from app.config import REDIS_JOB_TTL, REDIS_URL
from app.domains.job.state import MAX_RESUME_ATTEMPTS, TERMINAL_STATES

logger = logging.getLogger(__name__)


class JobStore:
    """
    Abstraction layer for job storage with Redis primary and in-memory fallback.

    This class provides a unified interface for storing, retrieving, and managing
    TTS job data. It attempts to use Redis as the primary storage backend, with
    automatic fallback to in-memory storage if Redis is unavailable.

    Attributes:
        use_redis: Whether Redis is currently being used.
        redis_client: The async Redis client (if connected).
        memory_store: In-memory fallback storage.
        lock: Async lock for thread-safe memory operations.
    """

    def __init__(self) -> None:
        """Initialize JobStore with default settings."""
        self.use_redis: bool = False
        self.redis_client: Optional[redis.Redis] = None
        self.memory_store: dict[str, dict[str, Any]] = {}
        self.lock: asyncio.Lock = asyncio.Lock()
        self._initialized: bool = False
        self._max_memory_jobs: int = 1000
        self._memory_job_ttl: int = 3600

    async def initialize(self, redis_url: Optional[str] = None) -> None:
        """
        Initialize Redis connection with fallback to in-memory.

        Args:
            redis_url: Optional Redis URL. Defaults to REDIS_URL from config.
        """
        if self._initialized:
            logger.debug('JobStore already initialized')
            return

        url = redis_url or REDIS_URL

        try:
            self.redis_client = redis.from_url(
                url,
                encoding='utf-8',
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            await self.redis_client.ping()
            self.use_redis = True
            self._initialized = True
            logger.info('Redis connected successfully - using persistent job storage')
        except Exception as exc:
            logger.warning(
                f'Redis connection failed: {exc}. '
                'Using in-memory storage (jobs will be lost on restart)'
            )
            self.use_redis = False
            self.redis_client = None
            self._initialized = True

    def _make_serializable(self, job_data: dict[str, Any]) -> dict[str, Any]:
        """
        Convert job data to JSON-serializable format.

        Args:
            job_data: The job data dictionary to convert.

        Returns:
            A dictionary with all values converted to JSON-serializable types.
        """
        serializable_data: dict[str, Any] = {}

        for key, value in job_data.items():
            if isinstance(value, (str, int, float, bool, type(None))):
                serializable_data[key] = value
            elif isinstance(value, (list, dict)):
                serializable_data[key] = value
            else:
                serializable_data[key] = str(value)

        return serializable_data

    def _cleanup_expired_memory_jobs(self) -> None:
        """Remove expired entries from the memory store."""
        now = time.time()
        expired_keys = [
            key
            for key, entry in self.memory_store.items()
            if isinstance(entry, dict) and 'expires_at' in entry and entry['expires_at'] < now
        ]
        for key in expired_keys:
            del self.memory_store[key]
        if expired_keys:
            logger.debug(f'Cleaned up {len(expired_keys)} expired memory store entries')

    async def set(self, job_id: str, job_data: dict[str, Any]) -> None:
        """
        Store job data with TTL.

        Args:
            job_id: The unique job identifier.
            job_data: Dictionary containing job data.

        Raises:
            ValueError: If job_id is empty or job_data is not a dict.
        """
        if not job_id:
            raise ValueError('job_id cannot be empty')
        if not isinstance(job_data, dict):
            raise ValueError(f'job_data must be a dict, got {type(job_data)}')

        serializable_data = self._make_serializable(job_data)

        if self.use_redis and self.redis_client:
            try:
                await self.redis_client.setex(
                    f'job:{job_id}',
                    REDIS_JOB_TTL,
                    json.dumps(serializable_data, default=str),
                )
                return
            except Exception as exc:
                logger.error(
                    f'Redis set failed for job {job_id}: {exc}. '
                    'Using in-memory fallback for this operation (Redis connection preserved)'
                )
                # Do NOT permanently disable Redis — this may be a transient error.
                # Fall through to memory store for this write only.

        async with self.lock:
            self.memory_store[job_id] = {
                'data': serializable_data,
                'expires_at': time.time() + self._memory_job_ttl,
            }

    async def get(self, job_id: str) -> Optional[dict[str, Any]]:
        """
        Retrieve job data.

        Args:
            job_id: The unique job identifier.

        Returns:
            Job data dictionary if found, None otherwise.
        """
        if self.use_redis and self.redis_client:
            try:
                data = await self.redis_client.get(f'job:{job_id}')
                if data:
                    return json.loads(data)
                return None
            except Exception as exc:
                logger.error(f'Redis get failed for job {job_id}: {exc}. Checking memory')
                async with self.lock:
                    self._cleanup_expired_memory_jobs()
                    entry = self.memory_store.get(job_id)
                    if entry and isinstance(entry, dict) and 'data' in entry:
                        return entry['data']
                    return None

        async with self.lock:
            self._cleanup_expired_memory_jobs()
            entry = self.memory_store.get(job_id)
            if entry and isinstance(entry, dict) and 'data' in entry:
                return entry['data']
            return None

    async def exists(self, job_id: str) -> bool:
        """
        Check if job exists.

        Args:
            job_id: The unique job identifier.

        Returns:
            True if job exists, False otherwise.
        """
        if self.use_redis and self.redis_client:
            try:
                exists = await self.redis_client.exists(f'job:{job_id}')
                return bool(exists)
            except Exception as exc:
                logger.error(f'Redis exists failed for job {job_id}: {exc}. Checking memory')
                async with self.lock:
                    self._cleanup_expired_memory_jobs()
                    return job_id in self.memory_store

        async with self.lock:
            self._cleanup_expired_memory_jobs()
            return job_id in self.memory_store

    async def create_if_not_exists(self, job_id: str, job_data: dict[str, Any]) -> bool:
        """
        Atomically create a job if it does not already exist.

        Args:
            job_id: The unique job identifier.
            job_data: Dictionary containing initial job data.

        Returns:
            True if created, False if it already existed.
        """
        if not job_id:
            raise ValueError('job_id cannot be empty')

        serializable_data = self._make_serializable(job_data)

        if self.use_redis and self.redis_client:
            try:
                # Use SET NX EX for atomic create-with-TTL (avoids setnx+expire race)
                created = await self.redis_client.set(
                    f'job:{job_id}',
                    json.dumps(serializable_data, default=str),
                    nx=True,
                    ex=REDIS_JOB_TTL,
                )
                return created is not None
            except Exception as exc:
                logger.error(
                    f'Redis create_if_not_exists failed: {exc}. '
                    'Using in-memory fallback for this operation (Redis connection preserved)'
                )
                # Do NOT permanently disable Redis — this may be a transient error.

        async with self.lock:
            if job_id in self.memory_store:
                return False
            # Evict oldest entry if at capacity
            if len(self.memory_store) >= self._max_memory_jobs:
                oldest = next(iter(self.memory_store))
                del self.memory_store[oldest]
                logger.warning(
                    f'Memory store at capacity ({self._max_memory_jobs}), '
                    f'evicted oldest job: {oldest}'
                )
            self.memory_store[job_id] = {
                'data': serializable_data,
                'expires_at': time.time() + self._memory_job_ttl,
            }
            return True

    async def update(self, job_id: str, updates: dict[str, Any]) -> None:
        """
        Update job data atomically.

        Args:
            job_id: The unique job identifier.
            updates: Dictionary of fields to update.
        """
        if not updates:
            return

        serializable_updates = self._make_serializable(updates)

        if self.use_redis and self.redis_client:
            try:
                # Redis doesn't have a direct JSON merge command in standard Redis (without RedisJSON module)
                # But we are storing the whole dict as a JSON string.
                # To make it atomic without RedisJSON, we should ideally use a Lua script.
                lua_script = """
                local data = redis.call('GET', KEYS[1])
                if data then
                    local ok, decoded = pcall(cjson.decode, data)
                    if not ok then
                        return -1
                    end
                    local updates = cjson.decode(ARGV[1])
                    for k, v in pairs(updates) do
                        decoded[k] = v
                    end
                    redis.call('SET', KEYS[1], cjson.encode(decoded))
                    redis.call('EXPIRE', KEYS[1], ARGV[2])
                    return 1
                end
                return 0
                """

                result = await self.redis_client.eval(
                    lua_script,
                    1,
                    f'job:{job_id}',
                    json.dumps(serializable_updates, default=str),
                    REDIS_JOB_TTL,
                )

                if result == 1:
                    return
                elif result == -1:
                    logger.warning(
                        f'Redis Lua script failed to decode JSON for job {job_id}, '
                        'falling back to memory store'
                    )
                else:
                    logger.warning(f'Cannot update non-existent job in Redis: {job_id}')
                    return
            except Exception as exc:
                logger.error(
                    f'Redis update failed: {exc}. Falling back to non-atomic memory update'
                )
                # Fallback to in-memory

        async with self.lock:
            entry = self.memory_store.get(job_id)
            if entry is None:
                logger.warning(f'Cannot update non-existent job in memory: {job_id}')
                return
            job_data = entry if isinstance(entry, dict) and 'data' in entry else entry
            if isinstance(entry, dict) and 'data' in entry:
                job_data = entry['data']
            job_data.update(serializable_updates)
            self.memory_store[job_id] = {
                'data': job_data,
                'expires_at': time.time() + self._memory_job_ttl,
            }

    async def delete(self, job_id: str) -> bool:
        """
        Delete a job from the store.

        Args:
            job_id: The unique job identifier.

        Returns:
            True if job was deleted, False if it didn't exist.
        """
        if self.use_redis and self.redis_client:
            try:
                result = await self.redis_client.delete(f'job:{job_id}')
                return bool(result)
            except Exception as exc:
                logger.error(f'Redis delete failed for job {job_id}: {exc}. Deleting from memory')
                async with self.lock:
                    return self.memory_store.pop(job_id, None) is not None

        async with self.lock:
            return self.memory_store.pop(job_id, None) is not None

    async def list_all(self) -> dict[str, dict[str, Any]]:
        """
        List all jobs.

        Returns:
            Dictionary mapping job_id to job data.
        """
        if self.use_redis and self.redis_client:
            try:
                jobs: dict[str, dict[str, Any]] = {}
                cursor = 0
                while True:
                    cursor, keys = await self.redis_client.scan(cursor, match='job:*', count=100)
                    if keys:
                        values = await self.redis_client.mget(*keys)
                        for key, data in zip(keys, values):
                            if data:
                                job_id = key.replace('job:', '', 1)
                                jobs[job_id] = json.loads(data)
                    if cursor == 0:
                        break
                return jobs
            except Exception as exc:
                logger.error(f'Redis list failed: {exc}. Returning memory store')
                async with self.lock:
                    self._cleanup_expired_memory_jobs()
                    return {
                        k: v['data'] if isinstance(v, dict) and 'data' in v else v
                        for k, v in self.memory_store.items()
                    }

        async with self.lock:
            self._cleanup_expired_memory_jobs()
            return {
                k: v['data'] if isinstance(v, dict) and 'data' in v else v
                for k, v in self.memory_store.items()
            }

    async def count(self) -> int:
        """
        Get the total number of jobs.

        Returns:
            Number of jobs in the store.
        """
        if self.use_redis and self.redis_client:
            try:
                count = 0
                cursor = 0
                while True:
                    cursor, keys = await self.redis_client.scan(cursor, match='job:*', count=100)
                    count += len(keys)
                    if cursor == 0:
                        break
                return count
            except Exception as exc:
                logger.error(f'Redis count failed: {exc}. Counting memory store')
                async with self.lock:
                    self._cleanup_expired_memory_jobs()
                    return len(self.memory_store)

        async with self.lock:
            self._cleanup_expired_memory_jobs()
            return len(self.memory_store)

    async def close(self) -> None:
        """Close Redis connection and cleanup resources."""
        if self.redis_client:
            try:
                await self.redis_client.close()
                logger.info('Redis connection closed')
            except Exception as exc:
                logger.error(f'Error closing Redis connection: {exc}')
            finally:
                self.redis_client = None
                self.use_redis = False

        self._initialized = False

    @property
    def storage_type(self) -> str:
        """Get the current storage backend type."""
        return 'redis' if self.use_redis else 'memory'


# Global singleton instance
_job_store: Optional[JobStore] = None


def get_job_store() -> JobStore:
    """
    Get the global JobStore singleton instance.

    Returns:
        The JobStore singleton instance.
    """
    global _job_store
    if _job_store is None:
        _job_store = JobStore()
    return _job_store


async def initialize_job_store(redis_url: Optional[str] = None) -> JobStore:
    """
    Initialize the global JobStore instance.

    Args:
        redis_url: Optional Redis URL.

    Returns:
        The initialized JobStore instance.
    """
    store = get_job_store()
    await store.initialize(redis_url)
    return store


async def _mark_orphaned(
    job_store: JobStore,
    job_id: str,
    original_status: str,
    reason: str,
) -> None:
    """Mark a single orphan as failed with diagnostic context.

    Per-record errors are caught and logged so one bad record doesn't
    block the rest of the reaper from running.
    """
    try:
        existing = await job_store.get(job_id) or {}
        started_at = existing.get('started_at') or existing.get('created_at') or time.time()
        await job_store.update(
            job_id,
            {
                'status': 'failed',
                'error': reason,
                'completed_at': time.time(),
                'duration_seconds': time.time() - started_at,
            },
        )
    except Exception as exc:
        logger.warning('Failed to mark orphan %s (was %s): %s', job_id, original_status, exc)


async def _scheduled_resume(
    job_id: str,
    text: str,
    gcs_object_path: str,
    site_slug: str,
    ready_event: asyncio.Event,
) -> None:
    """Wait for the TTS engine to be ready, then run the resumed job.

    run_tts_job() has its own engine-ready wait with a 60 s timeout. On a
    cold start where the model load takes ~60-65 s, mass-resuming N jobs
    would have all N independently hitting the timeout simultaneously.
    Awaiting ready_event here lets all resumed jobs proceed past the
    internal wait immediately once the engine signals ready.
    """
    # Local import to avoid circular: store -> tts_job -> ... -> store.
    from app.domains.job.runner import run_tts_job

    await ready_event.wait()
    await run_tts_job(job_id, text, gcs_object_path, site_slug)


async def reap_orphaned_jobs(job_store: JobStore) -> dict[str, int]:
    """At startup, resume queued jobs and fail mid-pipeline orphans.

    Single-container deployment assumption: this process is the sole worker.
    Any non-terminal job at startup is an orphan from a previous process
    that died before the job reached a terminal state. The work-in-progress
    state of a `processing` or `paused` job (segment WAVs, decoded audio
    buffers, in-memory async tasks) lived only in the previous process's
    memory and cannot be resumed; those must be marked failed. A `queued`
    job still has its inputs durable in Redis (after the schema change in
    /tts/generate) so it can be re-scheduled cleanly.

    Safe by construction: this runs inside FastAPI's lifespan startup,
    which completes before any request handler is registered — no new
    jobs can be created during reaper execution.

    Returns: counts by action, e.g.
        {"resumed": 2, "failed_processing": 1, "failed_paused": 0,
         "failed_legacy_queued": 0, "failed_resume_budget_exceeded": 0}
    """
    counts: defaultdict[str, int] = defaultdict(int)

    try:
        jobs = await job_store.list_all()
    except Exception as exc:
        logger.warning('Reaper could not list jobs (continuing startup): %s', exc)
        return {}

    if not jobs:
        return {}

    # Defer engine-ready event lookup until we know we have at least one
    # queued job to resume. Avoids touching the engine module unless needed.
    ready_event: Optional[asyncio.Event] = None

    for job_id, job_data in jobs.items():
        status = job_data.get('status')
        if not status or status in TERMINAL_STATES:
            continue

        if status == 'queued':
            text = job_data.get('text')
            gcs_path = job_data.get('gcs_object_path')
            site_slug = job_data.get('site_slug', 'site')
            resume_count = int(job_data.get('resume_count', 0) or 0)

            if not text or not gcs_path:
                # Pre-durable-queue record (created before this commit) has
                # no recoverable inputs in Redis. Mark failed so the
                # backfill discovery step re-triggers it.
                await _mark_orphaned(
                    job_store,
                    job_id,
                    status,
                    reason='legacy queued: no durable inputs in Redis',
                )
                counts['failed_legacy_queued'] += 1
                continue

            if resume_count >= MAX_RESUME_ATTEMPTS:
                await _mark_orphaned(
                    job_store,
                    job_id,
                    status,
                    reason=f'exceeded resume budget ({MAX_RESUME_ATTEMPTS} attempts)',
                )
                counts['failed_resume_budget_exceeded'] += 1
                continue

            try:
                await job_store.update(job_id, {'resume_count': resume_count + 1})
            except Exception as exc:
                logger.warning(
                    'Failed to bump resume_count for %s; skipping resume: %s',
                    job_id,
                    exc,
                )
                counts['failed_resume_count_update'] += 1
                continue

            if ready_event is None:
                # Local import to avoid circular dependency at module load.
                from app.core.tts_engine import get_engine_ready_event

                ready_event = get_engine_ready_event()

            asyncio.create_task(
                _scheduled_resume(job_id, text, gcs_path, site_slug, ready_event),
                name=f'resume-{job_id}',
            )
            counts['resumed'] += 1
        else:
            # processing, paused, or any other non-terminal transient state
            await _mark_orphaned(
                job_store,
                job_id,
                status,
                reason=f'TTS service restarted while job was {status}',
            )
            counts[f'failed_{status}'] += 1

    return dict(counts)
