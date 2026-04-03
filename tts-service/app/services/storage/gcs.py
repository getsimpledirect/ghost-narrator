"""GCSStorage backend - backward compatibility layer."""

from app.domains.storage.gcs import GCSStorageBackend


def __getattr__(name):
    if name == '_get_client':
        return GCSStorageBackend._get_client
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


GCSStorage = GCSStorageBackend
