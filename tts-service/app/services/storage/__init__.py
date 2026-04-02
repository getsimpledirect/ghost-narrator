"""Storage backend factory with backward compatibility."""

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
    raise ValueError(
        f"Unknown STORAGE_BACKEND={STORAGE_BACKEND!r}. Use: local, gcs, s3"
    )


# Backward-compatible functions for existing code
def get_gcs_client():
    """Backward compatibility - returns None (use StorageBackend instead)."""
    return None


def upload_to_gcs(
    local_path: str, gcs_object_path: str, content_type: str = "audio/mpeg"
) -> str:
    """Backward compatibility - raises error (use StorageBackend instead)."""
    from app.core.exceptions import StorageError

    raise StorageError(
        "upload_to_gcs is deprecated. Use StorageBackend.upload() instead.",
        details="Migrate to the new pluggable storage backend system.",
    )


def is_gcs_enabled() -> bool:
    """Backward compatibility - check if GCS backend is selected."""
    return STORAGE_BACKEND.lower() == "gcs"


def build_gcs_path(
    prefix: str, site_slug: str, job_id: str, extension: str = "mp3"
) -> str:
    """Backward compatibility - build GCS object path."""
    prefix = prefix.strip("/")
    site_slug = site_slug.strip("/")
    job_id = job_id.strip("/")
    extension = extension.lstrip(".")
    return f"{prefix}/{site_slug}/{job_id}.{extension}"


def get_public_url(gcs_uri: str) -> str:
    """Backward compatibility - convert GCS URI to public URL."""
    if not gcs_uri.startswith("gs://"):
        raise ValueError(f"Invalid GCS URI format: {gcs_uri}")
    path = gcs_uri[5:]
    return f"https://storage.googleapis.com/{path}"


def initialize_gcs_client():
    """Backward compatibility - returns None (use StorageBackend instead)."""
    return None


def cleanup_gcs_client() -> None:
    """Backward compatibility - no-op (use StorageBackend instead)."""
    pass
