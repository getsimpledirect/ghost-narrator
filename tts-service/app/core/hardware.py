"""Hardware detection and engine configuration for tiered model selection."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
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
    CPU_ONLY = "cpu_only"
    LOW_VRAM = "low_vram"
    MID_VRAM = "mid_vram"
    HIGH_VRAM = "high_vram"


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


_TIER_CONFIGS: dict[HardwareTier, EngineConfig] = {
    HardwareTier.CPU_ONLY: EngineConfig(
        tier=HardwareTier.CPU_ONLY,
        tts_model="Qwen/Qwen3-TTS-0.6B",
        tts_device="cpu",
        tts_precision="fp32",
        llm_model="qwen3:1.7b",
        narration_strategy="chunked",
        narration_chunk_words=500,
        tts_chunk_words=150,
        synthesis_workers=4,
        mp3_bitrate="192k",
        sample_rate=44100,
        target_lufs=-16.0,
    ),
    HardwareTier.LOW_VRAM: EngineConfig(
        tier=HardwareTier.LOW_VRAM,
        tts_model="Qwen/Qwen3-TTS-0.6B",
        tts_device="cuda",
        tts_precision="fp16",
        llm_model="qwen3:4b-q4",
        narration_strategy="chunked",
        narration_chunk_words=1000,
        tts_chunk_words=150,
        synthesis_workers=1,
        mp3_bitrate="192k",
        sample_rate=44100,
        target_lufs=-16.0,
    ),
    HardwareTier.MID_VRAM: EngineConfig(
        tier=HardwareTier.MID_VRAM,
        tts_model="Qwen/Qwen3-TTS-1.7B",
        tts_device="cuda",
        tts_precision="fp16",
        llm_model="qwen3:8b-q4",
        narration_strategy="single_shot",
        narration_chunk_words=2500,
        tts_chunk_words=200,
        synthesis_workers=1,
        mp3_bitrate="192k",
        sample_rate=44100,
        target_lufs=-16.0,
    ),
    HardwareTier.HIGH_VRAM: EngineConfig(
        tier=HardwareTier.HIGH_VRAM,
        tts_model="Qwen/Qwen3-TTS-1.7B",
        tts_device="cuda",
        tts_precision="fp32",  # fp32 for cleaner audio (have the VRAM)
        llm_model="qwen3:14b-q4",  # larger model for better narration
        narration_strategy="chunked",  # chunked enables pipelined narrate+synthesize
        narration_chunk_words=2500,  # large chunks, pipelining hides latency
        tts_chunk_words=200,
        synthesis_workers=2,  # parallel TTS on GPU (2 workers)
        mp3_bitrate="256k",
        sample_rate=48000,
        target_lufs=-14.0,
    ),
}


def _probe_tier() -> HardwareTier:
    """Probe hardware and return the appropriate tier."""
    if torch is None or not torch.cuda.is_available():
        logger.info("No CUDA device detected — using CPU_ONLY tier")
        return HardwareTier.CPU_ONLY
    vram = torch.cuda.get_device_properties(0).total_memory
    vram_gb = vram / _GB
    logger.info("CUDA device detected — %.1f GB VRAM", vram_gb)
    if vram_gb < 10:
        return HardwareTier.LOW_VRAM
    if vram_gb < 18:
        return HardwareTier.MID_VRAM
    return HardwareTier.HIGH_VRAM


def get_engine_config() -> EngineConfig:
    """Return EngineConfig for this machine. Respects HARDWARE_TIER env override."""
    override = os.environ.get("HARDWARE_TIER", "").strip().lower()
    if override:
        try:
            tier = HardwareTier(override)
            logger.info("HARDWARE_TIER override: %s", tier.value)
        except ValueError:
            logger.warning(
                "Invalid HARDWARE_TIER=%r — probing hardware instead", override
            )
            tier = _probe_tier()
    else:
        tier = _probe_tier()
    return _TIER_CONFIGS[tier]


# Module-level singleton — computed once at import time
ENGINE_CONFIG: EngineConfig = get_engine_config()
