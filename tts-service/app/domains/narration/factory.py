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
