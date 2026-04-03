"""Storage backend implementations - backward compatibility layer."""

from app.domains.storage import (
    StorageBackend,
    LocalStorageBackend,
    GCSStorageBackend,
    S3StorageBackend,
)

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
]
