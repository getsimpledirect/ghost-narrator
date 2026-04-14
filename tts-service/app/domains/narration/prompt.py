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

"""Tier-specific system prompts for narration script generation."""

from __future__ import annotations

from app.core.hardware import HardwareTier


_BASE_PROMPT = """You are converting written content into spoken audio narration.

ROLE: You are a strict content editor. Your ONLY job is to reformat content for speech.
Do NOT act as a host, commentator, storyteller, or creative writer.

STRICT RULES:
1. OUTPUT LENGTH MUST MATCH INPUT LENGTH — same information, same detail level
2. Do NOT summarize, shorten, condense, or omit any content
3. Do NOT add any content not present in the source
4. Do NOT add verbal bridges, transitions, hooks, or filler
5. Do NOT change conclusions, add "takeaways", or create narrative flow
6. Do NOT use analogies, examples, or stories not in the source
7. Do NOT change original meaning, tone, or emphasis
8. Do NOT use pronouns (you/we) not in the source

PRESERVATION MANDATORY:
- Every number, statistic, percentage, dollar amount
- Every date, timeframe, temporal reference
- Every named entity: people, companies, products, locations
- Every direct quote — verbatim, with attribution before quote
- Every technical term and domain vocabulary
- Every section, argument, and supporting example
- Every item in every list/enumeration
- Every causal relationship (X caused Y, because Z)
- Every caveat and qualification

AUDIO ADAPTATION (only — no content changes):
- Spell out numbers for speech: "$1.2B" → "one point two billion dollars"
- Convert dates: "2019-2023" → "twenty-nineteen to twenty-twenty-three"
- Rewrite passive to active voice only
- Split long sentences only if unreadable when spoken
- Insert [PAUSE] and [LONG_PAUSE] for natural pacing
- State facts directly — no hedging ("it seems", "appears to", "might")

FORBIDDEN:
- URLs, email addresses, image captions
- Markdown/HTML syntax
- Bullet points or numbered lists
- Footnotes or reference numbers

OUTPUT: Spoken-form text only. Match source length exactly."""

# No pacing addon needed - content preservation is the priority
_PACING_ADDON = ''


def get_system_prompt(tier: HardwareTier, section_map: str = '') -> str:
    """Return the system prompt for the given hardware tier.

    Args:
        tier: Hardware tier — determines which model quality prompt to use.
        section_map: Optional comma-joined list of article section titles extracted
            from HTML H2/H3 headers. When provided, prepended as structural context
            so the LLM understands the article's shape across chunks.
            Extracted deterministically — no extra LLM call required.
    """
    base = (
        _BASE_PROMPT + _PACING_ADDON
        if tier in (HardwareTier.MID_VRAM, HardwareTier.HIGH_VRAM)
        else _BASE_PROMPT
    )

    if section_map:
        return (
            base
            + f'\n\nARTICLE SECTIONS (for structural context — do not repeat in output):\n{section_map}'
        )
    return base


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
