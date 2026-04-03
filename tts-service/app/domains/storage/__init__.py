from app.domains.storage.base import StorageBackend
from app.domains.storage.local import LocalStorageBackend
from app.domains.storage.gcs import GCSStorageBackend
from app.domains.storage.s3 import S3StorageBackend


def get_storage_backend(config: dict = None) -> StorageBackend:
    """Factory function to get appropriate storage backend."""
    storage_type = (config or {}).get('type', 'local')

    if storage_type == 'local':
        return LocalStorageBackend(config or {})
    elif storage_type == 'gcs':
        return GCSStorageBackend(config or {})
    elif storage_type == 's3':
        return S3StorageBackend(config or {})
    else:
        raise ValueError(f'Unknown storage type: {storage_type}')


__all__ = [
    'StorageBackend',
    'LocalStorageBackend',
    'GCSStorageBackend',
    'S3StorageBackend',
    'get_storage_backend',
]
