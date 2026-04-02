# Plan B: Storage Backends + Voice Profiles

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add pluggable storage backends (local, GCS, AWS S3) and a full voice profile system (named profiles, runtime upload, backward-compatible default).

**Architecture:** `app/services/storage/` package with a `StorageBackend` ABC and three implementations. `app/services/voices/` package with `VoiceRegistry` and upload handling. New `/voices` API routes. `tts_job.py` wired to use both. The callback payload field `gcs_uri` is renamed `audio_uri`.

**Tech Stack:** Python 3.12, boto3 (S3), google-cloud-storage (GCS), FastAPI, pytest

**Spec:** `docs/superpowers/specs/2026-04-02-standalone-tts-design.md` — Sections 5, 6

**Dependency:** Plan A Task 2 must be complete (config.py must have STORAGE_BACKEND, S3 vars, GCS_SERVICE_ACCOUNT_KEY_PATH defined).

---

## File Map

```
tts-service/
├── app/
│   ├── config.py                              MODIFY — STORAGE_BACKEND, S3 vars (Plan A Task 2)
│   ├── core/
│   │   └── exceptions.py                      MODIFY — GCSUploadError → StorageUploadError
│   ├── services/
│   │   ├── storage.py                         DELETE — replaced by package below
│   │   ├── storage/
│   │   │   ├── __init__.py                    NEW — get_storage_backend()
│   │   │   ├── base.py                        NEW — StorageBackend ABC
│   │   │   ├── local.py                       NEW — LocalStorage
│   │   │   ├── gcs.py                         NEW — GCSStorage (existing logic moved)
│   │   │   └── s3.py                          NEW — S3Storage
│   │   ├── voices/
│   │   │   ├── __init__.py                    NEW
│   │   │   ├── registry.py                    NEW — VoiceRegistry
│   │   │   └── upload.py                      NEW — voice file validation + save
│   │   └── tts_job.py                         MODIFY — use storage backend + voice profile
│   ├── api/routes/
│   │   ├── voices.py                          NEW — /voices endpoints
│   │   └── health.py                          MODIFY — remove VQ token check, add tier status
│   ├── models/
│   │   └── schemas.py                         MODIFY — voice_profile in GenerateRequest
│   └── main.py                                MODIFY — register /voices router
└── tests/
    ├── test_storage.py                        NEW
    └── test_voices.py                         NEW
```

---

## Task 1: StorageBackend ABC + LocalStorage

**Files:**
- Create: `tts-service/app/services/storage/__init__.py`
- Create: `tts-service/app/services/storage/base.py`
- Create: `tts-service/app/services/storage/local.py`
- Create: `tts-service/tests/test_storage.py`

- [ ] **Step 1: Write failing tests**

```python
# tts-service/tests/test_storage.py
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock
import os


def test_get_storage_backend_local():
    with patch.dict(os.environ, {"STORAGE_BACKEND": "local"}):
        # Re-import to pick up env change
        import importlib
        import app.services.storage as m
        importlib.reload(m)
        backend = m.get_storage_backend()
    from app.services.storage.local import LocalStorage
    assert isinstance(backend, LocalStorage)


def test_get_storage_backend_unknown_raises():
    with patch.dict(os.environ, {"STORAGE_BACKEND": "dropbox"}):
        import importlib
        import app.services.storage as m
        importlib.reload(m)
        with pytest.raises(ValueError, match="Unknown STORAGE_BACKEND"):
            m.get_storage_backend()


@pytest.mark.asyncio
async def test_local_storage_upload(tmp_path):
    from app.services.storage.local import LocalStorage
    audio_file = tmp_path / "test.mp3"
    audio_file.write_bytes(b"fake-audio")
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    backend = LocalStorage(output_dir=output_dir, server_ip="localhost", port=8020)
    uri = await backend.upload(audio_file, job_id="job123", site_slug="site1")

    assert uri == "local://job123.mp3"
    assert (output_dir / "job123.mp3").exists()


def test_local_storage_make_public_url():
    from app.services.storage.local import LocalStorage
    backend = LocalStorage(output_dir=Path("/tmp"), server_ip="1.2.3.4", port=8020)
    url = backend.make_public_url("local://job123.mp3")
    assert url == "http://1.2.3.4:8020/tts/download/job123"
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd tts-service
python -m pytest tests/test_storage.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `storage/base.py`**

```python
"""StorageBackend abstract base class."""
from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path


class StorageBackend(ABC):
    @abstractmethod
    async def upload(self, local_path: Path, job_id: str, site_slug: str) -> str:
        """Upload audio file. Returns audio_uri string (e.g. 'local://', 'gs://', 's3://')."""

    @abstractmethod
    def make_public_url(self, audio_uri: str) -> str:
        """Convert storage URI to HTTP URL suitable for embedding in Ghost audio player."""
```

- [ ] **Step 4: Create `storage/local.py`**

```python
"""LocalStorage backend — saves audio to a mounted output directory."""
from __future__ import annotations
import shutil
from pathlib import Path
from app.services.storage.base import StorageBackend


class LocalStorage(StorageBackend):
    def __init__(self, output_dir: Path, server_ip: str, port: int = 8020) -> None:
        self._output_dir = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._server_ip = server_ip
        self._port = port

    async def upload(self, local_path: Path, job_id: str, site_slug: str) -> str:
        dest = self._output_dir / f"{job_id}.mp3"
        if local_path != dest:
            shutil.copy2(local_path, dest)
        return f"local://{job_id}.mp3"

    def make_public_url(self, audio_uri: str) -> str:
        # "local://job123.mp3" → extract job_id → download endpoint
        job_id = audio_uri.removeprefix("local://").removesuffix(".mp3")
        return f"http://{self._server_ip}:{self._port}/tts/download/{job_id}"
```

- [ ] **Step 5: Create `storage/__init__.py`**

```python
"""Storage backend factory."""
from __future__ import annotations
from app.services.storage.base import StorageBackend
from app.config import STORAGE_BACKEND


def get_storage_backend() -> StorageBackend:
    """Return the active StorageBackend based on STORAGE_BACKEND env var."""
    backend = STORAGE_BACKEND.lower()
    if backend == "local":
        from app.services.storage.local import LocalStorage
        from app.config import OUTPUT_DIR, SERVER_EXTERNAL_IP
        return LocalStorage(output_dir=OUTPUT_DIR, server_ip=SERVER_EXTERNAL_IP)
    if backend == "gcs":
        from app.services.storage.gcs import GCSStorage
        return GCSStorage()
    if backend == "s3":
        from app.services.storage.s3 import S3Storage
        return S3Storage()
    raise ValueError(f"Unknown STORAGE_BACKEND={STORAGE_BACKEND!r}. Use: local, gcs, s3")
```

- [ ] **Step 6: Run tests — verify they pass**

```bash
cd tts-service
python -m pytest tests/test_storage.py::test_get_storage_backend_local tests/test_storage.py::test_get_storage_backend_unknown_raises tests/test_storage.py::test_local_storage_upload tests/test_storage.py::test_local_storage_make_public_url -v
```
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add tts-service/app/services/storage/ tts-service/tests/test_storage.py
git commit -m "feat(storage): StorageBackend ABC + LocalStorage + factory"
```

---

## Task 2: GCSStorage

**Files:**
- Create: `tts-service/app/services/storage/gcs.py`
- Modify: `tts-service/app/core/exceptions.py`

- [ ] **Step 1: Rename `GCSUploadError` in `exceptions.py`**

Find `GCSUploadError` in `exceptions.py`. Replace:
```python
class GCSUploadError(StorageError):
    """Raised when GCS upload fails."""
```
With:
```python
class StorageUploadError(StorageError):
    """Raised when any storage backend upload fails."""

# Backward-compatible alias — remove after tts_job.py is updated
GCSUploadError = StorageUploadError
```

- [ ] **Step 2: Create `storage/gcs.py`** — move existing GCS logic from `storage.py`

```python
"""GCSStorage backend — uploads to Google Cloud Storage."""
from __future__ import annotations
import logging
from pathlib import Path
from app.services.storage.base import StorageBackend
from app.core.exceptions import StorageUploadError
from app.config import GCS_BUCKET_NAME, GCS_AUDIO_PREFIX, GCS_SERVICE_ACCOUNT_KEY_PATH, MAX_RETRIES, GCS_UPLOAD_TIMEOUT

logger = logging.getLogger(__name__)


class GCSStorage(StorageBackend):
    def __init__(self) -> None:
        if not GCS_BUCKET_NAME:
            raise ValueError("GCS_BUCKET_NAME must be set when STORAGE_BACKEND=gcs")

    def _get_client(self):
        from google.cloud import storage
        if GCS_SERVICE_ACCOUNT_KEY_PATH:
            return storage.Client.from_service_account_json(GCS_SERVICE_ACCOUNT_KEY_PATH)
        return storage.Client()  # uses ADC

    async def upload(self, local_path: Path, job_id: str, site_slug: str) -> str:
        import asyncio
        blob_path = f"{GCS_AUDIO_PREFIX}/{site_slug}/{job_id}.mp3"
        uri = f"gs://{GCS_BUCKET_NAME}/{blob_path}"
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                client = self._get_client()
                bucket = client.bucket(GCS_BUCKET_NAME)
                blob = bucket.blob(blob_path)
                await asyncio.to_thread(
                    blob.upload_from_filename,
                    str(local_path),
                    content_type="audio/mpeg",
                    timeout=GCS_UPLOAD_TIMEOUT,
                )
                logger.info("GCS upload complete: %s", uri)
                return uri
            except Exception as e:
                if attempt == MAX_RETRIES:
                    raise StorageUploadError(f"GCS upload failed after {MAX_RETRIES} attempts: {e}") from e
                wait = 2 ** attempt
                logger.warning("GCS upload attempt %d failed (%s) — retrying in %ds", attempt, e, wait)
                await asyncio.sleep(wait)
        return uri  # unreachable but satisfies type checker

    def make_public_url(self, audio_uri: str) -> str:
        # "gs://bucket/path/file.mp3" → "https://storage.googleapis.com/bucket/path/file.mp3"
        path = audio_uri.removeprefix("gs://")
        return f"https://storage.googleapis.com/{path}"
```

- [ ] **Step 3: Add GCS tests**

```python
# Append to tts-service/tests/test_storage.py:

@pytest.mark.asyncio
async def test_gcs_storage_upload(tmp_path):
    from unittest.mock import MagicMock, patch
    from app.services.storage.gcs import GCSStorage

    audio_file = tmp_path / "test.mp3"
    audio_file.write_bytes(b"fake-audio")

    mock_blob = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_client = MagicMock()
    mock_client.bucket.return_value = mock_bucket

    with patch("app.services.storage.gcs.GCSStorage._get_client", return_value=mock_client):
        with patch.dict(os.environ, {"GCS_BUCKET_NAME": "my-bucket", "STORAGE_BACKEND": "gcs"}):
            backend = GCSStorage()
            uri = await backend.upload(audio_file, job_id="job1", site_slug="site1")

    assert uri == "gs://my-bucket/audio/articles/site1/job1.mp3"
    mock_blob.upload_from_filename.assert_called_once()


def test_gcs_make_public_url():
    from app.services.storage.gcs import GCSStorage
    with patch.dict(os.environ, {"GCS_BUCKET_NAME": "my-bucket"}):
        backend = GCSStorage()
    url = backend.make_public_url("gs://my-bucket/audio/articles/site1/job1.mp3")
    assert url == "https://storage.googleapis.com/my-bucket/audio/articles/site1/job1.mp3"
```

- [ ] **Step 4: Run tests**

```bash
cd tts-service
python -m pytest tests/test_storage.py -v -k "gcs"
```
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add tts-service/app/services/storage/gcs.py tts-service/app/core/exceptions.py tts-service/tests/test_storage.py
git commit -m "feat(storage): GCSStorage + rename GCSUploadError to StorageUploadError"
```

---

## Task 3: S3Storage

**Files:**
- Create: `tts-service/app/services/storage/s3.py`

- [ ] **Step 1: Write failing S3 tests**

```python
# Append to tts-service/tests/test_storage.py:

@pytest.mark.asyncio
async def test_s3_storage_upload(tmp_path):
    from unittest.mock import MagicMock, patch
    from app.services.storage.s3 import S3Storage

    audio_file = tmp_path / "test.mp3"
    audio_file.write_bytes(b"fake-audio")

    with patch("app.services.storage.s3.boto3") as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.client.return_value = mock_s3
        with patch.dict(os.environ, {
            "AWS_ACCESS_KEY_ID": "key", "AWS_SECRET_ACCESS_KEY": "secret",
            "AWS_REGION": "us-east-1", "S3_BUCKET_NAME": "my-bucket"
        }):
            backend = S3Storage()
            uri = await backend.upload(audio_file, job_id="job1", site_slug="site1")

    assert uri == "s3://my-bucket/audio/articles/site1/job1.mp3"
    mock_s3.upload_file.assert_called_once()


def test_s3_make_public_url():
    from app.services.storage.s3 import S3Storage
    with patch.dict(os.environ, {
        "AWS_ACCESS_KEY_ID": "key", "AWS_SECRET_ACCESS_KEY": "secret",
        "AWS_REGION": "us-east-1", "S3_BUCKET_NAME": "my-bucket"
    }):
        backend = S3Storage()
    url = backend.make_public_url("s3://my-bucket/audio/articles/site1/job1.mp3")
    assert url == "https://my-bucket.s3.us-east-1.amazonaws.com/audio/articles/site1/job1.mp3"
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd tts-service
python -m pytest tests/test_storage.py -v -k "s3" 2>&1 | head -10
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `storage/s3.py`**

```python
"""S3Storage backend — uploads to AWS S3."""
from __future__ import annotations
import asyncio
import logging
from pathlib import Path
import boto3
from app.services.storage.base import StorageBackend
from app.core.exceptions import StorageUploadError
from app.config import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, S3_BUCKET_NAME, S3_AUDIO_PREFIX, MAX_RETRIES

logger = logging.getLogger(__name__)


class S3Storage(StorageBackend):
    def __init__(self) -> None:
        if not S3_BUCKET_NAME:
            raise ValueError("S3_BUCKET_NAME must be set when STORAGE_BACKEND=s3")
        self._bucket = S3_BUCKET_NAME
        self._region = AWS_REGION
        self._client = boto3.client(
            "s3",
            region_name=AWS_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID or None,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY or None,
        )

    async def upload(self, local_path: Path, job_id: str, site_slug: str) -> str:
        key = f"{S3_AUDIO_PREFIX}/{site_slug}/{job_id}.mp3"
        uri = f"s3://{self._bucket}/{key}"
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                await asyncio.to_thread(
                    self._client.upload_file,
                    str(local_path),
                    self._bucket,
                    key,
                    ExtraArgs={"ContentType": "audio/mpeg"},
                )
                logger.info("S3 upload complete: %s", uri)
                return uri
            except Exception as e:
                if attempt == MAX_RETRIES:
                    raise StorageUploadError(f"S3 upload failed after {MAX_RETRIES} attempts: {e}") from e
                wait = 2 ** attempt
                logger.warning("S3 upload attempt %d failed (%s) — retrying in %ds", attempt, e, wait)
                await asyncio.sleep(wait)
        return uri

    def make_public_url(self, audio_uri: str) -> str:
        # "s3://bucket/key" → "https://bucket.s3.region.amazonaws.com/key"
        path = audio_uri.removeprefix(f"s3://{self._bucket}/")
        return f"https://{self._bucket}.s3.{self._region}.amazonaws.com/{path}"
```

- [ ] **Step 4: Add boto3 to requirements.txt**

```
boto3>=1.34.0
```

- [ ] **Step 5: Run tests**

```bash
cd tts-service
python -m pytest tests/test_storage.py -v
```
Expected: all storage tests pass

- [ ] **Step 6: Commit**

```bash
git add tts-service/app/services/storage/s3.py tts-service/requirements.txt tts-service/tests/test_storage.py
git commit -m "feat(storage): S3Storage backend with boto3"
```

---

## Task 4: VoiceRegistry

**Files:**
- Create: `tts-service/app/services/voices/__init__.py`
- Create: `tts-service/app/services/voices/registry.py`
- Create: `tts-service/tests/test_voices.py`

- [ ] **Step 1: Write failing tests**

```python
# tts-service/tests/test_voices.py
import pytest
from pathlib import Path
import shutil, tempfile
from app.services.voices.registry import VoiceRegistry


@pytest.fixture
def voices_dir(tmp_path):
    default_dir = tmp_path / "default"
    default_dir.mkdir()
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    return tmp_path


def test_resolve_default_new_path(voices_dir):
    ref = voices_dir / "default" / "reference.wav"
    ref.write_bytes(b"fake-wav")
    reg = VoiceRegistry(voices_dir)
    assert reg.resolve("default") == ref


def test_resolve_default_fallback_old_path(voices_dir):
    # Old deployment: voices/reference.wav (no default/ subdir)
    old_ref = voices_dir / "reference.wav"
    old_ref.write_bytes(b"fake-wav")
    reg = VoiceRegistry(voices_dir)
    assert reg.resolve("default") == old_ref


def test_resolve_named_profile(voices_dir):
    profile = voices_dir / "profiles" / "narrator-warm.wav"
    profile.write_bytes(b"fake-wav")
    reg = VoiceRegistry(voices_dir)
    assert reg.resolve("narrator-warm") == profile


def test_resolve_unknown_raises(voices_dir):
    reg = VoiceRegistry(voices_dir)
    with pytest.raises(FileNotFoundError, match="Voice profile not found"):
        reg.resolve("ghost-voice")


def test_list_profiles(voices_dir):
    (voices_dir / "profiles" / "voice-a.wav").write_bytes(b"x")
    (voices_dir / "profiles" / "voice-b.wav").write_bytes(b"x")
    reg = VoiceRegistry(voices_dir)
    profiles = reg.list_profiles()
    assert set(profiles) == {"default", "voice-a", "voice-b"}
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd tts-service
python -m pytest tests/test_voices.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `voices/__init__.py`**

```python
"""Voice profile management."""
```

- [ ] **Step 4: Create `voices/registry.py`**

```python
"""VoiceRegistry — resolves named voice profiles to filesystem paths."""
from __future__ import annotations
from pathlib import Path


class VoiceRegistry:
    """Manages voice profiles under a voices/ directory.

    Structure:
        voices/default/reference.wav   → profile "default" (preferred)
        voices/reference.wav           → profile "default" (backward-compat fallback)
        voices/profiles/<name>.wav     → named profile "<name>"
    """

    def __init__(self, voices_dir: Path) -> None:
        self._voices_dir = voices_dir
        self._profiles_dir = voices_dir / "profiles"
        self._profiles_dir.mkdir(parents=True, exist_ok=True)

    def resolve(self, profile_name: str) -> Path:
        """Return Path to the WAV file for profile_name. Raises FileNotFoundError if not found."""
        if profile_name == "default":
            new_path = self._voices_dir / "default" / "reference.wav"
            if new_path.exists():
                return new_path
            fallback = self._voices_dir / "reference.wav"
            if fallback.exists():
                return fallback
            raise FileNotFoundError(
                "Voice profile not found: default. "
                "Place a reference.wav in voices/default/ or voices/"
            )
        path = self._profiles_dir / f"{profile_name}.wav"
        if not path.exists():
            raise FileNotFoundError(
                f"Voice profile not found: {profile_name}. "
                f"Expected at {path}"
            )
        return path

    def list_profiles(self) -> list[str]:
        """Return list of available profile names including 'default'."""
        profiles = ["default"]
        if self._profiles_dir.exists():
            profiles += [p.stem for p in self._profiles_dir.glob("*.wav")]
        return profiles

    def delete_profile(self, profile_name: str) -> None:
        """Delete a named profile. Raises ValueError if trying to delete 'default'."""
        if profile_name == "default":
            raise ValueError("Cannot delete the default voice profile")
        path = self.resolve(profile_name)
        path.unlink()
```

- [ ] **Step 5: Run tests**

```bash
cd tts-service
python -m pytest tests/test_voices.py -v
```
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add tts-service/app/services/voices/ tts-service/tests/test_voices.py
git commit -m "feat(voices): VoiceRegistry with backward-compatible default path fallback"
```

---

## Task 5: Voice upload + API routes

**Files:**
- Create: `tts-service/app/services/voices/upload.py`
- Create: `tts-service/app/api/routes/voices.py`

- [ ] **Step 1: Create `voices/upload.py`**

```python
"""Voice upload — validates and saves reference WAV files."""
from __future__ import annotations
import logging
from pathlib import Path
import soundfile as sf
from app.core.exceptions import TTSEngineError

logger = logging.getLogger(__name__)

MIN_DURATION_S = 5.0
MAX_DURATION_S = 120.0
MIN_SAMPLE_RATE = 16000


def validate_and_save(source_path: Path, dest_path: Path) -> None:
    """Validate WAV file quality and save to dest_path. Raises TTSEngineError on failure."""
    try:
        info = sf.info(str(source_path))
    except Exception as e:
        raise TTSEngineError(f"Cannot read audio file: {e}") from e

    duration = info.frames / info.samplerate
    if duration < MIN_DURATION_S:
        raise TTSEngineError(f"Voice sample too short ({duration:.1f}s) — minimum {MIN_DURATION_S}s")
    if duration > MAX_DURATION_S:
        raise TTSEngineError(f"Voice sample too long ({duration:.1f}s) — maximum {MAX_DURATION_S}s")
    if info.samplerate < MIN_SAMPLE_RATE:
        raise TTSEngineError(f"Sample rate too low ({info.samplerate} Hz) — minimum {MIN_SAMPLE_RATE} Hz")

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(source_path, dest_path)
    logger.info("Voice profile saved: %s (%.1fs, %d Hz)", dest_path.name, duration, info.samplerate)
```

- [ ] **Step 2: Create `api/routes/voices.py`**

```python
"""Voice profile management endpoints."""
from __future__ import annotations
import tempfile
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from app.services.voices.registry import VoiceRegistry
from app.services.voices.upload import validate_and_save
from app.config import VOICE_SAMPLE_PATH

router = APIRouter(prefix="/voices", tags=["voices"])

def _get_registry() -> VoiceRegistry:
    voices_dir = Path(VOICE_SAMPLE_PATH).parent.parent  # voices/default/reference.wav → voices/
    return VoiceRegistry(voices_dir)


@router.get("")
def list_voices():
    """List all available voice profiles."""
    registry = _get_registry()
    profiles = registry.list_profiles()
    return {"profiles": profiles, "count": len(profiles)}


@router.post("/upload")
async def upload_voice(name: str, file: UploadFile = File(...)):
    """Upload a new voice reference WAV and register it as a named profile."""
    if not name.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="Profile name must be alphanumeric (hyphens/underscores allowed)")
    if name == "default":
        raise HTTPException(status_code=400, detail="Use voices/default/reference.wav to update the default voice")
    if not file.filename or not file.filename.lower().endswith(".wav"):
        raise HTTPException(status_code=400, detail="Only WAV files are accepted")

    registry = _get_registry()
    dest = registry._profiles_dir / f"{name}.wav"

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)

    try:
        validate_and_save(tmp_path, dest)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    finally:
        tmp_path.unlink(missing_ok=True)

    return JSONResponse({"profile": name, "status": "created"}, status_code=201)


@router.delete("/{name}")
def delete_voice(name: str):
    """Delete a named voice profile."""
    registry = _get_registry()
    try:
        registry.delete_profile(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"profile": name, "status": "deleted"}
```

- [ ] **Step 3: Register router in `main.py`**

Find where other routers are included in `main.py`. Add:

```python
from app.api.routes.voices import router as voices_router
app.include_router(voices_router)
```

- [ ] **Step 4: Test voices endpoint manually**

```bash
cd tts-service
uvicorn app.main:app --port 8020 &
sleep 3
curl -s http://localhost:8020/voices | python -m json.tool
# Expected: {"profiles": ["default"], "count": 1}
kill %1
```

- [ ] **Step 5: Commit**

```bash
git add tts-service/app/services/voices/upload.py tts-service/app/api/routes/voices.py tts-service/app/main.py
git commit -m "feat(voices): voice upload API — POST /voices/upload, GET /voices, DELETE /voices/{name}"
```

---

## Task 6: Schema + health + tts_job wiring

**Files:**
- Modify: `tts-service/app/models/schemas.py`
- Modify: `tts-service/app/api/routes/health.py`
- Modify: `tts-service/app/services/tts_job.py`
- Delete: `tts-service/app/services/storage.py`

- [ ] **Step 1: Add `voice_profile` to `GenerateRequest` in `schemas.py`**

Find `GenerateRequest` class. Add one field:

```python
voice_profile: str = "default"  # Name of voice profile to use for cloning
```

- [ ] **Step 2: Update `health.py`**

Remove the VQ token check (Fish Speech specific). Add hardware tier and selected models to health response. Find the health check function and add:

```python
from app.core.hardware import ENGINE_CONFIG

# Add to health response dict:
"hardware_tier": ENGINE_CONFIG.tier.value,
"tts_model": ENGINE_CONFIG.tts_model,
"llm_model": ENGINE_CONFIG.llm_model,
```

Remove any lines referencing `reference_vq_tokens` or `vq_tokens`.

- [ ] **Step 3: Update `tts_job.py` to use storage backend and voice profile**

Find where `tts_job.py` uploads to GCS (calls `upload_to_gcs()`) and where it selects the voice path. Replace:

```python
# OLD: hardcoded GCS upload
from app.services.storage import upload_to_gcs
gcs_uri = await upload_to_gcs(output_path, job_id, site_slug)

# NEW: pluggable storage backend
from app.services.storage import get_storage_backend
backend = get_storage_backend()
audio_uri = await backend.upload(output_path, job_id, site_slug)
```

Replace voice path resolution:
```python
# OLD: hardcoded VOICE_SAMPLE_PATH
from app.config import VOICE_SAMPLE_PATH
voice_path = Path(VOICE_SAMPLE_PATH)

# NEW: resolve from VoiceRegistry using job's voice_profile
from app.services.voices.registry import VoiceRegistry
from app.config import VOICE_SAMPLE_PATH
voices_dir = Path(VOICE_SAMPLE_PATH).parent.parent
registry = VoiceRegistry(voices_dir)
voice_path = registry.resolve(job.voice_profile or "default")
```

Replace `gcs_uri` field in callback notification with `audio_uri`:
```python
# OLD: payload["gcs_uri"] = gcs_uri
# NEW:
payload["audio_uri"] = audio_uri
# Keep gcs_uri for backward compat during transition:
payload["gcs_uri"] = audio_uri
```

- [ ] **Step 4: Delete old `storage.py`**

```bash
rm tts-service/app/services/storage.py
```

Fix any remaining import of `from app.services.storage import` across the codebase:

```bash
grep -r "from app.services.storage import" tts-service/app/ --include="*.py"
```

Each one should import from `app.services.storage` (the package `__init__.py`) instead — which already works.

- [ ] **Step 5: Run full test suite**

```bash
cd tts-service
python -m pytest tests/ -v --tb=short
```
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add tts-service/app/models/schemas.py tts-service/app/api/routes/health.py tts-service/app/services/tts_job.py
git rm tts-service/app/services/storage.py
git commit -m "feat(storage+voices): wire storage backend and voice profiles into job pipeline"
```

---

## Task 7: Final Plan B verification

- [ ] **Step 1: Run full test suite**

```bash
cd tts-service
python -m pytest tests/ -v --tb=short
```
Expected: all pass

- [ ] **Step 2: Verify storage factory for all backends**

```bash
cd tts-service
STORAGE_BACKEND=local python -c "from app.services.storage import get_storage_backend; b = get_storage_backend(); print(type(b).__name__)"
# Expected: LocalStorage

STORAGE_BACKEND=gcs GCS_BUCKET_NAME=test python -c "from app.services.storage import get_storage_backend; b = get_storage_backend(); print(type(b).__name__)"
# Expected: GCSStorage

STORAGE_BACKEND=s3 S3_BUCKET_NAME=test AWS_ACCESS_KEY_ID=x AWS_SECRET_ACCESS_KEY=x python -c "from app.services.storage import get_storage_backend; b = get_storage_backend(); print(type(b).__name__)"
# Expected: S3Storage
```

- [ ] **Step 3: Commit**

```bash
git commit -m "chore(plan-b): Plan B complete — storage backends, voice profiles, API routes"
```
