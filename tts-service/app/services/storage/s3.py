"""S3Storage backend - backward compatibility layer."""

from app.domains.storage.s3 import S3StorageBackend


S3Storage = S3StorageBackend
