import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import time
from app.domains.job.store import JobStore


class TestJobStore:
    @pytest.fixture
    def job_store(self):
        store = JobStore()
        store.use_redis = False
        store.redis_client = None
        store.memory_store = {}
        store._initialized = True
        return store

    @pytest.mark.asyncio
    async def test_job_store_set_and_get(self, job_store):
        await job_store.set('test-job-1', {'status': 'processing', 'text': 'hello'})
        result = await job_store.get('test-job-1')
        assert result is not None
        assert result['status'] == 'processing'
        assert result['text'] == 'hello'

    @pytest.mark.asyncio
    async def test_job_store_update_merges_fields(self, job_store):
        await job_store.set('test-job-2', {'status': 'processing', 'text': 'hello'})
        await job_store.update(
            'test-job-2', {'status': 'completed', 'audio_uri': 'local://test.mp3'}
        )
        result = await job_store.get('test-job-2')
        assert result is not None
        assert result['status'] == 'completed'
        assert result['text'] == 'hello'
        assert result['audio_uri'] == 'local://test.mp3'

    @pytest.mark.asyncio
    async def test_job_store_exists(self, job_store):
        await job_store.set('existing-job', {'status': 'queued'})
        assert await job_store.exists('existing-job') is True
        assert await job_store.exists('nonexistent-job') is False

    @pytest.mark.asyncio
    async def test_job_store_list_all(self, job_store):
        await job_store.set('job-a', {'status': 'queued'})
        await job_store.set('job-b', {'status': 'completed'})
        jobs = await job_store.list_all()
        assert 'job-a' in jobs
        assert 'job-b' in jobs
        assert jobs['job-a']['status'] == 'queued'
        assert jobs['job-b']['status'] == 'completed'

    @pytest.mark.asyncio
    async def test_job_store_memory_ttl_expiration(self, job_store):
        job_store._memory_job_ttl = 1
        await job_store.set('expiring-job', {'status': 'processing'})
        result = await job_store.get('expiring-job')
        assert result is not None
        assert result['status'] == 'processing'
        await asyncio.sleep(1.1)
        result = await job_store.get('expiring-job')
        assert result is None
