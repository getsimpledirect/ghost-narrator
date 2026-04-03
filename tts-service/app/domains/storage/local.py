"""LocalStorage backend — saves audio to a mounted output directory."""

from __future__ import annotations
import shutil
from pathlib import Path
from app.domains.storage.base import StorageBackend


class LocalStorageBackend(StorageBackend):
    def __init__(
        self,
        config: dict = None,
        output_dir: str = None,
        server_ip: str = None,
        port: int = None,
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
