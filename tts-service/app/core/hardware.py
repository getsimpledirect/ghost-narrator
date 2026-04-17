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
        llm_model='qwen3:1.7b',
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
        tts_max_new_tokens=3000,
    ),
    HardwareTier.LOW_VRAM: EngineConfig(
        tier=HardwareTier.LOW_VRAM,
        tts_model='Qwen/Qwen3-TTS-12Hz-0.6B-Base',
        tts_device='cuda',
        tts_precision='fp32',  # fp16 overflows on older GPUs → inf/nan logits; 0.6B fp32 = ~1.2 GB VRAM
        llm_model='qwen3:4b',
        narration_strategy='chunked',
        narration_chunk_words=1000,
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
        tts_max_new_tokens=3000,  # 175 words ≈ 969 tokens; 3000 = 3.1× headroom
    ),
    HardwareTier.MID_VRAM: EngineConfig(
        tier=HardwareTier.MID_VRAM,
        tts_model='Qwen/Qwen3-TTS-12Hz-1.7B-Base',
        tts_device='cuda',
        tts_precision='fp16',
        llm_model='qwen3:8b',
        narration_strategy='single_shot',
        narration_chunk_words=2500,
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
        tts_max_new_tokens=3000,
    ),
    HardwareTier.HIGH_VRAM: EngineConfig(
        tier=HardwareTier.HIGH_VRAM,
        tts_model='Qwen/Qwen3-TTS-12Hz-1.7B-Base',
        tts_device='cuda',
        tts_precision='bf16',  # bf16: 1.5-2x faster on Tensor Core GPUs, imperceptible quality diff
        llm_model='qwen3:8b',  # sufficient for format-conversion narration at half the VRAM cost
        narration_strategy='chunked',  # chunked enables pipelined narrate+synthesize
        narration_chunk_words=2500,  # large chunks, pipelining hides latency
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
    if vram_gb < 10:
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
    if tts_model != config.tts_model or llm_model != config.llm_model:
        logger.info('Model overrides from env — tts: %s, llm: %s', tts_model, llm_model)
        config = replace(config, tts_model=tts_model, llm_model=llm_model)
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
