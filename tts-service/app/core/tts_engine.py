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

"""Qwen3-TTS engine wrapper with voice cloning and pre-computed reference caching."""

from __future__ import annotations

import asyncio
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
except ImportError:
    QwenTTS = None  # type: ignore[assignment,misc]
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
                    instance._synthesis_lock = (
                        threading.Lock()
                    )  # serialises GPU inference
                    instance._cancelled_jobs: set[str] = set()
                    instance._cached_voice_path: Optional[str] = (
                        None  # pre-computed voice cache
                    )
                    cls._instance = instance
        return cls._instance

    def initialize(self) -> None:
        """Load Qwen3-TTS model into memory and pre-compute voice reference.

        Called once at startup. Caches the default voice reference embedding
        so per-job synthesis doesn't repeat the expensive load_reference call.
        """
        with self._lock:
            if self._ready:
                return
            if QwenTTS is None:
                raise TTSEngineError(
                    "qwen-tts package not installed. Install with: pip install qwen-tts"
                )
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
                # Pre-compute and cache the default voice reference embedding
                from app.config import VOICE_SAMPLE_PATH

                voice_path = Path(VOICE_SAMPLE_PATH)
                if voice_path.exists():
                    logger.info("Pre-computing voice reference: %s", voice_path)
                    self._model.load_reference(str(voice_path))
                    self._cached_voice_path = str(voice_path)
                    logger.info("Voice reference cached in VRAM")
                else:
                    logger.warning(
                        "Voice sample not found at %s — will load per-job",
                        voice_path,
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
            with self._synthesis_lock:
                # Only reload voice reference if it's different from the cached one
                voice_path_str = str(voice_path)
                if voice_path_str != self._cached_voice_path:
                    self._model.load_reference(voice_path_str)
                    self._cached_voice_path = voice_path_str
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
_engine_ready_event: Optional[asyncio.Event] = None
_event_lock = threading.Lock()


def get_engine_ready_event() -> asyncio.Event:
    """Return an asyncio.Event that is set when the TTS engine is ready."""
    global _engine_ready_event
    with _event_lock:
        if _engine_ready_event is None:
            _engine_ready_event = asyncio.Event()
        return _engine_ready_event


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
    # Signal any coroutines waiting on engine readiness
    try:
        event = get_engine_ready_event()
        # The event must be set from the event loop thread, so we use call_soon_threadsafe
        # However, since this is called from the main thread during lifespan, we can set directly
        if not event.is_set():
            event.set()
    except RuntimeError:
        # No running event loop yet — will be set on first job's check
        pass
