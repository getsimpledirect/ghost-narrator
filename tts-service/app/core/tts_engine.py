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

"""Qwen3-TTS engine wrapper — replaces Fish Speech v1.5."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from app.config import DEVICE, SELECTED_TTS_MODEL
from app.core.exceptions import SynthesisError, TTSEngineError, VoiceSampleNotFoundError

logger = logging.getLogger(__name__)

# ── Verify these imports match the installed qwen-tts package ─────────────────
# Run: python -c "import qwen_tts; print(qwen_tts.__version__)"
# Adjust import path if the package uses a different module name.
try:
    from qwen_tts import QwenTTS  # type: ignore[import]
except ImportError as e:
    raise ImportError(
        "qwen-tts package not found. Install with: pip install qwen-tts"
    ) from e
# ─────────────────────────────────────────────────────────────────────────────


class TTSEngine:
    """Singleton Qwen3-TTS engine with voice cloning support."""

    _instance: Optional["TTSEngine"] = None
    _init_lock = threading.Lock()

    def __new__(cls) -> "TTSEngine":
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._model: Optional[QwenTTS] = None
                    instance._ready = False
                    instance._lock = threading.Lock()
                    instance._cancelled_jobs: set[str] = set()
                    cls._instance = instance
        return cls._instance

    def initialize(self) -> None:
        """Load Qwen3-TTS model into memory. Called once at startup."""
        with self._lock:
            if self._ready:
                return
            from app.core.hardware import ENGINE_CONFIG

            logger.info(
                "Loading %s on %s (%s)",
                SELECTED_TTS_MODEL,
                DEVICE,
                ENGINE_CONFIG.tts_precision,
            )
            try:
                self._model = QwenTTS(
                    model_name=SELECTED_TTS_MODEL,
                    device=DEVICE,
                    dtype=ENGINE_CONFIG.tts_precision,
                )
                self._ready = True
                logger.info("Qwen3-TTS engine ready")
            except Exception as e:
                raise TTSEngineError(f"Failed to load Qwen3-TTS model: {e}") from e

    @property
    def is_ready(self) -> bool:
        return self._ready

    def synthesize_to_file(
        self,
        text: str,
        output_path: str | Path,
        voice_path_or_job_id: str | Path = "",
        job_id: str = "",
    ) -> str:
        """Synthesize text to WAV using voice_path as reference.

        Supports both old signature (text, output_path, job_id) and
        new signature (text, output_path, voice_path).
        """
        if not self._ready or self._model is None:
            raise TTSEngineError("Engine not initialized — call initialize() first")

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Determine voice_path from the argument
        from app.config import VOICE_SAMPLE_PATH

        voice_path = Path(VOICE_SAMPLE_PATH)
        actual_job_id = job_id

        if voice_path_or_job_id:
            vp = Path(str(voice_path_or_job_id))
            if vp.exists() and vp.suffix.lower() in (".wav", ".mp3"):
                voice_path = vp
            else:
                # It's a job_id string
                actual_job_id = str(voice_path_or_job_id)

        if not voice_path.exists():
            raise VoiceSampleNotFoundError(f"Voice sample not found: {voice_path}")
        if actual_job_id and actual_job_id in self._cancelled_jobs:
            raise SynthesisError(f"Job {actual_job_id} was cancelled")

        try:
            self._model.load_reference(str(voice_path))
            audio_data = self._model.synthesize(text)
            self._model.save_wav(audio_data, str(output_path))
            return str(output_path)
        except SynthesisError:
            raise
        except Exception as e:
            raise SynthesisError(f"Synthesis failed: {e}") from e
        finally:
            if actual_job_id:
                self._cancelled_jobs.discard(actual_job_id)

    def cancel_job(self, job_id: str) -> None:
        """Signal that the next synthesize_to_file call for this job_id should abort."""
        self._cancelled_jobs.add(job_id)


_engine: Optional[TTSEngine] = None
_engine_lock = threading.Lock()


def get_tts_engine() -> TTSEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = TTSEngine()
    return _engine


def initialize_tts_engine() -> None:
    """Initialize the TTS engine. Called from main.py lifespan."""
    engine = get_tts_engine()
    engine.initialize()
