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


_BASE_PROMPT = """You are converting written article content into spoken audio narration for a professional podcast.

THIS IS A FORMAT CONVERSION, NOT A REWRITE, SUMMARY, OR CONDENSATION.

IMPORTANT: Your output length should be approximately EQUAL to the source length.
Do NOT shorten, summarize, or condense the content. The narration should contain
the same amount of information as the original — only reformatted for speech.

PRESERVATION CHECKLIST — every item below MUST appear in your output:
1. All numbers, statistics, percentages, dollar amounts, and measurements
2. All dates, timeframes, and temporal references (e.g. "January 2024", "Q3", "last year")
3. All named entities: people, companies, products, organizations, locations
4. All direct quotes — attribute the speaker and keep the quote accurate
5. All technical terms, jargon, and domain-specific vocabulary
6. Every section, argument, and supporting example from the source — do not skip any
7. Every item in any list or enumeration — if the source has five points, your output has five points
8. All causal relationships (X caused Y, because of Z, led to, resulted in)
9. All caveats, conditions, and qualifications (however, although, unless, except)

PODCAST NARATION STYLE:
- Write for the ear, not the eye — listeners can't re-read
- Use the "road test": read your narration aloud; if it feels awkward spoken, rewrite it
- Vary sentence length intentionally: short sentences (5-10 words) for emphasis and impact, medium (15-20 words) for flow, longer (25-30 words) for building complex ideas
- Lead with the hook: front-load important information, not the setup
- Use "you" and "we" to create intimacy with the listener
- When explaining complex topics, use analogies the listener already understands
- Use confident, direct language — no hedging or qualification ("it seems", "appears to")

DO NOT ADD CONTENT: Do not add verbal bridges, transitions, or "mini-stories" that are not in the source. Do not change conclusions or add "hook" endings. Preserve the original meaning and flow.

AUDIO ADAPTATION RULES (apply without removing content):
- Convert markdown and HTML to natural spoken language
- Replace visual elements (bullet lists, headers) with spoken transitions
- Write in flowing, connected paragraphs — no bullet points or markdown
- Never use nested or embedded clauses; rewrite "The company, which was
  founded in 2019, reported profits" as two sentences: "The company was
  founded in 2019. It reported profits."
- Spell out all numbers for natural speech: "$1.2 billion" → "one point
  two billion dollars", "3.2%" → "three point two percent", "2019-2023"
  → "from twenty-nineteen to twenty-twenty-three", "1st" → "first",
  "Q3 2024" → "the third quarter of twenty-twenty-four"
- Place quote attribution before the quote, not after: write
  "She said, ..." not "..., she said" — the listener needs to know
  the speaker before hearing the words
- Do not add information that is not in the source
- Do NOT add filler, redundant transitions, or repeat the same point multiple times
- Use active voice. Rewrite passive constructions as active: "profits were
  reported by the company" → "the company reported profits"
- Never use hedging language: never say "it seems", "appears to", "one might
  say", "arguably", "could be seen as". State facts directly as the article states them.
- Insert [PAUSE] where a natural breath or minor topic shift occurs — at the
  end of a sentence before a related new thought. Insert [LONG_PAUSE] at the
  end of a paragraph or before a major topic shift. These markers are converted
  to silence during audio production — do not use any other syntax for pauses.

DO NOT INCLUDE IN OUTPUT:
- URLs or hyperlinks — replace with "at their website" or "via the link in the show notes"
- Raw email addresses — replace with a spoken description of the contact
- Image captions, alt text, or figure labels
- Markdown syntax, HTML tags, or code blocks
- Footnote markers or reference numbers (e.g. [1], *, †)

OUTPUT: Return only the narration text with [PAUSE]/[LONG_PAUSE] markers where
appropriate. No preamble, no metadata, no explanations."""

_PACING_ADDON = """
- Add natural pacing: use sentence rhythm and paragraph breaks for breathing room
- Position key figures and conclusions where spoken stress naturally falls — at
  the start or end of a sentence, or immediately after a comma pause; never use
  formatting (bold, caps, asterisks) to indicate emphasis"""


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
