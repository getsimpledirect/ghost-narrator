"""S3Storage backend — uploads to AWS S3."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from app.domains.storage.base import StorageBackend
from app.core.exceptions import StorageUploadError
from app.config import (
    AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY,
    AWS_REGION,
    S3_BUCKET_NAME,
    S3_AUDIO_PREFIX,
    MAX_RETRIES,
)

logger = logging.getLogger(__name__)


class S3StorageBackend(StorageBackend):
    def __init__(self, config: Optional[dict] = None) -> None:
        self._bucket = S3_BUCKET_NAME
        self._region = AWS_REGION
        self._client = None

    def _get_client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client(
                's3',
                region_name=AWS_REGION,
                aws_access_key_id=AWS_ACCESS_KEY_ID or None,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY or None,
            )
        return self._client

    async def upload(self, local_path: Path, job_id: str, site_slug: str) -> str:
        key = f'{S3_AUDIO_PREFIX}/{site_slug}/{job_id}.mp3'
        uri = f's3://{self._bucket}/{key}'
        client = self._get_client()
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                await asyncio.to_thread(
                    client.upload_file,
                    str(local_path),
                    self._bucket,
                    key,
                    ExtraArgs={'ContentType': 'audio/mpeg'},
                )
                logger.info('S3 upload complete: %s', uri)
                return uri
            except Exception as e:
                if attempt == MAX_RETRIES:
                    raise StorageUploadError(
                        f'S3 upload failed after {MAX_RETRIES} attempts: {e}'
                    ) from e
                wait = 2**attempt
                logger.warning(
                    'S3 upload attempt %d failed (%s) — retrying in %ds',
                    attempt,
                    e,
                    wait,
                )
                await asyncio.sleep(wait)
        return uri

    def make_public_url(self, audio_uri: str) -> str:
        path = audio_uri.removeprefix(f's3://{self._bucket}/')
        return f'https://{self._bucket}.s3.{self._region}.amazonaws.com/{path}'
