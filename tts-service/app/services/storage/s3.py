"""S3Storage backend - backward compatibility layer."""

from app.domains.storage.s3 import S3StorageBackend

S3Storage = S3StorageBackend


def __getattr__(name):
    if name == '_bucket':
        return S3StorageBackend._bucket
    if name == '_region':
        return S3StorageBackend._region
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
