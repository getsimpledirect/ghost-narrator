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
