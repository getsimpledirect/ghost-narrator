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

"""DeepFilterNet 2 speech-enhancement wrapper for post-synthesis cleanup.

Runs between segment concatenation and mastering. Removes the faint vocoded
texture and noise fingerprint that Qwen3-TTS output carries, pulling the
audio distribution closer to a clean-speech prior. Model is MIT-licensed,
runs real-time on CPU, GPU-accelerated on CUDA, and has no runtime deps
beyond torch/torchaudio (already in the image).

When the package is missing or the model fails to load, enhance_audio
falls back to copying the input to the output untouched — enhancement is
a quality pass, not a correctness prerequisite.
"""

from __future__ import annotations

import logging
import shutil
import threading
from typing import Any, Optional


logger = logging.getLogger(__name__)


# Sentinel: once the module load or model init fails, subsequent calls
# should skip without retrying on every segment.
_UNAVAILABLE = object()

_model: Any = None
_df_state: Any = None
_lock = threading.Lock()


def _resolve_device() -> str:
    """Tier-aware device selection matching the Whisper policy.

    CPU_ONLY tier keeps DeepFilterNet on CPU even if CUDA is visible —
    honouring the operator's intent. GPU tiers prefer CUDA for the
    ~5-10x speed-up on the post-synthesis enhancement pass.
    """
    try:
        from app.core.hardware import ENGINE_CONFIG, HardwareTier

        if ENGINE_CONFIG.tier == HardwareTier.CPU_ONLY:
            return 'cpu'
    except Exception:
        pass  # hardware module unavailable during tests; fall through
    try:
        import torch

        if torch.cuda.is_available():
            return 'cuda:0'
    except Exception:
        pass
    return 'cpu'


def _get_model() -> Optional[tuple[Any, Any]]:
    """Lazy-load the DeepFilterNet model. Returns (model, df_state) or None."""
    global _model, _df_state
    if _model is _UNAVAILABLE:
        return None
    if _model is not None and _df_state is not None:
        return _model, _df_state
    with _lock:
        if _model is _UNAVAILABLE:
            return None
        if _model is not None and _df_state is not None:
            return _model, _df_state
        try:
            from df.enhance import init_df  # type: ignore[import-not-found]
        except ImportError as exc:
            logger.warning(
                'DeepFilterNet package unavailable — enhancement disabled (%s)',
                exc,
            )
            _model = _UNAVAILABLE
            return None
        try:
            model, df_state, _ = init_df()
        except Exception as exc:
            logger.warning('DeepFilterNet model init failed — enhancement disabled (%s)', exc)
            _model = _UNAVAILABLE
            return None

        # init_df() picks a default device (usually CPU even on CUDA boxes
        # in some df versions). Explicitly move the model so it follows the
        # tier policy — if .to() fails on a CUDA device, fall back to CPU
        # rather than refusing to enhance at all.
        target_device = _resolve_device()
        try:
            model = model.to(target_device)
            actual_device = target_device
        except Exception as exc:
            logger.warning(
                'DeepFilterNet .to(%s) failed (%s) — staying on default device',
                target_device,
                exc,
            )
            actual_device = 'default'

        _model = model
        _df_state = df_state
        logger.info('DeepFilterNet loaded on %s (sr=%d)', actual_device, df_state.sr())
        return _model, _df_state


def is_available() -> bool:
    """True when enhancement is expected to apply for the next call."""
    return _get_model() is not None


def enhance_audio(input_path: str, output_path: Optional[str] = None) -> str:
    """Apply DeepFilterNet enhancement. Writes to output_path (defaults to input).

    When the model cannot be loaded or enhancement raises, falls back to a
    straight copy so the caller's pipeline continues with the unenhanced
    audio. The return value is always a path to a valid WAV file.
    """
    out = output_path or input_path
    pair = _get_model()
    if pair is None:
        if out != input_path:
            shutil.copy2(input_path, out)
        return out

    model, df_state = pair
    try:
        from df.enhance import enhance, load_audio, save_audio  # type: ignore[import-not-found]

        audio, _meta = load_audio(input_path, sr=df_state.sr())
        enhanced = enhance(model, df_state, audio)
        save_audio(out, enhanced, df_state.sr())
        logger.info('DeepFilterNet enhanced: %s', input_path)
    except Exception as exc:
        logger.warning(
            'DeepFilterNet enhancement failed on %s — using unenhanced audio: %s',
            input_path,
            exc,
        )
        if out != input_path:
            shutil.copy2(input_path, out)
    return out
