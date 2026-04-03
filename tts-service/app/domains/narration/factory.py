"""Narration domain factory for creating strategy instances."""

from __future__ import annotations

from app.domains.narration.strategy import ChunkedStrategy, SingleShotStrategy
from app.config import LLM_MODEL_NAME, get_llm_client


def get_narration_strategy():
    """Return the NarrationStrategy for the current hardware tier."""
    from app.core.hardware import ENGINE_CONFIG, HardwareTier

    client = get_llm_client()
    tier = ENGINE_CONFIG.tier
    if ENGINE_CONFIG.narration_strategy == 'chunked':
        return ChunkedStrategy(
            llm_client=client,
            chunk_words=ENGINE_CONFIG.narration_chunk_words,
            tier=tier,
            model=LLM_MODEL_NAME,
        )
    return SingleShotStrategy(
        llm_client=client,
        fallback_threshold_words=3000 if tier == HardwareTier.MID_VRAM else 999999,
        fallback_chunk_words=ENGINE_CONFIG.narration_chunk_words,
        tier=tier,
        model=LLM_MODEL_NAME,
    )
