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

"""Hardware detection and engine configuration for tiered model selection."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, replace
from enum import Enum
from typing import Optional

try:
    import torch

    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False
    torch = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_GB = 1024**3


class HardwareTier(str, Enum):
    CPU_ONLY = 'cpu_only'
    LOW_VRAM = 'low_vram'
    MID_VRAM = 'mid_vram'
    HIGH_VRAM = 'high_vram'


@dataclass
class EngineConfig:
    tier: HardwareTier
    tts_model: str
    tts_device: str
    tts_precision: str  # "fp32" or "fp16"
    llm_model: str
    llm_num_ctx: int  # Ollama context window (prompt + response tokens)
    narration_strategy: str  # "chunked" or "single_shot"
    narration_chunk_words: int  # LLM narration chunk size
    tts_chunk_words: int  # TTS synthesis chunk size
    synthesis_workers: int
    mp3_bitrate: str
    sample_rate: int
    target_lufs: float
    # TTS generation parameters (passed to generate_voice_clone as **kwargs)
    tts_temperature: float
    tts_repetition_penalty: float
    tts_top_k: int
    tts_top_p: float
    tts_temperature_sub_talker: float
    tts_top_k_sub_talker: int
    tts_do_sample_sub_talker: bool
    tts_max_new_tokens: int


_TIER_CONFIGS: dict[HardwareTier, EngineConfig] = {
    HardwareTier.CPU_ONLY: EngineConfig(
        tier=HardwareTier.CPU_ONLY,
        tts_model='Qwen/Qwen3-TTS-12Hz-0.6B-Base',
        tts_device='cpu',
        tts_precision='fp32',
        llm_model='qwen3.5:2b',
        llm_num_ctx=4096,
        narration_strategy='chunked',
        narration_chunk_words=500,
        tts_chunk_words=200,  # Increased for smoother flow
        synthesis_workers=4,
        mp3_bitrate='192k',
        sample_rate=48000,  # Higher fidelity
        target_lufs=-16.0,
        tts_temperature=0.3,
        tts_repetition_penalty=1.05,
        tts_top_k=40,
        tts_top_p=0.85,
        tts_temperature_sub_talker=0.3,
        tts_top_k_sub_talker=40,
        tts_do_sample_sub_talker=True,
        tts_max_new_tokens=4500,  # 0.6B noise ceiling 300 words × 5.54 = 1662 tokens; 4500 = 2.7× headroom
    ),
    HardwareTier.LOW_VRAM: EngineConfig(
        tier=HardwareTier.LOW_VRAM,
        tts_model='Qwen/Qwen3-TTS-12Hz-0.6B-Base',
        tts_device='cuda',
        tts_precision='fp32',  # fp16 overflows on older GPUs → inf/nan logits; 0.6B fp32 = ~1.2 GB VRAM
        llm_model='qwen3.5:4b',
        llm_num_ctx=4096,
        narration_strategy='chunked',
        narration_chunk_words=500,
        tts_chunk_words=200,  # Increased for smoother flow
        synthesis_workers=1,
        mp3_bitrate='192k',
        sample_rate=48000,  # Higher fidelity
        target_lufs=-16.0,
        tts_temperature=0.3,
        tts_repetition_penalty=1.05,
        tts_top_k=40,
        tts_top_p=0.85,
        tts_temperature_sub_talker=0.3,
        tts_top_k_sub_talker=40,
        tts_do_sample_sub_talker=True,
        tts_max_new_tokens=4500,  # 0.6B noise ceiling 300 words × 5.54 = 1662 tokens; 4500 = 2.7× headroom
    ),
    HardwareTier.MID_VRAM: EngineConfig(
        tier=HardwareTier.MID_VRAM,
        tts_model='Qwen/Qwen3-TTS-12Hz-1.7B-Base',
        tts_device='cuda',
        tts_precision='fp16',
        # vLLM fp8: Qwen3.5-4B ≈ 4.25 GB — fits any 12–18 GB GPU alongside TTS (~5.1 GB runtime).
        llm_model='Qwen/Qwen3.5-4B',
        llm_num_ctx=8192,
        narration_strategy='single_shot',
        narration_chunk_words=400,  # 400 words ≈ 600 tokens; gives ~6000+ tokens for output
        tts_chunk_words=250,  # Increased for smoother flow
        synthesis_workers=1,
        mp3_bitrate='256k',  # Higher bitrate for studio quality
        sample_rate=48000,  # Higher fidelity
        target_lufs=-16.0,
        tts_temperature=0.3,
        tts_repetition_penalty=1.05,
        tts_top_k=40,
        tts_top_p=0.85,
        tts_temperature_sub_talker=0.3,
        tts_top_k_sub_talker=40,
        tts_do_sample_sub_talker=True,
        tts_max_new_tokens=7000,  # 650 words × 5.54 tok/word = 3601 tokens; 7000 = 1.94× headroom
    ),
    HardwareTier.HIGH_VRAM: EngineConfig(
        tier=HardwareTier.HIGH_VRAM,
        tts_model='Qwen/Qwen3-TTS-12Hz-1.7B-Base',
        tts_device='cuda',
        tts_precision='bf16',  # bf16: 1.5-2x faster on Tensor Core GPUs, imperceptible quality diff
        # vLLM fp8: Qwen3.5-9B ≈ 9.7 GB weights + fp8 KV ≈ 4.8 GB at 65 K tokens = 14.5 GB;
        # leaves ~3.5 GB headroom on 24 GB L4 alongside TTS (~5.1 GB runtime).
        llm_model='Qwen/Qwen3.5-9B',
        llm_num_ctx=65536,
        narration_strategy='single_shot',  # qwen3.5:9b narrates whole articles ≤8000 words in one call
        narration_chunk_words=4000,  # fallback chunk size when article > 8000 words
        tts_chunk_words=300,  # Larger chunks = fewer boundaries = smoother flow
        synthesis_workers=1,  # GPU synthesis is serial — gpu semaphore + _synthesis_lock
        mp3_bitrate='320k',  # Studio quality
        sample_rate=48000,  # Studio quality
        target_lufs=-14.0,  # Slightly louder for podcasts
        tts_temperature=0.3,
        tts_repetition_penalty=1.05,
        tts_top_k=40,
        tts_top_p=0.85,
        tts_temperature_sub_talker=0.3,
        tts_top_k_sub_talker=40,
        tts_do_sample_sub_talker=True,
        tts_max_new_tokens=7000,  # 650 words × 5.54 tok/word = 3601 tokens; 7000 = 1.94× headroom
    ),
}


# ── Dynamic segment sizing ──────────────────────────────────────────────────────
# Probed once in TTSEngine.initialize() after torch.compile() so free VRAM
# reflects the true runtime budget: both models + compile scratch loaded.
#
# Formula:  codec_budget = (free_vram - headroom) / BYTES_PER_CODEC_TOKEN
#           seg_words    = min(noise_ceiling, codec_budget / CODEC_TOKENS_PER_WORD)
#
# At 12 Hz and 130 WPM: 1 word ≈ 0.46 s ≈ 5.54 codec tokens.
# Empirical noise ceiling: model context overflow above this word count → artifacts.
_BYTES_PER_CODEC_TOKEN: int = 150_000  # 150 KB/token — Qwen3-TTS KV cache (conservative)
_CODEC_TOKENS_PER_WORD: float = 5.54  # 12 Hz × (60 s / 130 WPM)
_VRAM_SAFETY_HEADROOM: int = 512 * 1024 * 1024  # 512 MiB reserved for CUDA context

# Empirical quality ceilings per model family — above these word counts the
# codec context window fills up and the model produces noise or repetition.
_NOISE_CEILING: dict[str, int] = {
    '1.7B': 650,  # Qwen3-TTS-12Hz-1.7B-Base (hard limit ~700; conservative)
    '0.6B': 300,  # Qwen3-TTS-12Hz-0.6B-Base (hard limit ~400; conservative)
}
_DEFAULT_NOISE_CEILING: int = 400  # safe fallback for unrecognised models

_optimal_segment_words: Optional[int] = None


def _get_noise_ceiling(model_id: str) -> int:
    for key, ceiling in _NOISE_CEILING.items():
        if key in model_id:
            return ceiling
    return _DEFAULT_NOISE_CEILING


def probe_optimal_segment_words(model_id: str) -> int:
    """Compute and cache the optimal single-shot segment size from free VRAM.

    Called once from TTSEngine.initialize() after model load + torch.compile().
    Clamps between 200 (min useful quality) and the empirical noise ceiling for
    the loaded model. On CPU or when CUDA is unavailable, returns the noise ceiling.
    """
    global _optimal_segment_words
    try:
        noise_ceiling = _get_noise_ceiling(model_id)
        if torch is None or not torch.cuda.is_available():
            _optimal_segment_words = noise_ceiling
            logger.info('Optimal segment words (CPU): %d (noise ceiling)', noise_ceiling)
            return _optimal_segment_words

        free_vram, _ = torch.cuda.mem_get_info(0)
        available = max(0, free_vram - _VRAM_SAFETY_HEADROOM)
        codec_budget = available // _BYTES_PER_CODEC_TOKEN
        vram_words = int(codec_budget / _CODEC_TOKENS_PER_WORD)
        optimal = max(200, min(noise_ceiling, vram_words))
        _optimal_segment_words = optimal
        logger.info(
            'Optimal segment words probed: %d '
            '(free=%.1f GiB, codec_budget=%d tok, noise_ceiling=%d words)',
            optimal,
            free_vram / (1024**3),
            codec_budget,
            noise_ceiling,
        )
    except Exception as exc:
        logger.warning(
            'Segment probe failed (non-fatal): %s — using noise ceiling for %s', exc, model_id
        )
        _optimal_segment_words = _get_noise_ceiling(model_id)
    return _optimal_segment_words


def get_optimal_segment_words() -> int:
    """Return the optimal single-shot segment word count.

    Priority:
      1. SINGLE_SHOT_SEGMENT_WORDS env var (explicit user override)
      2. Probed value from probe_optimal_segment_words() (set at startup)
      3. Hardcoded fallback of 400 (safe for all GPU tiers before probe runs)
    """
    env_val = os.environ.get('SINGLE_SHOT_SEGMENT_WORDS', '').strip()
    if env_val.isdigit():
        return max(100, min(700, int(env_val)))
    if _optimal_segment_words is not None:
        return _optimal_segment_words
    return 400


def _probe_tier() -> HardwareTier:
    """Probe hardware and return the appropriate tier."""
    if torch is None or not torch.cuda.is_available():
        logger.info('No CUDA device detected — using CPU_ONLY tier')
        return HardwareTier.CPU_ONLY
    vram = torch.cuda.get_device_properties(0).total_memory
    vram_gb = vram / _GB
    logger.info('CUDA device detected — %.1f GB VRAM', vram_gb)
    if vram_gb < 12:
        return HardwareTier.LOW_VRAM
    if vram_gb < 18:
        return HardwareTier.MID_VRAM
    return HardwareTier.HIGH_VRAM


def get_engine_config() -> EngineConfig:
    """Return EngineConfig for this machine.

    Tier is selected by HARDWARE_TIER env var (written by hardware-probe.sh) or
    auto-probed. Model names are then resolved from SELECTED_TTS_MODEL /
    SELECTED_LLM_MODEL env vars (also written by hardware-probe.sh), falling back
    to _TIER_CONFIGS defaults so local dev without the init container still works.
    """
    override = os.environ.get('HARDWARE_TIER', '').strip().lower()
    if override:
        try:
            tier = HardwareTier(override)
            logger.info('HARDWARE_TIER override: %s', tier.value)
        except ValueError:
            logger.warning('Invalid HARDWARE_TIER=%r — probing hardware instead', override)
            tier = _probe_tier()
    else:
        tier = _probe_tier()

    config = _TIER_CONFIGS[tier]
    tts_model = os.environ.get('SELECTED_TTS_MODEL', '').strip() or config.tts_model
    llm_model = os.environ.get('SELECTED_LLM_MODEL', '').strip() or config.llm_model
    llm_num_ctx_env = os.environ.get('SELECTED_LLM_NUM_CTX', '').strip()
    llm_num_ctx = int(llm_num_ctx_env) if llm_num_ctx_env.isdigit() else config.llm_num_ctx
    overrides = {}
    if tts_model != config.tts_model:
        overrides['tts_model'] = tts_model
    if llm_model != config.llm_model:
        overrides['llm_model'] = llm_model
    if llm_num_ctx != config.llm_num_ctx:
        overrides['llm_num_ctx'] = llm_num_ctx
    if overrides:
        logger.info('Env overrides — %s', ', '.join(f'{k}: {v}' for k, v in overrides.items()))
        config = replace(config, **overrides)
    return config


# Module-level singleton — computed once at import time
ENGINE_CONFIG: EngineConfig = get_engine_config()


@dataclass
class HardwareInfo:
    tier: HardwareTier
    has_gpu: bool
    vram_gb: float = 0.0


def get_hardware_info() -> HardwareInfo:
    """Get hardware information for health checks."""
    has_gpu = _TORCH_AVAILABLE and torch.cuda.is_available()
    vram_gb = 0.0
    if has_gpu:
        vram_gb = torch.cuda.get_device_properties(0).total_memory / _GB
    return HardwareInfo(
        tier=ENGINE_CONFIG.tier,
        has_gpu=has_gpu,
        vram_gb=vram_gb,
    )
