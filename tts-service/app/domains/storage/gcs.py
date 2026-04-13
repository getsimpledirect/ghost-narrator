# MIT License
#
# Copyright (c) 2026 Ayush Naik
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""GCSStorage backend — uploads to Google Cloud Storage."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from app.domains.storage.base import StorageBackend
from app.core.exceptions import StorageUploadError
from app.config import (
    GCS_BUCKET_NAME,
    GCS_AUDIO_PREFIX,
    GCS_SERVICE_ACCOUNT_KEY_PATH,
    MAX_RETRIES,
    GCS_UPLOAD_TIMEOUT,
)

logger = logging.getLogger(__name__)


class GCSStorageBackend(StorageBackend):
    def __init__(self, config: Optional[dict] = None) -> None:
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google.cloud import storage

            if GCS_SERVICE_ACCOUNT_KEY_PATH:
                self._client = storage.Client.from_service_account_json(
                    GCS_SERVICE_ACCOUNT_KEY_PATH
                )
            else:
                self._client = storage.Client()
        return self._client

    async def upload(
        self, local_path: Path, job_id: str, site_slug: str, storage_path: str = None
    ) -> str:
        if not GCS_BUCKET_NAME:
            raise StorageUploadError('GCS_BUCKET_NAME is not configured — set it in your .env file')

        # Use provided storage_path if available, otherwise use default
        if storage_path:
            # Remove leading/trailing slashes and ensure .mp3 extension
            blob_path = storage_path.strip('/')
            if not blob_path.endswith('.mp3'):
                blob_path += '.mp3'
        else:
            blob_path = f'{GCS_AUDIO_PREFIX}/{site_slug}/{job_id}.mp3'

        uri = f'gs://{GCS_BUCKET_NAME}/{blob_path}'
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                client = self._get_client()
                bucket = client.bucket(GCS_BUCKET_NAME)
                blob = bucket.blob(blob_path)
                await asyncio.to_thread(
                    blob.upload_from_filename,
                    str(local_path),
                    content_type='audio/mpeg',
                    timeout=GCS_UPLOAD_TIMEOUT,
                )
                logger.info('GCS upload complete: %s', uri)
                return uri
            except Exception as e:
                if attempt == MAX_RETRIES:
                    raise StorageUploadError(
                        f'GCS upload failed after {MAX_RETRIES} attempts: {e}'
                    ) from e
                wait = 2**attempt
                logger.warning(
                    'GCS upload attempt %d failed (%s) — retrying in %ds',
                    attempt,
                    e,
                    wait,
                )
                await asyncio.sleep(wait)
        return uri

    def make_public_url(self, audio_uri: str) -> str:
        path = audio_uri.removeprefix('gs://')
        return f'https://storage.googleapis.com/{path}'
