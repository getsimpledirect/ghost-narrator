"""GCSStorage backend - backward compatibility layer."""

from app.domains.storage.gcs import GCSStorageBackend


GCSStorage = GCSStorageBackend

# Expose _get_client properly for tests
GCSStorage._get_client = GCSStorageBackend._get_client
