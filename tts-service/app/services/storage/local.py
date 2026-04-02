"""LocalStorage backend — saves audio to a mounted output directory."""

from __future__ import annotations
import shutil
from pathlib import Path
from app.services.storage.base import StorageBackend


class LocalStorage(StorageBackend):
    def __init__(self, output_dir: Path, server_ip: str, port: int = 8020) -> None:
        self._output_dir = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._server_ip = server_ip
        self._port = port

    async def upload(self, local_path: Path, job_id: str, site_slug: str) -> str:
        dest = self._output_dir / f"{job_id}.mp3"
        if local_path != dest:
            shutil.copy2(local_path, dest)
        return f"local://{job_id}.mp3"

    def make_public_url(self, audio_uri: str) -> str:
        job_id = audio_uri.removeprefix("local://").removesuffix(".mp3")
        return f"http://{self._server_ip}:{self._port}/tts/download/{job_id}"
