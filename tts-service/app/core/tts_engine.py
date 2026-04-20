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

from app.config import DEVICE, SELECTED_TTS_MODEL, VOICE_SAMPLE_REF_TEXT
from app.core.exceptions import SynthesisError, TTSEngineError, VoiceSampleNotFoundError

logger = logging.getLogger(__name__)

try:
    from qwen_tts import Qwen3TTSModel  # type: ignore[import]
except ImportError:
    Qwen3TTSModel = None  # type: ignore[assignment,misc]


class TTSEngine:
    """Singleton Qwen3-TTS engine with voice cloning support."""

    def initialize(self) -> None:
        """Load Qwen3-TTS model into memory and pre-compute voice reference.

        Called once at startup. Caches the default voice reference embedding
        so per-job synthesis doesn't repeat the expensive load_reference call.
        """
        with self._lock:
            if self._ready:
                return
            if Qwen3TTSModel is None:
                raise TTSEngineError(
                    'qwen-tts package not installed. Install with: pip install qwen-tts'
                )
            from app.core.hardware import ENGINE_CONFIG

            logger.info(
                'Loading %s on %s (%s)',
                SELECTED_TTS_MODEL,
                DEVICE,
                ENGINE_CONFIG.tts_precision,
            )
            try:
                import torch

                _PRECISION_MAP = {
                    'fp32': torch.float32,
                    'fp16': torch.float16,
                    'bf16': torch.bfloat16,
                }
                dtype = _PRECISION_MAP.get(ENGINE_CONFIG.tts_precision, torch.float32)
                self._model = Qwen3TTSModel.from_pretrained(
                    SELECTED_TTS_MODEL,
                    device_map=DEVICE,
                    dtype=dtype,
                )

                # Apply torch.compile() to Qwen3TTSModel's nn.Module sub-components.
                # Qwen3TTSModel is a Python wrapper class, not an nn.Module itself —
                # compiling the wrapper is a no-op. The real inference modules are
                # talker, code_predictor, and speaker_encoder; compile each individually.
                # First call on each sub-module incurs the 30-60s JIT penalty; all
                # subsequent calls get the 2-4× speedup. Skip on CPU — no benefit.
                try:
                    if hasattr(torch, 'compile') and torch.cuda.is_available():
                        _compiled_attrs: list[str] = []
                        for _attr in ('model', 'talker', 'code_predictor', 'speaker_encoder'):
                            _submod = getattr(self._model, _attr, None)
                            if isinstance(_submod, torch.nn.Module):
                                try:
                                    setattr(
                                        self._model, _attr, torch.compile(_submod, dynamic=True)
                                    )
                                    _compiled_attrs.append(_attr)
                                except Exception as _sub_exc:
                                    logger.debug(
                                        'torch.compile() on model.%s skipped: %s', _attr, _sub_exc
                                    )
                        if _compiled_attrs:
                            logger.info(
                                'torch.compile() applied to %s '
                                '(first-call penalty ~30-60s, subsequent calls 2-4× faster)',
                                ', '.join(_compiled_attrs),
                            )
                        else:
                            logger.warning(
                                'torch.compile() skipped — no compilable nn.Module sub-modules '
                                'found in Qwen3TTSModel (attrs: %s)',
                                [a for a in dir(self._model) if not a.startswith('_')],
                            )
                except Exception as compile_exc:
                    logger.warning(
                        'torch.compile() failed (non-fatal) — using eager mode: %s',
                        compile_exc,
                    )

                # Pre-compute and cache the default voice clone prompt
                from app.config import VOICE_SAMPLE_PATH

                voice_path = Path(VOICE_SAMPLE_PATH)
                if voice_path.exists():
                    logger.info('Pre-computing voice clone prompt: %s', voice_path)
                    # Use ICL mode when a reference transcription is provided (better quality).
                    # Fall back to x-vector-only mode when ref_text is empty — ICL mode
                    # raises an error if ref_text is empty or missing.
                    use_x_vector_only = not bool(VOICE_SAMPLE_REF_TEXT)
                    self._cached_voice_prompt = self._model.create_voice_clone_prompt(
                        str(voice_path),
                        ref_text=VOICE_SAMPLE_REF_TEXT,
                        x_vector_only_mode=use_x_vector_only,
                    )
                    self._cached_voice_path = str(voice_path)
                    logger.info(
                        'Voice clone prompt cached (mode: %s)',
                        'x-vector-only' if use_x_vector_only else 'ICL',
                    )
                else:
                    logger.warning(
                        'Voice sample not found at %s — will load per-job',
                        voice_path,
                    )

                # Enable cuDNN deterministic mode for reproducible synthesis.
                # deterministic=True forces cuDNN to use the same algorithm for
                # the same input shapes; benchmark=False stops cuDNN from running
                # a benchmark pass (which selects non-deterministic fast paths).
                # Both are set once at init and persist for the process lifetime.
                try:
                    if torch.cuda.is_available():
                        torch.backends.cudnn.deterministic = True
                        torch.backends.cudnn.benchmark = False
                        logger.info('cuDNN deterministic mode enabled')
                except Exception as _cudnn_exc:
                    logger.warning('cuDNN determinism setup failed (non-fatal): %s', _cudnn_exc)

                self._ready = True
                logger.info('Qwen3-TTS engine ready')
            except Exception as e:
                raise TTSEngineError(f'Failed to load Qwen3-TTS model: {e}') from e

    @property
    def is_ready(self) -> bool:
        return self._ready

    def synthesize_to_file(
        self,
        text: str,
        output_path: str | Path,
        voice_path_or_job_id: str | Path = '',
        job_id: str = '',
        generation_kwargs: Optional[dict] = None,
        voice_override: Optional[str] = None,
    ) -> str:
        """Synthesize text to WAV using voice_path as reference.

        Supports both old signature (text, output_path, job_id) and
        new signature (text, output_path, voice_path).

        Args:
            generation_kwargs: Extra kwargs forwarded to generate_voice_clone
                (temperature, repetition_penalty, top_k, top_p,
                temperature_sub_talker, top_k_sub_talker, do_sample_sub_talker,
                max_new_tokens, seed). Merged on top of tier defaults at call time.
            voice_override: Explicit WAV path for voice conditioning (e.g. tail of
                previous segment). Takes priority over voice_path_or_job_id and the
                VOICE_SAMPLE_PATH default.
        """
        if not self._ready or self._model is None:
            raise TTSEngineError('Engine not initialized — call initialize() first')

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Determine voice_path — voice_override (tail conditioning) wins over defaults
        from app.config import VOICE_SAMPLE_PATH

        actual_job_id = job_id
        if voice_override:
            voice_path = Path(voice_override)
            # voice_path_or_job_id is treated as job_id only when voice_override is set
            if voice_path_or_job_id and not Path(str(voice_path_or_job_id)).exists():
                actual_job_id = str(voice_path_or_job_id)
        else:
            voice_path = Path(VOICE_SAMPLE_PATH)
            if voice_path_or_job_id:
                vp = Path(str(voice_path_or_job_id))
                if vp.exists() and vp.suffix.lower() in ('.wav', '.mp3'):
                    voice_path = vp
                else:
                    actual_job_id = str(voice_path_or_job_id)

        if not voice_path.exists():
            raise VoiceSampleNotFoundError(f'Voice sample not found: {voice_path}')

        try:
            import soundfile as sf
            from app.config import TTS_LANGUAGE

            if actual_job_id and actual_job_id in self._cancelled_jobs:
                raise SynthesisError(f'Job {actual_job_id} was cancelled')

            with self._synthesis_lock:
                voice_path_str = str(voice_path)
                # Reuse cached prompt if same voice, otherwise create a new one.
                # Tail-conditioning passes a fresh WAV each call — cache will miss,
                # but create_voice_clone_prompt is fast (~0.5s) vs synthesis (~30s).
                if (
                    voice_path_str == self._cached_voice_path
                    and self._cached_voice_prompt is not None
                ):
                    prompt = self._cached_voice_prompt
                else:
                    use_x_vector_only = not bool(VOICE_SAMPLE_REF_TEXT)
                    prompt = self._model.create_voice_clone_prompt(
                        voice_path_str,
                        ref_text=VOICE_SAMPLE_REF_TEXT,
                        x_vector_only_mode=use_x_vector_only,
                    )
                    # Only cache default voice — tail WAVs change every segment
                    if not voice_override:
                        self._cached_voice_prompt = prompt
                        self._cached_voice_path = voice_path_str
                # Strip None values; extract seed before forwarding to the model
                gen_kw = {k: v for k, v in (generation_kwargs or {}).items() if v is not None}
                seed = gen_kw.pop('seed', None)
                if seed is not None:
                    try:
                        import random as _random

                        import numpy as _np
                        import torch as _torch

                        _seed_int = int(seed)
                        _random.seed(_seed_int)
                        _np.random.seed(_seed_int % (2**32))
                        _torch.manual_seed(_seed_int)
                        if _torch.cuda.is_available():
                            _torch.cuda.manual_seed_all(_seed_int)
                    except Exception:
                        pass
                try:
                    wavs, sr = self._model.generate_voice_clone(
                        text=text,
                        language=TTS_LANGUAGE,
                        voice_clone_prompt=prompt,
                        **gen_kw,
                    )
                except RuntimeError as exc:
                    # fp16 logits can overflow to inf/nan on older GPUs, causing
                    # "probability tensor contains either inf, nan or element < 0".
                    # Cast model to fp32 and retry once — permanent for this session
                    # since the model stays fp32, but safe because fp32 works on all CUDA GPUs.
                    if 'probability tensor' not in str(exc):
                        raise
                    import torch

                    logger.warning(
                        'fp16 NaN/inf detected during synthesis — casting model to fp32 and retrying'
                    )
                    self._model = self._model.to(torch.float32)
                    # Invalidate cached voice prompt: it was computed under fp16 weights
                    self._cached_voice_prompt = None
                    self._cached_voice_path = None
                    use_x_vector_only = not bool(VOICE_SAMPLE_REF_TEXT)
                    prompt = self._model.create_voice_clone_prompt(
                        voice_path_str,
                        ref_text=VOICE_SAMPLE_REF_TEXT,
                        x_vector_only_mode=use_x_vector_only,
                    )
                    self._cached_voice_prompt = prompt
                    self._cached_voice_path = voice_path_str
                    wavs, sr = self._model.generate_voice_clone(
                        text=text,
                        language=TTS_LANGUAGE,
                        voice_clone_prompt=prompt,
                        **gen_kw,
                    )
                sf.write(str(output_path), wavs[0], sr)
            # Discard cancel flag only on success — if synthesis raised SynthesisError
            # (including the cancellation case) the flag must survive so subsequent
            # segments / retries for the same job also abort immediately.
            if actual_job_id:
                self._cancelled_jobs.discard(actual_job_id)
            return str(output_path)
        except SynthesisError:
            raise
        except Exception as e:
            raise SynthesisError(f'Synthesis failed: {e}') from e

    def cancel_job(self, job_id: str) -> None:
        """Signal that the next synthesize_to_file call for this job_id should abort."""
        self._cancelled_jobs.add(job_id)

    def uncancel_job(self, job_id: str) -> None:
        """Clear any stale cancel flag for job_id before a fresh submission."""
        self._cancelled_jobs.discard(job_id)


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
            _engine = object.__new__(TTSEngine)
            _engine._model: Optional[Qwen3TTSModel] = None
            _engine._ready = False
            _engine._lock = threading.Lock()
            _engine._synthesis_lock = threading.Lock()
            _engine._cancelled_jobs: set[str] = set()
            _engine._cached_voice_path: Optional[str] = None
            _engine._cached_voice_prompt = None
    return _engine


def initialize_tts_engine() -> None:
    """Initialize the TTS engine. Called via loop.run_in_executor from main.py lifespan.

    NOTE: Do NOT call get_engine_ready_event().set() here. This function runs in a
    ThreadPoolExecutor worker thread; asyncio.Event is not thread-safe. The ready event
    is set by the async caller (_background_model_loader in main.py) after this function
    returns, ensuring event.set() is called from the event loop thread.
    """
    engine = get_tts_engine()
    engine.initialize()
