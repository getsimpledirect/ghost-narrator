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

"""LocalStorage backend — saves audio to a mounted output directory."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from app.domains.storage.base import StorageBackend


class LocalStorageBackend(StorageBackend):
    def __init__(
        self,
        config: Optional[dict] = None,
        output_dir: Optional[str] = None,
        server_ip: Optional[str] = None,
        port: Optional[int] = None,
    ) -> None:
        config = config or {}
        from app.config import (
            OUTPUT_DIR as DEFAULT_OUTPUT_DIR,
            SERVER_EXTERNAL_IP as DEFAULT_SERVER_IP,
        )

        self._output_dir = Path(output_dir or config.get('output_dir', DEFAULT_OUTPUT_DIR))
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._server_ip = server_ip or config.get('server_ip', DEFAULT_SERVER_IP)
        self._port = port or config.get('port', 8020)

    async def upload(self, local_path: Path, job_id: str, site_slug: str) -> str:
        dest = self._output_dir / f'{job_id}.mp3'
        if local_path != dest:
            shutil.copy2(local_path, dest)
        return f'local://{job_id}.mp3'

    def make_public_url(self, audio_uri: str) -> str:
        job_id = audio_uri.removeprefix('local://').removesuffix('.mp3')
        return f'http://{self._server_ip}:{self._port}/tts/download/{job_id}'
