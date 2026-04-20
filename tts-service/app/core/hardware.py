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
        tts_max_new_tokens=4500,  # 400 words ≈ 2200 tokens at 12 Hz; 4500 = 2× headroom
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
        tts_max_new_tokens=4500,  # 400 words ≈ 2200 tokens at 12 Hz; 4500 = 2× headroom
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
        tts_max_new_tokens=4500,  # 400 words ≈ 2200 tokens at 12 Hz; 4500 = 2× headroom
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
        tts_max_new_tokens=4000,
    ),
}


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
