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

"""Tests for the orphan-job reaper executed at TTS service startup."""

from __future__ import annotations

import asyncio

import pytest

from app.domains.job.state import MAX_RESUME_ATTEMPTS
from app.domains.job.store import JobStore, reap_orphaned_jobs


@pytest.fixture
def job_store():
    """In-memory JobStore (no Redis)."""
    store = JobStore()
    store.use_redis = False
    store.redis_client = None
    store.memory_store = {}
    store._initialized = True
    return store


@pytest.fixture
def schedule_recorder(monkeypatch):
    """Capture scheduled resume tasks without executing them.

    Replaces `asyncio.create_task` inside the store module so resumed
    coroutines are recorded as scheduled-but-not-run. Returns a list
    that the test can inspect; each entry is the coroutine that would
    have run. The coroutines are closed immediately so they do not emit
    "coroutine was never awaited" warnings during test teardown.
    """
    scheduled: list = []

    def fake_create_task(coro, *, name=None):
        scheduled.append({'coro': coro, 'name': name})
        # Close the coroutine to suppress the "never awaited" warning.
        # We do not actually want to execute run_tts_job in tests.
        coro.close()

        # Return a dummy completed future so callers awaiting it don't break.
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        fut.set_result(None)
        return fut

    monkeypatch.setattr('app.domains.job.store.asyncio.create_task', fake_create_task)
    return scheduled


def _make_job(**fields) -> dict:
    """Build a job-data dict with sensible defaults."""
    base = {
        'status': 'queued',
        'gcs_uri': None,
        'local_path': None,
        'created_at': 1000.0,
        'text': 'sample article text',
        'gcs_object_path': 'audio/articles/site/job.mp3',
        'site_slug': 'site',
        'resume_count': 0,
    }
    base.update(fields)
    return base


class TestReaperResumesQueuedJobs:
    """Queued jobs with durable inputs + budget remaining are resumed."""

    @pytest.mark.asyncio
    async def test_queued_with_inputs_is_resumed(self, job_store, schedule_recorder):
        await job_store.set('job-1', _make_job(status='queued'))

        counts = await reap_orphaned_jobs(job_store)

        assert counts == {'resumed': 1}
        assert len(schedule_recorder) == 1
        assert schedule_recorder[0]['name'] == 'resume-job-1'

    @pytest.mark.asyncio
    async def test_resume_increments_counter(self, job_store, schedule_recorder):
        await job_store.set('job-1', _make_job(status='queued', resume_count=0))

        await reap_orphaned_jobs(job_store)

        record = await job_store.get('job-1')
        assert record['resume_count'] == 1

    @pytest.mark.asyncio
    async def test_resume_increments_from_existing_count(self, job_store, schedule_recorder):
        await job_store.set('job-1', _make_job(status='queued', resume_count=2))

        await reap_orphaned_jobs(job_store)

        record = await job_store.get('job-1')
        assert record['resume_count'] == 3

    @pytest.mark.asyncio
    async def test_resume_count_string_value_is_handled(self, job_store, schedule_recorder):
        # Redis returns numeric values as strings after some round-trips;
        # the reaper must coerce safely.
        await job_store.set('job-1', _make_job(status='queued', resume_count='1'))

        await reap_orphaned_jobs(job_store)

        record = await job_store.get('job-1')
        assert int(record['resume_count']) == 2


class TestReaperFailsBudgetExceeded:
    """Queued jobs whose resume budget is exhausted are marked failed."""

    @pytest.mark.asyncio
    async def test_at_budget_marks_failed(self, job_store, schedule_recorder):
        await job_store.set(
            'job-1',
            _make_job(status='queued', resume_count=MAX_RESUME_ATTEMPTS),
        )

        counts = await reap_orphaned_jobs(job_store)

        assert counts == {'failed_resume_budget_exceeded': 1}
        assert len(schedule_recorder) == 0
        record = await job_store.get('job-1')
        assert record['status'] == 'failed'
        assert 'resume budget' in record['error']

    @pytest.mark.asyncio
    async def test_above_budget_marks_failed(self, job_store, schedule_recorder):
        await job_store.set(
            'job-1',
            _make_job(status='queued', resume_count=MAX_RESUME_ATTEMPTS + 5),
        )

        counts = await reap_orphaned_jobs(job_store)

        assert counts == {'failed_resume_budget_exceeded': 1}


class TestReaperFailsLegacyQueued:
    """Queued jobs without durable inputs (pre-this-commit records) fail."""

    @pytest.mark.asyncio
    async def test_missing_text_marks_failed(self, job_store, schedule_recorder):
        await job_store.set('job-1', _make_job(status='queued', text=None))

        counts = await reap_orphaned_jobs(job_store)

        assert counts == {'failed_legacy_queued': 1}
        record = await job_store.get('job-1')
        assert record['status'] == 'failed'
        assert 'legacy queued' in record['error']
        assert len(schedule_recorder) == 0

    @pytest.mark.asyncio
    async def test_missing_gcs_path_marks_failed(self, job_store, schedule_recorder):
        await job_store.set('job-1', _make_job(status='queued', gcs_object_path=None))

        counts = await reap_orphaned_jobs(job_store)

        assert counts == {'failed_legacy_queued': 1}

    @pytest.mark.asyncio
    async def test_empty_text_marks_failed(self, job_store, schedule_recorder):
        await job_store.set('job-1', _make_job(status='queued', text=''))

        counts = await reap_orphaned_jobs(job_store)

        assert counts == {'failed_legacy_queued': 1}


class TestReaperFailsMidPipeline:
    """Processing / paused / other non-terminal orphans are marked failed."""

    @pytest.mark.asyncio
    async def test_processing_marks_failed(self, job_store, schedule_recorder):
        await job_store.set('job-1', _make_job(status='processing', started_at=2000.0))

        counts = await reap_orphaned_jobs(job_store)

        assert counts == {'failed_processing': 1}
        record = await job_store.get('job-1')
        assert record['status'] == 'failed'
        assert 'processing' in record['error']
        assert 'completed_at' in record
        assert 'duration_seconds' in record

    @pytest.mark.asyncio
    async def test_paused_marks_failed(self, job_store, schedule_recorder):
        await job_store.set('job-1', _make_job(status='paused', started_at=2000.0))

        counts = await reap_orphaned_jobs(job_store)

        assert counts == {'failed_paused': 1}

    @pytest.mark.asyncio
    async def test_unknown_transient_status_marks_failed(self, job_store, schedule_recorder):
        # Defensive: any non-terminal status the reaper doesn't recognize
        # should still be marked failed (not silently skipped).
        await job_store.set('job-1', _make_job(status='quality_check'))

        counts = await reap_orphaned_jobs(job_store)

        assert counts == {'failed_quality_check': 1}


class TestReaperLeavesTerminalAlone:
    """Terminal-state jobs are untouched."""

    @pytest.mark.asyncio
    async def test_completed_untouched(self, job_store, schedule_recorder):
        await job_store.set('job-1', _make_job(status='completed'))
        original = await job_store.get('job-1')

        counts = await reap_orphaned_jobs(job_store)

        assert counts == {}
        assert await job_store.get('job-1') == original

    @pytest.mark.asyncio
    async def test_failed_untouched(self, job_store, schedule_recorder):
        await job_store.set('job-1', _make_job(status='failed', error='prior'))
        original = await job_store.get('job-1')

        counts = await reap_orphaned_jobs(job_store)

        assert counts == {}
        assert await job_store.get('job-1') == original

    @pytest.mark.asyncio
    async def test_cancelled_untouched(self, job_store, schedule_recorder):
        await job_store.set('job-1', _make_job(status='cancelled'))
        original = await job_store.get('job-1')

        counts = await reap_orphaned_jobs(job_store)

        assert counts == {}
        assert await job_store.get('job-1') == original

    @pytest.mark.asyncio
    async def test_deleted_untouched(self, job_store, schedule_recorder):
        # 'deleted' is transient in normal flow but can persist briefly
        # if the service crashes during the DELETE handler. Reaper must
        # respect user's deletion intent (let TTL clean up).
        await job_store.set('job-1', _make_job(status='deleted'))
        original = await job_store.get('job-1')

        counts = await reap_orphaned_jobs(job_store)

        assert counts == {}
        assert await job_store.get('job-1') == original


class TestReaperEdgeCases:
    """Empty store, missing status, mixed populations."""

    @pytest.mark.asyncio
    async def test_empty_store_returns_empty_dict(self, job_store, schedule_recorder):
        counts = await reap_orphaned_jobs(job_store)
        assert counts == {}
        assert len(schedule_recorder) == 0

    @pytest.mark.asyncio
    async def test_missing_status_field_skipped(self, job_store, schedule_recorder):
        # A record without a status field — defensive handling.
        await job_store.set('job-1', {'created_at': 1000.0})

        counts = await reap_orphaned_jobs(job_store)

        assert counts == {}

    @pytest.mark.asyncio
    async def test_mixed_population_aggregates_correctly(self, job_store, schedule_recorder):
        await job_store.set('job-1', _make_job(status='queued'))
        await job_store.set('job-2', _make_job(status='queued'))
        await job_store.set('job-3', _make_job(status='processing'))
        await job_store.set('job-4', _make_job(status='paused'))
        await job_store.set('job-5', _make_job(status='completed'))
        await job_store.set('job-6', _make_job(status='failed'))
        await job_store.set('job-7', _make_job(status='queued', text=None))
        await job_store.set(
            'job-8',
            _make_job(status='queued', resume_count=MAX_RESUME_ATTEMPTS),
        )

        counts = await reap_orphaned_jobs(job_store)

        assert counts == {
            'resumed': 2,
            'failed_processing': 1,
            'failed_paused': 1,
            'failed_legacy_queued': 1,
            'failed_resume_budget_exceeded': 1,
        }
        # Two resumed scheduled tasks
        assert len(schedule_recorder) == 2
        # Completed/failed records untouched
        assert (await job_store.get('job-5'))['status'] == 'completed'
        assert (await job_store.get('job-6'))['status'] == 'failed'


class TestReaperResilience:
    """Per-record errors do not block the rest of the reaper."""

    @pytest.mark.asyncio
    async def test_list_all_failure_returns_empty(self, monkeypatch, job_store):
        async def boom():
            raise RuntimeError('redis exploded')

        monkeypatch.setattr(job_store, 'list_all', boom)

        counts = await reap_orphaned_jobs(job_store)

        assert counts == {}

    @pytest.mark.asyncio
    async def test_per_record_update_failure_is_tolerated(
        self, monkeypatch, job_store, schedule_recorder
    ):
        await job_store.set('good-job', _make_job(status='processing'))
        await job_store.set('bad-job', _make_job(status='processing'))

        original_update = job_store.update
        call_count = {'n': 0}

        async def maybe_failing_update(job_id, updates):
            call_count['n'] += 1
            if job_id == 'bad-job':
                raise RuntimeError('update failed for bad-job')
            await original_update(job_id, updates)

        monkeypatch.setattr(job_store, 'update', maybe_failing_update)

        counts = await reap_orphaned_jobs(job_store)

        # bad-job's update threw; good-job still got processed.
        # _mark_orphaned swallows the exception and logs, so the count
        # increments for both even though only one Redis write succeeded.
        assert counts.get('failed_processing') == 2
        # The good-job record should have actually been updated.
        good = await job_store.get('good-job')
        assert good['status'] == 'failed'
