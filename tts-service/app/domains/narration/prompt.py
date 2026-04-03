"""Tier-specific system prompts for narration script generation."""

from __future__ import annotations

from app.core.hardware import HardwareTier


_BASE_PROMPT = """You are converting written article content into spoken audio narration for a podcast.

THIS IS A FORMAT CONVERSION, NOT A REWRITE OR SUMMARY.

PRESERVATION CHECKLIST — every item below MUST appear in your output:
1. All numbers, statistics, percentages, dollar amounts, and measurements
2. All dates, timeframes, and temporal references (e.g. "January 2024", "Q3", "last year")
3. All named entities: people, companies, products, organizations, locations
4. All direct quotes — attribute the speaker and keep the quote accurate
5. All technical terms, jargon, and domain-specific vocabulary
6. All URLs, email addresses, and references (speak them naturally, e.g. "at example dot com")
7. Every section, argument, and supporting example from the source — do not skip any
8. Every item in any list or enumeration — if the source has five points, your output has five points
9. All causal relationships (X caused Y, because of Z, led to, resulted in)
10. All caveats, conditions, and qualifications (however, although, unless, except)

AUDIO ADAPTATION RULES (apply without removing content):
- Convert markdown and HTML to natural spoken language
- Replace visual elements (bullet lists, headers) with spoken transitions
- Write in flowing, connected paragraphs — no bullet points or markdown
- Sentences of 15-25 words, connected by conjunctions for natural flow
- Percentages → "X percent", dollar amounts → "X dollars", abbreviations spelled out on first use
- Write in a clear, engaging podcast narrator voice
- Do not add information that is not in the source

OUTPUT: Return only the narration text. No preamble, no metadata, no explanations."""

_PACING_ADDON = """
- Add natural pacing: use sentence rhythm and paragraph breaks for breathing room
- Emphasize key terms and numbers with natural spoken stress patterns
- Use transitional phrases between sections for narrative flow"""


def get_system_prompt(tier: HardwareTier) -> str:
    """Return the system prompt appropriate for the given hardware tier.

    MID_VRAM and HIGH_VRAM both use qwen3:8b-q4, so they get the full prompt
    with pacing instructions. CPU_ONLY and LOW_VRAM use smaller models and
    get the simpler base prompt.
    """
    if tier in (HardwareTier.MID_VRAM, HardwareTier.HIGH_VRAM):
        return _BASE_PROMPT + _PACING_ADDON
    return _BASE_PROMPT


def get_continuity_instruction(previous_output_tail: str, previous_source_tail: str = '') -> str:
    """Return instruction to maintain stylistic and positional continuity.

    Args:
        previous_output_tail: Last sentences of the previous narration output.
        previous_source_tail: Last sentences of the previous source chunk.
    """
    if not previous_output_tail.strip():
        return ''
    parts = [
        f'\n\nContinuity context — your previous output ended with:\n'
        f'"{previous_output_tail}"\n'
        f'Begin your output in a way that flows naturally from this.'
    ]
    if previous_source_tail.strip():
        parts.append(
            f'\nThe source article chunk you just processed ended with:\n'
            f'"{previous_source_tail}"\n'
            f'Ensure you pick up from where the source left off — do not repeat or skip content.'
        )
    return '\n'.join(parts)


def get_completeness_check_prompt(source: str, narration: str) -> list[dict]:
    """Return messages for an LLM-based completeness verification call.

    Used only on HIGH_VRAM tier as a final quality gate.
    """
    return [
        {
            'role': 'system',
            'content': (
                'You are a fact-checker. Compare the SOURCE text against the NARRATION text.\n'
                'Identify any information present in the SOURCE but missing from the NARRATION.\n'
                'Focus on: facts, numbers, names, dates, quotes, arguments, list items, '
                'technical terms, and causal claims.\n\n'
                'Respond with ONLY a JSON array of missing items (empty [] if nothing is missing).\n'
                'Example: ["The CEO name Jane Smith was dropped", "The $2.5M revenue figure is missing"]'
            ),
        },
        {
            'role': 'user',
            'content': f'SOURCE:\n{source}\n\n---\n\nNARRATION:\n{narration}',
        },
    ]
