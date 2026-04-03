# Ghost Narrator TTS Service - Production Restructure Design

> **For agentic workers:** This spec defines a comprehensive restructure of the ghost-narrator TTS service. Implementation should follow the writing-plans skill.

**Goal:** Restructure the project for scalability, maintainability, and production-readiness while preserving all existing functionality.

**Architecture:** Domain-driven structure with clear module boundaries, enhanced error handling, caching, and observability.

**Tech Stack:** Python 3.11+, FastAPI, Redis, Optional dependencies (prometheus, opentelemetry)

---

## Current State Analysis

### Problems Identified

| File | Lines | Issue |
|------|-------|-------|
| `app/services/tts_job.py` | 647 | God module - does everything |
| `app/services/synthesis.py` | ~400 | Large, handles multiple concerns |
| `app/api/routes/tts.py` | ~300 | Growing route logic |
| No caching layer | - | Repeated computations |
| Limited error handling | - | Generic exceptions |

### Current Structure

```
app/
├── __init__.py
├── main.py              # FastAPI app
├── config.py           # Configuration
├── dependencies.py     # DI
├── api/
│   ├── routes/         # TTS, health, metrics, voices
│   ├── middleware/     # Rate limiting, API versioning
│   └── rate_limit_middleware/
├── core/
│   ├── tts_engine.py   # Qwen3-TTS
│   ├── hardware.py     # GPU detection
│   ├── exceptions.py
│   ├── circuit_breaker.py
│   └── tracing.py
├── models/
│   └── schemas.py      # Pydantic models
├── services/
│   ├── tts_job.py      # 647 lines - TOO LARGE
│   ├── synthesis.py
│   ├── job_store.py
│   ├── audio.py
│   ├── notification.py
│   ├── storage/        # Local, GCS, S3
│   ├── narration/     # Strategy, validator, prompt
│   └── voices/         # Registry, upload
└── utils/
    └── text.py
```

---

## Proposed Structure

### Phase 1: Folder Restructure

```
app/
├── __init__.py
├── main.py
├── config.py
├── dependencies.py
├── api/
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── tts.py
│   │   ├── health.py
│   │   ├── metrics.py
│   │   └── voices.py
│   └── middleware/
│       ├── __init__.py
│       ├── api_version.py      # NEW: separated from middleware.py
│       └── rate_limit.py
├── core/
│   ├── __init__.py
│   ├── config.py               # NEW: split from config.py
│   ├── tts_engine.py
│   ├── hardware.py
│   ├── exceptions.py
│   ├── circuit_breaker.py
│   ├── bulkhead.py
│   └── tracing.py
├── domains/                    # NEW: Domain-driven structure
│   ├── __init__.py
│   ├── narration/
│   │   ├── __init__.py
│   │   ├── base.py             # Abstract base class
│   │   ├── strategy.py
│   │   ├── validator.py
│   │   └── prompt.py
│   ├── synthesis/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── chunker.py          # NEW: extracted from tts_job.py
│   │   ├── concatenate.py      # NEW: extracted from tts_job.py
│   │   ├── normalize.py        # NEW: extracted from tts_job.py
│   │   └── mastering.py        # NEW: extracted from tts_job.py
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── local.py
│   │   ├── gcs.py
│   │   └── s3.py
│   └── job/
│       ├── __init__.py
│       ├── runner.py           # NEW: refactored from tts_job.py
│       ├── state.py            # NEW: job state management
│       └── callbacks.py        # NEW: notification logic
├── services/                  # Keep for backward compat, imports from domains
│   ├── __init__.py
│   └── ... (deprecated, imports from domains)
├── models/
│   └── schemas.py
├── cache/                     # NEW: caching layer
│   ├── __init__.py
│   ├── redis_cache.py
│   └── cache_decorator.py
└── utils/
    ├── __init__.py
    └── text.py
```

### Phase 2: Production Optimizations

#### 2.1 Caching Layer

```python
# app/cache/redis_cache.py
class RedisCache:
    """Redis-backed caching with TTL support."""
    
    def __init__(self, redis_url: str, default_ttl: int = 3600):
        self.client = redis.from_url(redis_url)
        self.default_ttl = default_ttl
    
    async def get(self, key: str) -> Optional[str]:
        return await self.client.get(key)
    
    async def set(self, key: str, value: str, ttl: Optional[int] = None):
        await self.client.setex(key, ttl or self.default_ttl, value)
    
    async def delete(self, key: str):
        await self.client.delete(key)

# app/cache/cache_decorator.py
def cached(key_template: str, ttl: int = 3600):
    """Decorator for caching function results."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            key = key_template.format(*args, **kwargs)
            cached = await cache.get(key)
            if cached:
                return json.loads(cached)
            result = await func(*args, **kwargs)
            await cache.set(key, json.dumps(result), ttl)
            return result
        return wrapper
    return decorator
```

**Use Cases:**
- Hardware detection result (cache for 1 hour)
- Model loading status
- Job status lookups (cache for 30 seconds)

#### 2.2 Enhanced Error Handling

```python
# app/core/exceptions.py - Add specific exceptions
class TTSServiceError(Exception):
    """Base exception for TTS service."""
    pass

class SynthesisError(TTSServiceError):
    """Synthesis-related errors."""
    pass

class NarrationError(TTSServiceError):
    """Narration-related errors."""
    pass

class StorageError(TTSServiceError):
    """Storage-related errors."""
    pass

class JobNotFoundError(TTSServiceError):
    """Job not found in store."""
    pass

class JobCancelledError(TTSServiceError):
    """Job was cancelled."""
    pass
```

#### 2.3 Observability Improvements

```python
# Enhanced metrics - app/api/routes/metrics.py additions
from prometheus_client import Counter, Histogram, Gauge

# Business metrics
jobs_created_total = Counter('tts_jobs_created_total', 'Total jobs created')
jobs_completed_total = Counter('tts_jobs_completed_total', 'Total jobs completed')
jobs_failed_total = Counter('tts_jobs_failed_total', 'Total jobs failed')

# Performance metrics
job_duration_seconds = Histogram('tts_job_duration_seconds', 'Job processing duration')
synthesis_duration_seconds = Histogram('tts_synthesis_duration_seconds', 'Synthesis duration')
narration_duration_seconds = Histogram('tts_narration_duration_seconds', 'Narration duration')

# Resource metrics
gpu_memory_usage_bytes = Gauge('tts_gpu_memory_usage_bytes', 'GPU memory usage')
gpu_utilization_percent = Gauge('tts_gpu_utilization_percent', 'GPU utilization')
active_jobs_count = Gauge('tts_active_jobs_count', 'Number of active jobs')
```

#### 2.4 Connection Pooling

```python
# app/core/connection_pool.py
from contextlib import asynccontextmanager
import asyncio

class ConnectionPool:
    """Generic async connection pool."""
    
    def __init__(self, factory, max_size: int = 10):
        self.factory = factory
        self.max_size = max_size
        self._pool: asyncio.Queue = asyncio.Queue(max_size)
        self._created = 0
        self._lock = asyncio.Lock()
    
    @asynccontextmanager
    async def acquire(self):
        conn = None
        try:
            conn = self._pool.get_nowait()
        except asyncio.QueueEmpty:
            async with self._lock:
                if self._created < self._max_size:
                    conn = await self.factory()
                    self._created += 1
                else:
                    conn = await self._pool.get()
            try:
                yield conn
            finally:
                await self._pool.put(conn)
        else:
            try:
                yield conn
            finally:
                await self._pool.put(conn)
```

---

## Implementation Tasks

### Phase 1: Structure (Tasks 1-8)

#### Task 1: Create domain structure
- Create `app/domains/` directory
- Create `app/domains/narration/`, `app/domains/synthesis/`, `app/domains/storage/`, `app/domains/job/`
- Create `app/cache/` directory
- Add `__init__.py` files

#### Task 2: Extract narration domain
- Move `app/services/narration/strategy.py` → `app/domains/narration/strategy.py`
- Move `app/services/narration/validator.py` → `app/domains/narration/validator.py`
- Move `app/services/narration/prompt.py` → `app/domains/narration/prompt.py`
- Create `app/domains/narration/base.py` (abstract base)
- Update imports in dependent modules

#### Task 3: Extract storage domain
- Move `app/services/storage/base.py` → `app/domains/storage/base.py`
- Move `app/services/storage/local.py` → `app/domains/storage/local.py`
- Move `app/services/storage/gcs.py` → `app/domains/storage/gcs.py`
- Move `app/services/storage/s3.py` → `app/domains/storage/s3.py`
- Create `app/domains/storage/__init__.py` with factory

#### Task 4: Extract synthesis domain
- Create `app/domains/synthesis/chunker.py` (from tts_job.py)
- Create `app/domains/synthesis/concatenate.py` (from tts_job.py)
- Create `app/domains/synthesis/normalize.py` (from tts_job.py)
- Create `app/domains/synthesis/mastering.py` (from tts_job.py)
- Create `app/domains/synthesis/base.py` (abstract base)

#### Task 5: Refactor job runner
- Create `app/domains/job/runner.py` (refactored from tts_job.py - ~300 lines)
- Create `app/domains/job/state.py` (job state machine)
- Create `app/domains/job/callbacks.py` (notification logic)
- Reduce tts_job.py to orchestrator (~200 lines)

#### Task 6: Create cache layer
- Create `app/cache/redis_cache.py`
- Create `app/cache/cache_decorator.py`
- Add caching for hardware detection
- Add caching for job status

#### Task 7: Update service imports (backward compat)
- Update `app/services/` to re-export from `app/domains/`
- Ensure all existing imports continue to work
- No breaking changes to external consumers

#### Task 8: Verify tests pass
- Run full test suite
- Fix any import issues
- Ensure 100% backward compatibility

### Phase 2: Production Optimizations (Tasks 9-15)

#### Task 9: Add enhanced exceptions
- Add specific exception classes to `app/core/exceptions.py`
- Update code to use specific exceptions
- Add exception handling middleware

#### Task 10: Add connection pooling
- Create `app/core/connection_pool.py`
- Add connection pooling for Redis
- Add connection pooling for HTTP clients

#### Task 11: Add enhanced metrics
- Add business metrics to metrics endpoint
- Add resource metrics (GPU, memory)
- Add job duration histograms

#### Task 12: Add health check improvements
- Add dependency health checks
- Add detailed health status endpoint
- Add readiness/liveness probes

#### Task 13: Add retry logic
- Add exponential backoff for external calls
- Add retry decorator
- Integrate with circuit breaker

#### Task 14: Add structured logging
- Use structlog for structured logging
- Add correlation IDs for requests
- Add job IDs to logs

#### Task 15: Final verification
- Run full test suite
- Check all endpoints work
- Verify performance improvements

---

## Backward Compatibility

- All existing imports must continue to work
- API contracts unchanged
- No breaking changes to external consumers
- Tests must pass without modification

---

## Success Criteria

1. **Structure:** All domains have clear boundaries with single responsibility
2. **Maintainability:** No file exceeds 300 lines
3. **Caching:** Hardware detection and job status cached
4. **Error Handling:** Specific exceptions for each domain
5. **Observability:** Enhanced metrics, structured logging
6. **Backward Compat:** All existing tests pass
7. **Performance:** Connection pooling reduces resource usage

---

## Files to Modify

| File | Action |
|------|--------|
| `app/services/tts_job.py` | Split into domains/job/ |
| `app/services/synthesis.py` | Move to domains/synthesis/ |
| `app/services/storage/*` | Move to domains/storage/ |
| `app/services/narration/*` | Move to domains/narration/ |
| `app/core/exceptions.py` | Add specific exceptions |
| `app/api/routes/metrics.py` | Add enhanced metrics |
| `app/main.py` | Update imports |

---

## Migration Guide

After restructure, imports will look like:

```python
# Old (still works)
from app.services.tts_job import run_tts_job
from app.services.narration.strategy import ChunkedStrategy
from app.services.storage import get_storage_backend

# New (preferred)
from app.domains.job.runner import run_tts_job
from app.domains.narration.strategy import ChunkedStrategy
from app.domains.storage import get_storage_backend
```

Both styles work during transition period.
