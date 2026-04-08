from app.domains.storage.base import StorageBackend
from app.domains.storage.local import LocalStorageBackend
from app.domains.storage.gcs import GCSStorageBackend
from app.domains.storage.s3 import S3StorageBackend
from app.config import STORAGE_BACKEND


def get_storage_backend(config: dict = None) -> StorageBackend:
    """Factory function to get appropriate storage backend."""
    storage_type = (config or {}).get('type', STORAGE_BACKEND)

    if storage_type == 'local':
        return LocalStorageBackend(config or {})
    elif storage_type == 'gcs':
        return GCSStorageBackend(config or {})
    elif storage_type == 's3':
        return S3StorageBackend(config or {})
    else:
        raise ValueError(f'Unknown storage type: {storage_type}')


def get_gcs_client():
    """Backward compatibility - returns None (use StorageBackend instead)."""
    return None


def upload_to_gcs(local_path: str, gcs_object_path: str, content_type: str = 'audio/mpeg') -> str:
    """Backward compatibility - raises error (use StorageBackend instead)."""
    from app.core.exceptions import StorageError

    raise StorageError(
        'upload_to_gcs is deprecated. Use StorageBackend.upload() instead.',
        details='Migrate to the new pluggable storage backend system.',
    )


def is_gcs_enabled() -> bool:
    """Backward compatibility - check if GCS backend is selected."""
    return STORAGE_BACKEND.lower() == 'gcs'


def build_gcs_path(prefix: str, site_slug: str, job_id: str, extension: str = 'mp3') -> str:
    """Backward compatibility - build GCS object path."""
    prefix = prefix.strip('/')
    site_slug = site_slug.strip('/')
    job_id = job_id.strip('/')
    extension = extension.lstrip('.')
    return f'{prefix}/{site_slug}/{job_id}.{extension}'


def get_public_url(gcs_uri: str) -> str:
    """Backward compatibility - convert GCS URI to public URL."""
    if not gcs_uri.startswith('gs://'):
        raise ValueError(f'Invalid GCS URI format: {gcs_uri}')
    path = gcs_uri[5:]
    return f'https://storage.googleapis.com/{path}'


def initialize_gcs_client():
    """Backward compatibility - returns None (use StorageBackend instead)."""
    return None


def cleanup_gcs_client() -> None:
    """Backward compatibility - no-op (use StorageBackend instead)."""
    pass


# Aliases for backward compatibility
LocalStorage = LocalStorageBackend
GCSStorage = GCSStorageBackend
S3Storage = S3StorageBackend


__all__ = [
    'StorageBackend',
    'LocalStorageBackend',
    'GCSStorageBackend',
    'S3StorageBackend',
    'LocalStorage',
    'GCSStorage',
    'S3Storage',
    'get_storage_backend',
    'get_gcs_client',
    'upload_to_gcs',
    'is_gcs_enabled',
    'build_gcs_path',
    'get_public_url',
    'initialize_gcs_client',
    'cleanup_gcs_client',
]
