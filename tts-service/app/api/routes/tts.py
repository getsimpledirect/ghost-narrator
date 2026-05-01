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
TTS API routes.

Endpoints for text-to-speech generation, job status, and audio download.
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    HTTPException,
    Path as FastApiPath,
    Query,
)
from fastapi.responses import FileResponse

from app.api.dependencies import require_api_key
from app.config import (
    GCS_AUDIO_PREFIX,
    MAX_JOB_ID_LENGTH,
    MAX_TEXT_LENGTH,
    OUTPUT_DIR,
    VALID_JOB_ID_PATTERN,
    VOICE_SAMPLE_PATH,
)
from app.models.schemas import (
    GenerateRequest,
    GenerateResponse,
    JobListResponse,
    StatusResponse,
)
from app.domains.job.store import get_job_store
from app.domains.job.runner import run_tts_job

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/tts', tags=['TTS'], dependencies=[Depends(require_api_key)])


def _sanitize_job_id(job_id: str | None) -> str:
    """
    Sanitize and validate a job ID.

    Args:
        job_id: Optional custom job ID.

    Returns:
        A sanitized job ID or a new UUID if none provided.

    Raises:
        HTTPException: If job ID is invalid.
    """
    if not job_id:
        return str(uuid.uuid4())

    # Sanitize: strip, replace spaces, lowercase
    sanitized = job_id.strip().replace(' ', '-').lower()

    if len(sanitized) > MAX_JOB_ID_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f'job_id exceeds maximum length of {MAX_JOB_ID_LENGTH} characters',
        )

    if not VALID_JOB_ID_PATTERN.match(sanitized):
        raise HTTPException(
            status_code=422,
            detail='job_id must contain only alphanumeric characters, hyphens, and underscores',
        )

    return sanitized


@router.post(
    '/generate',
    response_model=GenerateResponse,
    status_code=202,
    summary='Submit a TTS job',
    description=(
        'Submit text for asynchronous speech synthesis. The request returns immediately '
        'with a `job_id`. Poll `GET /tts/status/{job_id}` until `status` is `completed`, '
        'then retrieve the audio URL from the `gcs_uri` field or download via '
        '`GET /tts/download/{job_id}` (local storage only).\n\n'
        'If you submit a request with a `job_id` that already exists, the existing '
        "job's current status is returned — no duplicate synthesis is triggered.\n\n"
        'Queued state is durable across service restarts: the request payload '
        'is persisted to Redis at queue time, so a process crash leaves the job '
        'recoverable. On startup, an orphan reaper resumes queued jobs and marks '
        'mid-pipeline (processing/paused) jobs as failed.'
    ),
    responses={
        202: {'description': 'Job accepted and queued for synthesis'},
        401: {'description': 'Missing Authorization header'},
        403: {'description': 'Invalid API key'},
        422: {'description': 'Validation error — text is empty, too long, or job_id is malformed'},
        503: {'description': 'Voice sample not configured on the server'},
    },
)
async def generate(
    background_tasks: BackgroundTasks,
    request: GenerateRequest = Body(
        ...,
        openapi_examples={
            'basic': {
                'summary': 'Basic text synthesis',
                'description': 'Simple text with custom job ID and site slug.',
                'value': {
                    'text': 'Hello, this is a test of the text-to-speech system.',
                    'job_id': 'article-12345',
                    'site_slug': 'my-blog',
                },
            },
            'minimal': {
                'summary': 'Minimal request',
                'description': 'Only the required text field, all others use defaults.',
                'value': {
                    'text': 'Welcome to our podcast. Today we discuss the latest trends in artificial intelligence and machine learning.',
                },
            },
            'full': {
                'summary': 'Full request with custom GCS path',
                'description': 'All fields populated including a custom GCS output path.',
                'value': {
                    'text': 'Breaking news: Scientists have discovered a new species of deep-sea fish in the Pacific Ocean.',
                    'job_id': 'news-2024-06-15-pacific-discovery',
                    'storage_path': 'audio/news/2024/06/pacific-discovery.mp3',
                    'site_slug': 'news-daily',
                },
            },
        },
    ),
) -> GenerateResponse:
    """Submit a TTS job for background processing."""
    # Validate voice sample exists
    if not Path(VOICE_SAMPLE_PATH).exists():
        raise HTTPException(
            status_code=503,
            detail='Voice sample not configured. Please contact the administrator.',
        )

    # Validate text is not empty
    if not request.text.strip():
        raise HTTPException(
            status_code=422,
            detail='Text must not be empty or whitespace-only',
        )

    # Validate text length
    if len(request.text) > MAX_TEXT_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f'Text exceeds maximum length of {MAX_TEXT_LENGTH} characters',
        )

    # Sanitize and validate job ID
    job_id = _sanitize_job_id(request.job_id)

    # Atomically check for existing job and create initial record.
    # `text`, `gcs_object_path`, and `site_slug` are persisted so the orphan
    # reaper can resume queued jobs after a service restart. These fields
    # are stripped from the /tts/jobs list response (see list_jobs) and
    # ignored by StatusResponse (extra='ignore'), so they never reach
    # API consumers.
    job_store = get_job_store()
    gcs_object_path = request.storage_path or (
        f'{GCS_AUDIO_PREFIX}/{request.site_slug}/{job_id}.mp3'
    )
    initial_data = {
        'status': 'queued',
        'gcs_uri': None,
        'local_path': None,
        'created_at': time.time(),
        # Durable inputs for the orphan reaper (resume after restart).
        'text': request.text,
        'gcs_object_path': gcs_object_path,
        'site_slug': request.site_slug or 'site',
        'resume_count': 0,
    }

    created = await job_store.create_if_not_exists(job_id, initial_data)

    if not created:
        # Job already exists — return its current status (no race possible)
        existing_job = await job_store.get(job_id)
        existing_status = existing_job.get('status', 'unknown') if existing_job else 'unknown'
        return GenerateResponse(job_id=job_id, status=existing_status)

    # Record metrics for new job creation
    from app.api.routes.metrics import record_job_created

    record_job_created()

    # gcs_object_path was computed above and persisted into initial_data so the
    # orphan reaper can resume the job after a restart with the same path.

    # Add job to background tasks
    background_tasks.add_task(
        run_tts_job,
        job_id,
        request.text,
        gcs_object_path,
        request.site_slug or 'site',
    )

    logger.info(f'TTS job queued: {job_id}')

    return GenerateResponse(job_id=job_id, status='queued')


@router.get(
    '/status/{job_id}',
    response_model=StatusResponse,
    summary='Get job status',
    description=(
        'Returns the current status and metadata for a job. '
        'Poll this endpoint after submitting a job. '
        'Typical lifecycle: `queued` → `processing` → `completed` (or `failed`).\n\n'
        'If the service restarts while the job is in `queued`, the orphan reaper '
        'resumes it transparently — clients may observe `queued` for slightly '
        'longer than usual, then `processing` once a worker picks it up. Jobs '
        'that were already `processing`/`paused` at restart are marked `failed` '
        'with `error` indicating the orphan recovery (mid-pipeline state cannot '
        'be reconstructed).'
    ),
    responses={
        200: {'description': 'Job status and metadata'},
        401: {'description': 'Missing Authorization header'},
        403: {'description': 'Invalid API key'},
        404: {'description': 'No job found with the given ID'},
    },
)
async def get_status(
    job_id: str = FastApiPath(..., pattern=r'^[a-zA-Z0-9_-]{1,200}$'),
) -> StatusResponse:
    """Get the status of a TTS job."""
    job_store = get_job_store()
    job_data = await job_store.get(job_id)

    if not job_data:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_id}' not found",
        )

    return StatusResponse(job_id=job_id, **job_data)


@router.get(
    '/download/{job_id}',
    summary='Download generated audio',
    description=(
        'Download the synthesised MP3 directly from the server. '
        'Only available when `status` is `completed` and `STORAGE_BACKEND=local`. '
        'For GCS or S3 backends, use the URL in the `gcs_uri` field instead.'
    ),
    responses={
        200: {'description': 'MP3 audio file', 'content': {'audio/mpeg': {}}},
        401: {'description': 'Missing Authorization header'},
        403: {'description': 'Invalid API key'},
        404: {'description': 'No job found with the given ID'},
        409: {'description': 'Job is not yet completed'},
        410: {'description': 'Audio file has been deleted or is no longer available'},
    },
)
async def download(
    job_id: str = FastApiPath(..., pattern=r'^[a-zA-Z0-9_-]+$', max_length=200),
) -> FileResponse:
    """Download the generated MP3 audio file."""
    job_store = get_job_store()
    job = await job_store.get(job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_id}' not found",
        )

    if job['status'] != 'completed':
        raise HTTPException(
            status_code=409,
            detail=f"Job status is '{job['status']}', must be 'completed' to download",
        )

    local_path = job.get('local_path')
    if not local_path:
        raise HTTPException(
            status_code=410,
            detail='Audio file path not recorded',
        )

    file_path = Path(local_path).resolve()
    if not str(file_path).startswith(str(OUTPUT_DIR.resolve())):
        raise HTTPException(
            status_code=400,
            detail='Invalid file path',
        )
    if not file_path.exists():
        raise HTTPException(
            status_code=410,
            detail='Audio file no longer available',
        )

    try:
        file_size = file_path.stat().st_size
        if file_size == 0:
            raise HTTPException(
                status_code=500,
                detail='Audio file is empty',
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f'Error accessing file {local_path}: {exc}')
        raise HTTPException(
            status_code=500,
            detail='Error accessing audio file',
        )

    return FileResponse(
        local_path,
        media_type='audio/mpeg',
        filename=f'{job_id}.mp3',
    )


@router.post(
    '/pause/{job_id}',
    response_model=StatusResponse,
    summary='Pause a job',
    description=(
        'Pause an active TTS job. Synthesis stops after the current chunk finishes. '
        'Resume later with `POST /tts/resume/{job_id}`.'
    ),
    responses={
        200: {'description': 'Job paused successfully'},
        401: {'description': 'Missing Authorization header'},
        403: {'description': 'Invalid API key'},
        404: {'description': 'No job found with the given ID'},
        409: {'description': 'Job is already completed or failed and cannot be paused'},
    },
)
async def pause_job(
    job_id: str = FastApiPath(..., pattern=r'^[a-zA-Z0-9_-]+$', max_length=200),
) -> StatusResponse:
    """Pause a TTS job."""
    job_store = get_job_store()
    job = await job_store.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    if job['status'] in ('completed', 'failed'):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot pause job in '{job['status']}' state",
        )

    await job_store.update(job_id, {'status': 'paused'})
    logger.info(f'TTS job paused: {job_id}')

    updated_job = await job_store.get(job_id)
    return StatusResponse(job_id=job_id, **updated_job)


@router.post(
    '/resume/{job_id}',
    response_model=StatusResponse,
    summary='Resume a paused job',
    description='Resume a previously paused TTS job. The job must be in `paused` state.',
    responses={
        200: {'description': 'Job resumed successfully'},
        401: {'description': 'Missing Authorization header'},
        403: {'description': 'Invalid API key'},
        404: {'description': 'No job found with the given ID'},
        409: {'description': 'Job is not in paused state'},
    },
)
async def resume_job(
    job_id: str = FastApiPath(..., pattern=r'^[a-zA-Z0-9_-]+$', max_length=200),
) -> StatusResponse:
    """Resume a TTS job."""
    job_store = get_job_store()
    job = await job_store.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    if job['status'] != 'paused':
        raise HTTPException(status_code=409, detail=f"Job is '{job['status']}', not 'paused'")

    await job_store.update(job_id, {'status': 'processing'})
    logger.info(f'TTS job resumed: {job_id}')

    updated_job = await job_store.get(job_id)
    return StatusResponse(job_id=job_id, **updated_job)


@router.delete(
    '/{job_id}',
    summary='Delete a job',
    description=(
        'Abort a running job and permanently delete all associated files and records. '
        'If the job is actively synthesising, it is cancelled immediately. '
        'This operation cannot be undone.'
    ),
    responses={
        200: {'description': 'Job and all associated files deleted'},
        401: {'description': 'Missing Authorization header'},
        403: {'description': 'Invalid API key'},
        404: {'description': 'No job found with the given ID'},
    },
)
async def delete_job(
    job_id: str = FastApiPath(..., pattern=r'^[a-zA-Z0-9_-]+$', max_length=200),
) -> dict[str, Any]:
    """Delete a TTS job and cleanup resources."""
    job_store = get_job_store()
    job = await job_store.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    # 1. Update status to 'deleted' to signal the background worker to stop
    await job_store.update(job_id, {'status': 'deleted'})

    # 2. Instantly kill any active synthesis processes.
    # Only signal for jobs that are still running — completed/failed jobs have
    # already cleaned up their cancel signal via the synthesize_to_file finally
    # block, so calling cancel_job on them would leave a stale signal that
    # cancels any future run reusing the same job_id.
    from app.core.tts_engine import get_tts_engine

    if job.get('status') in ('pending', 'processing'):
        get_tts_engine().cancel_job(job_id)

    logger.info(f'TTS job signal for deletion: {job_id}')

    # 3. Cleanup local files if they exist
    job_dir = OUTPUT_DIR / job_id
    final_mp3 = OUTPUT_DIR / f'{job_id}.mp3'
    raw_wav = OUTPUT_DIR / f'{job_id}_raw.wav'

    try:
        if job_dir.exists():
            import shutil

            shutil.rmtree(job_dir, ignore_errors=True)
        if final_mp3.exists():
            final_mp3.unlink(missing_ok=True)
        if raw_wav.exists():
            raw_wav.unlink(missing_ok=True)
    except Exception as exc:
        logger.warning(f'File cleanup during deletion failed for {job_id}: {exc}')

    # 3. Remove from job store
    await job_store.delete(job_id)

    return {'message': f"Job '{job_id}' and associated resources deleted"}


# Fields a client is allowed to sort by. Matches Redis-stored job fields with
# meaningful ordering. `id` is the dict key, not a stored field, so it's
# handled specially in the sort key function below.
_ALLOWED_SORT_FIELDS: frozenset[str] = frozenset(
    {
        'created_at',
        'started_at',
        'completed_at',
        'duration_seconds',
        'status',
        'id',
    }
)

# Durable-input fields written by /tts/generate so the orphan reaper can resume
# queued jobs after a restart. They are large (text can be 100+ KB) and never
# needed by API consumers, so they are stripped from /tts/jobs responses.
# StatusResponse already drops them via Pydantic `extra='ignore'`; the list
# response uses `dict[str, Any]` which doesn't filter, so we strip explicitly.
_DURABLE_INPUT_FIELDS: tuple[str, ...] = ('text', 'gcs_object_path', 'site_slug')


def _filter_sort_paginate_jobs(
    jobs: dict[str, dict[str, Any]],
    *,
    prefix: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    site_slug: Optional[str] = None,
    created_after: Optional[float] = None,
    created_before: Optional[float] = None,
    completed_after: Optional[float] = None,
    completed_before: Optional[float] = None,
    has_error: Optional[bool] = None,
    sort: str = '-created_at',
    limit: Optional[int] = None,
    offset: int = 0,
) -> tuple[dict[str, dict[str, Any]], int]:
    """Filter, sort, and paginate the job dict in pure-function form.

    Returns ``(result_dict, total_before_pagination)``. Result dict insertion
    order reflects the requested sort. Each result-job dict is a fresh shallow
    copy with the durable-input fields removed — the input dict is not mutated.

    Raises:
        ValueError: if `sort` references an unknown field.
    """
    sort_field = sort[1:] if sort.startswith('-') else sort
    sort_desc = sort.startswith('-')
    if sort_field not in _ALLOWED_SORT_FIELDS:
        raise ValueError(
            f'Unknown sort field: {sort_field!r}. Allowed: {sorted(_ALLOWED_SORT_FIELDS)}'
        )

    statuses: Optional[set[str]] = (
        {s.strip() for s in status.split(',') if s.strip()} if status else None
    )
    q_lower = q.lower() if q else None

    # Build (job_id, job_data) tuples, applying every filter axis.
    items: list[tuple[str, dict[str, Any]]] = []
    for job_id, job_data in jobs.items():
        if prefix and not job_id.startswith(prefix):
            continue
        job_status = job_data.get('status')
        if statuses is not None and (job_status or '') not in statuses:
            continue
        if site_slug is not None and job_data.get('site_slug') != site_slug:
            continue
        if has_error is not None:
            err = job_data.get('error') or ''
            if has_error and not err:
                continue
            if not has_error and err:
                continue
        if q_lower is not None:
            err_lower = (job_data.get('error') or '').lower()
            if q_lower not in job_id.lower() and q_lower not in err_lower:
                continue
        if created_after is not None:
            ca = job_data.get('created_at')
            if ca is None or float(ca) < created_after:
                continue
        if created_before is not None:
            ca = job_data.get('created_at')
            if ca is None or float(ca) > created_before:
                continue
        if completed_after is not None:
            cb = job_data.get('completed_at')
            if cb is None or float(cb) < completed_after:
                continue
        if completed_before is not None:
            cb = job_data.get('completed_at')
            if cb is None or float(cb) > completed_before:
                continue
        items.append((job_id, job_data))

    # Sort. None values sort low (False < True for the (None, value) tuple),
    # so missing-field jobs cluster at the start of asc order / end of desc.
    def sort_key(item: tuple[str, dict[str, Any]]) -> tuple[bool, Any]:
        job_id, job_data = item
        if sort_field == 'id':
            return (False, job_id)
        v = job_data.get(sort_field)
        return (v is None, v if v is not None else '')

    items.sort(key=sort_key, reverse=sort_desc)

    total = len(items)

    # Paginate.
    if offset:
        items = items[offset:]
    if limit is not None:
        items = items[:limit]

    # Strip durable-input fields. Build fresh shallow copies so the in-memory
    # store fallback (which returns dict references rather than deep copies)
    # is not corrupted across requests.
    result_jobs: dict[str, dict[str, Any]] = {}
    for job_id, job_data in items:
        result_jobs[job_id] = {k: v for k, v in job_data.items() if k not in _DURABLE_INPUT_FIELDS}

    return result_jobs, total


@router.get(
    '/jobs',
    response_model=JobListResponse,
    summary='List, search, filter, sort, and paginate jobs',
    description=(
        'Returns jobs currently tracked in Redis, with their status and metadata. '
        'Jobs expire after the configured TTL (default 24 hours).\n\n'
        'All query parameters are optional; with no parameters the endpoint '
        'returns every job (sorted newest-first by `created_at`).\n\n'
        'Filters are AND-combined. Pagination is applied after filtering and '
        'sorting; `total` reflects the count after filtering, before pagination, '
        'so clients can iterate by varying `offset`.'
    ),
    responses={
        200: {'description': 'Jobs matching the filter, paginated and sorted'},
        401: {'description': 'Missing Authorization header'},
        403: {'description': 'Invalid API key'},
        422: {'description': 'Invalid query parameter (e.g. unknown sort field)'},
    },
)
async def list_jobs(
    prefix: Optional[str] = Query(
        None,
        description='Filter to job IDs that start with this prefix (e.g. `backfill-`).',
    ),
    status: Optional[str] = Query(
        None,
        description=(
            'Filter by status. Comma-separate for multiple values '
            '(e.g. `queued,processing`). Match is exact and case-sensitive.'
        ),
    ),
    q: Optional[str] = Query(
        None,
        description=(
            'Case-insensitive substring search across the `id` and `error` fields. '
            'Does not search the underlying article text (excluded for size + privacy).'
        ),
    ),
    site_slug: Optional[str] = Query(
        None,
        description='Filter by exact `site_slug` (e.g. `ghost-founderreality-com`).',
    ),
    created_after: Optional[float] = Query(
        None,
        description='Inclusive lower bound on `created_at` (Unix seconds).',
    ),
    created_before: Optional[float] = Query(
        None,
        description='Inclusive upper bound on `created_at` (Unix seconds).',
    ),
    completed_after: Optional[float] = Query(
        None,
        description='Inclusive lower bound on `completed_at` (Unix seconds).',
    ),
    completed_before: Optional[float] = Query(
        None,
        description='Inclusive upper bound on `completed_at` (Unix seconds).',
    ),
    has_error: Optional[bool] = Query(
        None,
        description='If true, only jobs with a non-empty `error` field. If false, only jobs without one.',
    ),
    sort: str = Query(
        '-created_at',
        description=(
            'Sort field, with optional `-` prefix for descending. '
            'Allowed: `created_at`, `started_at`, `completed_at`, '
            '`duration_seconds`, `status`, `id`. Default: `-created_at` (newest first).'
        ),
    ),
    limit: Optional[int] = Query(
        None,
        ge=1,
        le=10000,
        description='Maximum jobs to return. Omit for no limit.',
    ),
    offset: int = Query(
        0,
        ge=0,
        description='Number of jobs to skip in the filtered+sorted set.',
    ),
) -> JobListResponse:
    """List TTS jobs with filter, sort, and pagination."""
    job_store = get_job_store()
    jobs = await job_store.list_all()

    try:
        result_jobs, total = _filter_sort_paginate_jobs(
            jobs,
            prefix=prefix,
            status=status,
            q=q,
            site_slug=site_slug,
            created_after=created_after,
            created_before=created_before,
            completed_after=completed_after,
            completed_before=completed_before,
            has_error=has_error,
            sort=sort,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return JobListResponse(
        total=total,
        limit=limit,
        offset=offset,
        jobs=result_jobs,
    )
