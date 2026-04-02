"""Tier-specific system prompts for narration script generation."""

from __future__ import annotations

from app.core.hardware import HardwareTier


_BASE_PROMPT = """You are converting written article content into spoken audio narration for a podcast.

RULES:
- This is a FORMAT CONVERSION, not a rewrite or summary
- DO NOT skip, condense, or omit any information
- Every fact, statistic, quote, and argument must appear in your output
- Convert markdown and HTML to natural spoken language
- Replace visual elements (bullet lists, headers) with spoken transitions
- Write in a clear, engaging podcast narrator voice
- Do not add information that is not in the source

OUTPUT: Return only the narration text. No preamble, no metadata, no explanations."""

_PACING_ADDON = """
- Add natural pacing: use sentence rhythm and paragraph breaks for breathing room
- Emphasize key terms and numbers with natural spoken stress patterns
- Use transitional phrases between sections for narrative flow"""


def get_system_prompt(tier: HardwareTier) -> str:
    """Return the system prompt appropriate for the given hardware tier."""
    if tier == HardwareTier.HIGH_VRAM:
        return _BASE_PROMPT + _PACING_ADDON
    return _BASE_PROMPT


def get_continuity_instruction(previous_tail: str) -> str:
    """Return instruction to maintain stylistic continuity with previous chunk output."""
    if not previous_tail.strip():
        return ""
    return (
        f"\n\nContinuity context — your previous output ended with:\n"
        f'"{previous_tail}"\n'
        f"Begin your output in a way that flows naturally from this."
    )
